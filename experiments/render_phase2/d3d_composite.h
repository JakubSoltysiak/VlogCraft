#pragma once

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <dxgi1_4.h>

#include <chrono>
#include <cstring>
#include <memory>
#include <ostream>
#include <stdexcept>
#include <string>

#include "composite.h"
#include "pq_shader.h"

namespace render_phase2 {

using Clock=std::chrono::steady_clock;

inline double milliseconds(Clock::time_point start) {
    return std::chrono::duration<double,std::milli>(Clock::now()-start).count();
}

inline void require(HRESULT result,const char* label) {
    if (FAILED(result)) throw std::runtime_error(std::string(label)+" failed ("+
        std::to_string(static_cast<unsigned long>(result))+")");
}

template<class T> class Com {
    T* pointer=nullptr;
public:
    Com()=default;
    Com(const Com&)=delete;
    Com& operator=(const Com&)=delete;
    ~Com(){ if(pointer) pointer->Release(); }
    T** init(){ return &pointer; }
    T* get()const{ return pointer; }
    T* operator->()const{ return pointer; }
};

inline const char* shader_source=R"HLSL(
struct Layer {
    float4 geometry;
    float4 matte;
    uint4 selection;
};
cbuffer Frame : register(b0) {
    uint width, height, layers;
    float dissolve;
    Layer layer[3];
};
Texture2DArray<float4> sources : register(t0);
StructuredBuffer<uint2> edges : register(t1);
RWTexture2D<float4> outputPicture : register(u0);

float4 fetch(Layer p, int2 at) {
    float4 picture=sources.Load(int4(at,p.selection.x,0));
    if (p.selection.y==0) return picture;
    float2 delta=abs((float2(at)+.5)/float2(width,height)-.5)/p.matte.z;
    float distance=p.selection.y==1?length(delta):max(delta.x,delta.y);
    return picture*saturate((1-distance)/p.matte.w);
}

float4 sampleLayer(Layer p, uint n, uint2 outputPoint) {
    uint2 extent=edges[n*height+outputPoint.y];
    if (outputPoint.x<extent.x || outputPoint.x>=extent.y) return 0;
    float2 size=float2(width,height);
    float2 center=(size-1)*.5;
    float2 delta=(float2(outputPoint)-center-size*float2(p.geometry.w,p.matte.x))/p.geometry.x;
    float2 pixel=center+float2(delta.x*p.geometry.y+delta.y*p.geometry.z,
                               -delta.x*p.geometry.z+delta.y*p.geometry.y);
    pixel=clamp(pixel,0,size-1);
    int2 low=int2(pixel), high=min(low+1,int2(width,height)-1);
    float2 ratio=pixel-low;
    float4 upper=fetch(p,low)*(1-ratio.x)+fetch(p,int2(high.x,low.y))*ratio.x;
    float4 lower=fetch(p,int2(low.x,high.y))*(1-ratio.x)+fetch(p,high)*ratio.x;
    return (upper*(1-ratio.y)+lower*ratio.y)*p.matte.y;
}

[numthreads(16,8,1)]
void main(uint3 thread : SV_DispatchThreadID) {
    if (thread.x>=width || thread.y>=height) return;
    float4 result=0, left=0;
    for(uint n=0;n<layers;++n) {
        float4 foreground=sampleLayer(layer[n],n,thread.xy);
        if (dissolve>=0 && n<2) {
            if (n==0) left=foreground;
            else result=left*(1-dissolve)+foreground*dissolve;
        } else result=result*(1-foreground.a)+foreground;
    }
    outputPicture[thread.xy]=result;
}
)HLSL";

class GpuCompositor {
    Com<ID3D11ComputeShader> pqShader;
    Com<ID3D11ShaderResourceView> pqInput;
    Com<ID3D11UnorderedAccessView> pqTarget;
    Com<ID3D11Buffer> pqOutput,pqReadback;
    unsigned pqBytes=0;
    Com<ID3D11Device> device;
    Com<ID3D11DeviceContext> context;
    Com<IDXGIAdapter3> memory;
    Com<ID3D11Texture2D> source, output, readback;
    Com<ID3D11ShaderResourceView> view, edgeView;
    Com<ID3D11UnorderedAccessView> target;
    Com<ID3D11Buffer> constants, edges;
    Com<ID3D11ComputeShader> shader;
    Com<ID3D11Query> completed, disjoint, gpuStart, gpuEnd;
    unsigned width, height, sourceCount, outputStride;

    void query(D3D11_QUERY type,Com<ID3D11Query>& result) {
        const D3D11_QUERY_DESC desc={type,0};
        require(device->CreateQuery(&desc,result.init()),"Create query");
    }

