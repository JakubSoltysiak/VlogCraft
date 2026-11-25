#pragma once

#include "../../native/media.h"
#include <array>
#include <cstddef>
#include <cstdint>
#include <wrl/client.h>

// Executes a full visible-picture draw on the consumer device. Every output
// pixel records the four luma samples and one UV pair of a visible 2x2 block.
// The fourth channel identifies the draw, including when consecutive pictures
// contain identical samples. No shared image is staged or mapped here.
class HandoffPixels {
    using Blob = Microsoft::WRL::ComPtr<ID3DBlob>;
    struct Compiler {
        HMODULE mod = LoadLibraryExW(L"d3dcompiler_47.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
        ~Compiler() { if (mod) FreeLibrary(mod); }
    } compiler;

    static constexpr char shader[] = R"hlsl(
        Texture2DArray<float> luma : register(t0);
        Texture2DArray<float2> chroma : register(t1);
        cbuffer DrawInfo : register(b0) { uint4 drawInfo; };

        float4 vertex(uint id : SV_VertexID) : SV_Position {
            float2 uv = float2((id << 1) & 2, id & 2);
            return float4(uv * float2(2, -2) + float2(-1, 1), 0, 1);
        }

        uint pairCodes(float first, float second) {
            uint low = (uint)round(saturate(first) * SAMPLE_MAX);
            uint high = (uint)round(saturate(second) * SAMPLE_MAX);
            return low | (high << 16);
        }

        uint4 pixel(float4 position : SV_Position) : SV_Target {
            int2 block = int2(position.xy);
            int2 origin = 2 * block;
            float y00 = luma.Load(int4(origin, 0, 0));
            float y10 = luma.Load(int4(origin + int2(1, 0), 0, 0));
            float y01 = luma.Load(int4(origin + int2(0, 1), 0, 0));
            float y11 = luma.Load(int4(origin + int2(1, 1), 0, 0));
            float2 uv = chroma.Load(int4(block, 0, 0));
            return uint4(pairCodes(y00, y10), pairCodes(y01, y11),
                         pairCodes(uv.x, uv.y), drawInfo.x);
        }
    )hlsl";

    const UINT width;
    const UINT height;
    const bool tenBit;
    uint32_t submitted = 0;
    uint32_t staged = 0;
    Microsoft::WRL::ComPtr<ID3D11VertexShader> vertexShader;
    Microsoft::WRL::ComPtr<ID3D11PixelShader> pixelShader;
    Microsoft::WRL::ComPtr<ID3D11Buffer> drawInfo;
    Microsoft::WRL::ComPtr<ID3D11Texture2D> output;
    Microsoft::WRL::ComPtr<ID3D11RenderTargetView> target;
    Microsoft::WRL::ComPtr<ID3D11Texture2D> staging;

    Blob compile(const char* entry, const char* profile) const {
        const D3D_SHADER_MACRO options[] = {
            {"SAMPLE_MAX", tenBit ? "65535.0" : "255.0"}, {nullptr, nullptr}
        };
        Blob code;
        Blob errors;
        auto compileShader = compiler.mod ? reinterpret_cast<decltype(&D3DCompile)>(
            GetProcAddress(compiler.mod, "D3DCompile")) : nullptr;
        if (!compileShader) throw std::runtime_error("system shader compiler unavailable");
        const auto result = compileShader(shader, sizeof(shader) - 1, "handoff-pixels", options, nullptr,
                                      entry, profile, D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &code, &errors);
        if (FAILED(result) && errors)
            std::fprintf(stderr, "%s\n", static_cast<const char*>(errors->GetBufferPointer()));
        check(result, entry);
        return code;
    }

