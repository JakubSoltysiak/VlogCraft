let referenceRevision=0,referenceTimer=null,referenceBusy=false,referenceQueued=false;
function referenceChanged(){
  const rev=++referenceRevision;
  clearTimeout(referenceTimer);
  $('referenceImage').hidden=true;
  if(!$('referenceButton').classList.contains('active')||isPlaying||!state)return;
  const frame=frameIndex(playhead);
  if(frame>=frameIndex(duration()))return;
  referenceTimer=setTimeout(async()=>{
    if(referenceBusy){referenceQueued=true;return;}
    referenceBusy=true;
    try{
      if(modified>persisted)await flushSave();
      const result=await request('program/frame','POST',{frame});
      if(rev===referenceRevision){
        $('referenceImage').src=result.image;
        $('referenceImage').hidden=false;
      }
    }catch(err){if(rev===referenceRevision)toast('Reference monitor: '+err.message,true);}
    finally{referenceBusy=false;if(referenceQueued){referenceQueued=false;referenceChanged();}}
  },90);
}
function setupReference(){
  $('referenceButton').onclick=()=>{$('referenceButton').classList.toggle('active');referenceChanged();};
}
