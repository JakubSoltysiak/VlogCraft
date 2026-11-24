// Local provider calibration. No source media, decoded pictures or editor process.
#include <d3d11.h>
#include <wrl/client.h>
#include <cstdio>
#include <stdexcept>

using Microsoft::WRL::ComPtr;

static void check(HRESULT result, const char* operation) {
    if (FAILED(result)) {
        std::fprintf(stderr, "%s failed (0x%08lx)\n", operation, static_cast<unsigned long>(result));
        throw std::runtime_error(operation);
    }
}

int main() {
    try {
        ComPtr<ID3D11Device> device;
        ComPtr<ID3D11DeviceContext> immediate;
        check(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
              D3D11_CREATE_DEVICE_VIDEO_SUPPORT, nullptr, 0, D3D11_SDK_VERSION,
              &device, nullptr, &immediate), "create device");
        ComPtr<ID3D11VideoDevice> video;
        ComPtr<ID3D11VideoContext> context;
        check(device.As(&video), "video device");
        check(immediate.As(&context), "video context");

        D3D11_VIDEO_DECODER_DESC desc = {D3D11_DECODER_PROFILE_H264_VLD_NOFGT, 1920, 1080, DXGI_FORMAT_NV12};
        UINT configurations = 0;
        check(video->GetVideoDecoderConfigCount(&desc, &configurations), "configurations");
        ComPtr<ID3D11VideoDecoder> decoder;
        for (UINT i = 0; i < configurations && !decoder; ++i) {
            D3D11_VIDEO_DECODER_CONFIG config{};
            check(video->GetVideoDecoderConfig(&desc, i, &config), "decoder configuration");
            if (config.ConfigBitstreamRaw) video->CreateVideoDecoder(&desc, &config, &decoder);
        }
        if (!decoder) throw std::runtime_error("no supported H.264 decoder");
        // Distinct storage for both calls distinguishes a stack-slot address from a reused buffer.
        void* pointers[2]{};
        UINT sizes[2]{};
        for (int i = 0; i < 2; ++i) {
            check(context->GetDecoderBuffer(decoder.Get(), D3D11_VIDEO_DECODER_BUFFER_PICTURE_PARAMETERS,
                  &sizes[i], &pointers[i]), "get decoder buffer");
            std::printf("%lu %lu %p %p %u %p %p\n", GetCurrentProcessId(), GetCurrentThreadId(),
                static_cast<void*>(decoder.Get()), static_cast<void*>(&sizes[i]), sizes[i],
                static_cast<void*>(&pointers[i]), pointers[i]);
            check(context->ReleaseDecoderBuffer(decoder.Get(), D3D11_VIDEO_DECODER_BUFFER_PICTURE_PARAMETERS),
                  "release decoder buffer");
            if (!sizes[i] || !pointers[i]) throw std::runtime_error("empty input buffer");
        }
    } catch (const std::exception& e) {
        std::fprintf(stderr, "%s\n", e.what());
        return 1;
    }
    return 0;
}