    static void check_view(ID3D11ShaderResourceView* view, DXGI_FORMAT format) {
        if (!view) throw std::runtime_error("missing handoff shader plane view");
        D3D11_SHADER_RESOURCE_VIEW_DESC desc{};
        view->GetDesc(&desc);
        if (desc.Format != format || desc.ViewDimension != D3D11_SRV_DIMENSION_TEXTURE2DARRAY ||
            desc.Texture2DArray.MostDetailedMip != 0 || desc.Texture2DArray.MipLevels != 1 ||
            desc.Texture2DArray.FirstArraySlice != 0 || desc.Texture2DArray.ArraySize != 1)
            throw std::runtime_error("unexpected handoff shader plane view");
    }

public:
    HandoffPixels(ID3D11Device* consumer, UINT visibleWidth, UINT visibleHeight, DXGI_FORMAT format)
        : width(visibleWidth), height(visibleHeight), tenBit(format == DXGI_FORMAT_P010) {
        if (!width || !height || width % 2 || height % 2 ||
            width > D3D11_REQ_TEXTURE2D_U_OR_V_DIMENSION || height > D3D11_REQ_TEXTURE2D_U_OR_V_DIMENSION ||
            (format != DXGI_FORMAT_NV12 && format != DXGI_FORMAT_P010))
            throw std::runtime_error("unsupported visible handoff picture");

        const auto vs = compile("vertex", "vs_5_0");
        const auto ps = compile("pixel", "ps_5_0");
        check(consumer->CreateVertexShader(vs->GetBufferPointer(), vs->GetBufferSize(), nullptr, &vertexShader),
              "create handoff vertex shader");
        check(consumer->CreatePixelShader(ps->GetBufferPointer(), ps->GetBufferSize(), nullptr, &pixelShader),
              "create handoff pixel shader");

        D3D11_BUFFER_DESC constants{};
        constants.ByteWidth = sizeof(uint32_t) * 4;
        constants.Usage = D3D11_USAGE_DEFAULT;
        constants.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
        check(consumer->CreateBuffer(&constants, nullptr, &drawInfo), "create handoff draw marker buffer");

        D3D11_TEXTURE2D_DESC desc{};
        desc.Width = width / 2;
        desc.Height = height / 2;
        desc.ArraySize = desc.MipLevels = desc.SampleDesc.Count = 1;
        desc.Format = DXGI_FORMAT_R32G32B32A32_UINT;
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_RENDER_TARGET;
        check(consumer->CreateTexture2D(&desc, nullptr, &output), "create handoff draw target");
        check(consumer->CreateRenderTargetView(output.Get(), nullptr, &target), "create handoff target view");
        desc.Usage = D3D11_USAGE_STAGING;
        desc.BindFlags = 0;
        desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        check(consumer->CreateTexture2D(&desc, nullptr, &staging), "create verification staging texture");
    }

    // Logical size of the one render target and one staging texture combined.
    uint64_t verification_texture_payload_bytes() const {
        return uint64_t(width / 2) * (height / 2) * sizeof(uint32_t) * 4 * 2;
    }

    // The caller holds the image's keyed mutex and controls GPU completion.
    // The dedicated consumer immediate context starts in its default state.
    void submit(ID3D11DeviceContext* context, ID3D11ShaderResourceView* y, ID3D11ShaderResourceView* uv) {
        check_view(y, tenBit ? DXGI_FORMAT_R16_UNORM : DXGI_FORMAT_R8_UNORM);
        check_view(uv, tenBit ? DXGI_FORMAT_R16G16_UNORM : DXGI_FORMAT_R8G8_UNORM);
        if (submitted == UINT32_MAX) throw std::runtime_error("handoff draw marker exhausted");
        const uint32_t marker[] = {++submitted, 0, 0, 0};
        context->UpdateSubresource(drawInfo.Get(), 0, nullptr, marker, 0, 0);
        ID3D11Buffer* constants = drawInfo.Get();
        const D3D11_VIEWPORT viewport{0, 0, float(width / 2), float(height / 2), 0, 1};
        auto* renderTarget = target.Get();
        ID3D11ShaderResourceView* planes[] = {y, uv};
        context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context->RSSetViewports(1, &viewport);
        context->OMSetRenderTargets(1, &renderTarget, nullptr);
        context->VSSetShader(vertexShader.Get(), nullptr, 0);
        context->PSSetShader(pixelShader.Get(), nullptr, 0);
        context->PSSetConstantBuffers(0, 1, &constants);
        context->PSSetShaderResources(0, 2, planes);
        context->Draw(3, 0);
        ID3D11ShaderResourceView* unbound[] = {nullptr, nullptr};
        context->PSSetShaderResources(0, 2, unbound);
        context->OMSetRenderTargets(0, nullptr, nullptr);
    }

