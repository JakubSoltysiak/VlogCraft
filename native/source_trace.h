#pragma once
#include <array>
#include <mutex>

// Local, opt-in fixed storage. Source and decoder IDs are numeric ordinals;
// paths, media contents and application project identifiers never enter this trace.
struct SourceTrace {
 struct Context {
  int source=-1,decoder=-1,depth=-1,num=0,den=1;
  int64_t frame=-1,generation=-1,tick=0,clockUs=0,decodeEpoch=-1;
 };
 struct Event { const char* stage=nullptr; int64_t startUs=0,durationUs=0; Context context; };
 Clock::time_point origin=Clock::now();
 std::mutex guard;
 std::array<Event,1024> recent{};
 std::array<Event,32> longest{};
 struct Gap {
  int64_t frame=-1,lost=0,beginUs=0,endUs=0;
  std::array<Event,192> events{};
  size_t available=0,stored=0;
 };
 std::array<Gap,3> worstGaps{};
 int64_t lastSubmitStartUs=-1;
 uint64_t count=0;
 // Only the presentation thread advances these anchors. Trace time is independent
 // of the PCM clock; include work in the previous submission that delayed its return.
 void submitStart(){
  lastSubmitStartUs=std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-origin).count();
 }
 void miss(int64_t frame,int64_t lost){
  if(lastSubmitStartUs<0)return;
  auto slot=std::min_element(worstGaps.begin(),worstGaps.end(),
                            [](const Gap& a,const Gap& b){return a.lost<b.lost;});
  if(lost<=slot->lost)return;
  slot->endUs=std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-origin).count();
  slot->frame=frame;slot->lost=lost;slot->beginUs=lastSubmitStartUs;
  slot->available=slot->stored=0;
  std::lock_guard<std::mutex> lock(guard);
  auto begin=count>recent.size()?count-recent.size():0;
  for(auto i=begin;i<count;i++){
   const auto& event=recent[i%recent.size()];
   if(event.startUs>slot->endUs||event.startUs+event.durationUs<slot->beginUs)continue;
   slot->available++;
   if(slot->stored<slot->events.size())slot->events[slot->stored++]=event;
  }
 }
 void interval(const char* stage,Clock::time_point start,Clock::time_point end,const Context& context){
  auto duration=std::chrono::duration_cast<std::chrono::microseconds>(end-start).count();
  if(duration<2000)return;
  Event event{stage,std::chrono::duration_cast<std::chrono::microseconds>(start-origin).count(),duration,context};
  std::lock_guard<std::mutex> lock(guard);
  recent[count++%recent.size()]=event;
  auto shortest=std::min_element(longest.begin(),longest.end(),[](auto& a,auto& b){return a.durationUs<b.durationUs;});
  if(duration>shortest->durationUs)*shortest=event;
 }
 void add(const char* stage,Clock::time_point start,const Context& context){
  interval(stage,start,Clock::now(),context);
 }
 void json(std::ostream& out){
  std::lock_guard<std::mutex> lock(guard);
  auto emit=[&](const Event& e){
   auto& c=e.context;
   out<<"{\"stage\":\""<<e.stage<<"\",\"start_us\":"<<e.startUs<<",\"duration_us\":"<<e.durationUs
      <<",\"source\":"<<c.source<<",\"decoder\":"<<c.decoder<<",\"queue_depth\":"<<c.depth
      <<",\"frame\":"<<c.frame<<",\"generation\":"<<c.generation<<",\"decode_epoch\":"<<c.decodeEpoch
      <<",\"source_tick\":"<<c.tick<<",\"timebase_num\":"<<c.num<<",\"timebase_den\":"<<c.den
      <<",\"clock_us\":"<<c.clockUs<<"}";
  };
  out<<",\"stage_threshold_us\":2000,\"stage_event_count\":"<<count<<",\"recent_stages\":[";
  auto begin=count>recent.size()?count-recent.size():0;
  for(auto i=begin;i<count;i++){if(i!=begin)out<<",";emit(recent[i%recent.size()]);}
  out<<"],\"longest_stages\":[";bool comma=false;
  for(auto& e:longest)if(e.stage){if(comma)out<<",";emit(e);comma=true;}
  out<<"],\"largest_miss_windows\":[";comma=false;
  for(auto& gap:worstGaps)if(gap.frame>=0){
   if(comma)out<<",";comma=true;
   out<<"{\"frame\":"<<gap.frame<<",\"lost\":"<<gap.lost<<",\"begin_us\":"<<gap.beginUs
      <<",\"end_us\":"<<gap.endUs<<",\"matching_recent_events\":"<<gap.available<<",\"stages\":[";
   for(size_t i=0;i<gap.stored;i++){if(i)out<<",";emit(gap.events[i]);}
   out<<"]}";
  }
  out<<"]";
 }
};
inline SourceTrace* sourceTrace=nullptr;
inline thread_local SourceTrace::Context sourceContext;
struct SourceStage {
 const char* name;
 Clock::time_point start;
 explicit SourceStage(const char* stage):name(stage){if(sourceTrace)start=Clock::now();}
 ~SourceStage(){if(sourceTrace)sourceTrace->add(name,start,sourceContext);}
};
