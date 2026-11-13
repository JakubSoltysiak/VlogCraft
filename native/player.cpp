#include "media.h"
#include "timeline.h"
#include "renderer.h"
#include "timing_wait.h"
struct Reader {
 Input& input;std::thread worker;
 Reader(Input& x):input(x),worker([&x]{std::string line;while(std::getline(std::cin,line)){x.command(line);if(x.stop)break;}x.stop=true;SetEvent(x.changed);}){}
 ~Reader(){input.stop=true;CancelSynchronousIo((HANDLE)worker.native_handle());if(worker.joinable())worker.join();}
};
int main(int argc,char** argv){
 try{
  std::string filename,capture;HWND parent=nullptr;bool offscreen=false,software=false;int limit=0;
  for(int i=1;i<argc;i++){
   std::string arg=argv[i];auto value=[&]()->std::string{if(i+1>=argc)throw std::runtime_error("Missing native option value");return argv[++i];};
   if(arg=="--plan")filename=value();else if(arg=="--parent")parent=(HWND)(uintptr_t)std::stoull(value());
   else if(arg=="--offscreen")offscreen=true;else if(arg=="--software")software=true;else if(arg=="--frames")limit=std::stoi(value());
   else if(arg=="--capture")capture=value();else throw std::runtime_error("Unknown native option");
  }
  auto launch=Clock::now();av_log_set_level(AV_LOG_QUIET);Plan plan(filename);Renderer renderer(plan,parent,offscreen);Input input;DeadlineWait deadline(input.changed);
  std::unique_ptr<Reader> reader;if(!limit)reader=std::make_unique<Reader>(input);
  std::map<std::string,std::unique_ptr<Producer>> producers;
  std::map<std::string,std::string> currentClip;std::map<std::string,const Clip*> clipLookup;for(auto& c:plan.clips)clipLookup[c.id]=&c;
  auto start=Clock::now(),lastReport=start;int64_t previous=-1,generation=-1,drawnGeneration=-1;uint64_t waiting=0,skipped=0,sourceWait=0,gpuWait=0,sourceSkipped=0,gpuSkipped=0,clockSkipped=0,clockBackwards=0,repeatedSource=0,clockHolds=0,distinctFrames=0,redraws=0;int64_t highest=-1;bool sawSourceWait=false,sawGpuWait=false;std::map<std::string,int64_t> lastPTS;size_t maxDecoders=0,maxQueue=0;
  std::vector<std::pair<const Clip*,Frame>> selected;bool ready=false,eos=false;double first=0;
  auto report=[&](const char* event,int64_t frame){
   if(renderer.display)renderer.display->stats();
   std::cout<<"{\"event\":\""<<event<<"\",\"sequence_frame\":"<<frame<<",\"generation\":"<<generation
    <<",\"submitted_frames\":"<<renderer.submitted<<",\"completed_frames\":"<<renderer.completed
    <<",\"surface_parented\":"<<(renderer.display&&renderer.display->parent?"true":"false")<<",\"surface_visible\":"<<(renderer.display&&IsWindowVisible(renderer.display->window)?"true":"false")<<",\"surface_width\":"<<(renderer.display?renderer.display->width:0)<<",\"surface_height\":"<<(renderer.display?renderer.display->height:0)
    <<",\"completed_sequence_frame\":"<<renderer.completedFrame<<",\"completed_generation\":"<<renderer.completedGeneration<<",\"present_calls\":"<<(renderer.display?renderer.display->calls:0)<<",\"dxgi_statistics_available\":"<<(renderer.display&&renderer.display->statistics?"true":"false")
    <<",\"dxgi_present_count\":"<<(renderer.display?renderer.display->displayed:0)<<",\"waiting\":"<<(!ready?"true":"false")
    <<",\"waiting_iterations\":"<<waiting<<",\"skipped_sequence_frames\":"<<skipped<<",\"eos\":"<<(eos?"true":"false")
    <<",\"peak_decoder_count\":"<<maxDecoders<<",\"peak_source_queue_frames\":"<<maxQueue
    <<",\"gpu_slot_budget\":"<<renderer.slots.size()<<",\"peak_inflight_gpu_frames\":"<<renderer.peakPending<<",\"float16\":"<<"true"<<",\"hdr_linear_scrgb\":"<<(plan.hdr?"true":"false")
    <<",\"first_frame_seconds\":"<<first<<",\"wall_seconds\":"<<seconds(launch)<<",\"selected\":[";
   bool comma=false;for(auto& item:selected){if(comma)std::cout<<",";comma=true;
    auto& p=*producers[item.first->asset];std::cout<<"{\"clip\":\""<<item.first->id<<"\",\"pts\":"<<item.second->best_effort_timestamp<<",\"timebase_num\":"<<p.base.num<<",\"timebase_den\":"<<p.base.den<<",\"hdr10plus_retained\":"<<(av_frame_get_side_data(item.second.get(),AV_FRAME_DATA_DYNAMIC_HDR_PLUS)?"true":"false")<<",\"target_tick\":"<<av_rescale_q(plan.sourceTick(*item.first,frame),item.first->timebase,p.base)+p.origin<<"}";}
   std::cout<<"],\"source_wait_iterations\":"<<sourceWait<<",\"gpu_wait_iterations\":"<<gpuWait<<",\"skipped_after_source_wait\":"<<sourceSkipped<<",\"skipped_after_gpu_wait\":"<<gpuSkipped<<",\"skipped_without_queue_wait\":"<<clockSkipped<<",\"distinct_sequence_submissions\":"<<distinctFrames<<",\"nonadvancing_redraws\":"<<redraws<<",\"clock_rewind_hold_iterations\":"<<clockHolds<<",\"clock_backwards_frames\":"<<clockBackwards<<",\"repeated_source_layer_frames\":"<<repeatedSource;
   std::cout<<",\"timings\":{\"context_wait\":";renderer.contextWait.json();std::cout<<",\"submit_cpu\":";renderer.submitTime.json();std::cout<<",\"completion_observation\":";renderer.completionAge.json();std::cout<<",\"composition_gpu\":";renderer.gpuTime.json();
   if(renderer.display){std::cout<<",\"present_call\":";renderer.display->presentTime.json();std::cout<<",\"present_call_interval\":";renderer.display->presentIntervals.json();}
   std::cout<<",\"wake_overshoot\":";deadline.overshoot.json();std::cout<<"},\"high_resolution_wait\":"<<(deadline.timer?"true":"false")<<",\"decoder_statistics\":[";bool dc=false;
   for(auto& entry:producers){auto& p=*entry.second;std::lock_guard<std::mutex> lock(p.guard);if(dc)std::cout<<",";dc=true;
    std::cout<<"{\"decoded_frames\":"<<p.decoded<<",\"decode_wall_seconds\":"<<p.decodedSeconds<<",\"seeks\":"<<p.seeks<<",\"queued_frames\":"<<p.queue.size()<<",\"warm_cache_frames\":"<<p.warm.size()<<",\"warm_cache_hits\":"<<p.warmHits<<"}";}
   std::cout<<"]}"<<std::endl;
  };
  while(!input.stop){
   MSG message;while(PeekMessageW(&message,nullptr,0,0,PM_REMOVE)){TranslateMessage(&message);DispatchMessageW(&message);}
   int64_t us,epoch;bool playing;if(limit){us=av_rescale_q(renderer.submitted,av_inv_q(plan.rate),AV_TIME_BASE_Q);epoch=0;playing=false;}
   else input.snapshot(us,epoch,playing);
   int64_t frame=limit?(int64_t)renderer.submitted:av_rescale_q_rnd(us+1,AV_TIME_BASE_Q,av_inv_q(plan.rate),(AVRounding)AV_ROUND_DOWN);
   // The clock anchor is an exact sequence frame plus an independently advancing audio sample clock.
   frame=std::max<int64_t>(0,frame);eos=frame>=plan.end;frame=std::min(frame,plan.end-1);
   renderer.available();
   if(playing&&drawnGeneration==epoch&&frame<previous){clockHolds++;frame=previous;}
   if(drawnGeneration==epoch&&frame==previous&&!(renderer.display&&renderer.display->needsResize())){if(seconds(lastReport)>.1){report("status",frame);lastReport=Clock::now();}deadline.wait(playing?std::clamp<int64_t>(av_rescale_q(previous+1,av_inv_q(plan.rate),AV_TIME_BASE_Q)-us,100,5000):20000);continue;}
   bool reset=generation!=epoch;generation=epoch;
   std::vector<Clip*> active;std::map<std::string,bool> wanted;
   for(auto& c:plan.clips)if(c.position<=frame&&frame<c.end){active.push_back(&c);wanted[c.asset]=true;}
   if(active.size()>3)throw std::runtime_error("Native layer budget exceeded");
   bool evict=false;for(auto& p:producers)if(!wanted.count(p.first))evict=true;
   if(evict){renderer.drain();renderer.textures.clear();for(auto i=producers.begin();i!=producers.end();)if(!wanted.count(i->first)){currentClip.erase(i->first);i=producers.erase(i);}else ++i;}
   for(auto* c:active){
    if(!producers.count(c->asset)){producers[c->asset]=std::make_unique<Producer>(*c,renderer.hw,software,8+(int)renderer.slots.size()-3,Renderer::cacheBudget());currentClip[c->asset]=c->id;reset=true;}
    c->sourceRotation=producers[c->asset]->rotation;
    if(reset||(currentClip[c->asset]!=c->id&&!plan.adjacent(*clipLookup.at(currentClip[c->asset]),*c)))producers[c->asset]->reset(plan.sourceTick(*c,frame),c->timebase);
    currentClip[c->asset]=c->id;
   }
   maxDecoders=std::max(maxDecoders,producers.size());selected.clear();ready=true;
   for(auto* c:active){
    auto& p=*producers[c->asset];bool available=false;auto f=p.at(plan.sourceTick(*c,frame),c->timebase,available);
    {std::lock_guard<std::mutex> lock(p.guard);maxQueue=std::max(maxQueue,p.peak);}
    if(!available){ready=false;break;}selected.push_back({c,f});
   }
   Slot* slot=renderer.available();
   if(!ready||!slot){waiting++;if(!ready){sourceWait++;sawSourceWait=true;}else{gpuWait++;sawGpuWait=true;}if(seconds(lastReport)>.1){report("status",frame);lastReport=Clock::now();}deadline.wait(1000);continue;}
   if(previous>=0&&drawnGeneration==generation&&frame>previous+1){auto lost=frame-previous-1;skipped+=lost;if(sawSourceWait)sourceSkipped+=lost;else if(sawGpuWait)gpuSkipped+=lost;else clockSkipped+=lost;}
   if(drawnGeneration==generation&&frame<previous)clockBackwards++;
   for(auto& item:selected){auto pts=item.second->best_effort_timestamp;if(drawnGeneration==generation&&frame>previous&&lastPTS.count(item.first->asset)&&lastPTS[item.first->asset]==pts)repeatedSource++;lastPTS[item.first->asset]=pts;}
   sawSourceWait=sawGpuWait=false;
   if(drawnGeneration!=generation){highest=frame;distinctFrames++;}else if(frame>highest){highest=frame;distinctFrames++;}else redraws++;
   renderer.draw(*slot,plan,frame,generation,selected);
   if(!first)first=seconds(launch);
   previous=frame;drawnGeneration=generation;
   if(!capture.empty()&&(renderer.submitted==1||(limit&&renderer.submitted==(uint64_t)limit)))renderer.capture(*slot,capture+"-"+std::to_string(frame)+".rgba16f");
   if(seconds(lastReport)>.1){report("status",frame);lastReport=Clock::now();}
   if(limit&&renderer.submitted>=(uint64_t)limit)break;
  }
  renderer.drain();report("closed",previous);return 0;
 }catch(const std::exception& error){std::string message=error.what();const char* code=message.find("HDR display is not active")!=std::string::npos?"hdr_display_inactive":message.find("color contract")!=std::string::npos?"color_contract":"native_failure";std::cout<<"{\"event\":\"error\",\"code\":\""<<code<<"\",\"hresult\":"<<(uint32_t)nativeHResult<<",\"av_error\":"<<nativeAVError<<",\"reason\":\"Native decode, display or device failure; use the reference renderer\"}"<<std::endl;return 1;}
}
