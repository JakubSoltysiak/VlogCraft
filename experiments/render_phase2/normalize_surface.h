#pragma once

#include "d3d_composite.h"

namespace render_phase2 {

struct SurfaceInput {
    float codedWidth,codedHeight,orientedWidth,orientedHeight;
    unsigned fittedWidth,fittedHeight;
    int offsetX,offsetY;
    float yOffset,yScale,cOffset,cScale;
    unsigned clockwise,pq,slot,centeredChroma;
    unsigned transparentPadding,reserved[3];
};
static_assert(sizeof(SurfaceInput)==80);

inline const char* normalize_shader=R"HLSL(
Texture2DArray<float> sourceY : register(t2);
Texture2DArray<float2> sourceUV : register(t3);
RWTexture2DArray<float4> normalized : register(u0);
SamplerState linearChroma : register(s0);
cbuffer Input : register(b1) {
    float2 codedSize, orientedSize;
    uint2 fittedSize;
    int2 placement;
    float4 range;
    uint clockwise, isPq, slot, centeredChroma;
    uint transparentPadding;
    uint3 reserved;
};

float3 inversePQ(float3 value) {
    float3 p=pow(saturate(value),32.0/2523.0);
    return 100.0*pow(max(p-3424.0/4096.0,0)/
                     (2413.0/128.0-(2392.0/128.0)*p),4096.0/653.0);
}

float3 scene(int2 at) {
    at=clamp(at,0,int2(orientedSize)-1);
    int2 source=at;
    if(clockwise==90) source=int2(at.y,int(codedSize.y)-1-at.x);
    else if(clockwise==180) source=int2(codedSize)-1-at;
    else if(clockwise==270) source=int2(int(codedSize.x)-1-at.y,at.x);
    float y=(sourceY.Load(int4(source,0,0))-range.x)*range.y;
    uint paddedWidth,paddedHeight,depth;
    sourceUV.GetDimensions(paddedWidth,paddedHeight,depth);
    float2 chroma=(float2(source)-float2(centeredChroma?.5:0,.5))*.5;
    chroma=clamp(chroma,0,codedSize*.5-1);
    float2 uv=(sourceUV.SampleLevel(linearChroma,
               float3((chroma+.5)/float2(paddedWidth,paddedHeight),0),0)-range.z)*range.w;
    if(isPq) return inversePQ(float3(y+1.4746*uv.y,y-.164553*uv.x-.571353*uv.y,y+1.8814*uv.x));
    float3 rgb=pow(max(float3(y+1.5748*uv.y,y-.187324*uv.x-.468124*uv.y,y+1.8556*uv.x),0),2.4);
    return float3(dot(rgb,float3(.627404,.329283,.043313)),
                  dot(rgb,float3(.069097,.919540,.011362)),
                  dot(rgb,float3(.016391,.088013,.895595)));
}

[numthreads(16,8,1)]
void main(uint3 at : SV_DispatchThreadID) {
    uint width,height,layers;
    normalized.GetDimensions(width,height,layers);
    if(at.x>=width||at.y>=height) return;
    int2 p=int2(at.xy)-int2(placement);
    float3 result=0;
    bool inside=all(p>=0)&&all(p<int2(fittedSize));
    if(inside) {
        float2 step=orientedSize/float2(fittedSize);
        float2 phase=(float2(p)+.5)*step-.5;
        float2 filterWidth=max(step,1);
        int2 first=int2(floor(phase-filterWidth))+1;
        int2 last=int2(ceil(phase+filterWidth));
        float sum=0;
        for(int y=first.y;y<last.y;++y)
            for(int x=first.x;x<last.x;++x) {
                float2 weights=max(0,1-abs(float2(x,y)-phase)/filterWidth);
                float w=weights.x*weights.y;
                result+=scene(int2(x,y))*w;
                sum+=w;
            }
        result/=sum;
    }
    normalized[uint3(at.xy,slot)]=float4(result,inside||transparentPadding==0?1:0);
}
)HLSL";

class SurfaceNormalizer {
    GpuCompositor& compositor;
    Com<ID3D11ComputeShader> shader;
    Com<ID3D11UnorderedAccessView> destination;
    Com<ID3D11Buffer> params;
    Com<ID3D11SamplerState> sampler;
    unsigned width,height;

public:
    SurfaceNormalizer(GpuCompositor& gpu,unsigned w,unsigned h):compositor(gpu),width(w),height(h) {
        auto* device=gpu.d3d_device();
        Com<ID3DBlob> bytecode,errors;
        const auto code=D3DCompile(normalize_shader,std::strlen(normalize_shader),"source-normalize",
            nullptr,nullptr,"main","cs_5_0",D3DCOMPILE_IEEE_STRICTNESS|D3DCOMPILE_OPTIMIZATION_LEVEL3,
            0,bytecode.init(),errors.init());
        if(FAILED(code)&&errors.get())
            throw std::runtime_error(static_cast<const char*>(errors->GetBufferPointer()));
        require(code,"Compile source normalization");
        require(device->CreateComputeShader(bytecode->GetBufferPointer(),bytecode->GetBufferSize(),
            nullptr,shader.init()),"Create source normalization");
        require(device->CreateUnorderedAccessView(gpu.source_texture(),nullptr,destination.init()),
            "Open resident source texture for normalization");
        const D3D11_BUFFER_DESC d={sizeof(SurfaceInput),D3D11_USAGE_DEFAULT,D3D11_BIND_CONSTANT_BUFFER,0,0,0};
        require(device->CreateBuffer(&d,nullptr,params.init()),"Allocate normalization constants");
        D3D11_SAMPLER_DESC s{};
        s.Filter=D3D11_FILTER_MIN_MAG_LINEAR_MIP_POINT;
        s.AddressU=s.AddressV=s.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;
        require(device->CreateSamplerState(&s,sampler.init()),"Create chroma sampler");
    }

    double normalize(ID3D11ShaderResourceView* y,ID3D11ShaderResourceView* uv,const SurfaceInput& input) {
        auto started=Clock::now();
        auto* context=compositor.d3d_context();
        ID3D11ShaderResourceView* empty=nullptr;
        context->CSSetShaderResources(0,1,&empty);
        ID3D11ShaderResourceView* planes[]={y,uv};
        context->CSSetShaderResources(2,2,planes);
        auto* output=destination.get();
        context->CSSetUnorderedAccessViews(0,1,&output,nullptr);
        auto* samplerState=sampler.get();
        context->CSSetSamplers(0,1,&samplerState);
        auto* constants=params.get();
        context->UpdateSubresource(constants,0,nullptr,&input,0,0);
        context->CSSetConstantBuffers(1,1,&constants);
        context->CSSetShader(shader.get(),nullptr,0);
        context->Dispatch((width+15)/16,(height+7)/8,1);
        output=nullptr;
        planes[0]=planes[1]=nullptr;
        context->CSSetUnorderedAccessViews(0,1,&output,nullptr);
        context->CSSetShaderResources(2,2,planes);
        compositor.finish_source_work();
        compositor.restore_inputs();
        return milliseconds(started);
    }
};

}
