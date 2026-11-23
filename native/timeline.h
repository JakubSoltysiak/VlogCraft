#pragma once
#include "telemetry.h"
#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <deque>
#include <mutex>
#include <sstream>
#include <thread>
#include <array>
extern "C" {
#include <libavutil/display.h>
}
using Frame=std::shared_ptr<AVFrame>;
Frame retain(AVFrame* p){auto* copy=av_frame_clone(p);if(!copy)throw std::bad_alloc();return Frame(copy,[](AVFrame* f){av_frame_free(&f);});}
struct Key{double time=0,value=0;std::string mode;};
struct Clip {
 std::string id,asset,path;int64_t position=0,end=0,inTick=0,outTick=0;AVRational timebase={1,1},speed={1,1};
 double x=0,y=0,scale=1,rotation=0,opacity=1,fadeIn=0,fadeOut=0,sourceRotation=0;bool cover=false;
 std::map<std::string,std::vector<Key>> keys;
 double value(const std::string& prop,double source,double fallback)const{
  auto it=keys.find(prop);if(it==keys.end()||it->second.empty())return fallback;auto& v=it->second;
  if(source<=v.front().time)return v.front().value;
  for(size_t n=1;n<v.size();n++)if(source<v[n].time){
   auto& a=v[n-1];auto& b=v[n];double u=(source-a.time)/(b.time-a.time);
   if(a.mode=="hold")u=0;else if(a.mode=="ease-in")u*=u;else if(a.mode=="ease-out")u=u*(2-u);
   return a.value+(b.value-a.value)*u;
  }return v.back().value;
 }
};
struct Plan {
 AVRational rate={60,1};int width=960,height=540;int64_t end=0;bool hdr=false;
 std::vector<Clip> clips;
 Plan(const std::string& filename){
  std::ifstream input(std::filesystem::u8path(filename));std::string line;std::map<std::string,std::string> sources;
  if(!std::getline(input,line)||line!="VLOGCRAFT_NATIVE 1")throw std::runtime_error("Unsupported native plan version");
  while(std::getline(input,line)){
   std::istringstream s(line);std::string type;s>>type;
   if(type=="RATE")s>>rate.num>>rate.den;
   else if(type=="CANVAS")s>>width>>height;
   else if(type=="END")s>>end;
   else if(type=="COLOR"){std::string color;s>>color;hdr=color=="PQ";}
   else if(type=="SOURCE"){std::string id,path;s>>id;std::getline(s,path);if(!path.empty()&&path.front()=='\t')path.erase(0,1);else if(!path.empty()&&path.front()==' ')path.erase(0,1);sources[id]=path;}
   else if(type=="CLIP"){
    Clip c;int cover=0;s>>c.id>>c.asset>>c.position>>c.end>>c.inTick>>c.timebase.num>>c.timebase.den>>c.speed.num>>c.speed.den
     >>c.x>>c.y>>c.scale>>c.rotation>>c.opacity>>c.fadeIn>>c.fadeOut>>c.sourceRotation>>cover>>c.outTick;
    if(!s||!sources.count(c.asset)||c.end<=c.position||c.timebase.num<=0||c.timebase.den<=0||c.speed.num<=0||c.speed.den<=0)throw std::runtime_error("Invalid native clip contract");
    c.cover=cover;c.path=sources[c.asset];clips.push_back(c);
   }else if(type=="KEY"){
    std::string id,prop;Key key;s>>id>>prop>>key.time>>key.value>>key.mode;
    auto i=std::find_if(clips.begin(),clips.end(),[&](auto& c){return c.id==id;});
    if(i==clips.end()||!s)throw std::runtime_error("Invalid native key");i->keys[prop].push_back(key);
   }
  }
  if(rate.num<=0||rate.den<=0||width<2||height<2||width>3840||height>2160||end<1)throw std::runtime_error("Invalid native sequence contract");
 }
 bool continuousSource(const Clip& old,const Clip& next)const{
  return old.asset==next.asset&&av_compare_ts(old.outTick,old.timebase,next.inTick,next.timebase)==0;
 }
 bool adjacent(const Clip& old,const Clip& next)const{return old.end==next.position&&continuousSource(old,next);}
 const Clip* nextUse(const std::string& asset,int64_t frame)const{
  const Clip* next=nullptr;
  for(auto& c:clips)if(c.asset==asset&&c.position>frame&&(!next||c.position<next->position))next=&c;
  return next;
 }
 int64_t sourceTick(const Clip& c,int64_t frame)const{
  // Exact rescaling to source ticks, rounded down for half-open held-PTS selection.
  AVRational units=av_mul_q(av_inv_q(rate),c.speed);
  return c.inTick+av_rescale_q_rnd(frame-c.position,units,c.timebase,(AVRounding)AV_ROUND_DOWN);
 }
};
struct RefillWindow {
 Clock::time_point observedAt;
 int64_t clockUs,frameDueUs,periodUs;
};
struct Producer {
 WatchLease watch;
 const int watchSourceId,watchDecoderId;
 SourceTrace::Context request;
 std::mutex guard;std::condition_variable changed;std::deque<Frame> queue;Frame current;
 std::vector<Frame> warm;size_t warmBudget=0;int64_t warmTarget=INT64_MIN;uint64_t warmHits=0;
 std::thread worker;std::atomic<bool> stop{false};bool eof=false;std::string failure;
 int64_t epoch=0,workerEpoch=-1,seekTick=0,wantedPTS=0;size_t peak=0;double decodedSeconds=0;uint64_t decoded=0,seeks=0;
 uint64_t surfacePoolBytes=0;int poolFrames=0,codecThreads=0,threadType=0;
 DecodeReservation reservation;
 std::unique_ptr<Decoder> decoder;AVRational base{0,1};int64_t origin=0;double rotation=0;
 bool opened=false,decoding=false,singlePool=true,holdRefill=false;
 uint64_t deferredRefills=0;
 WatchTuple<7>::Values refillEdge{};
 Clock::time_point refillDeadline=Clock::time_point::max();
 int64_t lastTimedRefillFrame=-1,lastTimedRefillGeneration=-1;
 ID3D11Texture2D* lastPool=nullptr;
 int64_t requestedTick=0;AVRational requestedBase{1,1};
 int64_t streamTick(int64_t tick,AVRational sourceBase)const{
  return av_rescale_q_rnd(tick,sourceBase,base,AV_ROUND_DOWN);
 }
 // Call with guard held. Incoming decode state stays separate from the
 // interval the renderer selects from a cached prefix or outgoing tail.
 void watchQueueLocked()const{
  if(!stallWatch||watch.lane<0)return;
  watchQueue(watch.lane,opened?wantedPTS:AV_NOPTS_VALUE,
             current?current->best_effort_timestamp:AV_NOPTS_VALUE,
             queue.empty()?AV_NOPTS_VALUE:queue.front()->best_effort_timestamp,
             (int)queue.size(),(int)warm.size(),(int)cutTail.size(),epoch,
             opened&&current&&(eof||!queue.empty()),holdRefill,eof);
 }
 // Called with guard held, as are the CV predicate and decoded queue updates.
 void setRefillLocked(bool hold,int reason){
  if(hold==holdRefill)return;
  holdRefill=hold;
  if(!hold)refillDeadline=Clock::time_point::max();
  if(!stallWatch||watch.lane<0)return;
  auto now=stallWatch->now();
  if(hold)refillEdge={now,0,0,wantedPTS,queue.back()->best_effort_timestamp,epoch,refillEdge[6]+1};
  else {refillEdge[1]=now;refillEdge[2]=reason;}
  stallWatch->lanes[watch.lane].pacing.set(refillEdge);
 }
 Producer(const Clip& c,int64_t initialTick,AVBufferRef* device,bool software,int extraHardwareFrames,size_t cacheFrames,
          uint64_t speculativeBytes=0,int watchSourceId=-1,int watchDecoderId=-1):
          watchSourceId(watchSourceId),watchDecoderId(watchDecoderId),request(sourceContext),
          warmBudget(cacheFrames),requestedTick(initialTick),requestedBase(c.timebase){
  reservation.bytes=speculativeBytes;
  watchSource(watch.lane,watchSourceId,watchDecoderId,c.timebase.num,c.timebase.den);
  auto open=[this,clip=&c,device,software,extraHardwareFrames,watchSourceId,watchDecoderId]{
   if(sourceTrace)sourceContext=request;
   SourceStage timer("open_producer");
   WatchStage stage("open_producer");
   AVIOInterruptCB cancel{[](void* p){return static_cast<Producer*>(p)->stop.load()?1:0;},this};
   decoder=std::make_unique<Decoder>(clip->path,device,!software,extraHardwareFrames+(int)warmBudget,&reservation,cancel);
   auto* stream=decoder->file->streams[decoder->stream];
   auto* parameters=stream->codecpar;
   auto* matrix=av_packet_side_data_get(parameters->coded_side_data,parameters->nb_coded_side_data,AV_PKT_DATA_DISPLAYMATRIX);
   double angle=matrix?av_display_rotation_get((const int32_t*)matrix->data):0;
   if(!std::isfinite(angle)||std::abs(angle/90-std::round(angle/90))>.001)throw std::runtime_error("Unsupported source display matrix");
   std::lock_guard<std::mutex> lock(guard);
   rotation=angle;base=stream->time_base;
   origin=decoder->file->start_time==AV_NOPTS_VALUE?0:av_rescale_q(decoder->file->start_time,AV_TIME_BASE_Q,base);
   seekTick=streamTick(requestedTick,requestedBase);wantedPTS=seekTick+origin;warmTarget=seekTick;
   codecThreads=decoder->codec->thread_count;threadType=decoder->codec->active_thread_type;
   opened=true;
   watchSource(watch.lane,watchSourceId,watchDecoderId,base.num,base.den);
   watchQueueLocked();
  };
  if(speculativeBytes){
   worker=std::thread([this,open]{
    WatchThread thread(watch.lane);
    try{open();produce();}
    catch(const std::exception&){std::lock_guard<std::mutex> lock(guard);failure="Native source preparation failed";}
   });
  }else{
   open();worker=std::thread([this]{WatchThread thread(watch.lane);produce();});
  }
 }
 void cancel(){
  WatchStage stage("cancel_producer");
  {std::lock_guard<std::mutex> lock(guard);stop=true;setRefillLocked(false,4);}
  changed.notify_all();
 }
 ~Producer(){WatchStage stage("join_producer");cancel();if(worker.joinable())worker.join();}
 // The old tail and new decode queue SHARE the original four queue slots.
 // Each tail entry is a retained reference to an actual already-decoded
 // floor picture, proved against its successor before rewinding the decoder.
 static constexpr int64_t maxRewindLead=3;
 std::deque<Frame> cutTail;
 const Clip* cutOld=nullptr;
 const Clip* cutNext=nullptr;
 int64_t cutGeneration=-1,tailFirstFrame=-1;
 int64_t tailWatchFirstFrame=-1;
 std::array<int64_t,maxRewindLead> tailWatchSuccessors{};
 size_t peakCombinedQueue=0;
 uint64_t earlyRewinds=0,adoptedRewinds=0,tailHits=0;
 void clearCutLocked(){
  if(!cutNext)return;
  cutTail.clear();cutOld=cutNext=nullptr;cutGeneration=-1;
  reservation.bytes=0;
 }
 void resetLocked(int64_t tick,AVRational sourceBase){
  setRefillLocked(false,3);lastTimedRefillFrame=lastTimedRefillGeneration=-1;
  epoch++;requestedTick=tick;requestedBase=sourceBase;
  if(opened){
   seekTick=streamTick(tick,sourceBase);wantedPTS=seekTick+origin;
   if(warmTarget!=seekTick){warm.clear();warmTarget=seekTick;}
  }
  queue.clear();current.reset();eof=false;watchQueueLocked();changed.notify_all();
 }
 void reset(int64_t tick,AVRational sourceBase){
  WatchStage stage("reset_producer");
  std::lock_guard<std::mutex> lock(guard);
  clearCutLocked();resetLocked(tick,sourceBase);
 }
 bool primeRewind(const Plan& plan,const Clip& outgoing,const Clip& incoming,int64_t frame,int64_t transportGeneration){
  WatchStage stage("prime_rewind");
  std::lock_guard<std::mutex> lock(guard);
  if(cutNext||!current||!singlePool||!surfacePoolBytes||decoding||!failure.empty()||epoch!=workerEpoch||
     outgoing.end<=frame||outgoing.end-frame>maxRewindLead)return false;
  std::deque<Frame> verified;
  const bool recordTail=stallWatch&&watch.lane>=0;
  for(auto f=frame;f<outgoing.end;f++){
   const auto target=streamTick(plan.sourceTick(outgoing,f),outgoing.timebase)+origin;
   Frame floor=current;bool successor=false;
   for(auto& pictured:queue){
    if(pictured->best_effort_timestamp>target){
     successor=true;
     if(recordTail)tailWatchSuccessors[(size_t)(f-frame)]=pictured->best_effort_timestamp;
     break;
    }
    floor=pictured;
   }
   if(floor->best_effort_timestamp>target||(!successor&&!eof))return false;
   if(recordTail&&!successor)tailWatchSuccessors[(size_t)(f-frame)]=AV_NOPTS_VALUE;
   verified.push_back(floor);
  }
  // Existing decoded surfaces stay alive through AVFrame/slot ownership.
  // Forbid allocation of a second pool until the old tail has been consumed.
  reservation.hasPool=true;reservation.bytes=surfacePoolBytes;
  cutTail=std::move(verified);cutOld=&outgoing;cutNext=&incoming;
  cutGeneration=transportGeneration;tailFirstFrame=frame;
  if(recordTail)tailWatchFirstFrame=frame;
  if(sourceTrace){request.frame=frame;request.tick=incoming.inTick;request.num=incoming.timebase.num;request.den=incoming.timebase.den;}
  resetLocked(incoming.inTick,incoming.timebase);
  peakCombinedQueue=std::max(peakCombinedQueue,cutTail.size());earlyRewinds++;
  return true;
 }
 bool adoptRewind(const Clip& requested,int64_t transportGeneration){
  WatchStage stage("adopt_rewind");
  std::lock_guard<std::mutex> lock(guard);
  if(cutNext!=&requested||cutGeneration!=transportGeneration)return false;
  clearCutLocked();adoptedRewinds++;watchQueueLocked();changed.notify_one();return true;
 }
 // Returns zero if retaining this decoder could overlap differently sized
 // pools or a currently running format negotiation. Its active budget is unchanged.
 uint64_t parkableBytes(){
  WatchStage stage("parkable_producer");
  std::lock_guard<std::mutex> lock(guard);
  if(cutNext||!failure.empty()||!singlePool)return 0;
  if(reservation.bytes.load())return surfacePoolBytes?surfacePoolBytes:reservation.bytes.load();
  if(decoding||!surfacePoolBytes)return 0;
  reservation.hasPool=true;reservation.bytes=surfacePoolBytes;
  return surfacePoolBytes;
 }
 void produce(){
  try{
   while(!stop){
    int64_t generation,target;{
     std::unique_lock<std::mutex> lock(guard,std::defer_lock);
     {WatchStage stage("producer_guard");lock.lock();}
     while(!stop&&workerEpoch==epoch){
      if(holdRefill&&refillDeadline!=Clock::time_point::max()&&Clock::now()>=refillDeadline){
       setRefillLocked(false,6);watchQueueLocked();
      }
      if(!eof&&!holdRefill&&queue.size()+cutTail.size()<4)break;
      if(holdRefill&&refillDeadline!=Clock::time_point::max()){
       WatchStage stage("refill_deferred");changed.wait_until(lock,refillDeadline);
      }else{
       WatchStage stage(eof?"producer_eof":queue.size()+cutTail.size()>=4?"queue_full":"refill_deferred");changed.wait(lock);
      }
     }
     if(stop)return;decoding=true;generation=epoch;target=seekTick;
     if(sourceTrace){sourceContext=request;sourceContext.decodeEpoch=generation;sourceContext.depth=(int)queue.size();}
     if(workerEpoch!=generation){workerEpoch=generation;lock.unlock();
      {SourceStage timer("seek_demux");WatchStage stage("seek_demux");avcheck(av_seek_frame(decoder->file,decoder->stream,target+origin,AVSEEK_FLAG_BACKWARD),"source seek");}
      {SourceStage timer("flush_codec");WatchStage stage("flush_codec");avcodec_flush_buffers(decoder->codec);}decoder->eof=decoder->drained=false;
      {WatchStage stage("producer_guard");lock.lock();}seeks++;
      if(stop)return;
      if(generation!=epoch){decoding=false;continue;}
     }
    }
    auto began=Clock::now();bool ok;Frame frame;
    {WatchStage stage("decode_next");ok=decoder->next();if(ok)frame=retain(decoder->frame);}
    WatchStage stage("producer_commit");
    std::lock_guard<std::mutex> lock(guard);decoding=false;decodedSeconds+=seconds(began);if(generation!=epoch)continue;
    if(!ok){eof=true;setRefillLocked(false,5);}
    else{
     if(frame->best_effort_timestamp==AV_NOPTS_VALUE)throw std::runtime_error("Missing source presentation timestamp");
     if(frame->format==AV_PIX_FMT_D3D11&&lastPool!=(ID3D11Texture2D*)frame->data[0]){
      if(lastPool)singlePool=false;lastPool=(ID3D11Texture2D*)frame->data[0];
      D3D11_TEXTURE2D_DESC desc{};
      {WatchStage stage("decode_texture_desc");((ID3D11Texture2D*)frame->data[0])->GetDesc(&desc);}
      if(desc.Format==DXGI_FORMAT_NV12||desc.Format==DXGI_FORMAT_P010){
       poolFrames=(int)desc.ArraySize;
       surfacePoolBytes=(uint64_t)desc.Width*desc.Height*desc.ArraySize*3/(desc.Format==DXGI_FORMAT_P010?1:2);
      }
     }
     if(warmBudget&&frame->best_effort_timestamp>=target+origin&&warm.size()<warmBudget&&
        (warm.empty()||frame->best_effort_timestamp>warm.back()->best_effort_timestamp))warm.push_back(frame);
     // Keep the latest picture before the deadline and its actual successor.
     // Preroll and late-frame catch-up can run without a round trip every four pictures.
     if(frame->best_effort_timestamp<=wantedPTS&&queue.empty())current=frame;
     else queue.push_back(frame);
     decoded++;peak=std::max(peak,queue.size());peakCombinedQueue=std::max(peakCombinedQueue,queue.size()+cutTail.size());
    }watchQueueLocked();changed.notify_all();
   }
  }catch(const std::exception&){std::lock_guard<std::mutex> lock(guard);setRefillLocked(false,7);failure="Native source decode or seek failed";changed.notify_all();}
 }
 void releaseRefill(){
  WatchStage stage("release_refill");
  std::lock_guard<std::mutex> lock(guard);
  if(holdRefill){setRefillLocked(false,2);watchQueueLocked();changed.notify_one();}
 }
 // Returns the source picture whose half-open PTS interval contains the target.
 // Selection paths in the recorder are unavailable, live, warm and outgoing.
 Frame at(const Clip& clip,int64_t frame,int64_t transportGeneration,int64_t tick,bool& ready,bool coordinateRefill,
          int64_t* observation=nullptr,const RefillWindow* window=nullptr){
  WatchStage stage("select_picture");
  auto sourceBase=clip.timebase;
  auto entered=observation?stallWatch->now():0;
  std::lock_guard<std::mutex> lock(guard);
  auto record=[&](int64_t target,int64_t floor,int64_t successor,PictureReason reason){
   if(!observation||watch.lane<0)return;
   auto& channel=stallWatch->lanes[watch.lane];
   WatchTuple<3>::Values packet;
   auto reads=channel.packet.get(packet)?packet[2]:-1;
   const int64_t values[]={
    watch.lane,watchSourceId,watchDecoderId,epoch,tick,sourceBase.num,sourceBase.den,
    target,base.num,base.den,floor,successor,(int64_t)reason,entered,stallWatch->now(),
    (int64_t)queue.size(),AV_NOPTS_VALUE,AV_NOPTS_VALUE,AV_NOPTS_VALUE,AV_NOPTS_VALUE,
    (int64_t)warm.size(),(int64_t)cutTail.size(),eof,holdRefill,reads,channel.sent.load(std::memory_order_relaxed),
    (int64_t)decoded,cutGeneration,workerEpoch
   };
   static_assert(std::size(values)==WatchRequest::layer,"Source observation schema");
   std::copy(std::begin(values),std::end(values),observation);
   for(size_t i=0;i<queue.size()&&i<4;i++)observation[16+i]=queue[i]->best_effort_timestamp;
  };
  if(cutOld==&clip&&cutGeneration==transportGeneration){
   if(frame<tailFirstFrame||frame>=tailFirstFrame+(int64_t)cutTail.size())throw std::runtime_error("Requested old picture outside retained range");
   while(tailFirstFrame<frame){cutTail.pop_front();tailFirstFrame++;changed.notify_one();}
   if(stallWatch&&watch.lane>=0){
    watchQueueLocked();
    watchSelection(watch.lane,frame,transportGeneration,streamTick(tick,sourceBase)+origin,
                   cutTail.front()->best_effort_timestamp,tailWatchSuccessors[(size_t)(frame-tailWatchFirstFrame)],3);
    record(streamTick(tick,sourceBase)+origin,cutTail.front()->best_effort_timestamp,
           tailWatchSuccessors[(size_t)(frame-tailWatchFirstFrame)],PictureReason::outgoing);
   }
   ready=true;tailHits++;return cutTail.front();
  }
  if(!failure.empty())throw std::runtime_error(failure);
  if(!opened){
   watchSelection(watch.lane,frame,transportGeneration,AV_NOPTS_VALUE,AV_NOPTS_VALUE,AV_NOPTS_VALUE,0);
   record(AV_NOPTS_VALUE,AV_NOPTS_VALUE,AV_NOPTS_VALUE,PictureReason::opening);
   ready=false;return nullptr;
  }
  if(eof&&queue.empty()&&!current)throw std::runtime_error("No decodable source picture");
  if(sourceTrace){request=sourceContext;request.tick=tick;request.num=sourceBase.num;request.den=sourceBase.den;}
  int64_t target=streamTick(tick,sourceBase)+origin;
  wantedPTS=target;
  while(!queue.empty()&&(!current||queue.front()->best_effort_timestamp<=target)){
   current=queue.front();queue.pop_front();
  }
  ready=current&&(eof||!queue.empty());
  bool hold=coordinateRefill&&ready&&queue.size()>=2&&queue.size()+cutTail.size()<4&&!eof;
  bool notifyDeadline=false;
  if(hold&&window&&!holdRefill){
   // The last queued picture proves history only up to its own PTS. Keep
   // one full frame of that proof in reserve and never hold past half a
   // sequence frame after the requested deadline, even inside Present.
   const bool newRequest=frame!=lastTimedRefillFrame||transportGeneration!=lastTimedRefillGeneration;
   lastTimedRefillFrame=frame;lastTimedRefillGeneration=transportGeneration;
   const auto ahead=av_rescale_q_rnd(queue.back()->best_effort_timestamp-target,
       av_mul_q(base,av_inv_q(clip.speed)),AV_TIME_BASE_Q,AV_ROUND_DOWN);
   const auto holdUs=std::min(window->periodUs/2,ahead-window->periodUs);
   auto deadline=window->observedAt+std::chrono::microseconds(window->frameDueUs-window->clockUs+holdUs);
   hold=newRequest&&holdUs>0&&Clock::now()<deadline;
   if(hold){refillDeadline=deadline;notifyDeadline=true;}
  }
  setRefillLocked(hold,1);
  if(holdRefill)deferredRefills++;
  // A producer can already be asleep waiting for queue space. Notify when
  // installing a finite deadline so it can switch to the timed CV wait.
  if(!holdRefill||notifyDeadline)changed.notify_one();
  watchQueueLocked();
  if(!ready&&warm.size()>1){
   for(size_t i=1;i<warm.size();i++)if(warm[i-1]->best_effort_timestamp<=target&&target<warm[i]->best_effort_timestamp){
    watchSelection(watch.lane,frame,transportGeneration,target,warm[i-1]->best_effort_timestamp,warm[i]->best_effort_timestamp,2);
    record(target,warm[i-1]->best_effort_timestamp,warm[i]->best_effort_timestamp,PictureReason::warm);
    ready=true;warmHits++;return warm[i-1];
   }
  }
  if(stallWatch&&watch.lane>=0){
   const auto floor=current?current->best_effort_timestamp:AV_NOPTS_VALUE;
   const auto successor=queue.empty()?AV_NOPTS_VALUE:queue.front()->best_effort_timestamp;
   watchSelection(watch.lane,frame,transportGeneration,target,floor,successor,ready?1:0);
   auto reason=!current||floor>target?(ready?PictureReason::beforeFirst:PictureReason::missingFloor):
               !ready?PictureReason::missingSuccessor:eof&&queue.empty()?PictureReason::eof:PictureReason::live;
   record(target,floor,successor,reason);
  }
  return ready?current:nullptr;
 }
};
struct Input {
 HANDLE changed=CreateEventW(nullptr,FALSE,FALSE,nullptr);~Input(){if(changed)CloseHandle(changed);}
 std::mutex guard;std::atomic<bool> stop{false};int64_t microseconds=0,generation=0;bool playing=false;
 Clock::time_point received=Clock::now();Distribution correction;int64_t lastCorrection=0;uint64_t updates=0;
 void command(const std::string& line){
  std::istringstream s(line);std::string op;s>>op;
  std::lock_guard<std::mutex> lock(guard);
  if(op=="CLOCK"){
   auto now=Clock::now();auto previous=microseconds+(playing?std::chrono::duration_cast<std::chrono::microseconds>(now-received).count():0);bool oldPlaying=playing;auto oldGeneration=generation;
   s>>microseconds>>playing>>generation;
   lastCorrection=(oldPlaying&&playing&&oldGeneration==generation)?microseconds-previous:0;
   if(oldPlaying&&playing&&oldGeneration==generation)correction.add(std::abs((double)lastCorrection)/1000.);
   updates++;received=now;
   watchClock(microseconds,generation,playing);
  }
  else if(op=="CLOSE"){stop=true;watchClock(microseconds,generation,false);}
  SetEvent(changed);
 }
 void clockStats(){Distribution copy;uint64_t count;{std::lock_guard<std::mutex> lock(guard);copy=correction;count=updates;}std::cout<<",\"clock_updates\":"<<count<<",\"clock_correction_absolute\":";copy.json();}
 bool isGeneration(int64_t epoch){std::lock_guard<std::mutex> lock(guard);return epoch==generation;}
 bool stillPlaying(int64_t epoch){std::lock_guard<std::mutex> lock(guard);return !stop&&playing&&epoch==generation;}
 bool stillPaused(int64_t epoch){std::lock_guard<std::mutex> lock(guard);return !stop&&!playing&&epoch==generation;}
 void snapshot(int64_t& us,int64_t& gen,bool& play,double* age=nullptr,int64_t* adjustment=nullptr){
  std::lock_guard<std::mutex> lock(guard);us=microseconds;gen=generation;play=playing;
  if(age)*age=seconds(received)*1000;if(adjustment)*adjustment=lastCorrection;
  if(play)us+=std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-received).count();
 }
};