    template<class T>
    T wait(ID3D11Query* queryObject) {
        T value{};
        const auto start=Clock::now();
        HRESULT result;
        while ((result=context->GetData(queryObject,&value,sizeof(value),0))==S_FALSE) {
            if(milliseconds(start)>20000) throw std::runtime_error("Timed out waiting for D3D11 work");
            SwitchToThread();
        }
        require(result,"D3D11 query");
        return value;
    }

    void compile(const char* sourceCode,const char* label,Com<ID3D11ComputeShader>& targetShader) {
        Com<ID3DBlob> binary, errors;
        auto code=D3DCompile(sourceCode,std::strlen(sourceCode),label,nullptr,nullptr,"main","cs_5_0",
            D3DCOMPILE_OPTIMIZATION_LEVEL3|D3DCOMPILE_IEEE_STRICTNESS,0,binary.init(),errors.init());
        if(FAILED(code) && errors.get())
            throw std::runtime_error(static_cast<const char*>(errors->GetBufferPointer()));
        require(code,"Compile compute shader");
        require(device->CreateComputeShader(binary->GetBufferPointer(),binary->GetBufferSize(),nullptr,
                targetShader.init()),"Create compute shader");
    }

    void setup_pq() {
        compile(pq_shader_source,"phase2b-pq",pqShader);
        require(device->CreateShaderResourceView(output.get(),nullptr,pqInput.init()),"Create PQ input view");
        pqBytes=3*width*height;
        const D3D11_BUFFER_DESC packed={pqBytes,D3D11_USAGE_DEFAULT,D3D11_BIND_UNORDERED_ACCESS,
            0,D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS,0};
        require(device->CreateBuffer(&packed,nullptr,pqOutput.init()),"Allocate packed PQ surface");
        D3D11_UNORDERED_ACCESS_VIEW_DESC viewDesc{};
        viewDesc.Format=DXGI_FORMAT_R32_TYPELESS;
        viewDesc.ViewDimension=D3D11_UAV_DIMENSION_BUFFER;
        viewDesc.Buffer.NumElements=pqBytes/4;
        viewDesc.Buffer.Flags=D3D11_BUFFER_UAV_FLAG_RAW;
        require(device->CreateUnorderedAccessView(pqOutput.get(),&viewDesc,pqTarget.init()),"Create PQ output view");
        const D3D11_BUFFER_DESC staging={pqBytes,D3D11_USAGE_STAGING,0,D3D11_CPU_ACCESS_READ,0,0};
        require(device->CreateBuffer(&staging,nullptr,pqReadback.init()),"Allocate packed PQ readback");
    }

public:
    double uploadMs=0, dispatchMs=0, shaderMs=0, mapMs=0, colorMs=0, outputMs=0;
    bool gpuClockValid=false;
    unsigned long long localBytes=0, sharedBytes=0, currentLocal=0, currentShared=0;
    std::string adapterName;

