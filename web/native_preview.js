/* Experimental native video + reference PCM. Unsupported operations remain explicit. */
const nativeState={available:false,blocked:false,seeking:false,seekFrame:0,prepared:false,hdr:false,busy:null,signature:'',generation:0,serial:0,node:null,audioAbort:null,sent:0,ack:null,start:0,metrics:null,timer:null,bounds:''};
function* nativePCMBlocks(data,length){for(let offset=0;offset<length;offset+=32768)yield data.buffer.slice(offset,Math.min(length,offset+32768));}
function nativeQualityOptions(){
 const native=nativeSelected(),select=$('programResolution'),source=$('previewSource');
 if(native&&!source.disabled){nativeState.savedPreviewSource=source.value;source.value='original';source.disabled=true;}
 else if(!native&&source.disabled){source.disabled=false;source.value=nativeState.savedPreviewSource||'auto';}
 for(const option of select.options)if(option.dataset.nativeOnly)option.disabled=!native;
 if(!native&&Number(select.value)>1920)select.value='960';
}
function nativeSelected(){return $('playbackEngine')?.value==='native';}
function nativeRect(){const r=$('previewStage').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,dpr:devicePixelRatio};}
function nativeBoundsRect(){
 if(!nativeState.geometryObserver){
  const dirty=()=>nativeState.geometryDirty=true;nativeState.geometryObserver=new ResizeObserver(dirty);
  nativeState.geometryObserver.observe($('previewStage'));addEventListener('resize',dirty);
  addEventListener('scroll',event=>{if(event.target===document||event.target===window||event.target?.contains?.($('previewStage')))dirty();},true);dirty();
 }
 if(nativeState.geometryDirty||nativeState.geometry?.dpr!==devicePixelRatio){nativeState.geometry=nativeRect();nativeState.geometryDirty=false;}
 return nativeState.geometry;
}
function nativeSignature(){return JSON.stringify([$('programResolution').value,state.tracks,state.output,state.assets.map(a=>[a.id,a.path,a.size,a.cacheId])]);}
function nativeDuration(){return frameIndex(duration())/sequenceRate();}
function nativeSamplesAt(segments,now){
 let samples=0;for(const [start,end,first,last] of segments||[]){if(now<start)break;samples=Math.min(last,first+Math.max(0,now-start)*48000);}return samples;
}
function nativeClock(){
 const ack=nativeState.ack;if(!ack)return nativeState.start;
 let audible=mixer?.getOutputTimestamp?.(),now=mixer?.currentTime||0;
 if(audible?.performanceTime)now=audible.contextTime+(performance.now()-audible.performanceTime)/1000;
 const pending=ack.contextEnd?Math.max(0,(ack.contextEnd-now)*48000):0;
 const samples=nativeSamplesAt(ack.segments,now);
 if(ack.finished&&pending<1)return nativeDuration();
 return Math.min(nativeDuration(),nativeState.start+samples/48000);
}
function nativePause(){
 nativeState.node?.port.postMessage({type:'play',generation:nativeState.generation,playing:false});
 if(nativeState.prepared)void request('native/clock','POST',{generation:nativeState.generation,microseconds:Math.round(nativeClock()*1e6),playing:false}).catch(()=>{});
}
async function nativeStop(){
 nativeState.serial++;nativeState.pendingSeek=null;nativeState.audioAbort?.abort();nativeState.node?.disconnect();nativeState.node=null;
 nativeState.prepared=false;nativeState.seeking=false;nativeState.ack=null;clearInterval(nativeState.timer);nativeState.timer=null;
 await request('native/stop','POST',{}).catch(()=>{});
}
function nativeFail(message,code){
 nativePause();nativeState.audioAbort?.abort();isPlaying=false;$('playBtn').innerHTML=svg('play');
 $('programPreviewStatus').hidden=false;$('programPreviewStatus').textContent=message;
 const videoIds=new Set((programTracks||[]).filter(t=>t.type==='video'&&!t.hidden).flatMap(t=>t.clips.map(c=>c.assetId)));
 const hdr=code==='color_contract'||state.assets.some(a=>videoIds.has(a.id)&&(a.hdr||a.colorTransfer==='smpte2084'||a.colorTransfer==='arib-std-b67'));
 if(!hdr){void nativeStop();$('playbackEngine').value='rendered';invalidateRendered();refreshPlayers();syncPreview(true);toast('Reference fallback: '+message,true);}
 else{nativeState.blocked=true;void nativeStop();toast(message+' · Choose Composited preview for explicit SDR output.',true);}
}
async function nativeAudio(frame,serial){
 nativeState.audioAbort?.abort();const abort=new AbortController();nativeState.audioAbort=abort;
 nativeState.start=frame/sequenceRate();nativeState.sent=0;nativeState.ack=null;
 if(!mixer)await initializeMixer();
 if(mixer.sampleRate!==48000)throw Error('Native PCM currently requires a 48 kHz audio device');
 if(!nativeState.module){await mixer.audioWorklet.addModule('native_audio_worklet.js');nativeState.module=true;}
 nativeState.node?.disconnect();
 const generation=nativeState.generation,node=new AudioWorkletNode(mixer,'vlogcraft-pcm',{numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[2]});
 nativeState.node=node;node.connect(bus);node.port.postMessage({type:'reset',generation});
 node.port.onmessage=event=>{if(event.data.generation===nativeState.generation){if(event.data.error)return nativeFail(event.data.error);nativeState.ack=event.data;}};
 void(async()=>{
  let at=frame;
  while(at<frameIndex(duration())&&!abort.signal.aborted&&serial===nativeState.serial){
   const response=await fetch('api/native/audio?generation='+generation+'&frame='+at,{signal:abort.signal});
   if(!response.ok)throw Error('Native audio stream is unavailable');
   const expected=Number(response.headers.get('Content-Length'));let bytes=0,left=new Uint8Array(0);
   const reader=response.body.getReader();
   for(;;){
    const result=await reader.read();if(result.done)break;bytes+=result.value.byteLength;
    const joined=new Uint8Array(left.length+result.value.length);joined.set(left);joined.set(result.value,left.length);
    const n=Math.floor(joined.length/4)*4;left=joined.slice(n);if(!n)continue;
    for(const data of nativePCMBlocks(joined,n)){
    while(nativeState.sent-(nativeState.ack?.samples||0)+data.byteLength/4>96000){
     if(abort.signal.aborted||serial!==nativeState.serial){await reader.cancel();return;}
     await new Promise(r=>setTimeout(r,5));
    }
    if(abort.signal.aborted||serial!==nativeState.serial){await reader.cancel();return;}
    const frames=data.byteLength/4;node.port.postMessage({type:'push',generation,data},[data]);nativeState.sent+=frames;
    }
   }
   if(bytes!==expected||left.length)throw Error('Native audio sample budget was incomplete');
   at=Number(response.headers.get('X-End-Frame'));
  }
  if(!abort.signal.aborted)node.port.postMessage({type:'end',generation});
 })().catch(error=>{if(error.name!=='AbortError'&&serial===nativeState.serial)nativeFail(error.message);});
}
async function nativeSeek(frame){
 const serial=++nativeState.serial;nativeState.seeking=true;nativeState.seekFrame=frame;nativePause();nativeState.audioAbort?.abort();
 nativeState.pendingSeek={frame,serial};
 if(nativeState.seekBusy)return nativeState.seekBusy;
 nativeState.seekBusy=(async()=>{
  while(nativeState.pendingSeek){
   const {frame,serial}=nativeState.pendingSeek;nativeState.pendingSeek=null;
   const result=await request('native/seek','POST',{frame,generation:nativeState.generation});
   nativeState.generation=Math.max(nativeState.generation,result.generation);
   if(serial!==nativeState.serial)continue;nativeState.seeking=true;
   await nativeAudio(frame,serial);
   const began=performance.now();
   while(serial===nativeState.serial&&isPlaying&&(!nativeState.ack||nativeState.ack.queued<Math.min(12000,(nativeDuration()-nativeState.start)*48000)||nativeState.seeking)){
    if(performance.now()-began>30000)throw Error('Native seek preparation timed out');
    await new Promise(r=>setTimeout(r,10));
   }
   if(serial===nativeState.serial&&isPlaying)nativeState.node.port.postMessage({type:'play',generation:nativeState.generation,playing:true});
  }
 })().finally(()=>nativeState.seekBusy=null);
 return nativeState.seekBusy;
}
async function nativePrepare(){
 if(nativeState.busy)return nativeState.busy;
 nativeState.busy=(async()=>{
  nativePause();nativeState.audioAbort?.abort();await flushSave();
  const signature=nativeSignature(),frame=frameIndex(playhead),serial=++nativeState.serial;
  const result=await request('native/start','POST',{rect:nativeRect(),width:Number($('programResolution').value),microseconds:Math.round(playhead*1e6)});
  if(!nativeSelected()||serial!==nativeState.serial)return;
  nativeState.signature=signature;nativeState.generation=result.generation;nativeState.prepared=true;nativeState.hdr=result.hdr;nativeState.metrics=null;
  $('programPreviewStatus').textContent='Original media · '+result.width+' × '+result.height+' preview'+(result.width<state.output.width?' (reduced)':'')+' · '+(result.hdr?'HDR PQ; HDR10+ metadata not applied':'SDR')+' · Native GPU experimental';
  await nativeAudio(frame,serial);
  clearInterval(nativeState.timer);
  nativeState.timer=setInterval(async()=>{
   if(!nativeSelected()||!nativeState.prepared||nativeState.polling)return;
   nativeState.polling=true;
   try{
    const generation=nativeState.generation,serial=nativeState.serial;
    const rect=nativeBoundsRect(),visible=!nativeState.seeking&&!document.querySelector('dialog[open],.modal-overlay:not([hidden]),#dropOverlay:not([hidden]),#transferOverlay:not([hidden])')&&(isPlaying||!($('referenceButton').classList.contains('active')||$('scopeChoice').value)),bounds=JSON.stringify([rect,visible]);
    if(bounds!==nativeState.bounds){nativeState.bounds=bounds;await request('native/bounds','POST',{rect,visible});}
    const metrics=await request('native/clock','POST',{generation,microseconds:Math.round(nativeClock()*1e6),playing:isPlaying&&!nativeState.seeking&&!!nativeState.ack&&!nativeState.ack.waiting});
    if(generation!==nativeState.generation||serial!==nativeState.serial||!nativeState.prepared)return;
    nativeState.metrics=metrics;
    if(nativeState.seeking&&nativeState.metrics.completed_generation===nativeState.generation&&nativeState.metrics.completed_sequence_frame>=nativeState.seekFrame)nativeState.seeking=false;
    if(nativeState.metrics.event==='error')nativeFail(nativeState.metrics.reason,nativeState.metrics.code);
   }catch(error){if(nativeState.prepared&&nativeSelected())nativeFail(error.message);}
   finally{nativeState.polling=false;}
  },15);
 })().catch(error=>nativeFail(error.message)).finally(()=>nativeState.busy=null);
 return nativeState.busy;
}
function nativePreview(force){
 if(!nativeSelected())return false;
 if(nativeState.blocked)return true;
 if(!$('previewLayers').hidden)$('previewLayers').hidden=true;if(!$('emptyPreview').hidden)$('emptyPreview').hidden=true;
 if($('programPreviewStatus').hidden)$('programPreviewStatus').hidden=false;if($('programResolution').hidden)$('programResolution').hidden=false;
 if(!nativeState.prepared){if(!nativeState.busy)void nativePrepare();return true;}
 if(force){
  if(nativeSignature()!==nativeState.signature){nativeState.prepared=false;void nativePrepare();}
  else void nativeSeek(Math.min(frameIndex(playhead),Math.max(0,frameIndex(duration())-1))).catch(e=>nativeFail(e.message));
 }
 return true;
}
async function nativePlayPause(){
 if(isPlaying){stopPlayback();return;}
 if(!duration())return;
 if(playhead>=duration()-.001){playhead=0;if(nativeState.prepared)await nativeSeek(0);}
 await initializeMixer();if(!nativeState.prepared)await nativePrepare();
 if(!nativeSelected()||!nativeState.prepared)return;
 const started=performance.now();
 while(!nativeState.ack||nativeState.ack.queued<Math.min(12000,(nativeDuration()-nativeState.start)*48000)||!(nativeState.metrics?.completed_frames>0)||nativeState.metrics?.waiting){
  if(performance.now()-started>30000)return nativeFail('Native audio preparation timed out');
  if(!nativeState.prepared)return;await new Promise(r=>setTimeout(r,10));
 }
 isPlaying=true;nativeState.node.port.postMessage({type:'play',generation:nativeState.generation,playing:true});
 $('playBtn').innerHTML=svg('pause');requestAnimationFrame(animate);
}
async function setupNative(){
 const info=await request('native/capabilities');nativeState.available=info.available;
 const choice=document.createElement('option');choice.value='native';choice.textContent='Native GPU · experimental';choice.disabled=!info.available;
 $('playbackEngine').append(choice);
 for(const [value,label] of [[2560,'1440p · native preview'],[3840,'2160p · native preview']]){const o=new Option(label,value);o.dataset.nativeOnly='true';$('programResolution').add(o);}nativeQualityOptions();
}
