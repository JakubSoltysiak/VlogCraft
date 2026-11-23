#include "../native/media.h"
#include "../native/timeline.h"

using namespace std::chrono_literals;

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
 return 0;
}
