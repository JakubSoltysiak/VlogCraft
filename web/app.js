/* VlogCraft Studio 3 — native-local browser UI. No external JS dependencies. */
'use strict';
const $ = id => document.getElementById(id);
const svg = name => `<svg><use href="#i-${name}"/></svg>`;
const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const uid = () => (crypto.randomUUID?.() ?? (Date.now().toString(16)+Math.random().toString(16).slice(2))).replaceAll('-','');
const round = v => Math.round(v*1000)/1000;
const clamp = (v,lo,hi) => Math.max(lo,Math.min(hi,Number(v)));
const format = t => {t=Math.max(0,t||0);let s=Math.floor(t);return `${String(Math.floor(s/3600)).padStart(2,'0')}:${String(Math.floor(s%3600/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;};
const timecode = t => format(t)+':'+String(Math.floor(t%1*(state?.output?.fps||30))).padStart(2,'0');
const fileSize = b => b>=1024**3?(b/1024**3).toFixed(2)+' GB':b>=1024**2?(b/1024**2).toFixed(0)+' MB':(b/1024).toFixed(0)+' KB';
const seekUrl = aid => `/media/${encodeURIComponent(aid)}?proxy=1`;
const assetMap = () => Object.fromEntries((state?.assets||[]).map(a=>[a.id,a]));
const lengthOf = c => (c.end-c.start)/(c.speed||1);
const endOf = c => c.position+lengthOf(c);
const duration = () => Math.max(0,...state.tracks.filter(t=>!t.hidden).flatMap(t=>t.clips.map(endOf)));
let state=null, zoom=70, playhead=0, selectedId=null,selectedAssetId=null,insTab='clip',isPlaying=false,playStart=0,playAt=0;
let undoStack=[],redoStack=[],saveTimer=null,saveInFlight=Promise.resolve(),modified=0,persisted=0;
let lastPreviewKey='',activePlayers=new Map(),snap=true,clipGesture=null,transferStop=false,transferId=null,toastTimeout=null;
let renderPoll=null,proposalToken=null,proposalSnapshot=null;
async function request(path,method='GET',body=null){const o={method,cache:'no-store'};if(body!==null){o.headers={'Content-Type':'application/json'};o.body=JSON.stringify(body);}const r=await fetch('/api/'+path,o);let data=await r.json().catch(()=>({error:'Unexpected response from local editor'}));if(!r.ok)throw Error(data.error||`HTTP ${r.status}`);return data;}
function toast(message,warning=false){const box=$('toast');box.textContent=message;box.className='toast visible'+(warning?' warn':'');clearTimeout(toastTimeout);toastTimeout=setTimeout(()=>box.className='toast',4200);}
function setSaveStatus(txt){$('saveStatus').textContent=txt;}
function save(){modified++;setSaveStatus('UNSAVED CHANGES');clearTimeout(saveTimer);saveTimer=setTimeout(()=>void flushSave(),600);}
async function flushSave(){clearTimeout(saveTimer);saveTimer=null;let s=structuredClone(state);let rev=modified;
 const next=saveInFlight.catch(()=>{}).then(async()=>{if(!state)return;const saved=await request('state','POST',s);persisted=Math.max(rev,persisted);if(persisted>=modified)setSaveStatus('ALL CHANGES SAVED');return saved;});
 saveInFlight=next;try{await next;}catch(e){setSaveStatus('SAVE ERROR');toast('Could not save: '+e.message,true);}return next;}
function snapshot(){undoStack.push(structuredClone({tracks:state.tracks,name:state.name,output:state.output}));if(undoStack.length>80)undoStack.shift();redoStack=[];}
function restoreHistory(from,to){if(!from.length)return;to.push(structuredClone({tracks:state.tracks,name:state.name,output:state.output}));const s=from.pop();state.tracks=s.tracks;state.name=s.name;state.output=s.output;selectedId=null;playhead=Math.min(playhead,duration());redraw();save();}
function sel(){for(const t of state.tracks){const c=t.clips.find(c=>c.id===selectedId);if(c)return {clip:c,track:t};}return null;}
function trackById(id){return state.tracks.find(t=>t.id===id);}
function assetById(id){return state.assets.find(a=>a.id===id);}
function defaultTrack(kind){return [...state.tracks].reverse().find(t=>t.type===kind);}
function clipFromAsset(a,pos=0,trackType=null){const kind=trackType==='audio'?'audio':a.kind;return {id:uid(),assetId:a.id,kind,position:round(pos),start:0,end:a.kind==='image'?5:Math.max(.04,a.duration||5),speed:1,volume:1,opacity:1,scale:1,x:0,y:0,grade:'neutral',fit:'contain',fadeIn:0,fadeOut:0,locked:false};}
function canPlace(a,track){return track&&((track.type==='audio'&&a.kind!=='image')||(track.type==='video'&&a.kind!=='audio'));}
function addAsset(a,track,pos){if(!track)track=defaultTrack(a.kind==='audio'?'audio':'video');if(!canPlace(a,track)){toast('That file type cannot go on this track',true);return;}if(track.locked){toast('Track is locked',true);return;}snapshot();const c=clipFromAsset(a,pos??Math.max(0,...track.clips.map(endOf)),track.type);track.clips.push(c);selectedId=c.id;playhead=c.position;redraw();save();toast('Added '+a.name+' to '+track.name);}
function renderAssets(){const filter=$('assetFilter').value;const search=$('searchAssets').value.toLowerCase().trim();const list=state.assets.filter(a=>(filter==='all'||a.kind===filter)&&a.name.toLowerCase().includes(search));$('mediaCount').textContent=state.assets.length+' ASSETS';$('assetList').innerHTML=list.length?list.map(a=>`<article class="asset-card" draggable="true" data-asset="${a.id}" title="Drag to a timeline track, or double-click to add"><div class="asset-thumb">${a.kind==='audio'?svg('music'):`<img loading="lazy" src="/thumb/${a.id}" onerror="this.style.display='none'">`}<span class="asset-badge">${a.kind.toUpperCase()}</span>${a.hdr?'<span class="hdr-badge">HDR</span>':''}${a.kind!=='image'?`<span class="asset-duration">${format(a.duration)}</span>`:''}</div><div class="asset-text"><div class="asset-name">${esc(a.name)}</div><div class="asset-sub"><span>${fileSize(a.size)}</span><button class="asset-plus" title="Add to timeline" data-add="${a.id}">+</button></div></div></article>`).join(''):'<div class="empty-media">No matching files. <br>Drop MP4, MOV, MKV, audio or images to import.</div>';
 $('assetList').querySelectorAll('[draggable="true"]').forEach(el=>{el.ondragstart=e=>{e.dataTransfer.setData('application/x-vlogcraft',el.dataset.asset);e.dataTransfer.effectAllowed='copy';};el.ondblclick=()=>{const a=assetById(el.dataset.asset);addAsset(a);};});
 $('assetList').querySelectorAll('[data-add]').forEach(el=>el.onclick=e=>{e.stopPropagation();const a=assetById(el.dataset.add);addAsset(a);});}
function renderProjectInspector(){const out=state.output;return `<div class="section-label">SEQUENCE</div><div class="property"><label>Project name</label><input data-proj="name" value="${esc(state.name)}" maxlength="160"></div><div class="property"><label>Sequence length</label><div class="prop-time">${format(duration())}</div></div><div class="section-label">DELIVERY</div><div class="property"><label>Frame dimensions</label><select data-proj="width"><option value="1280" ${out.width===1280?'selected':''}>1280 × 720</option><option value="1920" ${out.width===1920?'selected':''}>1920 × 1080</option><option value="2560" ${out.width===2560?'selected':''}>2560 × 1440</option><option value="3840" ${out.width===3840?'selected':''}>3840 × 2160 (4K)</option></select></div><div class="property"><label>Frames per second</label><select data-proj="fps">${[24,25,30,60].map(v=>`<option ${out.fps===v?'selected':''}>${v}</option>`).join('')}</select></div><div class="section-label">NOTES</div><p class="dialog-note">All editing is non-destructive. Preview may use 720p proxies; export always renders from originals in the selected resolution.</p>`;}
const field=(label,key,value,min,max,step=.1)=>`<div class="property"><label>${label}</label><input data-prop="${key}" type="number" min="${min}" max="${max}" step="${step}" value="${round(value)}"></div>`;
const range=(label,key,value,min,max,step=.05,percent=true)=>`<div class="property"><label>${label}</label><div class="range-line"><input data-prop="${key}" type="range" min="${min}" max="${max}" step="${step}" value="${value}"><output>${percent?Math.round(value*100)+'%':round(value)}</output></div></div>`;
function renderInspector(){let html='';if(insTab==='project'){html=renderProjectInspector();}else{
 const current=sel();if(!current)html='<div class="inspector-empty-art"><strong>◇</strong>Choose a clip on the timeline to begin grading, trimming or mixing audio.</div>';
 else{
 const {clip:c,track:t}=current,a=assetById(c.assetId);const kind=c.kind;
 html=`<div class="prop-asset">${a&&a.kind!=='audio'?`<img class="prop-thumb" src="/thumb/${a.id}" onerror="this.style.visibility='hidden'">`:`<div class="prop-thumb" style="display:grid;place-items:center">${kind==='title'?'T':svg('music')}</div>`}<div class="prop-text"><div class="prop-name">${esc(a?.name || 'Title graphic')}</div><div class="prop-time">${esc(t.name)} · ${format(lengthOf(c))}</div></div></div>`;
 html+='<div class="section-label">TIMING</div><div class="prop-row">'+field('Timeline start (sec)','position',c.position,0,14400,.01)+field('Clip duration (sec)','duration',lengthOf(c),.05,14400,.01)+'</div>';
 if(a && a.kind!=='image'){html+='<div class="prop-row">'+field('Source in','start',c.start,0,36000,.01)+field('Source out','end',c.end,.04,36000,.01)+'</div>';html+=range('Playback speed','speed',c.speed,.25,4,.05,false);}
 if(t.type==='video'&&kind!=='title'){
 html+='<div class="section-label">COMPOSITION</div>'+range('Opacity','opacity',c.opacity,0,1,.01)+range('Scale','scale',c.scale,.1,3,.05,false);
 html+='<div class="prop-row">'+field('Horizontal offset','x',c.x,-2,2,.01)+field('Vertical offset','y',c.y,-2,2,.01)+'</div>';
 html+=`<div class="property"><label>Fit</label><select data-prop="fit"><option value="contain" ${c.fit==='contain'?'selected':''}>Fit entire frame</option><option value="cover" ${c.fit==='cover'?'selected':''}>Fill / crop</option></select></div>`;
 html+=`<div class="property"><label>Color grade</label><select data-prop="grade">${['neutral','warm','cool','vivid','cinematic','mono'].map(x=>`<option value="${x}" ${c.grade===x?'selected':''}>${x.toUpperCase()}</option>`).join('')}</select></div>`;
 }
 if(kind==='title')html+='<div class="section-label">TYPOGRAPHY</div>'+`<div class="property"><label>Title text</label><textarea data-prop="text" rows="3">${esc(c.text||'')}</textarea></div>`+range('Text size','fontScale',c.fontScale,.01,.15,.005,false)+`<div class="property"><label>Color</label><select data-prop="color">${['white','yellow','cyan','black','#f5ce8a','#a6ffdf'].map(x=>`<option ${x===c.color?'selected':''} value="${x}">${x}</option>`).join('')}</select></div>`;
 if((a?.hasAudio||kind==='audio'))html+='<div class="section-label">AUDIO MIX</div>'+range('Source volume','volume',c.volume,0,3,.05);
 html+='<div class="section-label">TRANSITIONS</div><div class="prop-row">'+field('Fade in (s)','fadeIn',c.fadeIn,0,30,.05)+field('Fade out (s)','fadeOut',c.fadeOut,0,30,.05)+'</div>';
 if(a?.kind==='video')html+='<div class="property-actions"><button id="makeProxyBtn" class="button secondary">CREATE 720p PROXY</button></div><small>Proxies make large 4K/HDR sources easier to scrub. Export remains original quality.</small>';
 html+='<div class="property-actions"><button id="deleteClipInspector" class="button secondary">'+svg('trash')+' REMOVE CLIP</button><button id="duplicateClipInspector" class="button secondary">'+svg('copy')+' DUPLICATE</button></div>';
 }}
 $('inspectorContent').innerHTML=html;
 $('inspectorContent').querySelectorAll('[data-proj]').forEach(el=>el.onchange=()=>{snapshot();let key=el.dataset.proj;if(key==='name'){state.name=el.value||'Untitled';}else if(key==='width'){state.output.width=Number(el.value);state.output.height=state.output.width*9/16;}else if(key==='fps')state.output.fps=Number(el.value);redraw();save();});
 $('inspectorContent').querySelectorAll('[data-prop]').forEach(el=>{const action=()=>{
  const cur=sel();if(!cur)return;const c=cur.clip,k=el.dataset.prop;
  const old=c[k];let v=el.type==='number'||el.type==='range'?Number(el.value):el.value;
  if(k==='duration'){v=clamp(v,.04,14400);c.end=c.start+v*c.speed;}
  else if(k==='position')c.position=clamp(v,0,14400);
  else if(k==='end')c.end=Math.max(c.start+.04,v);
  else if(k==='start')c.start=Math.min(v,c.end-.04);
  else if(['volume','opacity','scale','speed','x','y','fadeIn','fadeOut','fontScale'].includes(k))c[k]=v;
  else c[k]=v;
  if(c.assetId){const a=assetById(c.assetId);if(a.kind!=='image')c.end=Math.min(c.end,a.duration);}
  if(el.type==='range'){const out=el.parentElement.querySelector('output');if(out)out.textContent=['opacity','volume'].includes(k)?Math.round(v*100)+'%':round(v);}
  renderTimeline();syncPreview(true);save();
 };el.oninput=action;el.onfocus=()=>{if(!el.dataset.history){snapshot();el.dataset.history='yes';}};el.onblur=()=>{delete el.dataset.history;};});
 $('deleteClipInspector')?.addEventListener('click',removeSelected);$('duplicateClipInspector')?.addEventListener('click',duplicateSelected);
 $('makeProxyBtn')?.addEventListener('click',async()=>{const c=sel()?.clip;if(!c)return;try{await request('proxy','POST',{assetId:c.assetId});toast('Building a local 720p proxy. Editing continues.');}catch(e){toast(e.message,true);}});
}
function select(id){selectedId=id;renderTimeline();renderInspector();}
function tickStep(){const n=duration();if(n<25)return 2;if(n<60)return 5;if(n<180)return 10;if(n<600)return 30;return 60;}
function renderTimeline(){const total=Math.max(24,duration()+6);const canvas=Math.max(1500,Math.ceil(total*zoom)+100);const step=tickStep();
 let html=`<div class="ruler-row"><div class="ruler-left">TIME / ${state.output.fps} FPS</div><div class="ruler-lane" data-ruler style="width:${canvas}px;min-width:${canvas}px">`;
 for(let i=0;i<=total;i+=step){html+=`<div class="ruler-tick" style="left:${i*zoom}px">${format(i).slice(3)}</div>`;}
 html+='</div></div>';
 for(const t of state.tracks){html+=`<div class="track-row ${t.type==='audio'?'audio-row':''}" data-track-row="${t.id}"><div class="track-head"><div class="track-color"></div><div class="track-info"><div class="track-name" title="${esc(t.name)}">${esc(t.name)}</div><div class="track-actions"><button class="track-action ${t.muted?'on':''}" data-track-action="muted" data-track="${t.id}" title="Mute track">${svg('volume')}</button>${t.type==='video'?`<button class="track-action ${t.hidden?'on':''}" data-track-action="hidden" data-track="${t.id}" title="Hide video">${svg('eye')}</button>`:''}<button class="track-action ${t.locked?'on':''}" data-track-action="locked" data-track="${t.id}" title="Lock track">${svg('lock')}</button></div></div></div><div class="track-lane" data-lane="${t.id}" style="width:${canvas}px;min-width:${canvas}px">`;
 for(const c of t.clips){const a=assetById(c.assetId);const w=Math.max(5,lengthOf(c)*zoom);const left=Math.max(0,c.position*zoom);
 html+=`<div class="track-clip ${t.type==='audio'?'audio-clip':''} ${c.kind==='title'?'title-clip':''} ${selectedId===c.id?'selected':''}" data-clip="${c.id}" data-parent="${t.id}" title="${esc(a?.name||c.text||'Title')} · ${format(c.position)} → ${format(endOf(c))}" style="left:${left}px;width:${w}px"><div class="clip-bg" ${a?.kind!=='audio'?`style="background-image:url('/thumb/${a?.id}')"`:''}></div><div class="trim-handle trim-left" data-handle="left"></div><div class="clip-content"><strong>${c.kind==='title'?'T · '+esc(c.text):t.type==='audio'?'♫ '+esc(a?.name):esc(a?.name||'Clip')}</strong><small>${w>88?format(lengthOf(c)).slice(3):''}</small></div><div class="trim-handle trim-right" data-handle="right"></div></div>`;
 }
 html+='</div></div>';
 }
 html+='<div class="playhead" id="timelinePlayhead"></div>';
 const scroller=$('timelineScroller');const sx=scroller.scrollLeft,sy=scroller.scrollTop;
 $('timelineContent').innerHTML=html;
 scroller.scrollLeft=sx;scroller.scrollTop=sy;
 positionPlayhead();
 $('timelineContent').querySelectorAll('.track-name').forEach(el=>el.ondblclick=()=>{const t=trackById(el.closest('[data-track-row]').dataset.trackRow);if(!t)return;const name=prompt('Rename timeline track',t.name);if(name?.trim()){snapshot();t.name=name.trim().slice(0,90);redraw();save();}});
 $('timelineContent').querySelectorAll('[data-track-action]').forEach(btn=>btn.onclick=e=>{e.stopPropagation();let t=trackById(btn.dataset.track);snapshot();t[btn.dataset.trackAction]=!t[btn.dataset.trackAction];redraw();save();});
 $('timelineContent').querySelectorAll('[data-clip]').forEach(el=>el.onpointerdown=startClipGesture);
 $('timelineContent').querySelectorAll('[data-ruler]').forEach(el=>el.onpointerdown=e=>{if(e.button!==0)return;seek((e.clientX-el.getBoundingClientRect().left)/zoom);const onMove=ev=>seek((ev.clientX-el.getBoundingClientRect().left)/zoom);const onUp=()=>{window.removeEventListener('pointermove',onMove);window.removeEventListener('pointerup',onUp);};window.addEventListener('pointermove',onMove);window.addEventListener('pointerup',onUp);});
 $('timelineContent').querySelectorAll('[data-lane]').forEach(el=>{
  el.ondragover=e=>{if(e.dataTransfer.types.includes('application/x-vlogcraft')){e.preventDefault();el.classList.add('drop-ready');e.dataTransfer.dropEffect='copy';}};
  el.ondragleave=()=>el.classList.remove('drop-ready');
  el.ondrop=e=>{el.classList.remove('drop-ready');let aid=e.dataTransfer.getData('application/x-vlogcraft');if(!aid)return;e.preventDefault();e.stopPropagation();const t=trackById(el.dataset.lane);const p=clamp((e.clientX-el.getBoundingClientRect().left)/zoom,0,14400);addAsset(assetById(aid),t,snapTo(p));};
  el.ondblclick=e=>{if(e.target.closest('[data-clip]'))return;seek((e.clientX-el.getBoundingClientRect().left)/zoom);};
 });
}
function positionPlayhead(){const p=$('timelinePlayhead');if(p)p.style.left=(151+playhead*zoom)+'px';$('playheadTime').textContent=timecode(playhead);$('totalTime').textContent=timecode(duration());}
function seek(t){playhead=clamp(t,0,Math.max(0,duration()));if(isPlaying){playAt=playhead;playStart=performance.now();}positionPlayhead();syncPreview(true);}
function snapTo(value,ignore=null){value=Math.max(0,value);if(!snap)return round(value);const others=[0,playhead];for(const t of state.tracks)for(const c of t.clips)if(c.id!==ignore)others.push(c.position,endOf(c));const nearest=others.reduce((best,v)=>Math.abs(v-value)<Math.abs(best-value)?v:best,value);return round(Math.abs(nearest-value)<=Math.max(.08,9/zoom)?nearest:value);}
function startClipGesture(e){if(e.button!==0)return;const el=e.currentTarget,cid=el.dataset.clip,t=trackById(el.dataset.parent),c=t.clips.find(c=>c.id===cid);if(!c||t.locked||c.locked)return;
 e.stopPropagation();selectedId=cid;document.querySelectorAll('.track-clip').forEach(node=>node.classList.toggle('selected',node.dataset.clip===cid));renderInspector();const handle=e.target.closest('[data-handle]');const mode=handle?.dataset.handle||'move';let startX=e.clientX,baseline=structuredClone(c),newTrack=null,moved=false;el.setPointerCapture(e.pointerId);let hover=null;
 const move=ev=>{const dx=(ev.clientX-startX)/zoom;if(Math.abs(ev.clientX-startX)>2)moved=true;
   if(mode==='move'){
    const proposed=snap&& !ev.shiftKey?snapTo(baseline.position+dx,c.id):round(Math.max(0,baseline.position+dx));
    el.style.left=(proposed*zoom)+'px';
    const lane=document.elementFromPoint(ev.clientX,ev.clientY)?.closest('[data-lane]');
    if(hover&&hover!==lane)hover.classList.remove('drop-ready');
    if(lane&&lane.dataset.lane!==t.id){let dest=trackById(lane.dataset.lane),a=assetById(c.assetId);
      if(dest&&!dest.locked&&(c.kind==='title'?dest.type==='video':canPlace(a,dest))){lane.classList.add('drop-ready');hover=lane;newTrack=dest;}else newTrack=null;
    }else{newTrack=null;hover=null;}
   }else if(mode==='right')el.style.width=Math.max(4,(lengthOf(baseline)+dx)*zoom)+'px';
   else {el.style.left=(baseline.position+dx)*zoom+'px';el.style.width=Math.max(4,(lengthOf(baseline)-dx)*zoom)+'px';}
 };
 const up=ev=>{el.releasePointerCapture?.(e.pointerId);el.removeEventListener('pointermove',move);el.removeEventListener('pointerup',up);el.removeEventListener('pointercancel',up);if(hover)hover.classList.remove('drop-ready');if(!moved){renderTimeline();return;}
  const dx=(ev.clientX-startX)/zoom;let next=structuredClone(baseline),end0=endOf(baseline);
  if(mode==='move')next.position=snap&&!ev.shiftKey?snapTo(baseline.position+dx,c.id):round(Math.max(0,baseline.position+dx));
  else if(mode==='right'){
   if(c.kind==='image'||c.kind==='title')next.end=Math.max(.05,round(baseline.end+dx));
   else next.end=clamp(round(baseline.end+dx*baseline.speed),baseline.start+.05,assetById(c.assetId).duration);
  }else{
   const offset=clamp(dx,-baseline.position,lengthOf(baseline)-.05);
   if(c.kind==='image'||c.kind==='title'){next.position=round(baseline.position+offset);next.end=round(baseline.end-offset*baseline.speed);}
   else {next.start=clamp(round(baseline.start+offset*baseline.speed),0,baseline.end-.05);next.position=round(baseline.position+(next.start-baseline.start)/baseline.speed);}
  }
  if(next.position<0)next.position=0;
  if(JSON.stringify(next)!==JSON.stringify(baseline)||newTrack){snapshot();Object.assign(c,next);if(newTrack&&newTrack.id!==t.id){const a=assetById(c.assetId);t.clips.splice(t.clips.indexOf(c),1);c.kind=c.kind==='title'?'title':newTrack.type==='audio'?'audio':a.kind;newTrack.clips.push(c);}
   redraw();save();toast(`${mode==='move'?'Moved':'Trimmed'} clip to ${format(c.position)}`);
  }else renderTimeline();
 };
 el.addEventListener('pointermove',move);el.addEventListener('pointerup',up);el.addEventListener('pointercancel',up);
}
function splitSelected(){
 const item=sel();if(!item){toast('Select a clip to split',true);return;}
 const {clip:c,track:t}=item;if(t.locked||c.locked)return toast('Track or clip is locked',true);
 const beforeEnd=endOf(c),beforeDuration=lengthOf(c);
 if(playhead<c.position+.05||playhead>beforeEnd-.05)return toast('Place playhead within selected clip',true);
 snapshot();const right=structuredClone(c);right.id=uid();right.position=round(playhead);
 if(c.kind==='title'||c.kind==='image'){
  c.end=round((playhead-c.position)*c.speed);
  right.start=0;right.end=round((beforeEnd-playhead)*right.speed);
 }else{
  const sourceAt=round(c.start+(playhead-c.position)*c.speed);
  right.start=sourceAt;c.end=sourceAt;
 }
 c.fadeOut=0;right.fadeIn=0;t.clips.push(right);selectedId=right.id;
 redraw();save();toast('Split at '+timecode(playhead));
}
function removeSelected(){const item=sel();if(!item)return;const {clip:c,track:t}=item;if(t.locked||c.locked)return toast('Track is locked',true);snapshot();t.clips.splice(t.clips.indexOf(c),1);selectedId=null;redraw();save();}
function duplicateSelected(){const item=sel();if(!item)return;const {clip:c,track:t}=item;if(t.locked||c.locked)return;const clone=structuredClone(c);clone.id=uid();clone.position=round(endOf(c));snapshot();t.clips.push(clone);selectedId=clone.id;redraw();save();}
function addTrack(type){snapshot();let existing=state.tracks.filter(t=>t.type===type).length+1;const t={id:uid(),name:`${type==='video'?'V':'A'}${existing} · ${type==='video'?'Overlay':'Audio'}`,type,muted:false,hidden:false,locked:false,volume:1,clips:[]};if(type==='video')state.tracks.unshift(t);else state.tracks.push(t);redraw();save();}
function addTitle(){const t=state.tracks.find(t=>t.type==='video'&&!t.locked);if(!t)return toast('Unlock a video track first',true);const c={id:uid(),assetId:null,kind:'title',position:round(playhead),start:0,end:4,speed:1,volume:0,opacity:1,scale:1,x:0,y:0,grade:'neutral',fit:'contain',fadeIn:.25,fadeOut:.25,text:'KENYA',fontScale:.055,color:'white',titleAlign:'center',locked:false};snapshot();t.clips.push(c);selectedId=c.id;redraw();save();}
const gradeFilters={neutral:'',warm:'sepia(.17) saturate(1.12)',cool:'hue-rotate(6deg) saturate(.95)',vivid:'contrast(1.12) saturate(1.25)',cinematic:'contrast(1.13) saturate(.8)',mono:'grayscale(1)'};
function getActiveClips(){const vis=[];for(const t of [...state.tracks].reverse())if(t.type==='video'&&!t.hidden)for(const c of [...t.clips].sort((a,b)=>a.position-b.position))if(playhead>=c.position-.005&&playhead<endOf(c)-.005)vis.push({c,t});return vis;}
function makePlayer(c,t,z){const a=assetById(c.assetId);if(!a)return null;const wrap=document.createElement('div');wrap.className='preview-layer';wrap.dataset.previewId=c.id;wrap.style.zIndex=z;
 if(c.kind==='title')return null;
 const media=document.createElement(a.kind==='image'?'img':'video');media.src=a.kind==='image'?`/media/${a.id}`:seekUrl(a.id);if(media.tagName==='VIDEO'){media.preload='metadata';media.playsInline=true;media.autoplay=false;media.muted=false;media.disablePictureInPicture=true;}media.style.objectFit=c.fit==='cover'?'cover':'contain';wrap.appendChild(media);$('previewLayers').appendChild(wrap);return {media,wrap,clipId:c.id,aId:a.id};}
function syncPreview(force=false){if(!state)return;const active=getActiveClips();$('emptyPreview').hidden=state.tracks.some(t=>t.clips.length);
 const activeIds=new Set(active.map(x=>x.c.id));
 for(const [id,p] of activePlayers)if(!activeIds.has(id)||p.type!=='video'){
  p.media?.pause?.();p.wrap?.remove();activePlayers.delete(id);
 }
 let z=1;
 for(const {c,t} of active){
  let player=activePlayers.get(c.id);if(!player){
   if(c.kind==='title'){const wrap=document.createElement('div');wrap.className='preview-title';wrap.dataset.previewId=c.id;$('previewLayers').appendChild(wrap);player={wrap,media:null,type:'video'};}
   else player={...makePlayer(c,t,z),type:'video'};
   activePlayers.set(c.id,player);
  }
  player.wrap.style.zIndex=z++;const elapsed=Math.max(0,playhead-c.position),left=Math.max(0,endOf(c)-playhead);const fi=c.fadeIn?Math.min(1,elapsed/c.fadeIn):1,fo=c.fadeOut?Math.min(1,left/c.fadeOut):1;player.wrap.style.opacity=clamp(c.opacity*Math.min(fi,fo),0,1);
  if(c.kind==='title'){
   player.wrap.textContent=c.text||'';player.wrap.style.fontSize=(Math.max(8,Math.round($('previewStage').clientWidth*c.fontScale)))+'px';
   player.wrap.style.color=c.color;player.wrap.style.alignItems=c.titleAlign==='lower'?'flex-end':'center';
   continue;
  }
  const m=player.media;if(!m)continue;
  m.style.objectFit=c.fit==='cover'?'cover':'contain';
  m.style.filter=gradeFilters[c.grade]||'';
  m.style.transform=`translate(${c.x*100}%,${c.y*100}%) scale(${c.scale})`;
  if(m.tagName==='VIDEO'){
    const sourceTime=c.start+(playhead-c.position)*c.speed;
    const correction=Math.abs((m.currentTime||0)-sourceTime);
    if(force||correction>.23)try{m.currentTime=sourceTime;}catch{}
    m.playbackRate=c.speed;
    m.volume=t.muted?0:clamp(t.volume*c.volume*Math.min(fi,fo),0,1);
    if(isPlaying && m.paused)m.play().catch(()=>{});
    else if(!isPlaying&&!m.paused)m.pause();
  }
 }
 syncAudio(force);
}
const audioPlayers=new Map();
function syncAudio(force=false){const active=[];
 for(const t of state.tracks)if(t.type==='audio'&&!t.muted)for(const c of t.clips)if(playhead>=c.position-.005&&playhead<endOf(c)-.005)active.push({t,c});
 const keys=new Set(active.map(x=>x.c.id));for(const [id,p] of audioPlayers)if(!keys.has(id)){p.pause();p.remove();audioPlayers.delete(id);}
 for(const {t,c} of active){if(!c.assetId)continue;let m=audioPlayers.get(c.id);if(!m){m=document.createElement('audio');m.src=seekUrl(c.assetId);m.preload='metadata';document.body.appendChild(m);audioPlayers.set(c.id,m);}
  let target=c.start+(playhead-c.position)*c.speed;if(force||Math.abs(m.currentTime-target)>.23)try{m.currentTime=target;}catch{}
  m.playbackRate=c.speed;const elapsed=playhead-c.position,remaining=endOf(c)-playhead;const ai=c.fadeIn?Math.min(1,elapsed/c.fadeIn):1,ao=c.fadeOut?Math.min(1,remaining/c.fadeOut):1;m.volume=clamp(t.volume*c.volume*Math.min(ai,ao),0,1);
  if(isPlaying&&m.paused)m.play().catch(()=>{});else if(!isPlaying&&!m.paused)m.pause();
 }
}
function stopPlayback(){isPlaying=false;$('playBtn').innerHTML=svg('play');for(const p of activePlayers.values())p.media?.pause?.();for(const p of audioPlayers.values())p.pause();}
function playPause(){if(isPlaying){stopPlayback();return;}if(duration()<=0)return toast('Add footage first',true);if(playhead>=duration()-.001)playhead=0;isPlaying=true;playAt=playhead;playStart=performance.now();$('playBtn').innerHTML=svg('pause');syncPreview(true);requestAnimationFrame(animate);}
function animate(){if(!isPlaying)return;playhead=playAt+(performance.now()-playStart)/1000;if(playhead>=duration()){seek(duration());stopPlayback();return;}positionPlayhead();syncPreview(false);const p=$('timelinePlayhead');if(p){const scroller=$('timelineScroller');const edge=151+playhead*zoom;if(edge>scroller.scrollLeft+scroller.clientWidth-50)scroller.scrollLeft=edge-200;}requestAnimationFrame(animate);}
function redraw(){if(!state)return;$('projectTitle').textContent=state.name;$('renderRes').textContent=`${state.output.width} × ${state.output.height} · ${state.output.fps} FPS`;$('exportEstimate').textContent=`${state.output.width===3840?'4K UHD':state.output.width+'p'} · ${state.output.fps} FPS · H.264`;
 renderAssets();renderTimeline();renderInspector();$('timelineStatus').textContent=`${state.tracks.length} TRACKS · ${state.tracks.reduce((n,t)=>n+t.clips.length,0)} CLIPS`;
 syncPreview(true);
}
async function importLinked(){try{await flushSave();const response=await request('import','POST',{});const existing=new Set(state.assets.map(a=>a.id));for(const a of response.assets)if(!existing.has(a.id))state.assets.push(a);
 redraw();if(response.errors?.length)toast(response.errors[0],true);else toast(`Linked ${response.assets.length} source(s) with no copying`);setTimeout(renderAssets,1300);}catch(e){toast(e.message,true);}}
function transferUI(name,detail,progress){$('transferOverlay').hidden=false;$('transferTitle').textContent=name;$('transferDetail').textContent=detail;$('transferBar').style.width=progress+'%';}
async function importDropped(files,trackId=null,pos=null){const supported=[...files].filter(f=>/\.(mp4|mov|mkv|m4v|avi|wmv|webm|mpg|mpeg|mts|m2ts|jpg|jpeg|png|webp|bmp|tif|tiff|wav|mp3|m4a|aac|flac|ogg|opus|wma)$/i.test(f.name));if(!supported.length)return toast('No supported video, image, or audio files found',true);
 transferStop=false;let imported=0,total= supported.reduce((s,f)=>s+f.size,0),done=0;
 await flushSave();
 try{
  for(let i=0;i<supported.length;i++){
   const file=supported[i];const res=await request('upload/start','POST',{name:file.name,size:file.size});transferId=res.id;let offset=res.offset||0;const chunk=Math.min(8*1024*1024,res.chunkBytes);
   while(offset<file.size){if(transferStop)throw new Error('Import cancelled');
    const end=Math.min(file.size,offset+chunk);transferUI(`Importing ${i+1} / ${supported.length}`,file.name,(done+offset)/total*100);
    const part=file.slice(offset,end);let response;
    for(let attempt=0;attempt<3;attempt++){
     try{const r=await fetch(`/api/upload/chunk?id=${res.id}&offset=${offset}`,{method:'PUT',body:part});response=await r.json();if(!r.ok)throw new Error(response.error||`Transfer HTTP ${r.status}`);break;}
     catch(e){if(attempt===2)throw e;await new Promise(r=>setTimeout(r,(attempt+1)*750));let status=await request('upload/status?id='+res.id);if(status.offset===end){response={offset:end};break;} if(status.offset!==offset)throw new Error('Transfer offset changed unexpectedly');}
    }
    offset=response.offset;$('transferBar').style.width=(((done+offset)/total)*100).toFixed(1)+'%';$('transferStats').textContent=`${fileSize(done+offset)} / ${fileSize(total)}`;
   }
   const created=await request('upload/finish','POST',{id:res.id});transferId=null;done+=file.size;imported++;
   if(!state.assets.some(a=>a.id===created.asset.id))state.assets.push(created.asset);
   const track=trackById(trackId);if(track&&canPlace(created.asset,track)){addAsset(created.asset,track,pos??0);}else if(trackId&&track){toast('Imported; drag asset to a compatible track',true);}
   else addAsset(created.asset);
   await flushSave();
  }
  toast(`Imported ${imported} file(s) locally. Large clips are supported.`);setTimeout(renderAssets,1300);
 }catch(e){if(transferId)await request('upload/cancel','POST',{id:transferId}).catch(()=>{});toast('Import stopped: '+e.message,true);}finally{transferId=null;$('transferOverlay').hidden=true;redraw();}
}
function openModal(id){$(id).hidden=false;}
function closeModal(id){$(id).hidden=true;}
async function startExport(){state.output.width=Number($('exportResolution').value);state.output.height=state.output.width*9/16;state.output.fps=Number($('exportFps').value);state.output.crf=Number($('exportCrf').value);state.output.preset=$('exportPreset').value;save();await flushSave();try{const res=await request('export','POST',{});if(res.cancelled)return toast('Export location not selected');$('renderProgress').hidden=false;$('startRender').disabled=true;$('cancelRender').hidden=false;beginJobPoll('export');}catch(e){toast('Export: '+e.message,true);}}
function beginJobPoll(which,onDone){clearInterval(renderPoll);renderPoll=setInterval(async()=>{try{const d=await request('jobs');const j=d[which];if(which==='export'){
  $('renderMessage').textContent=j.message;$('renderPercent').textContent=j.percent+'%';$('renderBar').style.width=j.percent+'%';$('renderResult').textContent=j.error||j.path||'';
 }else{$('diskHint').textContent=j.message;}
 if(['done','error','cancelled'].includes(j.status)){clearInterval(renderPoll);renderPoll=null;$('startRender').disabled=false;$('cancelRender').hidden=true;if(which==='export'&&j.status==='done')toast('Export saved: '+j.path);if(j.status==='error')toast(j.error||'Render failed',true);onDone?.(j);}
 }catch(e){clearInterval(renderPoll);renderPoll=null;toast(e.message,true);}},900);}
function proposalText(){let t=$('proposalJson').value.trim();if(t.startsWith('```'))t=t.replace(/^```(?:json)?\s*/,'').replace(/\s*```$/,'');return JSON.parse(t);}
async function makeReviewPack(){try{await flushSave();$('reviewStatus').textContent='Sampling source frames locally…';const r=await request('review','POST',{});$('reviewPackLink').href=r.url;$('reviewPackLink').hidden=false;$('reviewStatus').textContent=`Review ZIP ready: ${r.frames} frames, ${fileSize(r.bytes)}. No full-size footage included.`;}catch(e){$('reviewStatus').textContent=e.message;}}
async function makeReviewVideo(){try{await flushSave();$('reviewVideoLink').hidden=true;$('reviewStatus').textContent='Rendering a compressed 720p review MP4…';const r=await request('review/video','POST',{});beginJobPoll('export',status=>{if(status.status==='done'){$('reviewVideoLink').href=r.url;$('reviewVideoLink').hidden=false;$('reviewStatus').textContent='Review ready — attach this MP4 here in ChatGPT.';}else $('reviewStatus').textContent=status.error||status.message;});}catch(e){$('reviewStatus').textContent=e.message;}}
async function analyzeAi(){const b=$('analyzeBtn');b.disabled=true;$('aiResults').textContent='Sending up to 8 sampled JPEG frames and project manifest to OpenAI API. Original video files stay local.';try{await flushSave();let r=await request('ai/analyze','POST',{apiKey:$('apiKey').value,goal:$('aiGoal').value});$('proposalJson').value=JSON.stringify(r,null,2);proposalToken=null;$('applyAiBtn').disabled=true;$('aiResults').textContent=`${r.summary||''}\n\n${(r.suggestions||[]).map(x=>'• '+x).join('\n')}\n\n${r.shotsSent} frames sent. Review changes before applying.`;}catch(e){$('aiResults').textContent='AI error: '+e.message;}finally{b.disabled=false;}}
async function previewAi(){try{await flushSave();const p=proposalText();const r=await request('ai/preview','POST',{proposal:p});proposalToken=r.approvalToken;proposalSnapshot=$('proposalJson').value;$('applyAiBtn').disabled=!r.count;$('aiResults').textContent=`${r.summary||'AI edit plan'}\n\n${r.changes.map(c=>'• '+c).join('\n')||'Advice only — no automatic edits.'}\n\nThis modifies V1 as a sequential rough cut and keeps other tracks. Check timing before approving.`;}catch(e){$('aiResults').textContent=e.message;}}
async function applyAi(){if(!proposalToken||proposalSnapshot!==$('proposalJson').value)return toast('Preview the exact proposal first',true);if(!confirm('Apply these AI actions to V1? Other tracks remain, but synchronization may need adjustment. Originals are untouched.'))return;try{const r=await request('ai/apply','POST',{proposal:proposalText(),approvalToken:proposalToken});state=r.state;selectedId=null;undoStack=[];redoStack=[];proposalToken=null;$('applyAiBtn').disabled=true;redraw();$('aiResults').textContent='Applied '+r.changes.length+' edits. Use Undo Last AI Apply to revert.';}catch(e){$('aiResults').textContent=e.message;}}
async function undoAi(){if(!confirm('Undo last AI changes?'))return;try{const r=await request('ai/undo','POST',{});state=r.state;selectedId=null;undoStack=[];redoStack=[];redraw();$('aiResults').textContent='AI edits undone.';}catch(e){$('aiResults').textContent=e.message;}}
function setup(){
 $('linkBtn').onclick=importLinked;$('firstImport').onclick=importLinked;$('dropBtn').onclick=()=>$('fileInput').click();$('fileInput').onchange=e=>{void importDropped(e.target.files);e.target.value='';};
 $('searchAssets').oninput=renderAssets;$('assetFilter').onchange=renderAssets;
 $('aiBtn').onclick=()=>openModal('aiModal');$('exportBtn').onclick=()=>{openModal('exportModal');$('exportResolution').value=state.output.width;$('exportFps').value=state.output.fps;$('exportCrf').value=state.output.crf||20;$('exportPreset').value=state.output.preset||'medium';};$('helpBtn').onclick=()=>openModal('helpModal');
 document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>closeModal(b.dataset.close));document.querySelectorAll('.modal-overlay').forEach(m=>m.onclick=e=>{if(e.target===m)m.hidden=true;});
 $('playBtn').onclick=playPause;$('stepBack').onclick=()=>seek(playhead-1/state.output.fps);$('stepForward').onclick=()=>seek(playhead+1/state.output.fps);$('jumpStart').onclick=()=>seek(0);
 $('undoBtn').onclick=()=>restoreHistory(undoStack,redoStack);$('redoBtn').onclick=()=>restoreHistory(redoStack,undoStack);
 $('splitBtn').onclick=splitSelected;$('duplicateBtn').onclick=duplicateSelected;$('deleteBtn').onclick=removeSelected;
 $('snapBtn').onclick=()=>{snap=!snap;$('snapBtn').classList.toggle('active',snap);};
 $('addVideoTrack').onclick=()=>addTrack('video');$('addAudioTrack').onclick=()=>addTrack('audio');$('addTitle').onclick=addTitle;
 $('timelineZoom').oninput=e=>{zoom=Number(e.target.value);$('zoomLabel').textContent=zoom+' px/s';renderTimeline();};
 $('zoomOut').onclick=()=>{$('timelineZoom').value=Math.max(14,zoom-15);$('timelineZoom').oninput({target:$('timelineZoom')});};
 $('zoomIn').onclick=()=>{$('timelineZoom').value=Math.min(190,zoom+15);$('timelineZoom').oninput({target:$('timelineZoom')});};
 document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{insTab=b.dataset.tab;document.querySelectorAll('[data-tab]').forEach(n=>n.classList.toggle('active',n===b));renderInspector();});
 $('startRender').onclick=()=>void startExport();$('cancelRender').onclick=()=>void request('job/cancel','POST',{job:'export'});
 $('reviewPackBtn').onclick=()=>void makeReviewPack();$('reviewVideoBtn').onclick=()=>void makeReviewVideo();$('openChat').onclick=()=>window.open('https://chatgpt.com/','_blank','noopener');
 $('analyzeBtn').onclick=()=>void analyzeAi();$('previewAiBtn').onclick=()=>void previewAi();$('applyAiBtn').onclick=()=>void applyAi();$('undoAiBtn').onclick=()=>void undoAi();
 $('proposalJson').oninput=()=>{proposalToken=null;$('applyAiBtn').disabled=true;};$('transferCancel').onclick=()=>{transferStop=true;toast('Cancel requested');};
 document.addEventListener('keydown',e=>{if(e.key==='Escape'){$('aiModal').hidden=$('exportModal').hidden=$('helpModal').hidden=true;return;}if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)||!$('aiModal').hidden||!$('exportModal').hidden||!$('helpModal').hidden)return;
  if(e.ctrlKey&&e.key.toLowerCase()==='s'){e.preventDefault();void flushSave();return;}
  if(e.ctrlKey&&e.key.toLowerCase()==='z'){e.preventDefault();restoreHistory(e.shiftKey?redoStack:undoStack,e.shiftKey?undoStack:redoStack);return;}
  if(e.ctrlKey&&e.key.toLowerCase()==='y'){e.preventDefault();restoreHistory(redoStack,undoStack);return;}
  if(e.ctrlKey&&e.key.toLowerCase()==='d'){e.preventDefault();duplicateSelected();return;}
  if(e.key.toLowerCase()==='s'&&!e.ctrlKey){e.preventDefault();splitSelected();return;}
  if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();removeSelected();return;}
  if(e.code==='Space'){e.preventDefault();playPause();return;}
  if(e.key==='ArrowLeft'){e.preventDefault();seek(playhead-1/state.output.fps);}
  if(e.key==='ArrowRight'){e.preventDefault();seek(playhead+1/state.output.fps);}
 });
 // Browser Files never expose original filesystem paths; chunked local streaming
 // is essential for 4.5+ GB drag-and-drop without whole-file buffering.
 let dragCount=0;
 window.addEventListener('dragenter',e=>{if(e.dataTransfer?.types.includes('Files')){e.preventDefault();dragCount++;$('dropOverlay').hidden=false;}});
 window.addEventListener('dragover',e=>{if(e.dataTransfer?.types.includes('Files')){e.preventDefault();e.dataTransfer.dropEffect='copy';}});
 window.addEventListener('dragleave',e=>{if(e.dataTransfer?.types.includes('Files')){dragCount=Math.max(0,dragCount-1);if(!dragCount)$('dropOverlay').hidden=true;}});
 window.addEventListener('drop',e=>{if(e.dataTransfer?.types.includes('Files')){e.preventDefault();e.stopPropagation();dragCount=0;$('dropOverlay').hidden=true;const lane=e.target.closest('[data-lane]');let id=lane?.dataset?.lane,p=lane?clamp((e.clientX-lane.getBoundingClientRect().left)/zoom,0,14400):null;void importDropped(e.dataTransfer.files,id,p);}});
}
(async()=>{setup();try{state=await request('state');redraw();toast('VlogCraft Studio ready. Drag 4.5GB+ videos anywhere to import.');}catch(e){toast('Editor failed to initialize: '+e.message,true);}})();
