// Prefix maxima also find long clips which begin before the visible range.
let laneIndex=new Map();
let sequenceEnd=0,programTracks=[];
function rebuildIndex(){
  laneIndex=new Map();sequenceEnd=0;
  programTracks=playbackTracks(state.tracks);
  for(const track of new Set([...state.tracks,...programTracks])){
    const clips=track.clips.slice().sort((a,b)=>a.position-b.position);
    const ends=[];let max=0;
    for(const clip of clips){max=Math.max(max,endOf(clip));ends.push(max);}
    laneIndex.set(track,{clips,ends});
    if(!track.hidden)sequenceEnd=Math.max(sequenceEnd,max);
  }
}
function clipsIn(track,from,to){
  const index=laneIndex.get(track);
  if(!index)return [];
  let lo=0,hi=index.ends.length;
  while(lo<hi){const mid=Math.floor((lo+hi)/2);if(index.ends[mid]<=from)lo=mid+1;else hi=mid;}
  const visible=[];
  for(let i=lo;i<index.clips.length && index.clips[i].position<=to;i++){
    if(endOf(index.clips[i])>from)visible.push(index.clips[i]);
  }
  return visible;
}
function audible(t){
  return !t.muted && (!programTracks.some(track=>track.solo) || t.solo);
}
function trackSettings(t){
  const dialog=document.createElement('dialog');dialog.className='motion-dialog';
  dialog.innerHTML='<form method="dialog"><h2>Track settings</h2><div class="property"><label>Name</label><input name="name" maxlength="90" required></div><div class="prop-row"><div class="property"><label>Color</label><input name="color" type="color"></div><div class="property"><label>Height (px)</label><input name="height" type="number" min="42" max="150" required></div></div><div class="property"><label>Track gain (0–3)</label><input name="gain" type="number" min="0" max="3" step=".01" required></div><div class="property"><label><input name="solo" type="checkbox"> Solo audio</label></div><div class="property"><label>Track order</label><select name="order"></select></div><div class="property-actions"><button class="button secondary" type="button">Cancel</button><button class="button primary">Save</button></div></form>';
  document.body.appendChild(dialog);const form=dialog.querySelector('form'),f=form.elements;
  f.name.value=t.name;f.color.value=t.color||(t.type==='audio'?'#ad95da':'#79b4de');f.height.value=t.height||67;
  f.gain.value=t.volume;f.solo.checked=!!t.solo;
  state.tracks.forEach((track,i)=>{if(t.type===track.type)f.order.add(new Option((i+1)+' · '+track.name,String(i),false,track===t));});
  form.querySelector('[type=button]').onclick=()=>dialog.close();
  form.onsubmit=e=>{
    e.preventDefault();snapshot();const dest=Number(f.order.value);
    Object.assign(t,{name:f.name.value.trim()||t.name,color:f.color.value,height:f.height.valueAsNumber,volume:f.gain.valueAsNumber,solo:f.solo.checked});
    const old=state.tracks.indexOf(t);state.tracks.splice(old,1);state.tracks.splice(dest,0,t);
    redraw();save();dialog.close();
  };
  dialog.onclose=()=>dialog.remove();dialog.showModal();
}
function sourceMonitor(a) {
  if(a.missing)return toast('Relink the missing source first',true);
  const dlg=document.createElement('dialog');dlg.className='motion-dialog';
  const still=a.kind==='image';
  dlg.innerHTML='<h2>Source monitor</h2><p class="source-name"></p><div class="source-media"></div><div class="source-marks"></div><div class="property-actions"><button class="button secondary close-source">Close</button><select class="compact-select" aria-label="Placement" id="sourcePlacement"><option value="append">Append</option><option value="insert">Insert at playhead</option><option value="overwrite">Overwrite at playhead</option></select><button class="button primary insert-source">Place clip</button></div>';
  document.body.appendChild(dlg);dlg.querySelector('.source-name').textContent=a.name;
  const media=document.createElement(still?'img':a.kind==='audio'?'audio':'video');
  media.src=seekUrl(a.id);if(!still)media.controls=true;dlg.querySelector('.source-media').appendChild(media);
  let marks={start:0,end:a.duration};
  if(!still){
    const host=dlg.querySelector('.source-marks');
    host.innerHTML='<div class="prop-row"><div class="property"><label>Source in (s)</label><input id="sourceIn" type="number" step="any" min="0"></div><div class="property"><label>Source out (s)</label><input id="sourceOut" type="number" step="any" min="0"></div></div><div class="property-actions"><button class="text-button" id="markIn">Mark in (I)</button><button class="text-button" id="markOut">Mark out (O)</button></div>';
    $('sourceIn').value=0;$('sourceOut').value=a.duration;
    $('markIn').onclick=()=>{$('sourceIn').value=media.currentTime;};$('markOut').onclick=()=>{$('sourceOut').value=media.currentTime;};
    dlg.onkeydown=e=>{if(e.target.tagName==='INPUT')return;if(e.key.toLowerCase()==='i')$('markIn').click();if(e.key.toLowerCase()==='o')$('markOut').click();};
  }
  dlg.querySelector('.close-source').onclick=()=>dlg.close();dlg.onclose=()=>{media.pause?.();dlg.remove();};
  dlg.querySelector('.insert-source').onclick=()=>{
    if(!still){
      marks={start:$('sourceIn').valueAsNumber,end:$('sourceOut').valueAsNumber};
      if(!Number.isFinite(marks.start)||!Number.isFinite(marks.end)||marks.start<0||marks.end>a.duration+.001||marks.end<=marks.start)return toast('Choose in and out points within the source',true);
    }
    const chosen=sel()?.track;
    const t=chosen&&canPlace(a,chosen)?chosen:defaultTrack(a.kind==='audio'?'audio':'video');
    if(!t||t.locked)return toast('Unlock a compatible destination track',true);
    const placement=$('sourcePlacement').value;
    const clip=clipFromAsset(a,0,t.type);
    if(!still)Object.assign(clip,marks);
    const at=placement==='append'?Math.max(0,...t.clips.map(c=>frameIndex(endOf(c)))):frameIndex(playhead);
    if(commitEdit(placement==='append'?'insert':placement,{trackId:t.id,at,clip},[]))dlg.close();
  };
  if(a.kind==='video')preciseSource(dlg,a,media);
  dlg.showModal();
}
