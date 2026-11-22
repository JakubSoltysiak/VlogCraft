#pragma once

#include "normalize_surface.h"
#include "../../native/media.h"
#include <climits>
#include <functional>

namespace render_phase2 {

class HardwareInputs {
    struct AvDevice {
        AVBufferRef* ref=nullptr;
        ~AvDevice(){ av_buffer_unref(&ref); }
    } avDevice;

    struct Description {
        std::uint32_t pathBytes,codedWidth,codedHeight,fittedWidth,fittedHeight;
        std::uint32_t clockwise,pq,pictures,timeNum,timeDen;
    };
    struct Source {
        std::unique_ptr<::Decoder> decoder;
        Description description{};
        std::vector<std::int64_t> timestamps;
        std::vector<std::int32_t> frames;
        unsigned slot=0;
        int index=-1,used=0;
        double normalizationMs=0;
    };

    GpuCompositor& gpu;
    SurfaceNormalizer normalize;
    std::vector<Source> sources;
    unsigned width,height;
    bool project;

    static void read(std::istream& file,void* target,std::size_t length) {
        if(!file.read(static_cast<char*>(target),std::streamsize(length)))
            throw std::runtime_error("Incomplete hardware source manifest");
    }

    void source(std::istream& file,Source& source,unsigned count) {
        auto& d=source.description;
        read(file,&d,sizeof(d));
        if(!d.pathBytes||d.pathBytes>32768||!d.codedWidth||!d.codedHeight||
           d.codedWidth>7680||d.codedHeight>4320||d.codedWidth%2||d.codedHeight%2||
           !d.fittedWidth||!d.fittedHeight||d.fittedWidth>width*2||d.fittedHeight>height*2||
           d.pictures>100000||!d.pictures||d.pq>1||d.clockwise>=360||d.clockwise%90||
           !d.timeNum||!d.timeDen||d.timeNum>INT_MAX||d.timeDen>INT_MAX)
            throw std::runtime_error("Unsupported hardware source dimensions or clock");
        const bool quarterTurn=d.clockwise%180!=0;
        if((quarterTurn?d.codedHeight:d.codedWidth)>2*d.fittedWidth ||
           (quarterTurn?d.codedWidth:d.codedHeight)>2*d.fittedHeight)
            throw std::runtime_error("Resident resize exceeds the tested filter support");
        std::string path(d.pathBytes,'\0');
        read(file,path.data(),path.size());
        source.timestamps.resize(d.pictures);
        source.frames.resize(count);
        read(file,source.timestamps.data(),source.timestamps.size()*sizeof(std::int64_t));
        read(file,source.frames.data(),source.frames.size()*sizeof(std::int32_t));
        if(std::adjacent_find(source.timestamps.begin(),source.timestamps.end(),std::greater_equal<>())!=source.timestamps.end())
            throw std::runtime_error("Invalid hardware frame-selection order");
        int previous=-1;
        for(int target:source.frames) {
            if(project&&target==-1) continue;
            if(target<0||target>=int(d.pictures)||target<previous)
                throw std::runtime_error("Invalid hardware frame-selection order");
            previous=target;
        }
        source.decoder=std::make_unique<::Decoder>(path,avDevice.ref,true,4);
        auto& dec=*source.decoder;
        const auto id=dec.codec->codec_id;
        const auto time=dec.file->streams[dec.stream]->time_base;
        if((id!=AV_CODEC_ID_H264 && id!=AV_CODEC_ID_HEVC)||time.num!=int(d.timeNum)||time.den!=int(d.timeDen))
            throw std::runtime_error("The resident decoder does not match the probed source");
    }

    void open_device() {
        avDevice.ref=av_hwdevice_ctx_alloc(AV_HWDEVICE_TYPE_D3D11VA);
        if(!avDevice.ref) throw std::runtime_error("D3D11VA hardware context unavailable");
        auto* context=reinterpret_cast<AVHWDeviceContext*>(avDevice.ref->data);
        auto* d3d=static_cast<AVD3D11VADeviceContext*>(context->hwctx);
        d3d->device=gpu.d3d_device();
        d3d->device->AddRef();
        d3d->BindFlags=D3D11_BIND_SHADER_RESOURCE;
        avcheck(av_hwdevice_ctx_init(avDevice.ref),"Open shared D3D11VA device");
    }

public:
    HardwareInputs(GpuCompositor& compositor,std::istream& file,unsigned w,unsigned h,unsigned count,
                   unsigned slots,bool isProject)
        :gpu(compositor),normalize(compositor,w,h),width(w),height(h),project(isProject) {
        std::uint32_t header=0;
        read(file,&header,sizeof(header));
        if(header!=(project?0x32445356u:0x31445356u))
            throw std::runtime_error("Invalid resident source manifest");
        av_log_set_level(AV_LOG_ERROR);
        std::uint32_t videos=2,stills=1;
        if(project) {
            read(file,&videos,sizeof(videos));
            read(file,&stills,sizeof(stills));
        }
        if(videos>4||stills>slots||videos+stills!=slots)
            throw std::runtime_error("Resident source budget exceeded");
        if(videos) open_device();
        sources.resize(videos);
        unsigned assigned=0;
        const auto slot_for=[&](unsigned fallback) {
            std::uint32_t slot=fallback;
            if(project) read(file,&slot,sizeof(slot));
            if(slot>=slots||(assigned&(1u<<slot))) throw std::runtime_error("Duplicate or invalid source slot");
            assigned|=1u<<slot;
            return slot;
        };
        for(unsigned i=0;i<videos;++i) {
            sources[i].slot=slot_for(i);
            source(file,sources[i],count);
        }
        std::vector<Pixel> overlay(stills?std::size_t(w)*h:0);
        for(unsigned i=0;i<stills;++i) {
            const auto slot=slot_for(videos+i);
            read(file,overlay.data(),overlay.size()*sizeof(Pixel));
            gpu.upload_slice(slot,overlay.data());
            gpu.finish_source_work();
        }
        if(file.peek()!=EOF) throw std::runtime_error("Unexpected trailing live source data");
    }

