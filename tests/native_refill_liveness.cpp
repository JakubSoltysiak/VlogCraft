#include "../native/media.h"
#include "../native/timeline.h"

using namespace std::chrono_literals;

// Exercise the decoded-floor guard with a real producer and a queued
// successor that arrives after the request reverses across a continuous cut.
int checkRetarget(const Clip& clip){
 Producer producer(clip,0,nullptr,true,0,0);
 int64_t floor,step,epoch;
 uint64_t seeks;
 {
  std::unique_lock<std::mutex> lock(producer.guard);
  if(!producer.changed.wait_for(lock,3s,[&]{return producer.queue.size()==4&&!producer.decoding;}))return 10;
  auto& queue=producer.queue;
  floor=queue.back()->best_effort_timestamp;
  step=floor-queue[2]->best_effort_timestamp;
  if(step<=1||av_cmp_q(producer.base,clip.timebase)||producer.origin)return 11;
  producer.setRefillLocked(true,1);
  producer.current=queue.back();queue.clear();
  producer.wantedPTS=floor+4*step;
  epoch=producer.epoch;seeks=producer.seeks;
 }
 if(producer.retargetFromFloor(floor-1,clip.timebase))return 12;
 const auto target=floor+step/2;
 if(!producer.retargetFromFloor(target,clip.timebase))return 13;
 producer.releaseRefill();
 {
  std::unique_lock<std::mutex> lock(producer.guard);
  if(!producer.changed.wait_for(lock,3s,[&]{return producer.queue.size()==4;}))return 14;
  if(producer.current->best_effort_timestamp!=floor||producer.queue.front()->best_effort_timestamp!=floor+step||
     producer.epoch!=epoch||producer.seeks!=seeks||producer.peakCombinedQueue>4)return 15;
 }
 bool ready=false;
 auto picture=producer.at(clip,839,2,target,ready,false);
 if(!ready||!picture||picture->best_effort_timestamp!=floor)return 16;
 producer.cancel();
 if(producer.retargetFromFloor(target,clip.timebase))return 17;
 return 0;
}

int main(int argc,char** argv){
 if(argc!=2)return 2;
 av_log_set_level(AV_LOG_QUIET);
 Clip clip;clip.path=argv[1];clip.timebase={1,60000};
 Producer producer(clip,0,nullptr,true,0,0);
 int64_t target;
 uint64_t before;
 {
  std::unique_lock<std::mutex> lock(producer.guard);
  if(!producer.changed.wait_for(lock,3s,[&]{return producer.queue.size()==4&&!producer.decoding;}))return 3;
  target=producer.queue.front()->best_effort_timestamp;
  before=producer.decoded;
 }
 constexpr int64_t generation=2;
 const RefillWindow first{Clock::now(),0,0,100000};
 bool ready=false;
 auto picture=producer.at(clip,0,generation,target,ready,true,nullptr,&first);
 if(!ready||!picture||picture->best_effort_timestamp!=target)return 4;
 {
  // Simulate a blocked Present. The real producer starts in an indefinite
  // queue-space wait and must wake for expiry without a renderer release.
  std::unique_lock<std::mutex> lock(producer.guard);
  if(!producer.changed.wait_for(lock,2s,[&]{return producer.decoded>before;}))return 5;
  if(producer.holdRefill||producer.deferredRefills!=1||producer.queue.size()!=4||producer.epoch!=0)return 6;
  // Make room while retaining the same valid interval. A later inspection
  // with the same generation and frame must not arm another hold.
  producer.queue.pop_back();before=producer.decoded;
 }
 const RefillWindow repeat{Clock::now(),0,0,100000};
 picture=producer.at(clip,0,generation,target,ready,true,nullptr,&repeat);
 if(!ready||!picture||picture->best_effort_timestamp!=target)return 7;
 {
  std::unique_lock<std::mutex> lock(producer.guard);
  if(!producer.changed.wait_for(lock,2s,[&]{return producer.decoded>before;}))return 8;
  if(producer.holdRefill||producer.deferredRefills!=1||producer.peakCombinedQueue>4)return 9;
 }
 producer.cancel();
 return checkRetarget(clip);
}
