let renderedTarget=0;
let renderedEpoch=0,renderedRequest=0,renderedCurrent=null,renderedNext=null,renderedLoading=false;
function renderedEnabled(){return $('playbackEngine')?.value==='rendered';}
function releaseProgram(item){
  if(!item)return;
  item.media.pause();releaseStrip(item.media);item.media.removeAttribute('src');item.media.load();item.media.remove();
}
function invalidateRendered(){
  renderedEpoch++;renderedRequest++;renderedLoading=false;
  releaseProgram(renderedCurrent);releaseProgram(renderedNext);renderedCurrent=renderedNext=null;
}
function renderedClock(){return renderedCurrent&&!renderedCurrent.media.seeking?Math.min(renderedCurrent.end,renderedCurrent.start+renderedCurrent.media.currentTime):playhead;}
function pauseRendered(){renderedCurrent?.media.pause();}
async function fetchProgram(at,epoch){
  if(modified>persisted)await flushSave();
  const frame=Math.min(frameIndex(at),Math.max(0,frameIndex(duration())-1));
  let info=await request('preview','POST',{frame,width:Number($('programResolution').value),proxies:useProxies});
  while(['queued','rendering'].includes(info.status)){
    if(epoch!==renderedEpoch)throw Error('Preview superseded');
    $('programPreviewStatus').textContent='Compositing '+info.percent+'%';
    await new Promise(resolve=>setTimeout(resolve,160));
    info=await request('preview/status?id='+info.id);
  }
  if(info.status!=='ready')throw Error(info.error||'Preview cancelled');
  if(epoch!==renderedEpoch)throw Error('Preview superseded');
  const media=document.createElement('video');media.className='rendered-program';
  media.playsInline=true;media.preload='auto';media.hidden=true;
  $('previewStage').append(media);
  const loaded=new Promise((resolve,reject)=>{media.onloadeddata=resolve;media.onerror=()=>reject(Error('Cannot decode program preview'));});
  media.src=info.url;
  try{await loaded;}catch(error){releaseProgram({media});throw error;}
  if(epoch!==renderedEpoch){releaseProgram({media});throw Error('Preview superseded');}
  return {...info,media};
}
async function loadProgram(at){
  if(renderedLoading)return;
  renderedTarget=at;
  const epoch=renderedEpoch,serial=++renderedRequest;
  renderedLoading=true;$('programPreviewStatus').hidden=false;
  try{
    let item;
    if(renderedNext&&at>=renderedNext.start&&at<renderedNext.end){item=renderedNext;renderedNext=null;}
    else item=await fetchProgram(at,epoch);
    if(serial!==renderedRequest||!renderedEnabled()){releaseProgram(item);return;}
    const target=Math.min(renderedTarget,Math.max(0,duration()-1/sequenceRate()));
    if(target<item.start||target>=item.end){
      releaseProgram(item);renderedLoading=false;return loadProgram(target);
    }
    releaseProgram(renderedCurrent);renderedCurrent=item;
    item.media.currentTime=Math.max(0,target-item.start);item.media.hidden=false;
    item.media.onended=()=>{
      if(!isPlaying)return;
      playhead=Math.min(item.end,duration());positionPlayhead();
      if(playhead>=duration()-1e-6)stopPlayback();else void loadProgram(playhead);
    };
    mixSource(item.media,{},1);
    $('programPreviewStatus').textContent='Composited · '+item.media.videoHeight+'p';
    if(isPlaying)await item.media.play();
  }catch(error){
    if(epoch===renderedEpoch&&serial===renderedRequest){
      $('programPreviewStatus').textContent=error.message;toast(error.message,true);stopPlayback();
    }
  }finally{if(serial===renderedRequest)renderedLoading=false;}
}
let prefetchEpoch=null;
function renderedPreview(force){
  if(!renderedEnabled())return false;
  $('previewLayers').hidden=true;
  if(force){renderedTarget=playhead;referenceChanged();}
  if(!duration())return true;
  const item=renderedCurrent;
  if(!item||playhead<item.start-1e-6||playhead>=item.end-1e-6){
    if(!renderedLoading)void loadProgram(playhead);
    return true;
  }
  mixSource(item.media,{},1);
  if(force && Math.abs(item.media.currentTime-(playhead-item.start))>.001)item.media.currentTime=playhead-item.start;
  if(isPlaying&&item.media.paused&&!renderedLoading&&!item.media.ended)void item.media.play().catch(e=>toast(e.message,true));
  if(!isPlaying)item.media.pause();
  if(isPlaying&&!renderedNext&&prefetchEpoch!==renderedEpoch&&item.end<duration()-1e-6){
    const epoch=renderedEpoch;prefetchEpoch=epoch;
    void fetchProgram(item.end,epoch).then(next=>{
      if(epoch===renderedEpoch)renderedNext=next;else releaseProgram(next);
    }).catch(error=>{if(epoch===renderedEpoch)toast(error.message,true);}).finally(()=>{if(prefetchEpoch===epoch)prefetchEpoch=null;});
  }
  return true;
}
function setupRenderedPreview(){
  const change=()=>{
    stopPlayback();invalidateRendered();refreshPlayers();
    if(!renderedEnabled())void request('preview/cancel','POST',{}).catch(e=>toast(e.message,true));
    $('previewLayers').hidden=renderedEnabled();
    $('programResolution').hidden=!renderedEnabled();$('programPreviewStatus').hidden=!renderedEnabled();
    syncPreview(true);
  };
  $('playbackEngine').onchange=change;
  $('programResolution').onchange=change;
}
