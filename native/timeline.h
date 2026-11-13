#pragma once
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
Frame retain(AVFrame* p){return Frame(av_frame_clone(p),[](AVFrame* f){av_frame_free(&f);});}
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
 bool adjacent(const Clip& old,const Clip& next)const{return old.asset==next.asset&&old.end==next.position&&std::llabs(av_rescale_q(old.outTick,old.timebase,next.timebase)-next.inTick)<=1;}
 int64_t sourceTick(const Clip& c,int64_t frame)const{
  // Exact rescaling to source ticks, rounded down for half-open held-PTS selection.
  AVRational units=av_mul_q(av_inv_q(rate),c.speed);
  return c.inTick+av_rescale_q_rnd(frame-c.position,units,c.timebase,(AVRounding)AV_ROUND_DOWN);
 }
};
struct Producer {
 std::mutex guard;std::condition_variable changed;std::deque<Frame> queue;Frame current;
 std::vector<Frame> warm;size_t warmBudget=0;int64_t warmTarget=INT64_MIN;uint64_t warmHits=0;
 std::thread worker;std::atomic<bool> stop{false};bool eof=false;std::string failure;
 int64_t epoch=0,workerEpoch=-1,seekTick=0;size_t peak=0;double decodedSeconds=0;uint64_t decoded=0,seeks=0;
 std::unique_ptr<Decoder> decoder;AVRational base;int64_t origin=0;double rotation=0;
 Producer(const Clip& c,AVBufferRef* device,bool software=false,int extraHardwareFrames=8,size_t cacheFrames=0):warmBudget(cacheFrames){
  decoder=std::make_unique<Decoder>(c.path,device,!software,extraHardwareFrames+(int)warmBudget);
  auto* parameters=decoder->file->streams[decoder->stream]->codecpar;
  auto* matrix=av_packet_side_data_get(parameters->coded_side_data,parameters->nb_coded_side_data,AV_PKT_DATA_DISPLAYMATRIX);
  if(matrix)rotation=av_display_rotation_get((const int32_t*)matrix->data);
  if(!std::isfinite(rotation)||std::abs(rotation/90-std::round(rotation/90))>.001)throw std::runtime_error("Unsupported source display matrix");
  base=decoder->file->streams[decoder->stream]->time_base;
  origin=decoder->file->start_time==AV_NOPTS_VALUE?0:av_rescale_q(decoder->file->start_time,AV_TIME_BASE_Q,base);
  decoder->file->interrupt_callback={[](void* p){return ((Producer*)p)->stop.load()?1:0;},this};
  seekTick=av_rescale_q(c.inTick,c.timebase,base);worker=std::thread([this]{produce();});
 }
 ~Producer(){stop=true;changed.notify_all();if(worker.joinable())worker.join();}
 void reset(int64_t tick,AVRational sourceBase){
  std::lock_guard<std::mutex> lock(guard);epoch++;seekTick=av_rescale_q(tick,sourceBase,base);if(warmTarget!=seekTick){warm.clear();warmTarget=seekTick;}queue.clear();current.reset();eof=false;changed.notify_all();
 }
 void produce(){
  try{
   while(!stop){
    int64_t generation,target;{
     std::unique_lock<std::mutex> lock(guard);changed.wait(lock,[&]{return stop||workerEpoch!=epoch||(!eof&&queue.size()<4);});
     if(stop)return;generation=epoch;target=seekTick;
     if(workerEpoch!=generation){workerEpoch=generation;lock.unlock();
      avcheck(av_seek_frame(decoder->file,decoder->stream,target+origin,AVSEEK_FLAG_BACKWARD),"source seek");
      avcodec_flush_buffers(decoder->codec);decoder->eof=decoder->drained=false;
      lock.lock();seeks++;
     }
    }
    auto began=Clock::now();bool ok=decoder->next();Frame frame=ok?retain(decoder->frame):nullptr;
    std::lock_guard<std::mutex> lock(guard);decodedSeconds+=seconds(began);if(generation!=epoch)continue;
    if(!ok)eof=true;
    else{
     if(frame->best_effort_timestamp==AV_NOPTS_VALUE)throw std::runtime_error("Missing source presentation timestamp");
     if(warmBudget&&frame->best_effort_timestamp>=target+origin&&warm.size()<warmBudget){if(warmTarget!=target){warm.clear();warmTarget=target;}warm.push_back(frame);}
     queue.push_back(frame);decoded++;peak=std::max(peak,queue.size());
    }changed.notify_all();
   }
  }catch(const std::exception&){std::lock_guard<std::mutex> lock(guard);failure="Native source decode or seek failed";changed.notify_all();}
 }
 // Returns the source picture whose half-open PTS interval contains the target.
 Frame at(int64_t tick,AVRational sourceBase,bool& ready){
  std::lock_guard<std::mutex> lock(guard);if(!failure.empty())throw std::runtime_error(failure);
  int64_t target=av_rescale_q(tick,sourceBase,base)+origin;
  while(!queue.empty()&&(!current||queue.front()->best_effort_timestamp<=target)){
   current=queue.front();queue.pop_front();changed.notify_all();
  }
  ready=current&&(eof||!queue.empty());
  if(!ready&&warm.size()>1){
   for(size_t i=1;i<warm.size();i++)if(warm[i-1]->best_effort_timestamp<=target&&target<warm[i]->best_effort_timestamp){ready=true;warmHits++;return warm[i-1];}
  }
  return ready?current:nullptr;
 }
};
struct Input {
 HANDLE changed=CreateEventW(nullptr,FALSE,FALSE,nullptr);~Input(){if(changed)CloseHandle(changed);}
 std::mutex guard;std::atomic<bool> stop{false};int64_t microseconds=0,generation=0;bool playing=false;
 Clock::time_point received=Clock::now();
 void command(const std::string& line){
  std::istringstream s(line);std::string op;s>>op;
  std::lock_guard<std::mutex> lock(guard);
  if(op=="CLOCK"){s>>microseconds>>playing>>generation;received=Clock::now();}
  else if(op=="CLOSE")stop=true;
  SetEvent(changed);
 }
 void snapshot(int64_t& us,int64_t& gen,bool& play){
  std::lock_guard<std::mutex> lock(guard);us=microseconds;gen=generation;play=playing;
  if(play)us+=std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-received).count();
 }
};
