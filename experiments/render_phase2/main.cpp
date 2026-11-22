#include "d3d_composite.h"

#include <psapi.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <utility>

using namespace render_phase2;

namespace {

struct InputHeader {
    std::uint32_t width,height,images,frames;
};

void read_exact(std::istream& stream,void* destination,std::size_t bytes) {
    if(!stream.read(static_cast<char*>(destination),std::streamsize(bytes)))
        throw std::runtime_error("Incomplete compositor fixture");
}

void validate(const Frame& frame,const InputHeader& input) {
    if(frame.width!=input.width || frame.height!=input.height ||
        !frame.layers || frame.layers>3 || !std::isfinite(frame.dissolve) ||
        frame.dissolve < -1 || frame.dissolve>1 || (frame.dissolve>=0 && frame.layers<2))
        throw std::runtime_error("Invalid frame parameters");
    for(unsigned i=0;i<frame.layers;++i) {
        const auto& layer=frame.layer[i];
        const float values[]={layer.scale,layer.cosine,layer.sine,layer.x,layer.y,
                              layer.opacity,layer.radius,layer.feather};
        if(!std::all_of(std::begin(values),std::end(values),[](float x){return std::isfinite(x);}) ||
            layer.scale<.1f || layer.scale>3 || std::abs(layer.x)>2 || std::abs(layer.y)>2 ||
            layer.opacity<0 || layer.opacity>1 || layer.radius<=0 || layer.feather<=0 ||
            layer.slice>=input.images || layer.mask>2)
            throw std::runtime_error("Invalid layer parameters");
    }
}

double process_cpu_ms() {
    FILETIME create{},exit{},kernel{},user{};
    if(!GetProcessTimes(GetCurrentProcess(),&create,&exit,&kernel,&user)) return -1;
    const auto ns100=[](FILETIME value){return (std::uint64_t(value.dwHighDateTime)<<32)|value.dwLowDateTime;};
    return double(ns100(kernel)+ns100(user))/10000;
}

}

