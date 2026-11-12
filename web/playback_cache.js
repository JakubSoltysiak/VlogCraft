const waitingPlayers=new Map(),videoPool=[];
let warmAt=0;
function sourceVideo(c){
  const src=seekUrl(c.assetId);
  const at=videoPool.findIndex(p=>p.aId===c.assetId&&p.src===src);
  if(at>=0)return videoPool.splice(at,1)[0].media;
  const media=document.createElement('video');media.src=src;media.preload='auto';
  media.playsInline=true;media.disablePictureInPicture=true;return media;
}
function recycleVideo(p){
  const media=p.media;if(!media)return;
  media.pause?.();media.remove();
  if(media.tagName!=='VIDEO'){releaseStrip(media);return;}
  const strip=strips.get(media);if(strip)strip.level.gain.value=0;
  if(videoPool.length>=4){const old=videoPool.shift().media;releaseStrip(old);old.removeAttribute('src');old.load();}
  videoPool.push({media,aId:p.aId,src:seekUrl(p.aId)});
}
function clearPlaybackCache(){
  for(const p of waitingPlayers.values()){releaseStrip(p.media);p.media.removeAttribute('src');p.media.load();}
  for(const p of videoPool){releaseStrip(p.media);p.media.removeAttribute('src');p.media.load();}
  waitingPlayers.clear();videoPool.length=0;warmAt=0;
}
function warmPlayers(){
  const now=performance.now();if(now-warmAt<180)return;warmAt=now;
  const upcoming=[];
  for(const t of programTracks)if(t.type==='video'&&!t.hidden){
    for(const c of clipsIn(t,playhead,playhead+.65))if(c.position>playhead&&c.kind==='video')upcoming.push(c);
  }
  const next=upcoming.sort((a,b)=>a.position-b.position).slice(0,4),ids=new Set(next.map(c=>c.id));
  for(const [id,p] of waitingPlayers)if(!ids.has(id)){waitingPlayers.delete(id);recycleVideo(p);}
  for(const c of next)if(!waitingPlayers.has(c.id)){
    const media=sourceVideo(c);
    const seek=()=>{try{media.currentTime=c.start;}catch{}};
    if(media.readyState)seek();else media.addEventListener('loadedmetadata',seek,{once:true});
    waitingPlayers.set(c.id,{media,aId:c.assetId});
  }
}
