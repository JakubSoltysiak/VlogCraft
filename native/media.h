#pragma once
// Shared libav/D3D11 primitives; original benchmark remains a separate entry point.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <dxgi.h>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
extern "C" {
#include <libavformat/avformat.h>
#include <libavcodec/avcodec.h>
#include <libavutil/hwcontext.h>
#include <libavutil/hwcontext_d3d11va.h>
#include <libavutil/pixdesc.h>
#include <libswscale/swscale.h>
}
using Clock=std::chrono::steady_clock;
double seconds(Clock::time_point a){return std::chrono::duration<double>(Clock::now()-a).count();}
thread_local HRESULT nativeHResult=S_OK;thread_local int nativeAVError=0;
void check(HRESULT h,const char* label){if(FAILED(h)){nativeHResult=h;char b[200];snprintf(b,sizeof(b),"%s HRESULT=0x%08lx",label,(unsigned long)h);throw std::runtime_error(b);}}
void avcheck(int h,const char* label){if(h<0){nativeAVError=h;char e[256];av_strerror(h,e,sizeof(e));throw std::runtime_error(std::string(label)+": "+e);}}
template<class T> struct Com {
    T* p=nullptr;~Com(){if(p)p->Release();}T** out(){if(p){p->Release();p=nullptr;}return &p;}
    T* operator->()const{return p;}operator T*()const{return p;}
};
enum AVPixelFormat hardware_format(AVCodecContext*,const enum AVPixelFormat* choices){
    for(auto p=choices;*p!=AV_PIX_FMT_NONE;p++)if(*p==AV_PIX_FMT_D3D11)return *p;
    return AV_PIX_FMT_NONE;
}
struct Decoder {
    AVFormatContext* file=nullptr;AVCodecContext* codec=nullptr;
    AVPacket* packet=av_packet_alloc();AVFrame* frame=av_frame_alloc();AVFrame* host=av_frame_alloc();
    SwsContext* scaler=nullptr;int stream=-1;bool drained=false;bool eof=false;
    std::vector<unsigned char> packed;Com<ID3D11Texture2D> uploaded;
    std::map<std::pair<ID3D11Texture2D*,int>,std::pair<ID3D11ShaderResourceView*,ID3D11ShaderResourceView*>> views;
    double decode_s=0,transfer_s=0,upload_s=0;int frames=0;bool direct=false;
    Decoder(const std::string& path,AVBufferRef* hw,bool useHardware,int extraHardwareFrames=8){
        int workers=1;if(const char* value=std::getenv("VLOGCRAFT_NATIVE_DECODE_THREADS")){char* end=nullptr;long n=std::strtol(value,&end,10);if(*end||n<1||n>4)throw std::runtime_error("Invalid native decoder worker budget");workers=(int)n;}
        if(!std::filesystem::is_regular_file(std::filesystem::u8path(path)))throw std::runtime_error("A local media file is required");
        AVDictionary* options=nullptr;av_dict_set(&options,"protocol_whitelist","file",0);
        int opened=avformat_open_input(&file,path.c_str(),nullptr,&options);av_dict_free(&options);avcheck(opened,"open");
        avcheck(avformat_find_stream_info(file,nullptr),"stream info");
        stream=av_find_best_stream(file,AVMEDIA_TYPE_VIDEO,-1,-1,nullptr,0);avcheck(stream,"video stream");
        auto decoder=avcodec_find_decoder(file->streams[stream]->codecpar->codec_id);
        codec=avcodec_alloc_context3(decoder);avcheck(avcodec_parameters_to_context(codec,file->streams[stream]->codecpar),"parameters");
        codec->thread_count=workers;codec->extra_hw_frames=extraHardwareFrames;
        if(useHardware){codec->hw_device_ctx=av_buffer_ref(hw);codec->get_format=hardware_format;}
        avcheck(avcodec_open2(codec,decoder,nullptr),"codec open");
    }
    ~Decoder(){
        for(auto& v:views){v.second.first->Release();v.second.second->Release();}
        sws_freeContext(scaler);av_frame_free(&host);av_frame_free(&frame);av_packet_free(&packet);
        avcodec_free_context(&codec);avformat_close_input(&file);
    }
    bool next(){
        auto start=Clock::now();av_frame_unref(frame);
        while(true){
            int r=avcodec_receive_frame(codec,frame);
            if(r==0){decode_s+=seconds(start);frames++;return true;}
            if(r==AVERROR_EOF){decode_s+=seconds(start);return false;}
            if(r!=AVERROR(EAGAIN))avcheck(r,"receive frame");
            if(eof){if(!drained){avcheck(avcodec_send_packet(codec,nullptr),"flush decoder");drained=true;}else throw std::runtime_error("decoder made no progress");}
            else {
                while(true){r=av_read_frame(file,packet);if(r<0){eof=true;break;}if(packet->stream_index==stream)break;av_packet_unref(packet);}
                if(!eof){avcheck(avcodec_send_packet(codec,packet),"send packet");av_packet_unref(packet);}
            }
        }
    }
    void seek(double at){
        avcheck(av_seek_frame(file,stream,(int64_t)(at/av_q2d(file->streams[stream]->time_base)),AVSEEK_FLAG_BACKWARD),"seek");
        avcodec_flush_buffers(codec);eof=drained=false;
        while(next()){if(frame->best_effort_timestamp*av_q2d(file->streams[stream]->time_base)+1e-9>=at)return;}
        throw std::runtime_error("seek past end");
    }
    std::pair<ID3D11ShaderResourceView*,ID3D11ShaderResourceView*> texture(ID3D11Device* device,ID3D11DeviceContext* context,bool download,float* uvscale,float* range){
        AVFrame* src=frame;ID3D11Texture2D* tex=nullptr;int slice=0;
        if(frame->format==AV_PIX_FMT_D3D11&&!download){
            tex=(ID3D11Texture2D*)frame->data[0];slice=(int)(intptr_t)frame->data[1];direct=true;
        }else{
            auto start=Clock::now();
            if(frame->format==AV_PIX_FMT_D3D11){av_frame_unref(host);avcheck(av_hwframe_transfer_data(host,frame,0),"hardware download");src=host;}
            transfer_s+=seconds(start);start=Clock::now();
            // Transfer controls preserve source depth; no mandatory 8-bit intermediate.
            const AVPixFmtDescriptor* format=av_pix_fmt_desc_get((AVPixelFormat)src->format);
            bool high=format&&format->comp[0].depth>8;int bytes=high?2:1;
            AVPixelFormat packedFormat=high?AV_PIX_FMT_P010LE:AV_PIX_FMT_NV12;
            packed.resize((size_t)src->width*src->height*3/2*bytes);
            scaler=sws_getCachedContext(scaler,src->width,src->height,(AVPixelFormat)src->format,src->width,src->height,packedFormat,SWS_BILINEAR,nullptr,nullptr,nullptr);
            if(!scaler)throw std::runtime_error("sws allocation");
            uint8_t* dst[4]={packed.data(),packed.data()+(size_t)src->width*src->height*bytes,nullptr,nullptr};int pitch[4]={src->width*bytes,src->width*bytes,0,0};
            sws_scale(scaler,src->data,src->linesize,0,src->height,dst,pitch);
            if(!uploaded.p){D3D11_TEXTURE2D_DESC d={};d.Width=src->width;d.Height=src->height;d.MipLevels=1;d.ArraySize=1;d.Format=high?DXGI_FORMAT_P010:DXGI_FORMAT_NV12;d.SampleDesc.Count=1;d.BindFlags=D3D11_BIND_SHADER_RESOURCE;
                check(device->CreateTexture2D(&d,nullptr,uploaded.out()),"upload texture");}
            tex=uploaded.p;context->UpdateSubresource(tex,0,nullptr,packed.data(),src->width*bytes,0);
            upload_s+=seconds(start);
        }
        D3D11_TEXTURE2D_DESC desc;tex->GetDesc(&desc);
        uvscale[0]=(float)frame->width/desc.Width;uvscale[1]=(float)frame->height/desc.Height;
        bool ten=desc.Format==DXGI_FORMAT_P010;
        if(desc.Format!=DXGI_FORMAT_NV12&&!ten)throw std::runtime_error("only NV12/P010 implemented");
        range[0]=ten?4096.f/65535:16.f/255;range[1]=ten?65535.f/56064:255.f/219;
        range[2]=ten?32768.f/65535:128.f/255;range[3]=ten?65535.f/57344:255.f/224;
        auto key=std::make_pair(tex,slice);auto old=views.find(key);if(old!=views.end())return old->second;
        D3D11_SHADER_RESOURCE_VIEW_DESC d={};d.Format=ten?DXGI_FORMAT_R16_UNORM:DXGI_FORMAT_R8_UNORM;
        d.ViewDimension=D3D11_SRV_DIMENSION_TEXTURE2DARRAY;d.Texture2DArray.MipLevels=1;d.Texture2DArray.ArraySize=1;d.Texture2DArray.FirstArraySlice=slice;
        ID3D11ShaderResourceView *y=nullptr,*uv=nullptr;
        check(device->CreateShaderResourceView(tex,&d,&y),"luma view");
        d.Format=ten?DXGI_FORMAT_R16G16_UNORM:DXGI_FORMAT_R8G8_UNORM;
        HRESULT r=device->CreateShaderResourceView(tex,&d,&uv);if(FAILED(r)){y->Release();check(r,"chroma view");}
        views[key]={y,uv};return {y,uv};
    }
};
const char* shader=R"HLSL(
Texture2DArray<float> Y:register(t0);Texture2DArray<float2> UV:register(t1);SamplerState S:register(s0);
cbuffer Params:register(b0){float4 geometry;float4 effect;float4 range;float4 source;float4 coefficients;}
struct Vertex {float4 pos:SV_Position;float2 uv:TEXCOORD0;};
Vertex vs(uint id:SV_VertexID){Vertex v;float2 q=float2((id<<1)&2,id&2);v.uv=q;v.pos=float4(q*float2(2,-2)+float2(-1,1),0,1);return v;}
float4 ps(Vertex v):SV_Target{
    float2 q=(v.uv-geometry.xy);q=float2(effect.x*q.x+effect.y*q.y,-effect.y*q.x+effect.x*q.y)/geometry.zw+.5;
    if(any(q<0)||any(q>1))discard;
    float y=(Y.Sample(S,float3(q*source.xy,0))-range.x)*range.y;
    float2 uv=(UV.Sample(S,float3(q*source.xy,0))-range.z)*range.w;
    float3 rgb=float3(y+coefficients.x*uv.y,y-coefficients.y*uv.x-coefficients.z*uv.y,y+coefficients.w*uv.x);
    rgb=saturate(rgb+effect.w);
    return float4(rgb,effect.z);
}
)HLSL";
struct Parameters {float geometry[4],effect[4],range[4],source[4],matrix[4];};
