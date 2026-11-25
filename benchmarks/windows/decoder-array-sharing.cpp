// Admission probe for sharing the playback decoder's entire output array.
#include "../../native/media.h"
#include <d3d11_1.h>
#include <dxgi1_2.h>
#include <wrl/client.h>

using Microsoft::WRL::ComPtr;

struct DeviceRef {
    AVBufferRef* ref = nullptr;
    ~DeviceRef() { av_buffer_unref(&ref); }
};

struct SharedHandle {
    HANDLE value = nullptr;
    ~SharedHandle() { if (value) CloseHandle(value); }
};

struct PoolProbe {
    UINT slices = 0;
    ComPtr<IDXGIKeyedMutex> key;
    bool owned = false;
    ~PoolProbe() { if (owned) key->ReleaseSync(0); }
};

static AVPixelFormat shared_format(AVCodecContext* codec, const AVPixelFormat* choices) {
    auto& pool = *static_cast<PoolProbe*>(codec->opaque);
    while (*choices != AV_PIX_FMT_NONE && *choices != AV_PIX_FMT_D3D11) ++choices;
    if (*choices != AV_PIX_FMT_D3D11 || pool.key) return AV_PIX_FMT_NONE;
    AVBufferRef* ref = nullptr;
    if (avcodec_get_hw_frames_parameters(codec, codec->hw_device_ctx, *choices, &ref) < 0)
        return AV_PIX_FMT_NONE;
    auto* frames = reinterpret_cast<AVHWFramesContext*>(ref->data);
    auto* d3d = reinterpret_cast<AVD3D11VAFramesContext*>(frames->hwctx);
    frames->initial_pool_size = pool.slices;
    d3d->MiscFlags |= D3D11_RESOURCE_MISC_SHARED_NTHANDLE | D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX;
    if (av_hwframe_ctx_init(ref) < 0 || !d3d->texture ||
        FAILED(d3d->texture->QueryInterface(IID_PPV_ARGS(&pool.key))) ||
        pool.key->AcquireSync(0, 1000) != S_OK) {
        av_buffer_unref(&ref);
        return AV_PIX_FMT_NONE;
    }
    pool.owned = true;
    codec->hw_frames_ctx = ref;
    return *choices;
}

// Only the isolated verifier reads pixels on the CPU. Compare both visible planes,
// accounting for the storage height of the decoder array and driver row pitch.
static void check_picture(ID3D11Device* consumer, ID3D11Texture2D* opened, UINT slice,
                          int width, int height, const std::vector<uint8_t>& reference) {
    D3D11_TEXTURE2D_DESC desc{};
    opened->GetDesc(&desc);
    const UINT rowBytes = width * (desc.Format == DXGI_FORMAT_P010 ? 2 : 1);
    desc.ArraySize = 1;
    desc.Usage = D3D11_USAGE_STAGING;
    desc.BindFlags = desc.MiscFlags = 0;
    desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    ComPtr<ID3D11Texture2D> staging;
    check(consumer->CreateTexture2D(&desc, nullptr, &staging), "verification staging");
    ComPtr<ID3D11DeviceContext> context;
    consumer->GetImmediateContext(&context);
    context->CopySubresourceRegion(staging.Get(), 0, 0, 0, 0, opened, slice, nullptr);
    D3D11_MAPPED_SUBRESOURCE mapped{};
    check(context->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped), "verification readback");
    bool equal = true;
    for (int y = 0; y < height + height / 2; ++y) {
        const UINT row = y < height ? y : desc.Height + y - height;
        const auto* data = static_cast<const uint8_t*>(mapped.pData) + size_t(row) * mapped.RowPitch;
        equal &= std::memcmp(data, reference.data() + size_t(y) * rowBytes, rowBytes) == 0;
    }
    context->Unmap(staging.Get(), 0);
    if (!equal) throw std::runtime_error("cross-device decoded picture differs");
}