    GpuCompositor(unsigned w,unsigned h,unsigned count,const Pixel* pixels,bool half,bool download,bool warp,
                  bool pq=false)
        :width(w),height(h),sourceCount(count),outputStride(half?8:16) {
        D3D_FEATURE_LEVEL level=D3D_FEATURE_LEVEL_11_0;
        require(D3D11CreateDevice(nullptr,warp?D3D_DRIVER_TYPE_WARP:D3D_DRIVER_TYPE_HARDWARE,
            nullptr,0,&level,1,D3D11_SDK_VERSION,device.init(),nullptr,context.init()),"D3D11 device");
        Com<IDXGIDevice> dxgi;
        Com<IDXGIAdapter> adapter;
        require(device->QueryInterface(__uuidof(IDXGIDevice),reinterpret_cast<void**>(dxgi.init())),"DXGI device");
        require(dxgi->GetAdapter(adapter.init()),"DXGI adapter");
        adapter->QueryInterface(__uuidof(IDXGIAdapter3),reinterpret_cast<void**>(memory.init()));
        DXGI_ADAPTER_DESC adapterInfo{};
        require(adapter->GetDesc(&adapterInfo),"DXGI adapter description");
        char adapterText[256]={};
        WideCharToMultiByte(CP_UTF8,0,adapterInfo.Description,-1,adapterText,sizeof(adapterText),nullptr,nullptr);
        for (char c:std::string(adapterText)) if(c>=32 && c!='"' && c!='\\') adapterName+=c;

        compile(shader_source,"phase2-composite",shader);
        const D3D11_BUFFER_DESC buffer={sizeof(Frame),D3D11_USAGE_DEFAULT,D3D11_BIND_CONSTANT_BUFFER,0,0,0};
        require(device->CreateBuffer(&buffer,nullptr,constants.init()),"Create frame parameters");
        const D3D11_BUFFER_DESC ranges={UINT(3*height*sizeof(RowRange)),D3D11_USAGE_DEFAULT,
            D3D11_BIND_SHADER_RESOURCE,0,D3D11_RESOURCE_MISC_BUFFER_STRUCTURED,sizeof(RowRange)};
        require(device->CreateBuffer(&ranges,nullptr,edges.init()),"Create coverage rows");
        require(device->CreateShaderResourceView(edges.get(),nullptr,edgeView.init()),"Create coverage view");
        query(D3D11_QUERY_EVENT,completed);
        query(D3D11_QUERY_TIMESTAMP_DISJOINT,disjoint);
        query(D3D11_QUERY_TIMESTAMP,gpuStart);
        query(D3D11_QUERY_TIMESTAMP,gpuEnd);

        D3D11_TEXTURE2D_DESC desc={width,height,1,sourceCount,DXGI_FORMAT_R32G32B32A32_FLOAT,{1,0},
                                   D3D11_USAGE_DEFAULT,D3D11_BIND_SHADER_RESOURCE,0,0};
        const auto started=Clock::now();
        require(device->CreateTexture2D(&desc,nullptr,source.init()),"Create reusable source surfaces");
        upload(pixels);
        uploadMs=milliseconds(started);
        require(device->CreateShaderResourceView(source.get(),nullptr,view.init()),"Create source view");
        desc.ArraySize=1;
        desc.Format=half?DXGI_FORMAT_R16G16B16A16_FLOAT:DXGI_FORMAT_R32G32B32A32_FLOAT;
        desc.BindFlags=D3D11_BIND_UNORDERED_ACCESS;
        if(pq) {
            if(width%4 || height%2 || half)
                throw std::runtime_error("Packed PQ needs FP32 and dimensions divisible by 4 by 2");
            desc.BindFlags|=D3D11_BIND_SHADER_RESOURCE;
        }
        require(device->CreateTexture2D(&desc,nullptr,output.init()),"Create output surface");
        require(device->CreateUnorderedAccessView(output.get(),nullptr,target.init()),"Create output view");
        if(pq) setup_pq();
        else if(download) {
            desc.BindFlags=0;
            desc.Usage=D3D11_USAGE_STAGING;
            desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
            require(device->CreateTexture2D(&desc,nullptr,readback.init()),"Create reusable download surface");
        }
        context->CSSetShader(shader.get(),nullptr,0);
        ID3D11Buffer* parameters[]={constants.get()};
        context->CSSetConstantBuffers(0,1,parameters);
        ID3D11ShaderResourceView* inputs[]={view.get(),edgeView.get()};
        context->CSSetShaderResources(0,2,inputs);
        sample_memory();
    }

    void sample_memory() {
        if(!memory.get()) return;
        DXGI_QUERY_VIDEO_MEMORY_INFO info{};
        if(SUCCEEDED(memory->QueryVideoMemoryInfo(0,DXGI_MEMORY_SEGMENT_GROUP_LOCAL,&info))) {
            currentLocal=info.CurrentUsage;
            localBytes=std::max(localBytes,currentLocal);
        }
        if(SUCCEEDED(memory->QueryVideoMemoryInfo(0,DXGI_MEMORY_SEGMENT_GROUP_NON_LOCAL,&info))) {
            currentShared=info.CurrentUsage;
            sharedBytes=std::max(sharedBytes,currentShared);
        }
    }

    void upload(const Pixel* pixels) {
        for(unsigned i=0;i<sourceCount;++i)
            context->UpdateSubresource(source.get(),i,nullptr,pixels+std::size_t(i)*width*height,width*sizeof(Pixel),0);
        context->End(completed.get());
        wait<BOOL>(completed.get());
    }