int wmain(int argc,wchar_t** argv) {
    try {
        if(argc!=8) throw std::runtime_error("Use: phase2 mode plan sources output warmup workers upload");
        const std::wstring mode=argv[1];
        const bool gpu=mode==L"gpu32"||mode==L"gpu16"||mode==L"warp32";
        const bool half=mode==L"gpu16";
        if(!gpu && mode!=L"scalar" && mode!=L"simd") throw std::runtime_error("Unknown compositor mode");
        const int warmup=std::stoi(argv[5]), workers=std::stoi(argv[6]), uploads=std::stoi(argv[7]);
        if(warmup<0||warmup>120||workers<1||workers>24||(uploads!=0&&uploads!=1)||(!gpu&&uploads))
            throw std::runtime_error("Invalid trial setup");
        const bool save=std::wstring(argv[4])!=L"-";
        std::ifstream plan(std::filesystem::path(argv[2]),std::ios::binary);
        std::ifstream source(std::filesystem::path(argv[3]),std::ios::binary);
        const auto readStart=Clock::now();
        InputHeader input{};
        read_exact(plan,&input,sizeof(input));
        const bool hasPreciseGeometry=(input.images&0x80000000u)!=0;
        input.images&=0x7fffffffu;
        if(!input.width||input.width>7680||!input.height||input.height>4320||
           !input.images||input.images>8||!input.frames||input.frames>7200)
            throw std::runtime_error("Unsupported generated fixture dimensions");
        const auto count=std::size_t(input.width)*input.height;
        if(count*input.images*sizeof(Pixel)>1ull<<31)
            throw std::runtime_error("Generated fixture exceeds the test texture budget");
        std::vector<Frame> frames(input.frames);
        read_exact(plan,frames.data(),frames.size()*sizeof(Frame));
        std::vector<Geometry> geometry(input.frames*3);
        if(hasPreciseGeometry) {
            read_exact(plan,geometry.data(),geometry.size()*sizeof(Geometry));
            for(const auto& g:geometry)
                if(!std::isfinite(g.scale)||!std::isfinite(g.cosine)||!std::isfinite(g.sine)||
                   !std::isfinite(g.x)||!std::isfinite(g.y)||g.scale<.1||g.scale>3||
                   std::abs(g.cosine)>1||std::abs(g.sine)>1||std::abs(g.x)>2||std::abs(g.y)>2)
                    throw std::runtime_error("Invalid precise geometry");
        } else {
            for(unsigned index=0;index<input.frames;++index)
                for(unsigned n=0;n<frames[index].layers && n<3;++n) {
                    const auto& p=frames[index].layer[n];
                    geometry[index*3+n]={p.scale,p.cosine,p.sine,p.x,p.y};
                }
        }
        if(plan.peek()!=EOF) throw std::runtime_error("Unexpected extra frame parameters");
        for(const auto& frame:frames) validate(frame,input);
        std::vector<Pixel> texture(count*input.images);
        read_exact(source,texture.data(),texture.size()*sizeof(Pixel));
        if(source.peek()!=EOF) throw std::runtime_error("Unexpected extra source bytes");
        const double inputMs=milliseconds(readStart);

        std::vector<Pixel> result(gpu?0:count);
        std::vector<char> pixels(gpu&&save?count*(half?8:16):0);
        std::ofstream out;
        if(save) {
            const std::filesystem::path destination(argv[4]);
            if(std::filesystem::exists(destination)) throw std::runtime_error("Refusing to replace fixture output");
            out.open(destination,std::ios::binary);
            if(!out) throw std::runtime_error("Could not open the fixture output");
        }
        const auto setupStart=Clock::now();
        std::unique_ptr<GpuCompositor> accelerator;
        std::unique_ptr<CpuCompositor> cpu;
        if(gpu) accelerator=std::make_unique<GpuCompositor>(input.width,input.height,input.images,
            texture.data(),half,save,mode==L"warp32");
        else cpu=std::make_unique<CpuCompositor>(mode==L"scalar"?0:workers);
        if(gpu && !uploads) {
            std::vector<Pixel>().swap(texture);
        }
        const double setupMs=milliseconds(setupStart);

        struct Sample { double work, upload, dispatch, shading, readback, write; bool gpuValid; };
        std::vector<Sample> records(input.frames);
        std::vector<RowRange> coverage(input.height*3);
        const auto render=[&](unsigned index,bool measured){
            Sample value{};
            const auto began=Clock::now();
            const auto& frame=frames[index];
            prepare_ranges(frame,geometry.data()+index*3,coverage.data());
            if(gpu) {
                if(uploads) {
                    const auto start=Clock::now();
                    accelerator->upload(texture.data());
                    value.upload=milliseconds(start);
                }
                accelerator->render(frame,coverage.data());
                value.dispatch=accelerator->dispatchMs;
                value.shading=accelerator->shaderMs;
                value.gpuValid=accelerator->gpuClockValid;
                if(save) {
                    accelerator->download(pixels.data());
                    value.readback=accelerator->mapMs;
                }
            } else cpu->render(frame,coverage.data(),texture.data(),result.data());
            value.work=milliseconds(began);
            if(save && measured) {
                const auto writeStart=Clock::now();
                if(gpu) out.write(pixels.data(),std::streamsize(pixels.size()));
                else out.write(reinterpret_cast<const char*>(result.data()),std::streamsize(count*sizeof(Pixel)));
                if(!out) throw std::runtime_error("Could not write the composed picture");
                value.write=milliseconds(writeStart);
            }
            return value;
        };
        for(int i=0;i<warmup;++i) render(i%frames.size(),false);
        struct Footprint { unsigned frames; std::size_t rss; std::uint64_t local,shared; };
        std::vector<Footprint> footprints;
        const auto footprint=[&](unsigned frame) {
            PROCESS_MEMORY_COUNTERS snapshot{};
            GetProcessMemoryInfo(GetCurrentProcess(),&snapshot,sizeof(snapshot));
            if(gpu) accelerator->sample_memory();
            footprints.push_back({frame,snapshot.WorkingSetSize,gpu?accelerator->currentLocal:0,
                                  gpu?accelerator->currentShared:0});
        };
        footprint(0);
        const double cpuStart=process_cpu_ms();
        const auto began=Clock::now();
        for(unsigned i=0;i<input.frames;++i) {
            records[i]=render(i,true);
            if((i+1)%300==0 || i+1==input.frames) footprint(i+1);
        }
        if(out.is_open()) out.close();
        if(out.fail()) throw std::runtime_error("Could not finalize composed pictures");
        const double wall=milliseconds(began), cpuTime=process_cpu_ms()-cpuStart;
        if(gpu) accelerator->sample_memory();
        PROCESS_MEMORY_COUNTERS memory{};
        GetProcessMemoryInfo(GetCurrentProcess(),&memory,sizeof(memory));
        std::cout<<"{\"wall_ms\":"<<wall<<",\"cpu_ms\":"<<cpuTime
                 <<",\"input_ms\":"<<inputMs<<",\"setup_ms\":"<<setupMs
                 <<",\"peak_rss_bytes\":"<<memory.PeakWorkingSetSize
                 <<",\"gpu_local_bytes\":"<<(gpu?accelerator->localBytes:0)
                 <<",\"gpu_nonlocal_bytes\":"<<(gpu?accelerator->sharedBytes:0)
                 <<",\"initial_upload_ms\":"<<(gpu?accelerator->uploadMs:0)
                 <<",\"adapter\":\""<<(gpu?accelerator->adapterName:"")<<"\",\"memory_samples\":[";
        bool memoryComma=false;
        for(const auto& row:footprints) {
            if(memoryComma) std::cout<<',';
            memoryComma=true;
            std::cout<<"{\"frames\":"<<row.frames<<",\"rss_bytes\":"<<row.rss
                     <<",\"gpu_local_bytes\":"<<row.local<<",\"gpu_nonlocal_bytes\":"<<row.shared<<'}';
        }
        std::cout<<"],\"samples\":[";
        bool comma=false;
        for(const auto& row:records) {
            if(comma) std::cout<<',';
            comma=true;
            std::cout<<"{\"work_ms\":"<<row.work<<",\"upload_ms\":"<<row.upload
                     <<",\"dispatch_ms\":"<<row.dispatch<<",\"gpu_ms\":";
            if(row.gpuValid) std::cout<<row.shading; else std::cout<<"null";
            std::cout<<",\"readback_ms\":"<<row.readback<<",\"write_ms\":"<<row.write<<'}';
        }
        std::cout<<"]}\n";
    } catch(const std::exception& error) {
        std::cerr<<error.what()<<'\n';
        return 1;
    }
}