    // Stage the private draw output independently of shared image ownership.
    // Run before another submit and signal a completion fence after this copy.
    void stage(ID3D11DeviceContext* context) {
        if (!submitted || staged == submitted) throw std::runtime_error("no new handoff draw to stage");
        context->CopyResource(staging.Get(), output.Get());
        staged = submitted;
    }

    uint64_t verify(ID3D11DeviceContext* context, const AVFrame* control, int64_t sourcePts) const {
        if (!staged || !control || sourcePts == AV_NOPTS_VALUE || control->best_effort_timestamp != sourcePts)
            throw std::runtime_error("handoff verification timestamp mismatch");
        const UINT sampleBytes = tenBit ? 2 : 1;
        const auto rowBytes = int64_t(width) * sampleBytes;
        if (control->format != (tenBit ? AV_PIX_FMT_P010LE : AV_PIX_FMT_NV12) ||
            control->width != int(width) || control->height != int(height) ||
            control->crop_left || control->crop_top || control->crop_right || control->crop_bottom)
            throw std::runtime_error("unexpected FFmpeg control picture");
        for (int plane = 0; plane < 2; ++plane) {
            const auto stride = int64_t(control->linesize[plane]);
            if (!control->data[plane] || (stride > -rowBytes && stride < rowBytes))
                throw std::runtime_error("invalid FFmpeg control stride");
        }

        D3D11_MAPPED_SUBRESOURCE mapped{};
        // Even after the GPU event, this driver can defer CPU mapping. This
        // verification-only wait is outside the measured draw/retirement span.
        const auto limit = Clock::now() + std::chrono::seconds(2);
        HRESULT result;
        do {
            result = context->Map(staging.Get(), 0, D3D11_MAP_READ, D3D11_MAP_FLAG_DO_NOT_WAIT, &mapped);
            if (result != DXGI_ERROR_WAS_STILL_DRAWING) break;
            SwitchToThread();
        } while (Clock::now() < limit);
        check(result, "map verified handoff draw output");
        using Pixel = std::array<uint32_t, 4>;
        if (!mapped.pData || mapped.RowPitch < (width / 2) * sizeof(Pixel)) {
            context->Unmap(staging.Get(), 0);
            throw std::runtime_error("invalid handoff draw output pitch");
        }
        const auto code = [sampleBytes](const uint8_t* sample) -> uint32_t {
            uint32_t value = sample[0];
            if (sampleBytes == 2) value |= uint32_t(sample[1]) << 8;
            return value;
        };
        const auto pair = [&](const uint8_t* samples) {
            return code(samples) | (code(samples + sampleBytes) << 16);
        };
        for (UINT y = 0; y < height / 2; ++y) {
            const auto* top = control->data[0] + (2 * std::ptrdiff_t(y)) * control->linesize[0];
            const auto* bottom = top + control->linesize[0];
            const auto* chroma = control->data[1] + std::ptrdiff_t(y) * control->linesize[1];
            const auto* outputRow = static_cast<const uint8_t*>(mapped.pData) + size_t(y) * mapped.RowPitch;
            for (UINT x = 0; x < width / 2; ++x) {
                const auto offset = size_t(x) * 2 * sampleBytes;
                const Pixel expected{pair(top + offset), pair(bottom + offset), pair(chroma + offset), staged};
                Pixel actual;
                std::memcpy(actual.data(), outputRow + size_t(x) * sizeof(Pixel), sizeof(Pixel));
                if (actual != expected) {
                    context->Unmap(staging.Get(), 0);
                    char error[256];
                    std::snprintf(error, sizeof(error), "handoff draw mismatch at %u,%u pts=%lld "
                                  "expected=%08x,%08x,%08x,%u actual=%08x,%08x,%08x,%u",
                                  x, y, static_cast<long long>(sourcePts),
                                  expected[0], expected[1], expected[2], expected[3],
                                  actual[0], actual[1], actual[2], actual[3]);
                    throw std::runtime_error(error);
                }
            }
        }
        context->Unmap(staging.Get(), 0);
        return uint64_t(rowBytes) * (height + height / 2);
    }
};