    void render(const Frame& frame,const RowRange* coverage) {
        const auto begun=Clock::now();
        context->UpdateSubresource(constants.get(),0,nullptr,&frame,0,0);
        context->UpdateSubresource(edges.get(),0,nullptr,coverage,0,0);
        ID3D11UnorderedAccessView* destinations[]={target.get()};
        context->CSSetUnorderedAccessViews(0,1,destinations,nullptr);
        context->Begin(disjoint.get());
        context->End(gpuStart.get());
        context->Dispatch((width+15)/16,(height+7)/8,1);
        context->End(gpuEnd.get());
        context->End(disjoint.get());
        destinations[0]=nullptr;
        context->CSSetUnorderedAccessViews(0,1,destinations,nullptr);
        const auto clock=wait<D3D11_QUERY_DATA_TIMESTAMP_DISJOINT>(disjoint.get());
        gpuClockValid=!clock.Disjoint && clock.Frequency;
        const auto start=wait<UINT64>(gpuStart.get()), end=wait<UINT64>(gpuEnd.get());
        shaderMs=gpuClockValid?1000.*double(end-start)/double(clock.Frequency):0;
        dispatchMs=milliseconds(begun);
    }

    void download(char* destination) {
        const auto begun=Clock::now();
        context->CopyResource(readback.get(),output.get());
        D3D11_MAPPED_SUBRESOURCE mapped{};
        require(context->Map(readback.get(),0,D3D11_MAP_READ,0,&mapped),"Map downloaded picture");
        const size_t stride=std::size_t(width)*outputStride;
        for (unsigned y=0;y<height;++y)
            std::memcpy(destination+y*stride,static_cast<const char*>(mapped.pData)+y*mapped.RowPitch,stride);
        context->Unmap(readback.get(),0);
        mapMs=milliseconds(begun);
    }

    void download_gbr(float* destination) {
        const auto begun=Clock::now();
        context->CopyResource(readback.get(),output.get());
        D3D11_MAPPED_SUBRESOURCE mapped{};
        require(context->Map(readback.get(),0,D3D11_MAP_READ,0,&mapped),"Map planar picture");
        const auto count=std::size_t(width)*height;
        for(unsigned y=0;y<height;++y) {
            const auto* row=reinterpret_cast<const Pixel*>(
                static_cast<const char*>(mapped.pData)+y*mapped.RowPitch);
            float* green=destination+std::size_t(y)*width;
            float* blue=green+count;
            float* red=blue+count;
            unsigned x=0;
            for(;x+4<=width;x+=4) {
                auto a=_mm_loadu_ps(&row[x].r), b=_mm_loadu_ps(&row[x+1].r);
                auto c=_mm_loadu_ps(&row[x+2].r), d=_mm_loadu_ps(&row[x+3].r);
                _MM_TRANSPOSE4_PS(a,b,c,d);
                _mm_storeu_ps(red+x,a);
                _mm_storeu_ps(green+x,b);
                _mm_storeu_ps(blue+x,c);
            }
            for(;x<width;++x) {
                red[x]=row[x].r;
                green[x]=row[x].g;
                blue[x]=row[x].b;
            }
        }
        context->Unmap(readback.get(),0);
        mapMs=milliseconds(begun);
    }

    void stream_pq(std::ostream& stream,bool measured) {
        ID3D11ShaderResourceView* sensor=pqInput.get();
        ID3D11UnorderedAccessView* sink=pqTarget.get();
        context->CSSetShader(pqShader.get(),nullptr,0);
        context->CSSetShaderResources(2,1,&sensor);
        context->CSSetUnorderedAccessViews(0,1,&sink,nullptr);
        context->Begin(disjoint.get());
        context->End(gpuStart.get());
        context->Dispatch((width+31)/32,(height+15)/16,1);
        context->End(gpuEnd.get());
        context->End(disjoint.get());
        sink=nullptr;
        sensor=nullptr;
        context->CSSetUnorderedAccessViews(0,1,&sink,nullptr);
        context->CSSetShaderResources(2,1,&sensor);
        context->CSSetShader(shader.get(),nullptr,0);
        const auto transfer=Clock::now();
        context->CopyResource(pqReadback.get(),pqOutput.get());
        D3D11_MAPPED_SUBRESOURCE mapped{};
        require(context->Map(pqReadback.get(),0,D3D11_MAP_READ,0,&mapped),"Map packed PQ picture");
        mapMs=milliseconds(transfer);
        const auto outputStart=Clock::now();
        if(measured) stream.write(static_cast<const char*>(mapped.pData),pqBytes);
        outputMs=milliseconds(outputStart);
        context->Unmap(pqReadback.get(),0);
        if(!stream) throw std::runtime_error("The packed PQ picture pipe was closed");
        const auto clock=wait<D3D11_QUERY_DATA_TIMESTAMP_DISJOINT>(disjoint.get());
        const auto start=wait<UINT64>(gpuStart.get()),end=wait<UINT64>(gpuEnd.get());
        colorMs=(!clock.Disjoint && clock.Frequency)?1000.*double(end-start)/double(clock.Frequency):-1;
    }
};

}