    double update(unsigned frame) {
        double elapsed=0;
        for(auto& input:sources) {
            const auto target=int(input.frames[frame]);
            if(target<0||target==input.index) continue;
            auto& decoder=*input.decoder;
            while(input.index<target) {
                if(!decoder.next()||decoder.frame->best_effort_timestamp!=input.timestamps[++input.index])
                    throw std::runtime_error("Hardware decoder changed the original PTS sequence");
            }
            AVFrame* picture=decoder.frame;
            const auto& d=input.description;
            if(picture->format!=AV_PIX_FMT_D3D11||picture->width!=int(d.codedWidth)||
               picture->height!=int(d.codedHeight)||
               (picture->color_range!=AVCOL_RANGE_MPEG&&picture->color_range!=AVCOL_RANGE_JPEG)||
               (picture->chroma_location!=AVCHROMA_LOC_LEFT&&picture->chroma_location!=AVCHROMA_LOC_CENTER&&
                picture->chroma_location!=AVCHROMA_LOC_UNSPECIFIED))
                throw std::runtime_error("Hardware decoder changed the supported surface contract");
            auto* mapping=reinterpret_cast<ID3D11Texture2D*>(picture->data[0]);
            D3D11_TEXTURE2D_DESC surface{};
            mapping->GetDesc(&surface);
            const bool pq=d.pq!=0;
            if((pq && (surface.Format!=DXGI_FORMAT_P010||picture->color_primaries!=AVCOL_PRI_BT2020||
                       picture->color_trc!=AVCOL_TRC_SMPTE2084||picture->colorspace!=AVCOL_SPC_BT2020_NCL))||
               (!pq && ((surface.Format!=DXGI_FORMAT_NV12&&surface.Format!=DXGI_FORMAT_P010)||
                        picture->color_primaries!=AVCOL_PRI_BT709||picture->color_trc!=AVCOL_TRC_BT709||
                        picture->colorspace!=AVCOL_SPC_BT709)))
                throw std::runtime_error("Hardware decoder changed the supported SDR/PQ interpretation");
            float padding[2],range[4];
            auto views=decoder.texture(gpu.d3d_device(),gpu.d3d_context(),false,padding,range);
            if(picture->color_range==AVCOL_RANGE_JPEG) {
                range[0]=0;
                range[1]=range[3]=surface.Format==DXGI_FORMAT_P010?65535.f/65472.f:1.f;
            }
            const bool quarterTurn=d.clockwise%180!=0;
            const auto result=normalize.normalize(views.first,views.second,{
                float(d.codedWidth),float(d.codedHeight),
                float(quarterTurn?d.codedHeight:d.codedWidth),float(quarterTurn?d.codedWidth:d.codedHeight),
                d.fittedWidth,d.fittedHeight,(int(width)-int(d.fittedWidth))/2,(int(height)-int(d.fittedHeight))/2,
                range[0],range[1],range[2],range[3],d.clockwise,d.pq,input.slot,
                unsigned(picture->chroma_location==AVCHROMA_LOC_CENTER),unsigned(project),{}});
            input.normalizationMs+=result;
            ++input.used;
            elapsed+=result;
        }
        return elapsed;
    }

    void measurements(std::ostream& stream) const {
        stream<<"[";
        for(unsigned i=0;i<sources.size();++i) {
            if(i)stream<<",";
            const auto& source=sources[i];
            stream<<"{\"decoded_pictures\":"<<source.decoder->frames<<",\"selected_pictures\":"<<source.used
                  <<",\"decode_wall_seconds\":"<<source.decoder->decode_s
                  <<",\"normalization_ms\":"<<source.normalizationMs
                  <<",\"source_cpu_transfer_bytes\":0,\"original_pts_verified\":true}";
        }
        stream<<"]";
    }
};

}