static void run(const char* fixture) {
    DeviceRef hardware;
    avcheck(av_hwdevice_ctx_create(&hardware.ref, AV_HWDEVICE_TYPE_D3D11VA, nullptr, nullptr, 0), "decode device");
    auto* hw = reinterpret_cast<AVD3D11VADeviceContext*>(
        reinterpret_cast<AVHWDeviceContext*>(hardware.ref->data)->hwctx);
    hw->BindFlags |= D3D11_BIND_SHADER_RESOURCE;
    D3D11_TEXTURE2D_DESC desc{};
    int width = 0, height = 0;
    int64_t pts = AV_NOPTS_VALUE;
    std::vector<uint8_t> reference;
    {
        // Same budget as the captured four compositor slots and six warm frames.
        Decoder decoder(fixture, hardware.ref, true, 8 + 4 - 3 + 6);
        if (!decoder.next() || decoder.frame->format != AV_PIX_FMT_D3D11)
            throw std::runtime_error("hardware picture unavailable");
        reinterpret_cast<ID3D11Texture2D*>(decoder.frame->data[0])->GetDesc(&desc);
        width = decoder.frame->width;
        height = decoder.frame->height;
        pts = decoder.frame->best_effort_timestamp;
        avcheck(av_hwframe_transfer_data(decoder.host, decoder.frame, 0), "reference readback");
        const int rowBytes = width * (desc.Format == DXGI_FORMAT_P010 ? 2 : 1);
        for (int plane = 0; plane < 2; ++plane) {
            for (int y = 0; y < (plane ? height / 2 : height); ++y) {
                const auto* row = decoder.host->data[plane] + y * decoder.host->linesize[plane];
                reference.insert(reference.end(), row, row + rowBytes);
            }
        }
    }
    if (desc.MipLevels != 1 || desc.ArraySize < 2 ||
        (desc.Format != DXGI_FORMAT_NV12 && desc.Format != DXGI_FORMAT_P010) ||
        !(desc.BindFlags & D3D11_BIND_DECODER) || !(desc.BindFlags & D3D11_BIND_SHADER_RESOURCE))
        throw std::runtime_error("unexpected production decoder texture");
    ComPtr<IDXGIDevice> dxgi;
    check(hw->device->QueryInterface(IID_PPV_ARGS(&dxgi)), "producer DXGI");
    ComPtr<IDXGIAdapter> adapter;
    check(dxgi->GetAdapter(&adapter), "producer adapter");
    ComPtr<ID3D11Device> consumer;
    check(D3D11CreateDevice(adapter.Get(), D3D_DRIVER_TYPE_UNKNOWN, nullptr, D3D11_CREATE_DEVICE_VIDEO_SUPPORT,
          nullptr, 0, D3D11_SDK_VERSION, &consumer, nullptr, nullptr), "same-adapter consumer");
    D3D11_FEATURE_DATA_D3D11_OPTIONS options{};
    check(hw->device->CheckFeatureSupport(D3D11_FEATURE_D3D11_OPTIONS, &options, sizeof(options)), "sharing features");
    std::printf("format=%u width=%u height=%u slices=%u bind=%u original_misc=%u extended_sharing=%d\n",
                desc.Format, desc.Width, desc.Height, desc.ArraySize, desc.BindFlags, desc.MiscFlags,
                options.ExtendedResourceSharing);
    PoolProbe pool;
    pool.slices = desc.ArraySize;
    Decoder decoded(fixture, hardware.ref, true, 15);
    decoded.codec->opaque = &pool;
    decoded.codec->get_format = shared_format;
    if (!decoded.next() || decoded.frame->format != AV_PIX_FMT_D3D11 || !pool.owned ||
        decoded.frame->width != width || decoded.frame->height != height ||
        decoded.frame->best_effort_timestamp != pts) throw std::runtime_error("shared decode or timestamp");
    auto* array = reinterpret_cast<ID3D11Texture2D*>(decoded.frame->data[0]);
    D3D11_TEXTURE2D_DESC shared{};
    array->GetDesc(&shared);
    if (shared.ArraySize != desc.ArraySize || shared.Width != desc.Width || shared.Height != desc.Height ||
        shared.Format != desc.Format || shared.BindFlags != desc.BindFlags) throw std::runtime_error("pool changed");
    UINT slice = static_cast<UINT>(reinterpret_cast<uintptr_t>(decoded.frame->data[1]));
    if (slice >= desc.ArraySize) throw std::runtime_error("invalid decoded slice");
    ComPtr<IDXGIResource1> resource;
    check(array->QueryInterface(IID_PPV_ARGS(&resource)), "shared resource");
    SharedHandle handle;
    check(resource->CreateSharedHandle(nullptr, DXGI_SHARED_RESOURCE_READ | DXGI_SHARED_RESOURCE_WRITE,
          nullptr, &handle.value), "create array handle");
    ComPtr<ID3D11Device1> device1;
    check(consumer.As(&device1), "consumer device1");
    ComPtr<ID3D11Texture2D> opened;
    check(device1->OpenSharedResource1(handle.value, IID_PPV_ARGS(&opened)), "open shared decoder array");
    D3D11_SHADER_RESOURCE_VIEW_DESC view{};
    view.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2DARRAY;
    view.Texture2DArray.MipLevels = view.Texture2DArray.ArraySize = 1;
    view.Texture2DArray.FirstArraySlice = slice;
    const bool ten = desc.Format == DXGI_FORMAT_P010;
    for (DXGI_FORMAT format : {ten ? DXGI_FORMAT_R16_UNORM : DXGI_FORMAT_R8_UNORM,
                               ten ? DXGI_FORMAT_R16G16_UNORM : DXGI_FORMAT_R8G8_UNORM}) {
        view.Format = format;
        ComPtr<ID3D11ShaderResourceView> plane;
        check(consumer->CreateShaderResourceView(opened.Get(), &view, &plane), "consumer plane view");
    }
    ComPtr<IDXGIKeyedMutex> consumerKey;
    check(opened.As(&consumerKey), "consumer mutex");
    HRESULT simultaneous = consumerKey->AcquireSync(0, 0);
    check(pool.key->ReleaseSync(1), "release producer");
    pool.owned = false;
    if (simultaneous != WAIT_TIMEOUT) throw std::runtime_error("unexpected concurrent acquisition");
    if (consumerKey->AcquireSync(1, 1000) != S_OK) throw std::runtime_error("consumer handoff");
    try { check_picture(consumer.Get(), opened.Get(), slice, width, height, reference); }
    catch (...) { consumerKey->ReleaseSync(2); throw; }
    check(consumerKey->ReleaseSync(2), "release consumer");
    if (pool.key->AcquireSync(2, 1000) != S_OK) throw std::runtime_error("return handoff");
    pool.owned = true; // Decoder closes while its device owns the array.
    std::printf("consumer_planes=2 concurrent_array_acquire=timeout round_trip_handoff=passed exact_bytes=%zu pts=%lld\n",
                reference.size(), static_cast<long long>(pts));
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    try { run(argv[1]); }
    catch (const std::exception& e) { std::fprintf(stderr, "%s\n", e.what()); return 1; }
    return 0;
}
