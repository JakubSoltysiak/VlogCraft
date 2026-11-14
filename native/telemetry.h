#pragma once
#include <array>
#include <algorithm>
#include <iostream>
// Bounded 0.1 ms histogram. Quantiles are bucket upper bounds; overflow is explicit.
struct Distribution {
 std::array<uint64_t,1001> bins={};uint64_t count=0,overflow=0;double sum=0,maximum=0,last=0;
 void add(double milliseconds){
  milliseconds=std::max(0.,milliseconds);last=milliseconds;count++;sum+=milliseconds;maximum=std::max(maximum,milliseconds);
  if(milliseconds>=100.)overflow++;
  bins[std::min<size_t>(1000,(size_t)(milliseconds*10))]++;
 }
 double quantile(double q)const{
  if(!count)return 0;uint64_t wanted=(uint64_t)std::ceil(q*count),seen=0;
  for(size_t i=0;i<bins.size();i++){seen+=bins[i];if(seen>=wanted)return i==1000?maximum:(i+1)/10.;}return maximum;
 }
 void json()const{std::cout<<"{\"count\":"<<count<<",\"mean_ms\":"<<(count?sum/count:0)<<",\"p50_upper_ms\":"<<quantile(.5)<<",\"p95_upper_ms\":"<<quantile(.95)<<",\"p99_upper_ms\":"<<quantile(.99)<<",\"max_ms\":"<<maximum<<",\"overflow_100ms\":"<<overflow<<"}";}
};
