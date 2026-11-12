function preciseSource(dlg,asset,media) {
  const host=document.createElement('div');
  host.className='source-precision';
  host.innerHTML='<div class="property-actions"><button class="text-button" data-step="-1">Previous frame</button><button class="text-button" data-step="0">Inspect frame</button><button class="text-button" data-step="1">Next frame</button></div><p role="status"></p>';
  dlg.querySelector('.source-media').after(host);
  const still=document.createElement('img');still.hidden=true;
  still.alt='Decoded original source frame';media.after(still);
  const message=host.querySelector('p');
  let frame=null,busy=false;
  const dismiss=()=>{frame=null;still.hidden=true;media.hidden=false;message.textContent='';};
  const resume=document.createElement('button');
  resume.className='text-button';resume.textContent='Return to playback';resume.hidden=true;host.append(resume);
  resume.onclick=()=>{resume.hidden=true;dismiss();};
  async function step(offset,mark){
    if(busy)return;
    media.pause();busy=true;const cursor=frame?.start??media.currentTime;
    host.querySelectorAll('[data-step]').forEach(b=>b.disabled=true);
    message.textContent='Indexing original presentation timestamps…';
    const report=setInterval(async()=>{
      try{const s=await request('source/status?assetId='+asset.id);if(s.indexing)message.textContent='Indexing · '+s.frames+' source frames';}catch{}
    },600);
    try{
      const result=await request('source/frame','POST',{assetId:asset.id,seconds:cursor,step:offset});
      if(!dlg.open)return;
      frame=result;media.currentTime=frame.start;still.src=frame.image;still.hidden=false;media.hidden=true;resume.hidden=false;
      message.textContent='Frame '+(frame.index+1)+' / '+frame.count+' · PTS '+frame.pts+' × '+frame.timeBase;
      if(mark)$('source'+mark).value=mark==='In'?frame.start:frame.end;
    }catch(e){if(dlg.open)message.textContent=e.message;}
    finally{clearInterval(report);busy=false;host.querySelectorAll('[data-step]').forEach(b=>b.disabled=false);}
  }
  host.querySelectorAll('[data-step]').forEach(b=>b.onclick=()=>step(Number(b.dataset.step)));
  $('markIn').onclick=()=>step(0,'In');$('markOut').onclick=()=>step(0,'Out');
  dlg.addEventListener('close',()=>{if(busy)void request('source/cancel','POST',{assetId:asset.id}).catch(()=>{});},{once:true});
}
