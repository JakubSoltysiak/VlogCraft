#include "media.h"
#include "timeline.h"
#include "renderer.h"
#include "timing_wait.h"
#include <set>
struct CompletionStamps {
 int64_t generation=-1,sequenceEnd=0,pictureDeadline=0,draw=0,gpu=0,eos=0,drained=0,joined=0;
 static int64_t now(){
  LARGE_INTEGER ticks,frequency;QueryPerformanceCounter(&ticks);QueryPerformanceFrequency(&frequency);
  return ticks.QuadPart/frequency.QuadPart*1000000+(ticks.QuadPart%frequency.QuadPart)*1000000/frequency.QuadPart;
 }
 void json(std::ostream& out)const{
  out<<",\"completion_stamps_us\":{\"generation\":"<<generation<<",\"sequence_end_deadline_qpc\":"<<sequenceEnd
     <<",\"last_picture_deadline_qpc\":"<<pictureDeadline<<",\"final_draw_return_qpc\":"<<draw
     <<",\"final_gpu_observed_qpc\":"<<gpu<<",\"first_clock_eos_qpc\":"<<eos<<",\"gpu_drained_qpc\":"<<drained
     <<",\"producer_join_qpc\":"<<joined<<",\"status_write_qpc\":"<<now()<<"}";
 }
};
struct Reader {
 Input& input;std::thread worker;
 Reader(Input& x):input(x),worker([&x]{std::string line;while(std::getline(std::cin,line)){x.command(line);if(x.stop)return;}x.command("CLOSE");}){}
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
  std::unique_ptr<StallWatch> flight;
  if(const char* path=std::getenv("VLOGCRAFT_STALL_CAPTURE"))if(*path)flight=std::make_unique<StallWatch>(path);
  WatchThread renderLane(flight?0:-1);
  const bool traceCompletion=std::getenv("VLOGCRAFT_COMPLETION_TRACE")!=nullptr;
  CompletionStamps completion;
  const char* tracePath=std::getenv("VLOGCRAFT_NATIVE_TRACE_FILE");
  std::unique_ptr<SourceTrace> trace;if(tracePath){trace=std::make_unique<SourceTrace>();sourceTrace=trace.get();}
  auto launch=Clock::now();av_log_set_level(AV_LOG_QUIET);Plan plan(filename);Renderer renderer(plan,parent,offscreen);Input input;DeadlineWait deadline(input.changed);
  if(flight)flight->start(plan.end,plan.rate.num,plan.rate.den);
  std::unique_ptr<Reader> reader;if(!limit)reader=std::make_unique<Reader>(input);
  std::map<std::string,std::unique_ptr<Producer>> producers;
  std::map<std::string,std::string> currentClip;std::map<std::string,const Clip*> clipLookup;for(auto& c:plan.clips)clipLookup[c.id]=&c;
  std::map<std::string,int> sourceIds;int nextDecoderId=0;
  if(trace||flight)for(auto& c:plan.clips)if(!sourceIds.count(c.asset))sourceIds.emplace(c.asset,(int)sourceIds.size());
  // Resolve exact source/sequence boundaries once, outside the playback loop.
  std::map<const Clip*,const Clip*> rewinds;
  {
  std::map<std::pair<std::string,int64_t>,const Clip*> starts;
  for(auto& c:plan.clips){
   auto result=starts.emplace(std::make_pair(c.asset,c.position),&c);
   if(!result.second)result.first->second=nullptr;
  }
  for(auto& c:plan.clips){
   auto next=starts.find({c.asset,c.end});
   if(next!=starts.end()&&next->second&&av_compare_ts(next->second->inTick,next->second->timebase,c.outTick,c.timebase)<0)
    rewinds[&c]=next->second;
  }
  }
  auto start=Clock::now(),lastReport=start;int64_t previous=-1,generation=-1,drawnGeneration=-1;uint64_t waiting=0,skipped=0,sourceWait=0,gpuWait=0,sourceSkipped=0,gpuSkipped=0,clockSkipped=0,clockBackwards=0,repeatedSource=0,clockHolds=0,distinctFrames=0,redraws=0;int64_t highest=-1;bool sawSourceWait=false,sawGpuWait=false;std::map<std::string,int64_t> lastPTS;size_t maxDecoders=0,maxQueue=0;
  int64_t reportedPausedGeneration=-1;
  std::set<std::string> lastActive;std::map<std::string,const Clip*> parked;
  constexpr uint64_t standbyBudget=896ULL*1024*1024;
  uint64_t peakStandbyBytes=0,peakReservedBytes=0,decoderOpens=0,resumedDecoders=0,coldPrepares=0,prepareRetries=0;
  std::set<std::string> retryOnFailure;
  std::vector<std::pair<const Clip*,Frame>> selected;bool ready=false,eos=false;double first=0;
  struct Miss {int64_t frame,lost,adjustment;double loopGap,sourceMs,clockAge,presentMs,contextMs;bool source,gpu;};
  std::deque<Miss> misses;auto lastLoop=Clock::now();Distribution selectTime;double clockAge=0;int64_t adjustment=0;
  // Reservations cover in-flight opens. Once a pool exists its exact texture
  // payload replaces the reservation; while idle it cannot allocate a second pool.
  auto observeStandby=[&]{
   uint64_t payload=0,reserved=0;
   for(auto& held:parked){
    auto& p=*producers.at(held.first);std::lock_guard<std::mutex> lock(p.guard);
    payload+=p.surfacePoolBytes;
    reserved+=p.surfacePoolBytes?p.surfacePoolBytes:p.reservation.bytes.load();
   }
   peakStandbyBytes=std::max(peakStandbyBytes,payload);
   peakReservedBytes=std::max(peakReservedBytes,reserved);
  };
  auto report=[&](const char* event,int64_t frame){
   WatchStage status("write_status");SourceStage timer("status_report");observeStandby();if(renderer.display)renderer.display->stats();
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
    auto& p=*producers[item.first->asset];std::cout<<"{\"clip\":\""<<item.first->id<<"\",\"pts\":"<<item.second->best_effort_timestamp<<",\"timebase_num\":"<<p.base.num<<",\"timebase_den\":"<<p.base.den<<",\"hdr10plus_retained\":"<<(av_frame_get_side_data(item.second.get(),AV_FRAME_DATA_DYNAMIC_HDR_PLUS)?"true":"false")<<",\"target_tick\":"<<p.streamTick(plan.sourceTick(*item.first,frame),item.first->timebase)+p.origin<<"}";}
   std::cout<<"],\"decoder_opens\":"<<decoderOpens<<",\"cold_prepares\":"<<coldPrepares<<",\"prepare_retries\":"<<prepareRetries<<",\"resumed_decoders\":"<<resumedDecoders<<",\"peak_standby_surface_bytes\":"<<peakStandbyBytes<<",\"peak_standby_reserved_bytes\":"<<peakReservedBytes<<",\"standby_surface_budget_bytes\":"<<standbyBudget<<",\"source_wait_iterations\":"<<sourceWait<<",\"gpu_wait_iterations\":"<<gpuWait<<",\"skipped_after_source_wait\":"<<sourceSkipped<<",\"skipped_after_gpu_wait\":"<<gpuSkipped<<",\"skipped_without_queue_wait\":"<<clockSkipped<<",\"distinct_sequence_submissions\":"<<distinctFrames<<",\"nonadvancing_redraws\":"<<redraws<<",\"clock_rewind_hold_iterations\":"<<clockHolds<<",\"clock_backwards_frames\":"<<clockBackwards<<",\"repeated_source_layer_frames\":"<<repeatedSource;
   std::cout<<",\"timings\":{\"context_wait\":";renderer.contextWait.json();std::cout<<",\"submit_cpu\":";renderer.submitTime.json();std::cout<<",\"completion_observation\":";renderer.completionAge.json();std::cout<<",\"composition_gpu\":";renderer.gpuTime.json();
   if(renderer.display){std::cout<<",\"present_call\":";renderer.display->presentTime.json();std::cout<<",\"present_call_interval\":";renderer.display->presentIntervals.json();std::cout<<",\"playback_present_interval\":";renderer.display->playIntervals.json();}
   std::cout<<",\"source_selection\":";selectTime.json();std::cout<<",\"wake_overshoot\":";deadline.overshoot.json();std::cout<<"},\"high_resolution_wait\":"<<(deadline.timer?"true":"false")<<",\"decoder_statistics\":[";bool dc=false;
   for(auto& entry:producers){auto& p=*entry.second;std::lock_guard<std::mutex> lock(p.guard);if(dc)std::cout<<",";dc=true;
    std::cout<<"{\"decoded_frames\":"<<p.decoded<<",\"decode_wall_seconds\":"<<p.decodedSeconds<<",\"seeks\":"<<p.seeks<<",\"queued_frames\":"<<p.queue.size()<<",\"warm_cache_frames\":"<<p.warm.size()<<",\"warm_cache_hits\":"<<p.warmHits<<",\"deferred_refills\":"<<p.deferredRefills<<",\"early_rewinds\":"<<p.earlyRewinds<<",\"adopted_rewinds\":"<<p.adoptedRewinds<<",\"rewind_tail_hits\":"<<p.tailHits<<",\"peak_queue_plus_tail\":"<<p.peakCombinedQueue<<",\"warm_budget_frames\":"<<p.warmBudget<<",\"decoder_threads\":"<<p.codecThreads<<",\"active_thread_type\":"<<p.threadType<<",\"hardware_pool_frames\":"<<p.poolFrames<<"}";}
   std::cout<<"]";input.clockStats();std::cout<<",\"retained_surface_views\":"<<renderer.textures.views.size()<<",\"retained_texture_pools\":"<<renderer.textures.pools.size()<<",\"retained_texture_estimated_MiB\":"<<renderer.textures.estimatedBytes()/1048576.;
   if(traceCompletion&&(completion.draw||completion.eos))completion.json(std::cout);
   std::cout<<"}"<<std::endl;
  };
  // Prepare unseen sources only after an exact paused picture has been
  // acknowledged. One opening may be in flight, with at most two idle leases.
  int64_t exhaustedGeneration=-1,exhaustedFrame=-1;
  auto prepareWhilePaused=[&](int64_t frame){
   if(software||producers.size()>=3||parked.size()>=2)return;
   if(exhaustedGeneration==generation&&exhaustedFrame==frame)return;
   if(!input.stillPaused(generation))return;
   uint64_t reserved=0;
   for(auto& held:parked){
    auto& p=*producers.at(held.first);std::lock_guard<std::mutex> lock(p.guard);
    if(!p.surfacePoolBytes||!p.failure.empty())return;
    reserved+=p.surfacePoolBytes;
   }
   if(reserved>=standbyBudget)return;
   const Clip* next=nullptr;
   for(auto& c:plan.clips){
    if(c.position<=frame||producers.count(c.asset)||av_compare_ts(c.position-frame,av_inv_q(plan.rate),2,{1,1})>0)continue;
    if(!next||c.position<next->position)next=&c;
   }
   if(!next){exhaustedGeneration=generation;exhaustedFrame=frame;return;}
   if(!input.stillPaused(generation))return;
   if(trace||flight){
    sourceContext.source=sourceIds.at(next->asset);sourceContext.decoder=nextDecoderId++;
    sourceContext.tick=next->inTick;sourceContext.num=next->timebase.num;sourceContext.den=next->timebase.den;
   }
   producers[next->asset]=std::make_unique<Producer>(*next,next->inTick,renderer.hw,false,
       8+(int)renderer.slots.size()-3,Renderer::cacheBudget(),standbyBudget-reserved,flight?sourceIds.at(next->asset):-1,sourceContext.decoder);
   currentClip[next->asset]=next->id;parked[next->asset]=next;decoderOpens++;coldPrepares++;
   maxDecoders=std::max(maxDecoders,producers.size());observeStandby();
  };
  while(!input.stop){
   double loopGap=seconds(lastLoop)*1000;lastLoop=Clock::now();
   {WatchStage stage("dispatch_messages");MSG message;while(PeekMessageW(&message,nullptr,0,0,PM_REMOVE)){TranslateMessage(&message);DispatchMessageW(&message);}}
   int64_t us,epoch;bool playing;if(limit){us=av_rescale_q(renderer.submitted,av_inv_q(plan.rate),AV_TIME_BASE_Q);epoch=0;playing=false;}
   else input.snapshot(us,epoch,playing,&clockAge,&adjustment);
   int64_t frame=limit?(int64_t)renderer.submitted:av_rescale_q_rnd(us+1,AV_TIME_BASE_Q,av_inv_q(plan.rate),(AVRounding)AV_ROUND_DOWN);
   // The clock anchor is an exact sequence frame plus an independently advancing audio sample clock.
   frame=std::max<int64_t>(0,frame);eos=frame>=plan.end;frame=std::min(frame,plan.end-1);
   if(traceCompletion){
    if(playing&&completion.generation!=epoch){completion={};completion.generation=epoch;}
    if(playing&&frame==plan.end-1&&!completion.eos){
     auto at=CompletionStamps::now()-us;
     completion.sequenceEnd=at+av_rescale_q(plan.end,av_inv_q(plan.rate),AV_TIME_BASE_Q);
     completion.pictureDeadline=at+av_rescale_q(plan.end-1,av_inv_q(plan.rate),AV_TIME_BASE_Q);
    }
    if(epoch==completion.generation&&eos&&!completion.eos)completion.eos=CompletionStamps::now();
   }
   if(trace){sourceContext={};sourceContext.frame=frame;sourceContext.generation=epoch;sourceContext.clockUs=us;}
   if(flight)flight->loop.set({frame,epoch,us,av_rescale_q(frame+1,av_inv_q(plan.rate),AV_TIME_BASE_Q),flight->now()});
   // The completion query shares the decoder device lock. During live
   // playback with a free slot, inspect the exact source request before
   // competing for that lock. Paused and terminal acknowledgements poll eagerly.
   const bool sourcesFirst=playing&&frame<plan.end-1&&drawnGeneration==epoch;
   Slot* slot=renderer.freeSlot();
   const bool retireWithDraw=sourcesFirst&&slot;
   if(!retireWithDraw){SourceStage timer("gpu_available");slot=renderer.available();}
   if(traceCompletion&&completion.generation==renderer.completedGeneration&&renderer.completedFrame==plan.end-1){
    if(!completion.gpu)completion.gpu=CompletionStamps::now();
    if(!completion.drained&&renderer.completed==renderer.submitted)completion.drained=CompletionStamps::now();
   }
   // Publish the completed paused target once per generation. Playback keeps
   // its regular status cadence, and an older GPU submission cannot answer a seek.
   if(!playing&&ready&&drawnGeneration==epoch&&previous==frame&&
      renderer.completedGeneration==epoch&&renderer.completedFrame==frame&&reportedPausedGeneration!=epoch){
    report("status",frame);lastReport=Clock::now();reportedPausedGeneration=epoch;
   }
   if(!limit&&!playing&&reportedPausedGeneration==epoch&&previous==frame)prepareWhilePaused(frame);
   if(playing&&drawnGeneration==epoch&&frame<previous){clockHolds++;frame=previous;}
   if(drawnGeneration==epoch&&frame==previous&&!(renderer.display&&renderer.display->needsResize())){if(seconds(lastReport)>.1){report("status",frame);lastReport=Clock::now();}WatchStage stage("wait_clock_deadline");deadline.wait(playing?std::clamp<int64_t>(av_rescale_q(previous+1,av_inv_q(plan.rate),AV_TIME_BASE_Q)-us,100,5000):20000);continue;}
   auto selectionStart=Clock::now();bool reset=generation!=epoch;generation=epoch;
   std::vector<Clip*> active;std::map<std::string,bool> wanted;
   for(auto& c:plan.clips)if(c.position<=frame&&frame<c.end){active.push_back(&c);wanted[c.asset]=true;}
   if(active.size()>3)throw std::runtime_error("Native layer budget exceeded");
   bool changed=reset||active.size()!=lastActive.size();
   for(auto* c:active)if(!lastActive.count(c->id))changed=true;
   if(changed){
    std::vector<std::pair<const Clip*,uint64_t>> candidates;
    for(auto& entry:producers){
     if(wanted.count(entry.first)||reset||!playing)continue;
     auto* next=plan.nextUse(entry.first,frame);
     if(!next||av_compare_ts(next->position-frame,av_inv_q(plan.rate),2,{1,1})>0)continue;
     auto& p=*entry.second;
     uint64_t bytes=p.parkableBytes();if(bytes)candidates.emplace_back(next,bytes);
    }
    std::sort(candidates.begin(),candidates.end(),[](auto& a,auto& b){return a.first->position<b.first->position;});
    std::map<std::string,const Clip*> keep;
    uint64_t standbyBytes=0;
    for(auto& candidate:candidates){
     if(keep.size()>=2||active.size()+keep.size()>=3)break;
     if(candidate.second>standbyBudget-standbyBytes)continue;
     keep[candidate.first->asset]=candidate.first;standbyBytes+=candidate.second;
    }
    observeStandby();
    bool drained=false;
    for(auto it=producers.begin();it!=producers.end();){
     if(wanted.count(it->first)){++it;continue;}
     auto leased=keep.find(it->first);
     if(leased!=keep.end()){
      auto& next=*leased->second;
      auto& outgoing=*clipLookup.at(currentClip.at(it->first));
      if(outgoing.id!=next.id&&!plan.continuousSource(outgoing,next))it->second->reset(next.inTick,next.timebase);
      currentClip[it->first]=next.id;++it;continue;
     }
     if(!drained){
      {SourceStage timer("drain_compositor");renderer.drain();}
      {SourceStage timer("release_views");renderer.textures.clear();}
      drained=true;
     }
     if(trace){sourceContext.source=sourceIds.at(it->first);sourceContext.decoder=it->second->request.decoder;}
     SourceStage timer("retire_decoder");retryOnFailure.erase(it->first);currentClip.erase(it->first);it=producers.erase(it);
    }
    for(auto* c:active){
     auto tick=plan.sourceTick(*c,frame);
     if(trace){sourceContext.source=sourceIds.at(c->asset);sourceContext.tick=tick;sourceContext.num=c->timebase.num;sourceContext.den=c->timebase.den;}
     if(!producers.count(c->asset)){
      if(trace||flight)sourceContext.decoder=nextDecoderId++;
      SourceStage timer("create_decoder");
      producers[c->asset]=std::make_unique<Producer>(*c,tick,renderer.hw,software,8+(int)renderer.slots.size()-3,Renderer::cacheBudget(),0,flight?sourceIds.at(c->asset):-1,sourceContext.decoder);
      decoderOpens++;
     }else{
      auto& outgoing=*clipLookup.at(currentClip.at(c->asset));
      auto& producer=*producers[c->asset];
      if(reset||outgoing.id!=c->id){
       bool primed=producer.cutNext!=nullptr;
       if(primed)retryOnFailure.insert(c->asset);
       bool adopted=!reset&&primed&&producer.adoptRewind(*c,epoch);
       if(!adopted&&(primed||reset||!plan.adjacent(outgoing,*c)))producer.reset(tick,c->timebase);
      }
      if(parked.count(c->asset)){
       retryOnFailure.insert(c->asset);
       producers[c->asset]->reservation.bytes=0;
       if(!reset)resumedDecoders++;
      }
     }
     currentClip[c->asset]=c->id;
    }
    lastActive.clear();for(auto* c:active)lastActive.insert(c->id);
    parked=std::move(keep);observeStandby();
   }
   maxDecoders=std::max(maxDecoders,producers.size());selected.clear();ready=true;
   WatchRequest observed;
   size_t watchIndex=0;
   if(flight){
    observed.fields={0,0,frame,epoch,playing,us,av_rescale_q_rnd(frame,av_inv_q(plan.rate),AV_TIME_BASE_Q,AV_ROUND_UP),
                     (1LL<<active.size())-1,0,previous,drawnGeneration,(int64_t)(renderer.submitted-renderer.completed)};
   }
   const bool coordinateRefill=playing&&active.size()>1;
   auto releaseRefills=[&]{if(coordinateRefill)for(auto* clip:active)producers.at(clip->asset)->releaseRefill();};
   for(auto* c:active){
    auto& p=*producers[c->asset];
    const auto tick=plan.sourceTick(*c,frame);
    if(trace){sourceContext.decoder=p.request.decoder;sourceContext.source=sourceIds.at(c->asset);sourceContext.tick=tick;sourceContext.num=c->timebase.num;sourceContext.den=c->timebase.den;}
    bool available=false;Frame f;
    auto index=watchIndex++;
    auto* picture=flight?observed.at(index):nullptr;
    try{SourceStage timer("select_picture");f=p.at(*c,frame,epoch,tick,available,coordinateRefill,picture);}
    catch(const std::runtime_error&){
     if(!retryOnFailure.erase(c->asset))throw;
     if(picture)picture[12]=(int64_t)PictureReason::replaced;
     // Oversized/changed-format speculative decoding never removes a source
     // from playback. Retire and retry the exact active point at normal capacity.
     renderer.drain();renderer.textures.clear();producers.erase(c->asset);
     if(trace||flight)sourceContext.decoder=nextDecoderId++;
     producers[c->asset]=std::make_unique<Producer>(*c,plan.sourceTick(*c,frame),renderer.hw,software,
         8+(int)renderer.slots.size()-3,Renderer::cacheBudget(),0,flight?sourceIds.at(c->asset):-1,sourceContext.decoder);
     decoderOpens++;prepareRetries++;ready=false;continue;
    }
    if(available){c->sourceRotation=p.rotation;retryOnFailure.erase(c->asset);}
    {std::lock_guard<std::mutex> lock(p.guard);maxQueue=std::max(maxQueue,p.peak);}
    if(!available){ready=false;continue;}selected.push_back({c,f});
    if(flight)observed.fields[8]|=1LL<<index;
   }
   double sourceMs=seconds(selectionStart)*1000;selectTime.add(sourceMs);
   // Source selection may drain slots, but only draw() can occupy one.
   if(ready&&!slot){
    SourceStage timer("gpu_available");slot=renderer.available();
   }
   if(flight){
    if(slot)observed.fields[8]|=8;
    flight->publishRequest(observed);
   }
   if(!ready||!slot){releaseRefills();waiting++;if(!ready){sourceWait++;sawSourceWait=true;}else{gpuWait++;sawGpuWait=true;}if(seconds(lastReport)>.1){report("status",frame);lastReport=Clock::now();}WatchStage stage(!ready?"wait_source_retry":"wait_gpu_slot");deadline.wait(1000);continue;}
   // A seek can arrive while a playing source handoff is unlocking or opening.
   // Fence it at the same submission boundary as a paused seek.
   if(!limit&&!input.isGeneration(epoch)){releaseRefills();continue;}
   if(previous>=0&&drawnGeneration==generation&&frame>previous+1){auto lost=frame-previous-1;if(trace)trace->miss(frame,lost);skipped+=lost;if(sawSourceWait)sourceSkipped+=lost;else if(sawGpuWait)gpuSkipped+=lost;else clockSkipped+=lost;
    if(misses.size()==256)misses.pop_front();misses.push_back({frame,lost,adjustment,loopGap,sourceMs,clockAge,renderer.display?renderer.display->lastPresentMs:0,renderer.contextWait.last,sawSourceWait,sawGpuWait});}
   if(drawnGeneration==generation&&frame<previous)clockBackwards++;
   for(auto& item:selected){auto pts=item.second->best_effort_timestamp;if(drawnGeneration==generation&&frame>previous&&lastPTS.count(item.first->asset)&&lastPTS[item.first->asset]==pts)repeatedSource++;lastPTS[item.first->asset]=pts;}
   sawSourceWait=sawGpuWait=false;
   if(drawnGeneration!=generation){highest=frame;distinctFrames++;}else if(frame>highest){highest=frame;distinctFrames++;}else redraws++;
   if(trace)trace->submitStart();
   {SourceStage timer("draw_and_present");renderer.draw(*slot,plan,frame,generation,selected,playing,retireWithDraw);}
   if(flight&&(previous!=frame||drawnGeneration!=epoch))flight->submit.set({frame,epoch,flight->now()});
   if(traceCompletion&&epoch==completion.generation&&frame==plan.end-1&&!completion.draw)completion.draw=CompletionStamps::now();
   if(coordinateRefill&&!software){
    // Only simultaneous same-file backwards boundaries qualify. The three
    // leads are staggered and no current-source lookup waits for a new frame.
    for(size_t layer=0;layer<active.size();layer++){
     auto* c=active[layer];
     const auto lead=c->end-frame;
     if(lead<1||lead>3-(int64_t)layer)continue;
     auto next=rewinds.find(c);if(next==rewinds.end())continue;
     bool simultaneous=std::any_of(active.begin(),active.end(),[&](const Clip* other){
      return other!=c&&other->end==c->end&&rewinds.count(other);
     });
     if(simultaneous&&input.stillPlaying(epoch))producers.at(c->asset)->primeRewind(plan,*c,*next->second,frame,epoch);
    }
   }
   releaseRefills();
   if(!first)first=seconds(launch);
   previous=frame;drawnGeneration=generation;
   if(!capture.empty()&&(renderer.submitted==1||(limit&&renderer.submitted==(uint64_t)limit)))renderer.capture(*slot,capture+"-"+std::to_string(frame)+".rgba16f");
   if(seconds(lastReport)>.1){report("status",frame);lastReport=Clock::now();}
   if(limit&&renderer.submitted>=(uint64_t)limit)break;
  }
  for(auto& entry:producers)entry.second->cancel();
  renderer.drain();
  if(traceCompletion&&completion.draw){
   if(renderer.completedFrame==plan.end-1&&renderer.completedGeneration==completion.generation){
    if(!completion.gpu)completion.gpu=CompletionStamps::now();
    if(!completion.drained)completion.drained=CompletionStamps::now();
   }
  }
  report("closed",previous);
  selected.clear();producers.clear();
  if(traceCompletion&&completion.draw){
   completion.joined=CompletionStamps::now();
   std::cout<<"{\"event\":\"completion_diagnostic\",\"generation\":"<<completion.generation;
   completion.json(std::cout);std::cout<<"}"<<std::endl;
  }
  if(trace){std::ofstream out(std::filesystem::u8path(tracePath));out<<"{\"bounded_missed_events\":[";bool comma=false;for(auto& m:misses){if(comma)out<<",";comma=true;out<<"{\"frame\":"<<m.frame<<",\"lost\":"<<m.lost<<",\"loop_gap_ms\":"<<m.loopGap<<",\"source_selection_ms\":"<<m.sourceMs<<",\"clock_age_ms\":"<<m.clockAge<<",\"clock_adjustment_us\":"<<m.adjustment<<",\"previous_present_ms\":"<<m.presentMs<<",\"context_wait_ms\":"<<m.contextMs<<",\"source_wait\":"<<m.source<<",\"gpu_wait\":"<<m.gpu<<"}";}out<<"]";trace->json(out);out<<"}";}
  return 0;
 }catch(const std::exception& error){std::string message=error.what();const char* code=message.find("HDR display is not active")!=std::string::npos?"hdr_display_inactive":message.find("color contract")!=std::string::npos?"color_contract":"native_failure";std::cout<<"{\"event\":\"error\",\"code\":\""<<code<<"\",\"hresult\":"<<(uint32_t)nativeHResult<<",\"av_error\":"<<nativeAVError<<",\"reason\":\"Native decode, display or device failure; use the reference renderer\"}"<<std::endl;return 1;}
}
