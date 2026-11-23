#pragma once
#include <array>
#include <atomic>
#include <deque>
#include <thread>

// One writer per tuple (the queue tuple's writers already share the producer
// guard). Atomic members make an interrupted/torn observation safe to reject.
// The sampler never retries or waits for the application.
template<size_t N> struct WatchTuple {
 using Values=std::array<int64_t,N>;
 std::atomic<uint64_t> revision{0};
 std::array<std::atomic<int64_t>,N> fields{};
 void set(const Values& input){
  revision.fetch_add(1,std::memory_order_acq_rel);
  for(size_t n=0;n<N;n++)fields[n].store(input[n],std::memory_order_relaxed);
  revision.fetch_add(1,std::memory_order_release);
 }
 bool get(Values& out)const{
  auto before=revision.load(std::memory_order_acquire);
  for(size_t n=0;n<N;n++)out[n]=fields[n].load(std::memory_order_relaxed);
  std::atomic_thread_fence(std::memory_order_acquire);
  return !(before&1)&&before==revision.load(std::memory_order_relaxed);
 }
};
struct StallWatch;
inline StallWatch* stallWatch=nullptr;
inline thread_local int watchLane=-1;
struct WatchChannel {
 std::atomic<bool> leased{false};
 std::atomic<unsigned> leaseGeneration{0};
 std::atomic<DWORD> threadId{0};
 std::atomic<const char*> stage{"idle"},lastSlow{"idle"};
 std::atomic<int64_t> since{0},calls{0},exits{0},slowStart{0},slowEnd{0},slowCount{0};
 WatchTuple<4> source;
 WatchTuple<11> queue;
 WatchTuple<6> selection;
 WatchTuple<3> packet,device;
};
struct StallWatch {
 using I=int64_t;
 struct Lane {
  DWORD thread=0;bool live=false;const char* stage="idle";const char* slow="idle";
  // lane array order is defined in write().
  std::array<I,9> activity{};
  WatchTuple<4>::Values source{};WatchTuple<11>::Values queue{};
  WatchTuple<6>::Values selection{};WatchTuple<3>::Values packet{},device{};
 };
 struct Sample{
  I t=0;unsigned torn=0;
  WatchTuple<4>::Values transport{};WatchTuple<5>::Values loop{};
  WatchTuple<3>::Values submit{};WatchTuple<4>::Values gpu{};
  I flips=0,modeSince=0;std::array<Lane,4> lanes{};
 };
 struct Incident{
  I last=-1,gen=-1,age=0;bool recovered=false,transition=false,truncated=false;
  unsigned dropped=0;std::vector<Sample> samples;
 };
 std::array<WatchChannel,4> lanes;
 WatchTuple<5> transport; // command position, generation, playing, arrival, last transport transition
 WatchTuple<5> loop;      // requested frame, generation, clock, next deadline (audio us), heartbeat
 WatchTuple<3> submit;    // last returned distinct draw: frame, generation, time
 WatchTuple<4> gpu;       // submitted/completed counts, completed frame and generation
 std::atomic<I> flips{0},exitWatch{0};
 I oldMode=-1,oldGeneration=-1,modeSince=0; // reader-thread only
 const std::string path;Clock::time_point origin=Clock::now();
 I utc100ns=0,qpc=0,freq=0,lastFrame=-1,rateNum=1,rateDen=1;unsigned triggerCount=0,tornSamples=0;
 I pollCount=0,maxPollGap=0;unsigned liveWriteFailures=0;
 std::deque<Sample> pre;
 std::vector<Incident> archive;
 std::thread worker;
 // Handles are acquired/read only on the watchdog thread. Times are sampled
 // CPU accounting; the OS can update these counters at a coarser cadence.
 struct Cpu{DWORD id=0;unsigned generation=0;HANDLE handle=nullptr;~Cpu(){if(handle)CloseHandle(handle);}};
 std::array<Cpu,4> cpu;
 explicit StallWatch(std::string filename):path(std::move(filename)){
  FILETIME utc;GetSystemTimePreciseAsFileTime(&utc);utc100ns=ticks(utc);
  LARGE_INTEGER c,f;QueryPerformanceCounter(&c);QueryPerformanceFrequency(&f);qpc=c.QuadPart;freq=f.QuadPart;
  lanes[0].leased=true;submit.set({-1,-1,0});stallWatch=this;
 }
 ~StallWatch(){exitWatch=1;if(worker.joinable())worker.join();stallWatch=nullptr;}
 void start(I end,int num,int den){lastFrame=end-1;rateNum=num;rateDen=den;worker=std::thread([this]{sampleLoop();});}
 static I ticks(FILETIME t){return ((uint64_t)t.dwHighDateTime<<32)|t.dwLowDateTime;}
 I now()const{return std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-origin).count();}
 void command(I us,I gen,bool play){
  auto t=now();
  if(oldMode!=(I)play||oldGeneration!=gen){modeSince=t;oldMode=play;oldGeneration=gen;}
  transport.set({us,gen,play,t,modeSince});
 }
 I threadCpu(size_t n,DWORD id,unsigned generation){
  auto& v=cpu[n];if(v.id!=id||v.generation!=generation){if(v.handle)CloseHandle(v.handle);v.id=id;v.generation=generation;v.handle=id?OpenThread(THREAD_QUERY_LIMITED_INFORMATION,FALSE,id):nullptr;}
  FILETIME start,stop,k,u;
  return v.handle&&GetThreadTimes(v.handle,&start,&stop,&k,&u)?(ticks(k)+ticks(u))/10:-1;
 }
 Sample snapshot(){
  Sample s;s.t=now();s.flips=flips;
  WatchTuple<5>::Values clock;
  bool stable=transport.get(clock);
  std::copy_n(clock.begin(),4,s.transport.begin());s.modeSince=clock[4];
  stable &= loop.get(s.loop);stable &= submit.get(s.submit);stable &= gpu.get(s.gpu);
  if(!stable)s.torn|=1;
  for(size_t n=0;n<4;n++){
   auto& c=lanes[n];auto& l=s.lanes[n];auto generation=c.leaseGeneration.load();
   l.live=c.leased;l.thread=c.threadId;l.stage=c.stage;l.slow=c.lastSlow;
   l.activity={c.since,c.calls,c.exits,c.slowStart,c.slowEnd,c.slowCount,threadCpu(n,l.thread,generation),l.live,l.thread};
   bool valid=c.source.get(l.source);valid &= c.queue.get(l.queue);valid &= c.selection.get(l.selection);
   valid &= c.packet.get(l.packet);valid &= c.device.get(l.device);
   if(!valid||(generation&1)||generation!=c.leaseGeneration.load())s.torn|=2u<<n;
  }
  if(s.torn)tornSamples++;return s;
 }
 template<class Range> static void ints(std::ostream& out,const Range& values){
  out<<'[';bool comma=false;for(auto v:values){if(comma)out<<',';out<<v;comma=true;}out<<']';
 }
 static void row(std::ostream& out,const Sample& s){
  out<<'['<<s.t<<','<<s.torn<<','<<s.modeSince<<',';ints(out,s.transport);out<<',';ints(out,s.loop);out<<',';ints(out,s.submit);out<<',';ints(out,s.gpu);out<<','<<s.flips;
  for(const auto& l:s.lanes){
   out<<",[\""<<l.stage<<"\",\""<<l.slow<<"\",";ints(out,l.activity);out<<',';ints(out,l.source);out<<',';ints(out,l.queue);out<<',';ints(out,l.selection);out<<',';ints(out,l.packet);out<<',';ints(out,l.device);out<<']';
  }out<<']';
 }
 bool write(const Incident* live=nullptr){
  auto target=std::filesystem::u8path(path+(live?".live":""));auto temp=target;temp+=L".tmp";
  std::ofstream out(temp,std::ios::trunc);if(!out)return false;
  out<<"{\"version\":1,\"start_filetime_100ns\":"<<utc100ns<<",\"qpc_anchor\":"<<qpc<<",\"qpc_frequency\":"<<freq
     <<",\"shared_device_ordinal\":0,\"sample_bytes\":"<<sizeof(Sample)<<",\"polls\":"<<pollCount<<",\"max_poll_gap_us\":"<<maxPollGap<<",\"torn_samples\":"<<tornSamples<<",\"trigger_count\":"<<triggerCount<<",\"live_write_failures\":"<<liveWriteFailures
     <<",\"sample_schema\":\"us,torn_mask,mode_since,clock(us,gen,playing,arrival),loop(frame,gen,audio_us,next_audio_deadline_us,heartbeat_us),last_return(frame,gen,us),gpu(submits,completions,frame,gen),presents,render_lane,source_lanes_1_2_3\""
     <<",\"lane_schema\":\"stage,last_slow,activity(stage_since,entries,exits,slow_begin,slow_end,slow_count,cpu_us,leased,tid),source(id,decoder,tb_num,tb_den),queue(target,floor,next,depth,warm,tail,epoch,ready,held,eof,observed_us),selection(frame,gen,target,floor,next,path),packet(pts,dts,count),device(waiting,owned,transition_us)\",\"incidents\":[";
  auto incident=[&](const Incident& a){
   out<<"{\"last_frame\":"<<a.last<<",\"generation\":"<<a.gen<<",\"observed_age_us\":"<<a.age<<",\"recovered\":"<<a.recovered<<",\"transition\":"<<a.transition<<",\"truncated\":"<<a.truncated<<",\"dropped_middle_samples\":"<<a.dropped<<",\"samples\":[";
   bool comma=false;for(auto& s:a.samples){if(comma)out<<',';row(out,s);comma=true;}out<<"]}";
  };
  if(live)incident(*live);else{bool comma=false;for(auto& a:archive){if(comma)out<<',';incident(a);comma=true;}}
  out<<"]}";out.close();return out&&MoveFileExW(temp.c_str(),target.c_str(),MOVEFILE_REPLACE_EXISTING);
 }
 void keep(Incident a){
  if(archive.size()<3)archive.push_back(std::move(a));
  else{auto it=std::min_element(archive.begin(),archive.end(),[](auto& x,auto& y){return x.age<y.age;});if(a.age>it->age)*it=std::move(a);}
 }
 void sampleLoop(){
  Incident a;bool collecting=false,liveSaved=false;I until=0,prev=0,stallStart=0,initialModeSince=0;
  do{
   auto s=snapshot();pollCount++;if(prev)maxPollGap=std::max(maxPollGap,s.t-prev);prev=s.t;
   bool coherent=!(s.torn&1);
   auto expected=(static_cast<long double>(s.transport[0])+s.t-s.transport[3])*rateNum/(1000000LL*rateDen);
   bool active=coherent&&s.transport[2]&&s.transport[1]==s.submit[1]&&s.loop[1]==s.submit[1]&&s.submit[0]>=0&&s.submit[0]<lastFrame;
   I age=s.t-std::max(s.modeSince,s.submit[2]);
   if(!collecting&&active&&age>=100000&&expected>=s.submit[0]+1){
    a=Incident{};a.last=s.submit[0];a.gen=s.submit[1];a.samples.reserve(832);a.samples.assign(pre.begin(),pre.end());collecting=true;until=0;stallStart=s.t-age;initialModeSince=s.modeSince;liveSaved=false;triggerCount++;
   }
   if(collecting){
    if(!until&&coherent){
     if(s.modeSince!=initialModeSince||!s.transport[2]||s.transport[1]!=a.gen||s.submit[0]!=a.last||s.submit[1]!=a.gen){
      a.transition=s.modeSince!=initialModeSince||s.transport[1]!=a.gen||s.submit[1]!=a.gen||!s.transport[2];
      a.recovered=!a.transition&&s.submit[0]!=a.last;
      if(a.recovered)a.age=std::max(a.age,s.submit[2]-stallStart);
      until=s.t+180000;
     }
     else a.age=std::max(a.age,age);
    }
    if(a.samples.size()<768)a.samples.push_back(s);
    else if(until&&a.samples.size()<832)a.samples.push_back(s);
    else {a.dropped++;a.truncated=true;}
    if(!liveSaved&&a.age>=500000){if(!write(&a))liveWriteFailures++;liveSaved=true;}
    if(until&&s.t>=until){keep(std::move(a));collecting=false;}
   }
   pre.push_back(s);if(pre.size()>96)pre.pop_front();
   if(!exitWatch)std::this_thread::sleep_for(std::chrono::milliseconds(4));
  }while(!exitWatch);
  if(collecting){a.truncated=true;keep(std::move(a));}write();
 }
};
struct WatchLease{
 int lane=-1;
 WatchLease(){
  // Only the render thread constructs/destroys producers. Destruction joins the worker.
  if(stallWatch)for(int n=1;n<4;n++){
   auto& c=stallWatch->lanes[n];if(c.leased)continue;
   ++c.leaseGeneration;
   c.threadId=0;c.stage="idle";c.lastSlow="idle";c.since=0;c.calls=0;c.exits=0;c.slowStart=0;c.slowEnd=0;c.slowCount=0;
   c.source.set({-1,-1,0,0});c.queue.set({0,INT64_MIN,INT64_MIN,0,0,0,0,0,0,0,0});
   c.selection.set({-1,-1,INT64_MIN,INT64_MIN,INT64_MIN,0});c.packet.set({INT64_MIN,INT64_MIN,0});c.device.set({});
   c.leased=true;++c.leaseGeneration;lane=n;break;
  }
 }
 ~WatchLease(){if(lane>=0)stallWatch->lanes[lane].leased=false;}
 WatchLease(const WatchLease&)=delete;
};
struct WatchThread{
 int previous=watchLane;
 explicit WatchThread(int n){watchLane=n;if(stallWatch&&n>=0)stallWatch->lanes[n].threadId=GetCurrentThreadId();}
 ~WatchThread(){if(stallWatch&&watchLane>=0)stallWatch->lanes[watchLane].threadId=0;watchLane=previous;}
};
struct WatchStage{
 WatchChannel* c=nullptr;const char* before=nullptr;const char* label=nullptr;int64_t start=0,priorStart=0;
 explicit WatchStage(const char* name){
  if(!stallWatch||watchLane<0)return;c=&stallWatch->lanes[watchLane];label=name;start=stallWatch->now();
  before=c->stage.load();priorStart=c->since.load();c->since=start;c->stage=name;++c->calls;
 }
 ~WatchStage(){
  if(!c)return;auto end=stallWatch->now();if(end-start>=2000){c->slowStart=start;c->slowEnd=end;c->lastSlow=label;++c->slowCount;}
  c->since=priorStart;c->stage=before;++c->exits;
 }
};
inline void watchQueue(int n,int64_t target,int64_t floor,int64_t next,int depth,int warm,int tail,int64_t epoch,bool ready,bool held,bool eof){
 if(stallWatch&&n>=0)stallWatch->lanes[n].queue.set({target,floor,next,depth,warm,tail,epoch,ready,held,eof,stallWatch->now()});
}
inline void watchSelection(int n,int64_t frame,int64_t gen,int64_t target,int64_t floor,int64_t next,int path){
 if(stallWatch&&n>=0)stallWatch->lanes[n].selection.set({frame,gen,target,floor,next,path});
}
inline void watchPacket(int64_t pts,int64_t dts){if(stallWatch&&watchLane>=0){
 auto& group=stallWatch->lanes[watchLane].packet;group.set({pts,dts,group.fields[2].load()+1});
}}
inline void watchDevice(bool wait,bool hold){if(stallWatch&&watchLane>=0)stallWatch->lanes[watchLane].device.set({wait,hold,stallWatch->now()});}
inline void watchSource(int n,int source,int decoder,int num,int den){if(stallWatch&&n>=0)stallWatch->lanes[n].source.set({source,decoder,num,den});}
inline void watchGPU(uint64_t s,uint64_t c,int64_t f,int64_t g){if(stallWatch)stallWatch->gpu.set({(int64_t)s,(int64_t)c,f,g});}
inline void watchPresent(){if(stallWatch)++stallWatch->flips;}
inline void watchClock(int64_t us,int64_t gen,bool play){if(stallWatch)stallWatch->command(us,gen,play);}
