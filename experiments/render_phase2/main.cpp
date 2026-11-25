#include "d3d_composite.h"

#include <psapi.h>
#include <fcntl.h>
#include <io.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <utility>

#ifdef VLOGCRAFT_RESIDENT_DECODE
#include "hardware_inputs.h"
#endif

using namespace render_phase2;

namespace {

struct InputHeader {
    std::uint32_t width,height,images,frames;
};

void read_exact(std::istream& stream,void* destination,std::size_t bytes) {
    if(!stream.read(static_cast<char*>(destination),std::streamsize(bytes)))
        throw std::runtime_error("Incomplete compositor fixture");
}

void read_live(void* destination,std::size_t bytes) {
    auto* cursor=static_cast<char*>(destination);
    while(bytes) {
        DWORD received=0;
        const DWORD requested=static_cast<DWORD>(std::min<std::size_t>(bytes,1u<<20));
        if(!ReadFile(GetStdHandle(STD_INPUT_HANDLE),cursor,requested,&received,nullptr) || !received)
            throw std::runtime_error("Incomplete live source picture");
        cursor+=received;
        bytes-=received;
    }
}

void finish_live() {
    char trailing=0;
    DWORD received=0;
    if(ReadFile(GetStdHandle(STD_INPUT_HANDLE),&trailing,1,&received,nullptr)) {
        if(received) throw std::runtime_error("Unexpected extra live source bytes");
    } else if(GetLastError()!=ERROR_BROKEN_PIPE)
        throw std::runtime_error("The live source stream could not be closed");
}

void validate(const Frame& frame,const InputHeader& input,bool project) {
    if(frame.width!=input.width || frame.height!=input.height ||
        frame.project!=unsigned(project) || (!project && !frame.layers) ||
        frame.layers>(project?layerBudget:legacyLayerBudget) || !std::isfinite(frame.dissolve) ||
        frame.dissolve < -1 || frame.dissolve>1 || (frame.dissolve>=0 && frame.layers<2))
        throw std::runtime_error("Invalid frame parameters");
    bool incoming=false,complete=false;
    if(project && (!std::isfinite(frame.white)||frame.white<0||frame.white>10))
        throw std::runtime_error("Invalid project white level");
    for(unsigned i=0;i<frame.layers;++i) {
        const auto& layer=frame.layer[i];
        const float values[]={layer.scale,layer.cosine,layer.sine,layer.x,layer.y,
                              layer.opacity,layer.radius,layer.feather};
        if(!std::all_of(std::begin(values),std::end(values),[](float x){return std::isfinite(x);}) ||
            layer.scale<.1f || layer.scale>3 || std::abs(layer.x)>2 || std::abs(layer.y)>2 ||
            layer.opacity<0 || layer.opacity>1 || layer.radius<=0 || layer.feather<=0 ||
            layer.slice>=input.images || layer.mask>2)
            throw std::runtime_error("Invalid layer parameters");
        if(project) {
            float gain;
            std::memcpy(&gain,&layer.reserved2,sizeof(gain));
            const auto op=layer.reserved1;
            if(!std::isfinite(gain)||gain<0||gain>4096||op>4||
               (incoming && op<2)||(!incoming && op>=2)||(complete&&op))
                throw std::runtime_error("Invalid project layer operation");
            incoming=op==1;
            complete|=op>=2;
        }
    }
    if(project&&(incoming||complete!=(frame.dissolve>=0)))
        throw std::runtime_error("Incomplete project transition");
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
        if(argc!=8 && argc!=9)
            throw std::runtime_error("Use: phase2 mode plan sources output warmup workers upload [fault-frame]");
        const std::wstring mode=argv[1];
        const bool firstExport=mode==L"gpu32-first-export";
        const bool gpu=firstExport||mode==L"gpu32"||mode==L"gpu16"||mode==L"warp32";
        const bool half=mode==L"gpu16";
        if(!gpu && mode!=L"scalar" && mode!=L"simd") throw std::runtime_error("Unknown compositor mode");
        const int warmup=std::stoi(argv[5]), workers=std::stoi(argv[6]), uploads=std::stoi(argv[7]);
        const int fault=argc==9?std::stoi(argv[8]):-1;
        if(warmup<0||warmup>120||workers<1||workers>24||(uploads!=0&&uploads!=1)||(!gpu&&uploads))
            throw std::runtime_error("Invalid trial setup");
        if(argc==9 && (!gpu || fault<1))
            throw std::runtime_error("Fault injection requires a GPU and an active frame");
        const std::wstring destinationMode=argv[4];
        const bool pq=destinationMode==L"@pq-stream";
        const bool pipe=pq||destinationMode==L"@gbr-stream";
        const std::wstring sourceMode=argv[3];
        const bool live=sourceMode==L"@live-stdin";
        const std::wstring residentPrefix=L"@resident:";
        const bool resident=sourceMode.rfind(residentPrefix,0)==0;
        const bool save=destinationMode!=L"-";
        if(pipe && (!gpu || half))
            throw std::runtime_error("Planar pipe requires an FP32 compositor");
        if(pipe && _setmode(_fileno(stdout),_O_BINARY)==-1)
            throw std::runtime_error("Cannot put the picture pipe into binary mode");
        if((live||resident) && (!gpu || !pipe || uploads || warmup))
            throw std::runtime_error("Live uploads require a binary FP32 pipe without warmup");
#ifndef VLOGCRAFT_RESIDENT_DECODE
        if(resident) throw std::runtime_error("Resident decoder is unavailable in this worker build");
#endif
        std::ifstream plan(std::filesystem::path(argv[2]),std::ios::binary);
        std::ifstream sourceFile;
        if(!live) sourceFile.open(std::filesystem::path(
            resident?sourceMode.substr(residentPrefix.size()):sourceMode),std::ios::binary);
        const auto readStart=Clock::now();
        InputHeader input{};
        read_exact(plan,&input,sizeof(input));
        const bool hasPreciseGeometry=(input.images&0x80000000u)!=0;
        const bool project=(input.images&0x40000000u)!=0;
        if(firstExport&&(!project||!resident||!pq))
            throw std::runtime_error("First-export verification requires a resident Main10 project");
        input.images&=0x3fffffffu;
        if(!input.width||input.width>7680||!input.height||input.height>4320||
           !input.images||input.images>8||!input.frames||input.frames>7200)
            throw std::runtime_error("Unsupported generated fixture dimensions");
        if(fault>=int(input.frames)) throw std::runtime_error("Fault is outside the trial");
        if(resident&&!project&&input.images!=3) throw std::runtime_error("Two video and one still source slots required");
        if(project&&!hasPreciseGeometry) throw std::runtime_error("Project plans require precise geometry");
        const auto count=std::size_t(input.width)*input.height;
        if(count*input.images*sizeof(Pixel)>1ull<<31)
            throw std::runtime_error("Generated fixture exceeds the test texture budget");
        std::vector<Frame> frames(input.frames);
        const unsigned wireLayers=project?layerBudget:legacyLayerBudget;
        for(auto& frame:frames) read_exact(plan,&frame,project?sizeof(Frame):legacyFrameSize);
        std::vector<Geometry> geometry(input.frames*layerBudget);
        if(hasPreciseGeometry) {
            for(unsigned index=0;index<input.frames;++index) {
                auto* row=geometry.data()+index*layerBudget;
                read_exact(plan,row,wireLayers*sizeof(Geometry));
                for(unsigned n=0;n<wireLayers;++n) {
                    const auto& g=row[n];
                    if(!std::isfinite(g.scale)||!std::isfinite(g.cosine)||!std::isfinite(g.sine)||
                       !std::isfinite(g.x)||!std::isfinite(g.y)||g.scale<.1||g.scale>3||
                       std::abs(g.cosine)>1||std::abs(g.sine)>1||std::abs(g.x)>2||std::abs(g.y)>2)
                        throw std::runtime_error("Invalid precise geometry");
                }
            }
        } else {
            for(unsigned index=0;index<input.frames;++index)
                for(unsigned n=0;n<frames[index].layers && n<legacyLayerBudget;++n) {
                    const auto& p=frames[index].layer[n];
                    geometry[index*layerBudget+n]={p.scale,p.cosine,p.sine,p.x,p.y};
                }
        }
        if(plan.peek()!=EOF) throw std::runtime_error("Unexpected extra frame parameters");
        for(const auto& frame:frames) validate(frame,input,project);
        std::vector<Pixel> texture(resident?0:count*input.images);
        if(live) read_live(texture.data(),texture.size()*sizeof(Pixel));
        else if(!resident) {
            read_exact(sourceFile,texture.data(),texture.size()*sizeof(Pixel));
            if(sourceFile.peek()!=EOF) throw std::runtime_error("Unexpected extra source bytes");
        }
        const double inputMs=milliseconds(readStart);

        std::vector<Pixel> result(gpu?0:count);
        std::vector<char> pixels(gpu&&save&&!pipe?count*(half?8:16):0);
        std::vector<float> planes(pipe&&!pq?count*3:0);
        std::ofstream out;
        if(save && !pipe) {
            const std::filesystem::path destination(argv[4]);
            if(std::filesystem::exists(destination)) throw std::runtime_error("Refusing to replace fixture output");
            out.open(destination,std::ios::binary);
            if(!out) throw std::runtime_error("Could not open the fixture output");
        }
        const auto setupStart=Clock::now();
        std::unique_ptr<GpuCompositor> accelerator;
        std::unique_ptr<CpuCompositor> cpu;
        if(gpu) accelerator=std::make_unique<GpuCompositor>(input.width,input.height,input.images,
            resident?nullptr:texture.data(),half,save,mode==L"warp32",pq,resident);
        else cpu=std::make_unique<CpuCompositor>(mode==L"scalar"?0:workers);
        if(firstExport && accelerator->adapterName!="AMD Radeon(TM) 890M Graphics")
            throw std::runtime_error("First-export verification requires the qualified Radeon 890M adapter");
        if(gpu && !uploads) {
            std::vector<Pixel>().swap(texture);
        }
#ifdef VLOGCRAFT_RESIDENT_DECODE
        std::unique_ptr<HardwareInputs> decoder;
        if(resident) decoder=std::make_unique<HardwareInputs>(*accelerator,sourceFile,
            input.width,input.height,input.frames,input.images,project);
#endif
        const double setupMs=milliseconds(setupStart);

        struct Sample { double work, upload, dispatch, shading, readback, write, color, copy, normalize; bool gpuValid; };
        std::vector<Sample> records(input.frames);
        std::vector<RowRange> coverage(input.height*layerBudget);
        std::vector<Pixel> updated(live?count:0);
        const auto render=[&](unsigned index,bool measured){
            Sample value{};
#ifdef VLOGCRAFT_RESIDENT_DECODE
            if(resident) value.normalize=decoder->update(index);
#endif
            if(live && index) {
                std::uint32_t changes=0;
                read_live(&changes,sizeof(changes));
                if(changes>>input.images) throw std::runtime_error("Invalid live texture slot");
                for(unsigned slot=0;slot<input.images;++slot) if(changes&(1u<<slot)) {
                    read_live(updated.data(),updated.size()*sizeof(Pixel));
                    const auto began=Clock::now();
                    accelerator->upload_slice(slot,updated.data());
                    value.upload+=milliseconds(began);
                }
            }
            const auto began=Clock::now();
            const auto& frame=frames[index];
            prepare_ranges(frame,geometry.data()+index*layerBudget,coverage.data());
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
                    if(pq) {
                        accelerator->stream_pq(std::cout,measured);
                        value.color=accelerator->colorMs;
                        value.copy=accelerator->copyMs;
                        value.write=accelerator->outputMs;
                    } else if(pipe) accelerator->download_gbr(planes.data());
                    else accelerator->download(pixels.data());
                    value.readback=accelerator->mapMs;
                }
            } else cpu->render(frame,coverage.data(),texture.data(),result.data());
            value.work=milliseconds(began)-value.write;
            if(save && measured && !pq) {
                const auto writeStart=Clock::now();
                if(pipe) {
                    std::cout.write(reinterpret_cast<const char*>(planes.data()),std::streamsize(planes.size()*sizeof(float)));
                    if(!std::cout) throw std::runtime_error("The picture pipe was closed");
                } else {
                    if(gpu) out.write(pixels.data(),std::streamsize(pixels.size()));
                    else out.write(reinterpret_cast<const char*>(result.data()),std::streamsize(count*sizeof(Pixel)));
                    if(!out) throw std::runtime_error("Could not write the composed picture");
                }
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
            if(int(i)==fault) require(DXGI_ERROR_DEVICE_REMOVED,"Injected D3D11 device removal");
            records[i]=render(i,true);
            if((i+1)%300==0 || i+1==input.frames) footprint(i+1);
        }
        if(live) finish_live();
        if(out.is_open()) out.close();
        if(out.fail()) throw std::runtime_error("Could not finalize composed pictures");
        if(pipe && !std::cout.flush()) throw std::runtime_error("Could not finish the picture pipe");
        const double wall=milliseconds(began), cpuTime=process_cpu_ms()-cpuStart;
        if(gpu) accelerator->sample_memory();
        PROCESS_MEMORY_COUNTERS memory{};
        GetProcessMemoryInfo(GetCurrentProcess(),&memory,sizeof(memory));
        auto& stats=pipe?std::cerr:std::cout;
        stats<<"{\"wall_ms\":"<<wall<<",\"cpu_ms\":"<<cpuTime
                 <<",\"input_ms\":"<<inputMs<<",\"setup_ms\":"<<setupMs
                 <<",\"peak_rss_bytes\":"<<memory.PeakWorkingSetSize
                 <<",\"gpu_local_bytes\":"<<(gpu?accelerator->localBytes:0)
                 <<",\"gpu_nonlocal_bytes\":"<<(gpu?accelerator->sharedBytes:0)
                 <<",\"initial_upload_ms\":"<<(gpu?accelerator->uploadMs:0)
                 <<",\"adapter\":\""<<(gpu?accelerator->adapterName:"")<<"\",\"memory_samples\":[";
        bool memoryComma=false;
        for(const auto& row:footprints) {
            if(memoryComma) stats<<',';
            memoryComma=true;
            stats<<"{\"frames\":"<<row.frames<<",\"rss_bytes\":"<<row.rss
                     <<",\"gpu_local_bytes\":"<<row.local<<",\"gpu_nonlocal_bytes\":"<<row.shared<<'}';
        }
        stats<<"]";
#ifdef VLOGCRAFT_RESIDENT_DECODE
        if(resident) {
            stats<<",\"resident_sources\":";
            decoder->measurements(stats);
        }
#endif
        stats<<",\"samples\":[";
        bool comma=false;
        for(const auto& row:records) {
            if(comma) stats<<',';
            comma=true;
            stats<<"{\"work_ms\":"<<row.work<<",\"upload_ms\":"<<row.upload
                     <<",\"dispatch_ms\":"<<row.dispatch<<",\"gpu_ms\":";
            if(row.gpuValid) stats<<row.shading; else stats<<"null";
            stats<<",\"readback_ms\":"<<row.readback<<",\"write_ms\":"<<row.write;
            if(pq) {
                stats<<",\"color_gpu_ms\":";
                if(row.color>=0) stats<<row.color; else stats<<"null";
                stats<<",\"pq_copy_gpu_ms\":";
                if(row.copy>=0) stats<<row.copy; else stats<<"null";
            }
            if(resident) stats<<",\"source_normalization_ms\":"<<row.normalize;
            stats<<'}';
        }
        stats<<"]}\n";
    } catch(const std::exception& error) {
        std::cerr<<error.what()<<'\n';
        return 1;
    }
}
