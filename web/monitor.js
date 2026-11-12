let referenceRevision=0,referenceTimer=null,referenceBusy=false,referenceQueued=false;
function referenceChanged(){
  const rev=++referenceRevision;
  clearTimeout(referenceTimer);
  $('referenceImage').hidden=true;
  const showReference=$('referenceButton').classList.contains('active'),scope=$('scopeChoice').value;
  $('scopeCanvas').hidden=true;
  if((!showReference&&!scope)||isPlaying||!state)return;
  const frame=frameIndex(playhead);
  if(frame>=frameIndex(duration()))return;
  referenceTimer=setTimeout(async()=>{
    if(referenceBusy){referenceQueued=true;return;}
    referenceBusy=true;
    try{
      if(modified>persisted)await flushSave();
      const result=await request('program/frame','POST',{frame});
      if(rev===referenceRevision){
        const image=new Image();image.src=result.image;await image.decode();
        if(rev!==referenceRevision)return;
        if(showReference){$('referenceImage').src=image.src;$('referenceImage').hidden=false;}
        if(scope){$('scopeCanvas').hidden=false;drawScopes(image);}
      }
    }catch(err){if(rev===referenceRevision)toast('Reference monitor: '+err.message,true);}
    finally{referenceBusy=false;if(referenceQueued){referenceQueued=false;referenceChanged();}}
  },90);
}
function setupReference(){
  $('scopeChoice').onchange=referenceChanged;
  $('referenceButton').onclick=()=>{$('referenceButton').classList.toggle('active');referenceChanged();};
}
