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
    struct AccessPoint {
        std::int64_t dts,position;
        std::uint32_t picture,kind;
        std::vector<std::int64_t> decodableLeading;
    };
    struct Playback {
        std::unique_ptr<::Decoder> decoder;
        int index=-1;
        unsigned lastFrame=0;
    };
    struct Source {
        std::shared_ptr<Playback> playback;
        std::string path;
        Description description{};
        std::vector<std::int64_t> timestamps;
        std::vector<std::int32_t> frames;
        std::vector<AccessPoint> accessPoints;
        std::vector<const AccessPoint*> seeks;
        unsigned slot=0;
        unsigned firstFrame=0,lastFrame=0;
        int index=-1,used=0,decoded=0;
        bool reused=false;
        double normalizationMs=0,decodeSeconds=0,seekSeconds=0;
    };

    GpuCompositor& gpu;
    SurfaceNormalizer normalize;
    std::vector<Source> sources;
    unsigned width,height;
    bool project,indexed=false;

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
        source.path.resize(d.pathBytes);
        read(file,source.path.data(),source.path.size());
        source.timestamps.resize(d.pictures);
        source.frames.resize(count);
        read(file,source.timestamps.data(),source.timestamps.size()*sizeof(std::int64_t));
        read(file,source.frames.data(),source.frames.size()*sizeof(std::int32_t));
        if(std::adjacent_find(source.timestamps.begin(),source.timestamps.end(),std::greater_equal<>())!=source.timestamps.end())
            throw std::runtime_error("Invalid hardware frame-selection order");
        int previous=-1;
        for(unsigned i=0;i<count;++i) {
            const int target=source.frames[i];
            if(project&&target==-1) continue;
            if(target<0||target>=int(d.pictures)||target<previous)
                throw std::runtime_error("Invalid hardware frame-selection order");
            if(previous==-1) source.firstFrame=i;
            source.lastFrame=i;
            previous=target;
        }
        if(indexed) {
            if(previous<0) throw std::runtime_error("An indexed video has no selected pictures");
            read_access_points(file,source);
        }
    }

    void read_access_points(std::istream& file,Source& source) {
        std::uint32_t count=0,previous=0;
        read(file,&count,sizeof(count));
        if(count>=source.timestamps.size()) throw std::runtime_error("Invalid random-access index size");
        source.accessPoints.resize(count);
        for(auto& point:source.accessPoints) {
            std::uint32_t leading=0;
            read(file,&point.dts,sizeof(point.dts));
            read(file,&point.position,sizeof(point.position));
            read(file,&point.picture,sizeof(point.picture));
            read(file,&point.kind,sizeof(point.kind));
            read(file,&leading,sizeof(leading));
            if(point.picture<=previous||point.picture>=source.timestamps.size()||point.dts==AV_NOPTS_VALUE||
               point.position<0||leading>32||
               (point.kind!=5&&(point.kind<16||point.kind>21))||
               (leading&&point.kind!=16&&point.kind!=17&&point.kind!=19&&point.kind!=21))
                throw std::runtime_error("Invalid random-access index entry");
            point.decodableLeading.resize(leading);
            if(leading) {
                auto& ticks=point.decodableLeading;
                read(file,ticks.data(),ticks.size()*sizeof(ticks.front()));
                if(std::adjacent_find(ticks.begin(),ticks.end(),std::greater_equal<>())!=ticks.end()||
                   ticks.back()>=source.timestamps[point.picture]||ticks.front()==AV_NOPTS_VALUE||
                   !std::includes(source.timestamps.begin(),source.timestamps.end(),ticks.begin(),ticks.end()))
                    throw std::runtime_error("Invalid random-access leading pictures");
            }
            previous=point.picture;
        }
    }

    void open_source(Source& source,unsigned before) {
        if(indexed) {
            // The slots keep distinct normalization caches. A single decode
            // cursor can serve identical source clocks on disjoint ranges.
            for(unsigned i=before;i>0;--i) {
                auto& prior=sources[i-1];
                const auto& a=prior.description;
                const auto& b=source.description;
                if(source.path!=prior.path || prior.playback->lastFrame!=prior.lastFrame ||
                   prior.lastFrame>=source.firstFrame || a.timeNum!=b.timeNum || a.timeDen!=b.timeDen ||
                   a.codedWidth!=b.codedWidth || a.codedHeight!=b.codedHeight ||
                   prior.frames[prior.lastFrame]>source.frames[source.firstFrame]) continue;
                if(prior.timestamps.size()>source.timestamps.size()||
                   !std::equal(prior.timestamps.begin(),prior.timestamps.end(),source.timestamps.begin())) continue;
                // Continue through a nearby cut on the live cursor. For a
                // distant cut, start at an IRAP on a fresh codec context so
                // delayed pictures from the old decode cannot enter the range.
                const int cutStart=source.frames[source.firstFrame];
                const int cutEnd=prior.frames[prior.lastFrame];
                const auto opportunities=std::count_if(source.accessPoints.begin(),source.accessPoints.end(),
                    [&](const AccessPoint& point){return int(point.picture)>cutEnd&&int(point.picture)<=cutStart;});
                if(opportunities>2) continue;
                source.playback=prior.playback;
                source.reused=true;
                break;
            }
        }
        if(!source.playback) {
            source.playback=std::make_shared<Playback>();
            source.playback->decoder=std::make_unique<::Decoder>(source.path,avDevice.ref,true,4);
        }
        source.playback->lastFrame=source.lastFrame;
        auto& dec=*source.playback->decoder;
        const auto id=dec.codec->codec_id;
        const auto time=dec.file->streams[dec.stream]->time_base;
        const auto& d=source.description;
        if((id!=AV_CODEC_ID_H264 && id!=AV_CODEC_ID_HEVC)||time.num!=int(d.timeNum)||time.den!=int(d.timeDen))
            throw std::runtime_error("The resident decoder does not match the probed source");
        if(indexed) {
            for(int i=0;i<dec.stream;++i)
                if(dec.file->streams[i]->codecpar->codec_type==AVMEDIA_TYPE_VIDEO)
                    throw std::runtime_error("The resident decoder did not select the indexed video stream");
            if(std::any_of(source.accessPoints.begin(),source.accessPoints.end(),[&](const AccessPoint& point){
                return (id==AV_CODEC_ID_H264)!=(point.kind==5);
            })) throw std::runtime_error("The indexed random-access picture does not match the codec");
            dec.codec->err_recognition|=AV_EF_EXPLODE;
        }
    }

    void advance(Source& source,int target) {
        auto& cursor=*source.playback;
        auto& decoder=*cursor.decoder;
        const auto beganWith=decoder.frames;
        const auto decodeAtStart=decoder.decode_s;
        const AccessPoint* anchor=nullptr;
        if(cursor.index<0&&!source.accessPoints.empty()) {
            const auto after=std::upper_bound(source.accessPoints.begin(),source.accessPoints.end(),target,
                [](int picture,const AccessPoint& point){return picture<int(point.picture);});
            if(after!=source.accessPoints.begin()&&int((after-1)->picture)>cursor.index+1)
                anchor=&*(after-1);
        }
        const auto anchorPts=anchor?source.timestamps[anchor->picture]:AV_NOPTS_VALUE;
        if(anchor) {
            const auto began=::Clock::now();
            decoder.seek_indexed_packet(anchorPts,anchor->dts,anchor->position);
            source.seekSeconds+=::seconds(began);
            source.seeks.push_back(anchor);
            cursor.index=int(anchor->picture)-1;
        }
        auto leading=AV_NOPTS_VALUE;
        while(cursor.index<target) {
            if(!decoder.next()) throw std::runtime_error("Hardware decoder stopped before the indexed picture");
            const auto* frame=decoder.frame;
            const auto pts=frame->best_effort_timestamp;
            if(indexed&&(frame->flags&AV_FRAME_FLAG_CORRUPT||frame->decode_error_flags))
                throw std::runtime_error("Hardware decoder reported a damaged indexed picture");
            if(anchor&&pts<anchorPts) {
                if(pts<=leading||
                   !std::binary_search(anchor->decodableLeading.begin(),anchor->decodableLeading.end(),pts))
                    throw std::runtime_error("Unverified leading picture at "+std::to_string(pts)+
                        " (frame PTS "+std::to_string(frame->pts)+", target IRAP "+
                        std::to_string(anchorPts)+", type "+std::to_string(anchor->kind)+")");
                leading=pts;
                continue;
            }
            if(pts!=source.timestamps[++cursor.index]||
               (anchor&&pts==anchorPts&&!(frame->flags&AV_FRAME_FLAG_KEY)))
                throw std::runtime_error("Hardware decoder changed the original PTS sequence");
        }
        source.index=target;
        source.decoded+=decoder.frames-beganWith;
        source.decodeSeconds+=decoder.decode_s-decodeAtStart;
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
        indexed=project&&header==0x33445356u;
        if(!indexed&&header!=(project?0x32445356u:0x31445356u))
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
            open_source(sources[i],i);
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
            auto& decoder=*input.playback->decoder;
            advance(input,target);
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
            stream<<"{\"decoded_pictures\":"<<source.decoded<<",\"selected_pictures\":"<<source.used
                  <<",\"decode_wall_seconds\":"<<source.decodeSeconds
                  <<",\"seek_wall_seconds\":"<<source.seekSeconds
                  <<",\"decoder_reused\":"<<(source.reused?"true":"false")
                  <<",\"seek_points\":[";
            bool comma=false;
            for(const auto* point:source.seeks) {
                if(comma) stream<<',';
                comma=true;
                stream<<"{\"picture_index\":"<<point->picture
                      <<",\"pts\":"<<source.timestamps[point->picture]<<",\"dts\":"<<point->dts
                      <<",\"packet_position\":"<<point->position<<",\"nal_type\":"<<point->kind
                      <<",\"decodable_leading_pictures\":"<<point->decodableLeading.size()<<'}';
            }
            stream<<']'
                  <<",\"normalization_ms\":"<<source.normalizationMs
                  <<",\"source_cpu_transfer_bytes\":0,\"original_pts_verified\":true}";
        }
        stream<<"]";
    }
};

}
