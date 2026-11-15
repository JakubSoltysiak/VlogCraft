/* Opt-in QA only. Fixed storage; no AudioWorklet/render-thread modification. */
globalThis.installQAFlightRecorder=function({capacity=256,eventLimit=16,tailMs=5000}={}){
 const node=nativeState.node,original=node.port.onmessage,ring=new Float64Array(capacity*9);
 let count=0,last=-Infinity,lastUnder=nativeState.ack?.underruns||0,lastSkip=nativeState.metrics?.skipped_sequence_frames||0;
 const events=[];let pending=null;
 function rows(){const result=[];for(let i=Math.max(0,count-capacity);i<count;i++)result.push(Array.from(ring.subarray((i%capacity)*9,(i%capacity+1)*9)));return result;}
 function header(now){return {view_ms:now,native_wall_seconds:nativeState.metrics?.wall_seconds,
  samples:nativeState.ack?.samples,underruns:nativeState.ack?.underruns,skips:nativeState.metrics?.skipped_sequence_frames,
  native_timings:nativeState.metrics?.timings};}
 function wrapped(event){
  original?.call(this,event);if(event.data.generation!==nativeState.generation)return;
  const now=performance.now(),under=event.data.underruns||0,skip=nativeState.metrics?.skipped_sequence_frames||0;
  if(now-last>=100||under>lastUnder||skip-lastSkip>=6){
   const i=(count++%capacity)*9;
   ring.set([now,mixer.currentTime,event.data.samples,event.data.queued,nativeState.sent,event.data.underruns,
    nativeState.metrics?.wall_seconds??NaN,nativeState.metrics?.sequence_frame??NaN,skip],i);last=now;
  }
  if(!pending&&(under>lastUnder||skip-lastSkip>=6)&&events.length<eventLimit)
   pending={reason:under>lastUnder?'audio_underrun':'skip_counter_increase',before:rows(),trigger:header(now),until:now+tailMs};
  if(pending&&now>=pending.until){pending.after=rows();pending.end=header(now);events.push(pending);pending=null;}
  lastUnder=under;lastSkip=skip;
 }
 node.port.onmessage=wrapped;
 return {stop(){if(node.port.onmessage===wrapped)node.port.onmessage=original;if(pending){pending.after=rows();events.push(pending);pending=null;}
   return {columns:['view_ms','context_seconds','samples','queued','sent','underruns','native_wall_seconds','sequence_frame','skips'],
    capacity,event_limit:eventLimit,events,recent:rows(),final:header(performance.now()),
    clock_scope:'View performance clock, audio context and native process wall time remain distinct. Native status is asynchronously delivered; tuples bound observations, not exact execution timestamps.'};}};
};
