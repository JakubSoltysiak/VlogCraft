/* VlogCraft Studio 3 — native-local browser UI. No external JS dependencies. */
'use strict';
const $ = id => document.getElementById(id);
const svg = name => `<svg><use href="#i-${name}"/></svg>`;
const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const uid = () => (crypto.randomUUID?.() ?? (Date.now().toString(16)+Math.random().toString(16).slice(2))).replaceAll('-','');
const round = v => Math.round(v*1000)/1000;
const clamp = (v,lo,hi) => Math.max(lo,Math.min(hi,Number(v)));
const format = t => {t=Math.max(0,t||0);let s=Math.floor(t);return `${String(Math.floor(s/3600)).padStart(2,'0')}:${String(Math.floor(s%3600/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;};
const fileSize = b => b>=1024**3?(b/1024**3).toFixed(2)+' GB':b>=1024**2?(b/1024**2).toFixed(0)+' MB':(b/1024).toFixed(0)+' KB';
const seekUrl = aid => `/media/${encodeURIComponent(aid)}?proxy=${useProxies?1:0}&v=${encodeURIComponent(assetById(aid)?.cacheId||aid)}`;
const assetMap = () => Object.fromEntries((state?.assets||[]).map(a=>[a.id,a]));
const lengthOf = c => (c.end-c.start)/(c.speed||1);
const endOf = c => c.position+lengthOf(c);
const duration = () => sequenceEnd;
let state=null, zoom=70, playhead=0, selectedId=null,selectedAssetId=null,insTab='clip',isPlaying=false,playStart=0,playAt=0;
let undoStack=[],redoStack=[],saveTimer=null,saveInFlight=Promise.resolve(),modified=0,persisted=0;
let lastPreviewKey='',activePlayers=new Map(),snap=true,clipGesture=null,transferStop=false,transferId=null,toastTimeout=null;
let renderPoll=null,proposalToken=null,proposalSnapshot=null;
let timelineScrollManualUntil=0;
let librarySelection=new Set();
async function request(path,method='GET',body=null){const o={method,cache:'no-store'};if(body!==null){o.headers={'Content-Type':'application/json'};o.body=JSON.stringify(body);}const r=await fetch('/api/'+path,o);let data=await r.json().catch(()=>({error:'Unexpected response from local editor'}));if(!r.ok)throw Error(data.error||`HTTP ${r.status}`);return data;}
function toast(message,warning=false){const box=$('toast');box.textContent=message;box.className='toast visible'+(warning?' warn':'');clearTimeout(toastTimeout);toastTimeout=setTimeout(()=>box.className='toast',4200);}
function setSaveStatus(txt){$('saveStatus').textContent=txt;}
function save(){modified++;recoveryCheckpoint(true);setSaveStatus('UNSAVED CHANGES');clearTimeout(saveTimer);saveTimer=setTimeout(()=>void flushSave(),600);}
async function flushSave(){clearTimeout(saveTimer);saveTimer=null;let s=structuredClone(state);if(s){delete s.luts;delete s.assets;}let rev=modified;if(s){s._desktopEpoch=recoveryEpoch;s._editRevision=rev;}
 const next=saveInFlight.catch(()=>{}).then(async()=>{if(!state)return;const saved=await request('state','POST',s);persisted=Math.max(rev,persisted);if(persisted>=modified)setSaveStatus('ALL CHANGES SAVED');return saved;});
 saveInFlight=next;try{await next;}catch(e){setSaveStatus('SAVE ERROR');toast('Could not save: '+e.message,true);}return next;}
function snapshot(){invalidateRendered();undoStack.push(structuredClone({tracks:state.tracks,name:state.name,output:state.output}));if(undoStack.length>80)undoStack.shift();redoStack=[];}
function restoreHistory(from,to){if(!from.length)return;invalidateRendered();to.push(structuredClone({tracks:state.tracks,name:state.name,output:state.output}));const s=from.pop();state.tracks=s.tracks;state.name=s.name;state.output=s.output;selectedId=null;playhead=Math.min(playhead,duration());redraw();save();}
function sel(){for(const t of state.tracks){const c=t.clips.find(c=>c.id===selectedId);if(c)return {clip:c,track:t};}return null;}
function trackById(id){return state.tracks.find(t=>t.id===id);}
function assetById(id){return state.assets.find(a=>a.id===id);}
function defaultTrack(kind){return [...state.tracks].reverse().find(t=>t.type===kind);}
function clipFromAsset(a,pos=0,trackType=null){const kind=trackType==='audio'?'audio':a.kind;return {id:uid(),assetId:a.id,kind,position:round(pos),start:0,end:a.kind==='image'?5:Math.max(1/sequenceRate(),a.duration||5),speed:1,volume:1,opacity:1,scale:1,x:0,y:0,grade:'neutral',fit:'contain',fadeIn:0,fadeOut:0,locked:false};}
function canPlace(a,track){return track&&((track.type==='audio'&&a.kind!=='image')||(track.type==='video'&&a.kind!=='audio'));}
function addAsset(a,track,pos){if(!track)track=defaultTrack(a.kind==='audio'?'audio':'video');if(!canPlace(a,track)){toast('That file type cannot go on this track',true);return;}if(track.locked){toast('Track is locked',true);return;}snapshot();const c=clipFromAsset(a,pos??Math.max(0,...track.clips.map(endOf)),track.type);applyDefaultMotion(c);track.clips.push(c);applyDefaultBoundary(track,c);selectedId=c.id;playhead=c.position;redraw();save();toast('Added '+a.name+' to '+track.name);}
function renderAssets(){
 const filter=$('assetFilter').value;
 const search=$('searchAssets').value.toLowerCase().trim();
 const removed=new Set(state.output.removedMedia||[]);
 const archived=$('showRemovedMedia').checked;
 const list=state.assets.filter(a=>removed.has(a.id)===archived &&
   (filter==='all'||a.kind===filter) && a.name.toLowerCase().includes(search));
 const panel=$('assetList');
 const scroll=panel.scrollTop;
 panel.classList.toggle('list-view',$('libraryView').value==='list');
 $('mediaCount').textContent=(state.assets.length-removed.size)+' ASSETS';
 panel.innerHTML=list.map(a=>{
  const details=[a.width&&a.height?a.width+' × '+a.height:'',a.kind!=='image'?format(a.duration):'',fileSize(a.size)].filter(Boolean).join(' · ');
  const thumb=a.kind==='audio'?svg('music'):`<img loading="lazy" src="/thumb/${a.id}?v=${a.cacheId||a.id}${archived?'':'&restore=1'}" alt="" onerror="this.style.display='none'">`;
  return `<article class="asset-card" tabindex="0" data-asset="${a.id}" draggable="${!archived}">
   <div class="asset-thumb">${thumb}<span class="asset-badge">${a.missing?'OFFLINE':a.kind.toUpperCase()}</span>${a.hdr?'<span class="hdr-badge">HDR</span>':''}</div>
   <div class="asset-text"><div class="asset-name" title="${esc(a.name)}">${esc(a.name)}</div>
   <div class="asset-description">${details}</div>
   ${archived?'':`<div class="asset-sub"><button class="text-button" data-source="${a.id}">Source</button>
      ${a.missing?`<button data-relink="${a.id}" class="text-button">Relink</button>`:''}
      <button class="asset-plus" title="Add to timeline" data-add="${a.id}">+</button></div>`}</div></article>`;
 }).join('')||'<div class="empty-media">No matching files</div>';
 panel.scrollTop=scroll;
 const syncSelection=()=>{
  for(const card of panel.querySelectorAll('[data-asset]'))card.classList.toggle('selected',librarySelection.has(card.dataset.asset));
  const button=$('libraryRemove');
  button.disabled=!list.some(a=>librarySelection.has(a.id));
  button.textContent=archived?'Restore selected':'Remove selected from project';
 };
 for(const card of panel.querySelectorAll('[data-asset]')){
  const a=assetById(card.dataset.asset);
  const select=event=>{
   if(event.target.closest('button'))return;
   if(event.ctrlKey||event.metaKey){
    if(librarySelection.has(a.id))librarySelection.delete(a.id);else librarySelection.add(a.id);
   }else librarySelection=new Set([a.id]);
   syncSelection();
  };
  card.onclick=select;
  card.onkeydown=event=>{if(event.code==='Space'&&event.target===card){event.preventDefault();select(event);}};
  if(!archived){
   card.ondragstart=event=>{event.dataTransfer.setData('application/x-vlogcraft',a.id);event.dataTransfer.effectAllowed='copy';};
   card.ondblclick=event=>{if(!event.target.closest('button'))addAsset(a);};
  }
 }
 panel.querySelectorAll('[data-source]').forEach(b=>b.onclick=()=>sourceMonitor(assetById(b.dataset.source)));
 panel.querySelectorAll('[data-add]').forEach(b=>b.onclick=()=>addAsset(assetById(b.dataset.add)));
 syncSelection();
}
function changeLibrarySelection(){
 const removed=new Set(state.output.removedMedia||[]);
 const entries=[...$('assetList').querySelectorAll('[data-asset]')].map(el=>el.dataset.asset)
   .filter(id=>librarySelection.has(id));
 if(!entries.length)return;
 if(!$('showRemovedMedia').checked){
  const used=[];
  function collect(tracks){
   for(const track of tracks)for(const c of track.clips){
    if(entries.includes(c.assetId))used.push(track.name);
    if(c.kind==='sequence')collect(c.children);
   }
  }
  collect(state.tracks);
  if(used.length){toast('Selection is used by '+used.length+' clip(s) on '+[...new Set(used)].join(', '),true);return;}
 }
 snapshot();
 for(const id of entries){
  if($('showRemovedMedia').checked)removed.delete(id);else removed.add(id);
 }
 state.output.removedMedia=[...removed].sort();
 librarySelection.clear();
 renderAssets();save();
}
function renderProjectInspector(){
 const out=state.output;
 const preset=sequenceDimensions.find(([, ,width,height])=>width===out.width&&height===out.height);
 return `<div class="section-label">SEQUENCE</div>
 <div class="property"><label>Project name</label><input data-proj="name" value="${esc(state.name)}" maxlength="160"></div>
 <div class="property"><label>Sequence length</label><div class="prop-time">${timecode(duration())}</div></div>
 <div class="property"><label for="sequenceAspect">Aspect ratio and size</label><select id="sequenceAspect">
 ${sequenceDimensions.map(([id,label])=>`<option value="${id}" ${preset?.[0]===id?'selected':''}>${label}</option>`).join('')}
 <option value="custom" ${!preset?'selected':''}>Custom dimensions</option></select></div>
 <div id="sequenceCustom" ${preset?'hidden':''}><div class="prop-row">
 <div class="property"><label for="sequenceWidth">Width</label><input id="sequenceWidth" type="number" min="16" max="16384" step="2" value="${out.width}"></div>
 <div class="property"><label for="sequenceHeight">Height</label><input id="sequenceHeight" type="number" min="16" max="16384" step="2" value="${out.height}"></div></div>
 <button type="button" class="button secondary" id="applySequenceSize">Apply size</button></div>
 <p class="dialog-note">Existing clip fit and transforms are preserved. Review framing after changing the canvas.</p>
 <button type="button" class="button secondary" id="storageUsage">Storage usage</button>
 <div class="property"><label>Frames per second</label><select data-proj="fps">${rateOptions(out.fps)}</select></div>`;
}
const field=(label,key,value,min,max,step=.1)=>`<div class="property"><label>${label}</label><input data-prop="${key}" type="number" min="${min}" max="${max}" step="${step}" value="${round(value)}"></div>`;
const range=(label,key,value,min,max,step=.05,percent=true)=>`<div class="property"><label>${label}</label><div class="range-line"><input data-prop="${key}" type="range" min="${min}" max="${max}" step="${step}" value="${value}"><output>${percent?Math.round(value*100)+'%':round(value)}</output></div></div>`;
function renderInspector(){let html='';if(insTab==='project'){html=renderProjectInspector();}else{
 const current=sel();if(!current)html='<div class="inspector-empty-art"><strong>◇</strong>Choose a clip on the timeline to begin grading, trimming or mixing audio.</div>';
 else{
 if(current.clip.kind==='sequence'){
   $('inspectorContent').innerHTML='<div class="section-label">NESTED SEQUENCE</div><p class="dialog-note">Move the sequence as one clip. Expand it to edit its original tracks and keyframes.</p><button class="button secondary" id="expandNested">Expand sequence</button>';
   $('expandNested').onclick=()=>commitEdit('expand');return;
 }
 const {clip:c,track:t}=current,a=assetById(c.assetId);const kind=c.kind;
 html=`<div class="prop-asset">${a&&a.kind!=='audio'?`<img class="prop-thumb" src="/thumb/${a.id}?v=${a.cacheId||a.id}" onerror="this.style.visibility='hidden'">`:`<div class="prop-thumb" style="display:grid;place-items:center">${kind==='title'?'T':svg('music')}</div>`}<div class="prop-text"><div class="prop-name">${esc(a?.name || 'Title graphic')}</div><div class="prop-time">${esc(t.name)} · ${format(lengthOf(c))}</div></div></div>`;
 html+='<div class="section-label">TIMING</div><div class="prop-row">'+field('Timeline start (sec)','position',c.position,0,1e12,.01)+field('Clip duration (sec)','duration',lengthOf(c),1/sequenceRate(),1e12,.01)+'</div>';
 if(a && a.kind!=='image'){html+='<div class="prop-row">'+field('Source in','start',c.start,0,36000,.01)+field('Source out','end',c.end,.04,36000,.01)+'</div>';html+=range('Playback speed','speed',c.speed,.1,4,.01,false);}
 if(t.type==='video'&&kind!=='title'){
 html+=inputColorControls(c,a);
 html+='<div class="section-label">COMPOSITION</div>'+range('Opacity','opacity',c.opacity,0,1,.01)+range('Scale','scale',c.scale,.1,3,.05,false);
 html+=field('Rotation (degrees)','rotation',c.rotation??0,-360,360,1)+effectControls(c);
 html+='<div class="prop-row">'+field('Horizontal offset','x',c.x,-2,2,.01)+field('Vertical offset','y',c.y,-2,2,.01)+'</div>';
 html+=`<div class="property"><label>Fit</label><select data-prop="fit"><option value="contain" ${c.fit==='contain'?'selected':''}>Fit entire frame</option><option value="cover" ${c.fit==='cover'?'selected':''}>Fill / crop</option></select></div>`;
 html+=`<div class="property"><label>Color grade</label><select data-prop="grade">${['neutral','warm','cool','vivid','cinematic','mono'].map(x=>`<option value="${x}" ${c.grade===x?'selected':''}>${x.toUpperCase()}</option>`).join('')}</select></div>`;
 }
 if(kind==='title')html+='<div class="section-label">TYPOGRAPHY</div>'+`<div class="property"><label>Title text</label><textarea data-prop="text" rows="3">${esc(c.text||'')}</textarea></div>`+range('Text size','fontScale',c.fontScale,.01,.15,.005,false)+`<div class="property"><label>Color</label><select data-prop="color">${['white','yellow','cyan','black','#f5ce8a','#a6ffdf'].map(x=>`<option ${x===c.color?'selected':''} value="${x}">${x}</option>`).join('')}</select></div>`;
 if(kind==='title'){
   html+='<div class="prop-row"><div class="property"><label>Font</label><select data-prop="titleFont">'+
     Object.entries({segoe:'Segoe UI',arial:'Arial',georgia:'Georgia'}).map(([id,name])=>'<option value="'+id+'" '+((c.titleFont||'segoe')===id?'selected':'')+'>'+name+'</option>').join('')+
     '</select></div><div class="property"><label>Placement</label><select data-prop="titleAlign"><option value="center">Center</option><option value="lower" '+(c.titleAlign==='lower'?'selected':'')+'>Lower</option></select></div></div>';
   html+=range('Opacity','opacity',c.opacity,0,1,.01)+field('Horizontal offset','x',c.x,-2,2,.01)+field('Vertical offset','y',c.y,-2,2,.01);
   if(state.output.color)html+=range('Scale','scale',c.scale,.1,3,.05,false)+field('Rotation (degrees)','rotation',c.rotation??0,-360,360,1)+effectControls(c);
 }
 if((a?.hasAudio||kind==='audio'))html+='<div class="section-label">AUDIO MIX</div>'+range('Source volume','volume',c.volume,0,3,.05)+(!c.audioDetached?mixerControls(c,t):'');
 if(a?.kind==='video'&&a.hasAudio){
   const audioFormat=[a.audioSampleRate?Number(a.audioSampleRate)/1000+' kHz':'',a.audioChannelLayout||''].filter(Boolean).join(' · ');
   html+='<p class="dialog-note">'+(kind==='audio'?'Camera audio track':c.audioDetached?'Camera audio on a separate track':'Embedded camera audio')+
     (audioFormat?' · '+esc(audioFormat):'')+'</p>';
   if(kind==='video'&&!c.audioDetached&&!c.linkId)html+='<button type="button" id="separateCameraAudio" class="button secondary">Separate and link camera audio</button>';
   if(c.linkId&&(kind==='audio'||c.audioDetached))html+='<button type="button" id="unlinkCameraAudio" class="button secondary">Unlink camera audio</button>';
 }
 if(t.type==='video'&&kind!=='title')html+='<button class="button secondary" id="gradeOpen">Curves, wheels &amp; LUT</button>';
 if(a || kind==='title')html+=animationControls(c);
 if(kind==='video')html+='<div class="property-actions"><button id="motionOpen" class="button secondary">TRACK / STABILIZE</button></div>';
 html+='<div class="section-label">TRANSITIONS</div><div class="prop-row">'+field('Fade in (s)','fadeIn',c.fadeIn,0,30,.05)+field('Fade out (s)','fadeOut',c.fadeOut,0,30,.05)+'</div>';
 if(t.type==='video'&&kind!=='title')html+='<div class="property"><label>Entrance wipe</label><select data-prop="wipe">'+['none','right','left','down','up'].map(v=>'<option value="'+v+'" '+(v===(c.wipe||'none')?'selected':'')+'>'+v+'</option>').join('')+'</select></div>'+field('Wipe duration (s)','wipeDuration',c.wipeDuration??.5,.001,30,.05);
 if(a?.kind==='video')html+='<div class="property-actions"><button id="makeProxyBtn" class="button secondary">CREATE 720p PROXY</button></div><small>Proxies make large 4K/HDR sources easier to scrub. Export remains original quality.</small>';
 html+='<div class="property-actions"><button id="rippleDeleteBtn" class="button secondary">RIPPLE DELETE</button><button id="deleteClipInspector" class="button secondary">'+svg('trash')+' REMOVE CLIP</button><button id="duplicateClipInspector" class="button secondary">'+svg('copy')+' DUPLICATE</button></div>';
 }}
 $('inspectorContent').innerHTML=html;
 bindInputColor();
 $('storageUsage')?.addEventListener('click',openProjectStorage);
 if($('gradeOpen'))$('gradeOpen').onclick=gradeDialog;
 $('inspectorContent').querySelectorAll('[data-proj]').forEach(el=>el.onchange=()=>{snapshot();const key=el.dataset.proj;if(key==='name')state.name=el.value||'Untitled';else if(key==='fps')state.output.fps=rateChoice(el.value);redraw();save();});
 if($('sequenceAspect')){
  $('sequenceAspect').onchange=event=>{
   const dimensions=sequenceDimensions.find(row=>row[0]===event.target.value);
   $('sequenceCustom').hidden=!!dimensions;
   if(dimensions)applySequenceDimensions(dimensions[2],dimensions[3]);
  };
  $('applySequenceSize').onclick=()=>applySequenceDimensions($('sequenceWidth').valueAsNumber,$('sequenceHeight').valueAsNumber);
 }
 $('inspectorContent').querySelectorAll('[data-prop]').forEach(el=>{const action=()=>{
  const cur=sel();if(!cur || cur.track.locked || cur.clip.locked)return;const c=cur.clip,k=el.dataset.prop;
  if(c.linkId && ['position','duration','start','end','speed'].includes(k)){toast('Use timeline handles to trim the linked pair, or unlink for independent timing',true);renderInspector();return;}
  const old=c[k];let v=el.type==='checkbox'?el.checked:el.type==='number'||el.type==='range'?Number(el.value):el.value;
  if(k==='duration'){v=atFrame(Math.max(1,frameIndex(clamp(v,0,1e12))));c.end=c.start+v*(c.speed||1);}
  else if(k==='position')c.position=frameTime(Math.max(0,v));
  else if(k==='end')c.end=Math.max(c.start+c.speed/sequenceRate(),v);
  else if(k==='start')c.start=Math.min(v,c.end-c.speed/sequenceRate());
  else if(['volume','opacity','scale','speed','x','y','fadeIn','fadeOut','fontScale'].includes(k))c[k]=v;
  else c[k]=v;
  if(c.assetId){const a=assetById(c.assetId);if(a.kind!=='image')c.end=Math.min(c.end,a.duration);}
  if(el.type==='range'){const out=el.parentElement.querySelector('output');if(out)out.textContent=['opacity','volume'].includes(k)?Math.round(v*100)+'%':round(v);}
  renderTimeline();syncPreview(true);save();
 };el.oninput=action;el.onfocus=()=>{if(!el.dataset.history){snapshot();el.dataset.history='yes';}};el.onblur=()=>{delete el.dataset.history;};});
 $('rippleDeleteBtn')?.addEventListener('click',rippleDelete);
 $('separateCameraAudio')?.addEventListener('click',()=>commitEdit('extractAudio',{},[sel().clip.id]));
 $('unlinkCameraAudio')?.addEventListener('click',()=>commitEdit('unlink',{},[sel().clip.id]));
 $('normalizeClip')?.addEventListener('click',()=>analyzeLevels('normalize'));
 $('duckClip')?.addEventListener('click',()=>analyzeLevels('duck'));
 bindAnimation();
 $('motionOpen')?.addEventListener('click',openMotion);
 $('deleteClipInspector')?.addEventListener('click',removeSelected);$('duplicateClipInspector')?.addEventListener('click',duplicateSelected);
 $('makeProxyBtn')?.addEventListener('click',async()=>{const c=sel()?.clip;if(!c)return;try{await request('proxy','POST',{assetId:c.assetId});toast('Building a local 720p proxy. Editing continues.');}catch(e){toast(e.message,true);}});
}
function select(id){multiple.clear();selectedId=id;document.querySelectorAll('[data-clip]').forEach(el=>el.classList.toggle('selected',el.dataset.clip===id));renderInspector();}
function tickStep(){const n=duration();if(n<25)return 2;if(n<60)return 5;if(n<180)return 10;if(n<600)return 30;return 60;}
function renderTimeline(scrollOnly=false){if(!scrollOnly)rebuildIndex();const total=Math.max(24,duration()+6);const canvas=Math.max(1500,Math.ceil(total*zoom)+100);const step=tickStep();
 const viewport=$('timelineScroller');
 const viewStart=Math.max(0,(viewport.scrollLeft-600)/zoom),viewEnd=(viewport.scrollLeft+viewport.clientWidth+600)/zoom;
 viewport.dataset.first=viewStart;viewport.dataset.last=viewEnd;
 let html=`<div class="ruler-row"><div class="ruler-left">TIME / ${rateLabel(state.output.fps)} FPS</div><div class="ruler-lane" data-ruler style="width:${canvas}px;min-width:${canvas}px">`;
 for(let i=Math.floor(viewStart/step)*step;i<=Math.min(total,viewEnd);i+=step){html+=`<div class="ruler-tick" style="left:${i*zoom}px">${format(i).slice(3)}</div>`;}
 html+='</div></div>';
 for(const t of state.tracks){html+=`<div class="track-row ${t.type==='audio'?'audio-row':''}" style="height:${t.height||67}px" data-track-row="${t.id}"><div class="track-head"><div class="track-color" style="background:${t.color || (t.type==='audio'?'#ad95da':'#79b4de')}"></div><div class="track-info"><div class="track-name" title="${esc(t.name)}">${esc(t.name)}</div><div class="track-actions"><button class="track-action" data-track-settings="${t.id}" title="Track settings">⋯</button><button class="track-action ${t.muted?'on':''}" data-track-action="muted" data-track="${t.id}" title="Mute track">${svg('volume')}</button>${t.type==='video'?`<button class="track-action ${t.hidden?'on':''}" data-track-action="hidden" data-track="${t.id}" title="Hide video">${svg('eye')}</button>`:''}<button class="track-action ${t.locked?'on':''}" data-track-action="locked" data-track="${t.id}" title="Lock track">${svg('lock')}</button></div></div></div><div class="track-lane" data-lane="${t.id}" style="width:${canvas}px;min-width:${canvas}px">`;
 for(const c of clipsIn(t,viewStart,viewEnd)){const a=assetById(c.assetId);const w=Math.max(5,lengthOf(c)*zoom);const left=Math.max(0,c.position*zoom);
 const wave=a?.hasAudio && t.type==='audio';
 const fraction=wave?(c.end-c.start)/Math.max(a.duration,.00001):1;
 const waveStyle=wave?'background-image:url(/wave/'+a.id+'?v='+(a.cacheId||a.id)+');background-size:'+100/fraction+'% 100%;background-position:'+100*c.start/Math.max(.00001,a.duration-(c.end-c.start))+'% center;opacity:.72':'';
 html+=`<div class="track-clip ${t.type==='audio'?'audio-clip':''} ${c.kind==='title'?'title-clip':''} ${chosenClip(c.id)?'selected':''}" data-clip="${c.id}" data-parent="${t.id}" title="${esc(a?.name||c.text||'Title')} · ${format(c.position)} → ${format(endOf(c))}" style="left:${left}px;width:${w}px"><div class="clip-bg" ${wave?`style="${waveStyle}"`:a&&a.kind!=='audio'?`style="background-image:url('/thumb/${a?.id}')"`:''}></div><div class="trim-handle trim-left" data-handle="left"></div><div class="clip-content"><strong>${c.kind==='title'?'T · '+esc(c.text):t.type==='audio'?'♫ '+esc(a?.name):esc(a?.name||c.name||'Clip')}</strong><small>${w>88?format(lengthOf(c)).slice(3):''}</small></div><div class="trim-handle trim-right" data-handle="right"></div></div>`;
 }
 for(const c of clipsIn(t,viewStart,viewEnd))html+=boundaryBadge(t,c);
 html+='</div></div>';
 }
 html+='<div class="playhead" id="timelinePlayhead"></div><div id="timelineSnapGuide" class="snap-guide" hidden></div>';
 const scroller=$('timelineScroller');const sx=scroller.scrollLeft,sy=scroller.scrollTop;
 $('timelineContent').innerHTML=html;
 scroller.scrollLeft=sx;scroller.scrollTop=sy;
 positionPlayhead();
 $('timelineContent').querySelectorAll('.track-name').forEach(el=>el.ondblclick=()=>{const t=trackById(el.closest('[data-track-row]').dataset.trackRow);if(!t)return;const name=prompt('Rename timeline track',t.name);if(name?.trim()){snapshot();t.name=name.trim().slice(0,90);redraw();save();}});
 $('timelineContent').querySelectorAll('[data-track-settings]').forEach(b=>b.onclick=()=>trackSettings(trackById(b.dataset.trackSettings)));
 $('timelineContent').querySelectorAll('[data-track-action]').forEach(btn=>btn.onclick=e=>{e.stopPropagation();let t=trackById(btn.dataset.track);snapshot();t[btn.dataset.trackAction]=!t[btn.dataset.trackAction];redraw();save();});
 bindBoundaryMarkers();$('timelineContent').querySelectorAll('[data-clip]').forEach(el=>el.onpointerdown=startClipGesture);
 $('timelineContent').querySelectorAll('[data-ruler]').forEach(el=>el.onpointerdown=startRulerGesture);
 $('timelineContent').querySelectorAll('[data-lane]').forEach(el=>{
  el.ondragover=e=>{if(e.dataTransfer.types.includes('application/x-vlogcraft')||e.dataTransfer.types.includes(boundaryDrag)){e.preventDefault();el.classList.add('drop-ready');e.dataTransfer.dropEffect='copy';}};
  el.ondragleave=()=>el.classList.remove('drop-ready');
  el.ondrop=e=>{el.classList.remove('drop-ready');if(dropBoundary(e,el))return;let aid=e.dataTransfer.getData('application/x-vlogcraft');if(!aid)return;e.preventDefault();e.stopPropagation();const t=trackById(el.dataset.lane);const p=clamp((e.clientX-el.getBoundingClientRect().left)/zoom,0,1e12);addAsset(assetById(aid),t,snapTo(p));};
  el.ondblclick=e=>{if(e.target.closest('[data-clip]'))return;seek((e.clientX-el.getBoundingClientRect().left)/zoom);};
 });
}
function positionPlayhead(){
 const p=$('timelinePlayhead'),frame=frameIndex(playhead),rate=sequenceRate();
 if(p&&isPlaying&&nativeSelected()&&p._paintFrame===frame&&p._paintRate===rate&&p._paintZoom===zoom)return;
 if(p){p._paintFrame=frame;p._paintRate=rate;p._paintZoom=zoom;if(p.style.left!=='151px')p.style.left='151px';p.style.transform='translateX('+(playhead*zoom)+'px)';}
 const head=$('playheadTime'),total=$('totalTime'),value=timecode(playhead),end=timecode(duration());
 if(head.textContent!==value)head.textContent=value;if(total.textContent!==end)total.textContent=end;
}
function seek(t,{scrubbing=false}={}){
 playhead=clamp(frameTime(t),0,Math.max(0,duration()));
 if(isPlaying){playAt=playhead;playStart=transportNow();}
 positionPlayhead();syncPreview(true,scrubbing);
 if(!scrubbing)recoveryCheckpoint(false);
}
function snapTo(value,ignore=null,{bypass=false,guide=false,skipPlayhead=false}={}){
 value=Math.max(0,value);
 let nearest=0;
 let distance=Math.abs(value);
 const candidate=time=>{
  const delta=Math.abs(time-value);
  if(delta<=distance){nearest=time;distance=delta;}
 };
 const grid=$('snapGrid').value;
 if(snap && !bypass){
  if(!skipPlayhead)candidate(playhead);
  for(const track of state.tracks)for(const clip of track.clips){
   if(clip.id===ignore)continue;
   candidate(clip.position);candidate(endOf(clip));
  }
  if(grid!=='edges')candidate(atFrame(gridFrame(value,grid,sequenceRate())));
 }
 const snapped=snap && !bypass && distance<=Math.max(.08,9/zoom);
 const result=frameTime(snapped?nearest:value);
 if(guide)showSnapGuide(snapped?result:null);
 return result;
}
function showSnapGuide(time){
 const guide=$('timelineSnapGuide'),ruler=document.querySelector('.ruler-left');
 if(!guide)return;
 guide.hidden=time===null;
 if(time!==null)guide.style.left=((ruler?.offsetWidth||151)+time*zoom)+'px';
}
function startRulerGesture(event){
 if(event.button!==0)return;
 let queued=event,raf=null,moved=false;
 const targetAt=ev=>{
  const ruler=document.querySelector('[data-ruler]');
  if(!ruler)return playhead;
  return clamp(snapTo((ev.clientX-ruler.getBoundingClientRect().left)/zoom,null,
                  {bypass:ev.shiftKey,guide:true,skipPlayhead:true}),0,duration());
 };
 const update=()=>{
  raf=null;
  const target=targetAt(queued);
  if(frameIndex(target)===frameIndex(playhead))return;
  moved=true;seek(target,{scrubbing:true});
 };
 const move=ev=>{
  if(ev.pointerId!==event.pointerId)return;
  queued=ev;if(raf===null)raf=requestAnimationFrame(update);
 };
 const finish=ev=>{
  if(ev.type!=='blur'&&ev.pointerId!==event.pointerId)return;
  if(raf!==null)cancelAnimationFrame(raf);
  window.removeEventListener('pointermove',move);
  window.removeEventListener('pointerup',finish);
  window.removeEventListener('pointercancel',finish);
  window.removeEventListener('blur',finish);
  const target=ev.type==='pointerup'?targetAt(ev):playhead;
  showSnapGuide(null);
  if(frameIndex(target)!==frameIndex(playhead)||(moved&&nativeSelected()))seek(target);
  else if(moved)recoveryCheckpoint(false);
 };
 update();
 window.addEventListener('pointermove',move);
 window.addEventListener('pointerup',finish);
 window.addEventListener('pointercancel',finish);
 window.addEventListener('blur',finish);
}
function startClipGesture(e){if(e.button!==0)return;const el=e.currentTarget,cid=el.dataset.clip,t=trackById(el.dataset.parent),c=t.clips.find(c=>c.id===cid);if(!c||t.locked||c.locked)return;
 e.stopPropagation();
 if(e.ctrlKey||e.metaKey){
   const set=new Set(editingIds());
   if(set.has(cid))set.delete(cid);else set.add(cid);
   multiple=set;selectedId=set.has(cid)?cid:(set.values().next().value||null);renderTimeline();renderInspector();return;
 }
 if(!chosenClip(cid))multiple.clear();
 selectedId=cid;document.querySelectorAll('.track-clip').forEach(node=>node.classList.toggle('selected',chosenClip(node.dataset.clip)));renderInspector();const handle=e.target.closest('[data-handle]');const mode=handle?.dataset.handle||'move';let startX=e.clientX,baseline=structuredClone(c),newTrack=null,moved=false;el.setPointerCapture(e.pointerId);let hover=null;
 const label=el.querySelector('.clip-content small');
 const asset=assetById(c.assetId);
 const anchor=mode==='right'?endOf(baseline):baseline.position;
 const point=(ev,guide)=>snapTo(anchor+(ev.clientX-startX)/zoom,c.id,{bypass:ev.shiftKey,guide});
 const move=ev=>{const target=point(ev,true);if(Math.abs(ev.clientX-startX)>2)moved=true;
   if(mode==='move'){
    el.style.left=(target*zoom)+'px';
    label.textContent=timecode(target)+' → '+timecode(target+lengthOf(baseline));
    const lane=document.elementFromPoint(ev.clientX,ev.clientY)?.closest('[data-lane]');
    if(hover&&hover!==lane)hover.classList.remove('drop-ready');
    if(lane&&lane.dataset.lane!==t.id){let dest=trackById(lane.dataset.lane),a=assetById(c.assetId);
      if(dest&&!dest.locked&&((c.kind==='title'||c.kind==='sequence')?dest.type==='video':canPlace(a,dest))){lane.classList.add('drop-ready');hover=lane;newTrack=dest;}else newTrack=null;
    }else{newTrack=null;hover=null;}
   }else{
    const from=mode==='left'?target:baseline.position;
    const to=mode==='right'?target:endOf(baseline);
    const length=to-from;
    const out=baseline.start+length*(baseline.speed||1);
    const inPoint=baseline.start+(target-baseline.position)*(baseline.speed||1);
    const timed=asset && asset.kind!=='image';
    if(length<1/sequenceRate()-.000001 || (timed && (mode==='left'?inPoint<-.000001:out>asset.duration+.000001))){
     label.textContent='Source or frame limit';
     return;
    }
    el.style.left=(from*zoom)+'px';
    el.style.width=Math.max(4,length*zoom)+'px';
    label.textContent=timecode(from)+' → '+timecode(to)+' · '+timecode(length);
   }
 };
 const up=ev=>{if(el.hasPointerCapture(e.pointerId))el.releasePointerCapture(e.pointerId);el.removeEventListener('pointermove',move);el.removeEventListener('pointerup',up);el.removeEventListener('pointercancel',up);if(hover)hover.classList.remove('drop-ready');showSnapGuide(null);if(!moved||ev.type==='pointercancel'){renderTimeline(true);return;}
  const target=point(ev,false);
  if(mode!=='move' || !newTrack || newTrack.id===t.id){
    const frames=frameIndex(target)-frameIndex(anchor);
    if(frames)commitEdit(mode==='move'?'move':mode==='left'?'trimLeft':'trimRight',{frames});
    else renderTimeline(true);
    return;
  }
  if(c.linkId||editingIds().length>1){toast('Move linked or multiple clips within their tracks, or unlink before changing tracks',true);redraw();return;}
  const next=structuredClone(baseline);
  next.position=target;
  if(next.position<0)next.position=0;
  if(JSON.stringify(next)!==JSON.stringify(baseline)||newTrack){snapshot();Object.assign(c,next);if(newTrack&&newTrack.id!==t.id){const a=assetById(c.assetId);t.clips.splice(t.clips.indexOf(c),1);c.kind=['title','sequence'].includes(c.kind)?c.kind:newTrack.type==='audio'?'audio':a.kind;newTrack.clips.push(c);}
   redraw();save();toast(`${mode==='move'?'Moved':'Trimmed'} clip to ${format(c.position)}`);
  }else renderTimeline();
 };
 el.addEventListener('pointermove',move);el.addEventListener('pointerup',up);el.addEventListener('pointercancel',up);
}
function splitSelected(){return commitEdit('split',{at:frameIndex(playhead)});}
function removeSelected(){return commitEdit('delete');}
function rippleDelete(){
 const hit=sel();if(!hit||hit.track.locked||hit.clip.locked)return;
 const {clip,track}=hit,tail=endOf(clip),shift=lengthOf(clip);
 if(clip.linkId||editingIds().length>1||track.clips.some(c=>c.position>=tail&&c.linkId))return toast('Ripple delete requires independent clips on this track',true);
 if(track.clips.some(c=>c!==clip && c.position>=tail && c.locked))return toast('Unlock downstream clips before a ripple delete',true);
 snapshot();track.clips=track.clips.filter(c=>c!==clip);
 for(const c of track.clips)if(c.position>=tail)c.position=frameTime(c.position-shift);
 selectedId=null;seek(Math.min(playhead,duration()));redraw();save();
}
function duplicateSelected(){return commitEdit('duplicate');}
function addTrack(type){snapshot();let existing=state.tracks.filter(t=>t.type===type).length+1;const t={id:uid(),name:`${type==='video'?'V':'A'}${existing} · ${type==='video'?'Overlay':'Audio'}`,type,muted:false,hidden:false,locked:false,volume:1,clips:[]};if(type==='video')state.tracks.unshift(t);else state.tracks.push(t);redraw();save();}
function addTitle(){const t=state.tracks.find(t=>t.type==='video'&&!t.locked);if(!t)return toast('Unlock a video track first',true);const c={id:uid(),assetId:null,kind:'title',position:round(playhead),start:0,end:4,speed:1,volume:0,opacity:1,scale:1,x:0,y:0,grade:'neutral',fit:'contain',fadeIn:.25,fadeOut:.25,text:'KENYA',fontScale:.055,color:'white',titleAlign:'center',locked:false};snapshot();t.clips.push(c);selectedId=c.id;redraw();save();}
const gradeFilters={neutral:'',warm:'sepia(.17) saturate(1.12)',cool:'hue-rotate(6deg) saturate(.95)',vivid:'contrast(1.12) saturate(1.25)',cinematic:'contrast(1.13) saturate(.8)',mono:'grayscale(1)'};
function getActiveClips(){const vis=[];for(const t of [...programTracks].reverse())if(t.type==='video'&&!t.hidden)for(const c of clipsIn(t,playhead,playhead))vis.push({c,t});return vis;}
function makePlayer(c,t,z){const a=assetById(c.assetId);if(!a)return null;const wrap=document.createElement('div');wrap.className='preview-layer';wrap.dataset.previewId=c.id;wrap.style.zIndex=z;
 if(c.kind==='title')return null;
 const prepared=waitingPlayers.get(c.id);waitingPlayers.delete(c.id);
 const media=a.kind==='image'?document.createElement('img'):(prepared?.media||sourceVideo(c));
 if(a.kind==='image')media.src='/media/'+a.id;if(media.tagName==='VIDEO'){media.preload='metadata';media.playsInline=true;media.autoplay=false;media.muted=false;media.disablePictureInPicture=true;}media.style.objectFit=c.fit==='cover'?'cover':'contain';wrap.appendChild(media);$('previewLayers').appendChild(wrap);return {media,wrap,clipId:c.id,aId:a.id};}
function syncPreview(force=false,scrubbing=false){if(!state)return;if(transitionsOnTimeline()||state.output.color&&$('playbackEngine').value==='interactive')$('playbackEngine').value='rendered';if(nativePreview(force,scrubbing))return;if(renderedPreview(force))return;if(force)referenceChanged();const active=getActiveClips();$('emptyPreview').hidden=state.tracks.some(t=>t.clips.length);
 const activeIds=new Set(active.map(x=>x.c.id));
 for(const [id,p] of activePlayers)if(!activeIds.has(id)||p.type!=='video'){
  recycleVideo(p);p.wrap?.remove();activePlayers.delete(id);
 }
 let z=1;
 for(const {c,t} of active){
  let player=activePlayers.get(c.id);if(!player){
   if(c.kind==='title'){const wrap=document.createElement('div');wrap.className='preview-title';wrap.dataset.previewId=c.id;$('previewLayers').appendChild(wrap);player={wrap,media:null,type:'video'};}
   else player={...makePlayer(c,t,z),type:'video'};
   activePlayers.set(c.id,player);
  }
  player.wrap.style.zIndex=z++;const elapsed=Math.max(0,playhead-c.position),left=Math.max(0,endOf(c)-playhead);const fi=c.fadeIn?Math.min(1,elapsed/c.fadeIn):1,fo=c.fadeOut?Math.min(1,left/c.fadeOut):1;player.wrap.style.opacity=clamp(animated(c,'opacity')*Math.min(fi,fo),0,1);
  if(c.kind==='title'){
   player.wrap.style.transform='translate('+animated(c,'x')*100+'%,'+animated(c,'y')*100+'%)';player.wrap.textContent=c.text||'';player.wrap.style.fontSize=(Math.max(8,Math.round($('previewStage').clientWidth*c.fontScale)))+'px';
   player.wrap.style.fontFamily=({segoe:'Segoe UI',arial:'Arial',georgia:'Georgia'})[c.titleFont||'segoe'];player.wrap.style.color=c.color;player.wrap.style.alignItems=c.titleAlign==='lower'?'flex-end':'center';
   continue;
  }
  const m=player.media;if(!m)continue;
  liveEffects(player,c);
  if(m.tagName==='VIDEO'){
    const sourceTime=c.start+(playhead-c.position)*c.speed;
    syncMediaTime(m,sourceTime,c.speed,force);
    mixSource(m,c,c.audioDetached||!audible(t)?0:t.volume*animated(c,'volume')*Math.min(fi,fo));
    if(isPlaying && m.paused)m.play().catch(()=>{});
    else if(!isPlaying&&!m.paused)m.pause();
  }
 }
 syncAudio(force);warmPlayers();
}
const audioPlayers=new Map();
function syncAudio(force=false){const active=[];
 for(const t of programTracks)if(t.type==='audio'&&audible(t))for(const c of clipsIn(t,playhead,playhead))active.push({t,c});
 const keys=new Set(active.map(x=>x.c.id));for(const [id,p] of audioPlayers)if(!keys.has(id)){p.pause();releaseStrip(p);p.remove();audioPlayers.delete(id);}
 for(const {t,c} of active){if(!c.assetId)continue;let m=audioPlayers.get(c.id);if(!m){m=document.createElement('audio');m.src=audioUrl(c.assetId);m.preload='metadata';document.body.appendChild(m);audioPlayers.set(c.id,m);}
  let target=c.start+(playhead-c.position)*c.speed;syncMediaTime(m,target,c.speed,force);
  const elapsed=playhead-c.position,remaining=endOf(c)-playhead;const ai=c.fadeIn?Math.min(1,elapsed/c.fadeIn):1,ao=c.fadeOut?Math.min(1,remaining/c.fadeOut):1;
  mixSource(m,c,t.volume*animated(c,'volume')*Math.min(ai,ao));
  if(isPlaying&&m.paused)m.play().catch(()=>{});else if(!isPlaying&&!m.paused)m.pause();
 }
}
function stopPlayback(){isPlaying=false;recoveryCheckpoint(false);updateMeter.peak=0;updateMeter.lastPaint=undefined;nativePause();pauseRendered();$('masterMeter').value=-60;referenceChanged();$('playBtn').innerHTML=svg('play');for(const p of activePlayers.values())p.media?.pause?.();for(const p of audioPlayers.values())p.pause();}
async function playPause(){if(nativeSelected())return nativePlayPause();if(isPlaying){stopPlayback();return;}if(duration()<=0)return toast('Add footage first',true);if(playhead>=duration()-.001)playhead=0;try{await initializeMixer();transportClock=mixer.state==='running'?mixer:null;}catch{transportClock=null;}
 isPlaying=true;playAt=playhead;playStart=transportNow();$('playBtn').innerHTML=svg('pause');syncPreview(true);requestAnimationFrame(animate);}
function animate(){if(!isPlaying)return;updateMeter();playhead=nativeSelected()?nativeClock():renderedEnabled()?renderedClock():playAt+(transportNow()-playStart)/1000;
 if(nativeSelected()&&playhead>=nativeDuration()){
  const trace=nativeState.completionTrace;
  if(trace?.generation===nativeState.generation)trace.gui_endpoint_ms=performance.now();
  playhead=nativeDuration();positionPlayhead();stopPlayback();
  if(trace?.generation===nativeState.generation)trace.gui_stopped_ms=performance.now();
  return;
 }
 if(!nativeSelected()&&playhead>=duration()){seek(duration());stopPlayback();return;}
 positionPlayhead();syncPreview(false);followTimelinePlayhead();requestAnimationFrame(animate);
}

function followTimelinePlayhead(){
 const mode=$('timelineFollow').value;
 if(mode==='off'||performance.now()<timelineScrollManualUntil)return;
 const scroller=$('timelineScroller');
 const width=scroller.clientWidth, header=151;
 const local=header+playhead*zoom-scroller.scrollLeft;
 const anchor=mode==='center'?(width+header)/2:header+30;
 if(mode==='center'||local>width-45||local<header){
  scroller.scrollLeft=Math.max(0,header+playhead*zoom-anchor);
 }
}

function changeTimelineZoom(value,anchor=null){
 const next=clamp(value,14,190);
 if(next===zoom)return;
 const viewport=$('timelineScroller');
 const header=document.querySelector('.ruler-left')?.offsetWidth||151;
 const local=header+playhead*zoom-viewport.scrollLeft;
 const visible=local>=header&&local<=viewport.clientWidth;
 const x=anchor??(visible?local:(header+viewport.clientWidth)/2);
 const scroll=zoomScrollOffset(x,zoom,next,viewport.scrollLeft,header);
 zoom=next;
 $('timelineZoom').value=zoom;
 $('zoomLabel').textContent=zoom+' px/s';
 renderTimeline(true);
 viewport.scrollLeft=scroll;
 timelineScrollManualUntil=performance.now()+4000;
}
function redraw(){if(!state)return;rebuildIndex();$('projectTitle').textContent=state.name;$('renderRes').textContent=`${state.output.width} × ${state.output.height} · ${rateLabel(state.output.fps)} FPS`;$('exportEstimate').textContent=`${state.output.width===3840?'4K UHD':state.output.width+'p'} · ${rateLabel(state.output.fps)} FPS · H.264`;
 document.querySelector('.export-feature strong').textContent=state.name;sizeMonitor();renderAssets();renderTimeline(true);renderInspector();$('timelineStatus').textContent=`${state.tracks.length} TRACKS · ${state.tracks.reduce((n,t)=>n+t.clips.length,0)} CLIPS`;
 syncPreview(true);
}
async function importLinked(){try{await flushSave();const response=await request('import','POST',{autoProxy:useProxies});const existing=new Set(state.assets.map(a=>a.id));for(const a of response.assets)if(!existing.has(a.id))state.assets.push(a);
 redraw();if(response.errors?.length)toast(response.errors[0],true);else toast(`Linked ${response.assets.length} source(s) with no copying`);setTimeout(renderAssets,1300);}catch(e){toast(e.message,true);}}
function transferUI(name,detail,progress){$('transferOverlay').hidden=false;$('transferTitle').textContent=name;$('transferDetail').textContent=detail;$('transferBar').style.width=progress+'%';}
async function importDropped(files,trackId=null,pos=null){const supported=[...files];if(!supported.length)return toast('No supported video, image, or audio files found',true);
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
async function browseExport(){
 const result=await request('export/browse','POST',{path:$('exportPath').value});
 if(result.cancelled)return false;
 $('exportPath').value=result.path;
 return true;
}
async function startExport(){
 $('startRender').disabled=true;
 let started=false;
 try{
  const delivery=$('exportWorkflow').value;
  const preserving=delivery==='hdr10plus-copy';
  const nativeProject=!$('nativeProjectExport').hidden&&$('useNativeProjectExport').checked;
  const firstExport=nativeProject&&$('nativeProjectPolicy').value==='first';
  const mixedExport=nativeProject&&$('nativeProjectPolicy').value==='mixed';
  const comparisonMaster=nativeProject&&!firstExport?$('comparisonMaster').value:'';
  if(nativeProject&&!firstExport&&!comparisonMaster)throw Error('Choose a verified comparison master for GPU rendering');
  const fixed=['samsung-hdr10plus','youtube-hdr'].includes(delivery);
  let renderSettings;
  if(!preserving){
  const custom=$('exportResolution').value==='custom';
  const w=fixed?3840:Number(custom?$('outputWidth').value:$('exportResolution').value);
  const h=fixed?2160:custom?Number($('outputHeight').value):w*9/16;
  const bitrate=fixed?0:$('outputBitrate').valueAsNumber;
  if(![w,h].every(v=>Number.isInteger(v)&&v>=16&&v<=16384&&v%2===0))throw Error('Choose even dimensions between 16 and 16384 pixels');
  if(!Number.isFinite(bitrate)||bitrate<0||bitrate>2000)throw Error('Invalid output bitrate');
   const color=await validatedColorFromControls();
   renderSettings={width:w,height:h,fps:fixed?60:rateChoice($('exportFps').value),crf:Number($('exportCrf').value),
                   preset:$('exportPreset').value,encoder:color?.output==='hdr10'?'libx265':$('encoderChoice').value,bitrate,color};
  }
  if(!$('exportPath').value.trim() && !await browseExport())return;
  const destination=await request('export/destination','POST',{path:$('exportPath').value});
  if(destination.exists && !confirm('Replace the existing MP4 at this destination?'))return;
  $('exportPath').value=destination.path;
  if(renderSettings && delivery==='render'){
   snapshot();Object.assign(state.output,renderSettings);redraw();save();
  }
  await flushSave();
  const res=await request('export','POST',{path:destination.path,overwrite:destination.exists,delivery,
                                         ...(firstExport?{experimentalFirstExport:true}:nativeProject?{comparisonMaster}:{}),
                                         ...(mixedExport?{experimentalMixedExport:true}:{}),
                                         ...(delivery!=='render'&&!preserving?{settings:renderSettings}:{})});
  if(res.cancelled)return;
  started=true;
  $('renderProgress').hidden=false;$('openExportFolder').hidden=true;
  $('cancelRender').hidden=false;beginJobPoll('export');
 }catch(e){toast('Export: '+e.message,true);}
 finally{if(!started)$('startRender').disabled=false;}
}
function paintExportJob(j){
  $('renderProgress').hidden=false;
  $('renderMessage').textContent=j.message;$('renderPercent').textContent=j.percent+'%';$('renderBar').style.width=j.percent+'%';$('renderResult').textContent=j.error||j.path||'';
  const details=[];
  if(j.segment && j.stage!=='final-mux')details.push('Segment '+j.segment+' / '+j.segments);
  if(j.encoder)details.push(j.encoder);
  if(j.frames!=null)details.push(j.frames.toLocaleString()+' video frames');
  if(j.encodedSeconds!=null)details.push(j.encodedSeconds.toFixed(2)+'s encoded');
  if(j.fps)details.push(j.fps.toFixed(1)+' processing fps');
  if(j.elapsedSeconds!=null)details.push(j.elapsedSeconds.toFixed(1)+'s elapsed');
  if(j.status==='rendering' && j.activityAge!=null)details.push(
   j.activityAge>=15?'No FFmpeg progress reported for '+Math.floor(j.activityAge)+'s':'Last progress '+j.activityAge.toFixed(1)+'s ago');
  if(j.fallback)details.push(j.fallback);
  $('renderDetails').textContent=details.join(' · ');
  $('openExportFolder').hidden=j.status!=='done' || !document.documentElement.classList.contains('native-ready');
}
function beginJobPoll(which,onDone){clearInterval(renderPoll);renderPoll=setInterval(async()=>{try{const d=await request('jobs');const j=d[which];if(which==='export')paintExportJob(j);
 else $('diskHint').textContent=j.message;
 if(['done','error','cancelled','interrupted'].includes(j.status)){clearInterval(renderPoll);renderPoll=null;$('startRender').disabled=false;$('cancelRender').hidden=true;if(which==='export'&&j.status==='done')toast('Export saved: '+j.path);if(j.status==='error')toast(j.error||'Render failed',true);onDone?.(j);}
 }catch(e){clearInterval(renderPoll);renderPoll=null;toast(e.message,true);}},900);}
function proposalText(){let t=$('proposalJson').value.trim();if(t.startsWith('```'))t=t.replace(/^```(?:json)?\s*/,'').replace(/\s*```$/,'');return JSON.parse(t);}
async function makeReviewPack(){try{await flushSave();$('reviewStatus').textContent='Rendering program frames locally…';const r=await request('review','POST',$('reviewCurrentFrame').checked?{frames:[Math.min(frameIndex(playhead),Math.max(0,frameIndex(duration())-1))]}:{});$('reviewPackLink').href=r.url;$('reviewPackLink').hidden=false;$('reviewStatus').textContent=`Review ZIP ready: ${r.frames} frames, ${fileSize(r.bytes)}. No full-size footage included.`;}catch(e){$('reviewStatus').textContent=e.message;}}
async function makeReviewVideo(){try{await flushSave();$('reviewVideoLink').hidden=true;$('reviewStatus').textContent='Rendering a compressed 720p review MP4…';const r=await request('review/video','POST',{});beginJobPoll('export',status=>{if(status.status==='done'){$('reviewVideoLink').href=r.url;$('reviewVideoLink').hidden=false;$('reviewStatus').textContent='Review ready — attach this MP4 here in ChatGPT.';}else $('reviewStatus').textContent=status.error||status.message;});}catch(e){$('reviewStatus').textContent=e.message;}}
async function analyzeAi(){const b=$('analyzeBtn');b.disabled=true;$('aiResults').textContent='Sending up to 8 sampled JPEG frames and project manifest to OpenAI API. Original video files stay local.';try{await flushSave();let r=await request('ai/analyze','POST',{apiKey:$('apiKey').value,goal:$('aiGoal').value});$('proposalJson').value=JSON.stringify(r,null,2);proposalToken=null;$('applyAiBtn').disabled=true;$('aiResults').textContent=`${r.summary||''}\n\n${(r.suggestions||[]).map(x=>'• '+x).join('\n')}\n\n${r.shotsSent} frames sent. Review changes before applying.`;}catch(e){$('aiResults').textContent='AI error: '+e.message;}finally{b.disabled=false;}}
async function previewAi(){try{await flushSave();const p=proposalText();const r=await request('ai/preview','POST',{proposal:p});proposalToken=r.approvalToken;proposalSnapshot=$('proposalJson').value;$('applyAiBtn').disabled=!r.count;$('aiResults').textContent=`${r.summary||'AI edit plan'}\n\n${r.changes.map(c=>'• '+c).join('\n')||'Advice only — no automatic edits.'}\n\nReview the track and clip changes above before approving.`;}catch(e){$('aiResults').textContent=e.message;}}
async function applyAi(){if(!proposalToken||proposalSnapshot!==$('proposalJson').value)return toast('Preview the exact proposal first',true);if(!confirm('Apply the previewed edits to this timeline?'))return;try{await flushSave();const r=await request('ai/apply','POST',{proposal:proposalText(),approvalToken:proposalToken});snapshot();state=r.state;selectedId=null;proposalToken=null;$('applyAiBtn').disabled=true;redraw();$('aiResults').textContent='Applied '+r.changes.length+' edits. Use Undo Last AI Apply to revert.';}catch(e){$('aiResults').textContent=e.message;}}
async function undoAi(){if(!confirm('Undo last AI changes?'))return;try{const r=await request('ai/undo','POST',{});invalidateRendered();redoStack.push(structuredClone({tracks:state.tracks,name:state.name,output:state.output}));undoStack.pop();state=r.state;selectedId=null;redraw();$('aiResults').textContent='AI edits undone. Ctrl+Y restores the approved edits.';}catch(e){$('aiResults').textContent=e.message;}}
function setup(){
 setupRenderedPreview();setupReference();$('editCommands').onclick=commandDialog;
 $('motionPresetsBtn').onclick=motionPresetDialog;setupBoundaryControl();
 let pendingScroll=false;
 $('timelineScroller').onscroll=()=>{
   if(pendingScroll||!state)return;pendingScroll=true;
   requestAnimationFrame(()=>{pendingScroll=false;const v=$('timelineScroller'),left=v.scrollLeft/zoom,right=(v.scrollLeft+v.clientWidth)/zoom;
     if((left>0&&left<Number(v.dataset.first)+100/zoom)||right>Number(v.dataset.last)-100/zoom)renderTimeline(true);
   });
 };
 $('linkBtn').onclick=importLinked;$('firstImport').onclick=importLinked;$('dropBtn').onclick=()=>$('fileInput').click();$('fileInput').onchange=e=>{void importDropped(e.target.files);e.target.value='';};
 $('searchAssets').oninput=renderAssets;$('assetFilter').onchange=renderAssets;
 $('libraryView').onchange=renderAssets;
 $('libraryThumbs').oninput=e=>$('assetList').style.setProperty('--asset-size',e.target.value+'px');
 $('libraryWidth').oninput=e=>document.querySelector('.workspace').style.setProperty('--library-width',e.target.value+'px');
 $('showRemovedMedia').onchange=()=>{librarySelection.clear();renderAssets();};
 $('libraryRemove').onclick=changeLibrarySelection;
 $('performanceBtn').onclick=()=>{stopPlayback();openModal('performanceModal');};$('performanceRun').onclick=performanceTest;$('performanceApply').onclick=applyPerformancePreview;
 $('aiBtn').onclick=()=>openModal('aiModal');$('exportBtn').onclick=openExport;$('helpBtn').onclick=()=>openModal('helpModal');
 document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>closeModal(b.dataset.close));document.querySelectorAll('.modal-overlay').forEach(m=>m.onclick=e=>{if(e.target===m)m.hidden=true;});
 $('playBtn').onclick=playPause;$('stepBack').onclick=()=>seek(playhead-1/sequenceRate());$('stepForward').onclick=()=>seek(playhead+1/sequenceRate());$('jumpStart').onclick=()=>seek(0);
 $('undoBtn').onclick=()=>restoreHistory(undoStack,redoStack);$('redoBtn').onclick=()=>restoreHistory(redoStack,undoStack);
 $('splitBtn').onclick=splitSelected;$('duplicateBtn').onclick=duplicateSelected;$('deleteBtn').onclick=removeSelected;
 $('snapBtn').onclick=()=>{snap=!snap;$('snapBtn').classList.toggle('active',snap);$('snapBtn').setAttribute('aria-pressed',String(snap));};
 $('timelineFollow').onchange=()=>{timelineScrollManualUntil=0;if(isPlaying)followTimelinePlayhead();};
 $('addVideoTrack').onclick=()=>addTrack('video');$('addAudioTrack').onclick=()=>addTrack('audio');$('addTitle').onclick=addTitle;
 $('timelineZoom').oninput=e=>changeTimelineZoom(Number(e.target.value));
 $('zoomOut').onclick=()=>{$('timelineZoom').value=Math.max(14,zoom-15);$('timelineZoom').oninput({target:$('timelineZoom')});};
 $('zoomIn').onclick=()=>{$('timelineZoom').value=Math.min(190,zoom+15);$('timelineZoom').oninput({target:$('timelineZoom')});};
 const timelineViewport=$('timelineScroller');
 timelineViewport.addEventListener('wheel',event=>{
  timelineScrollManualUntil=performance.now()+4000;
  if(!event.ctrlKey)return;
  event.preventDefault();
  if(event.deltaY)changeTimelineZoom(zoom+(event.deltaY<0?12:-12),
                                     Math.max(151,event.clientX-timelineViewport.getBoundingClientRect().left));
 },{passive:false});
 timelineViewport.addEventListener('pointerdown',()=>{timelineScrollManualUntil=performance.now()+4000;});
 document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{insTab=b.dataset.tab;document.querySelectorAll('[data-tab]').forEach(n=>n.classList.toggle('active',n===b));renderInspector();});
 $('startRender').onclick=()=>void startExport();$('cancelRender').onclick=()=>void request('job/cancel','POST',{job:'export'});
 $('browseExport').onclick=()=>void browseExport().catch(e=>toast(e.message,true));
 $('openExportFolder').onclick=()=>void request('export/open-folder','POST',{}).catch(e=>toast(e.message,true));
 $('reviewPackBtn').onclick=()=>void makeReviewPack();$('reviewVideoBtn').onclick=()=>void makeReviewVideo();$('openChat').onclick=()=>window.open('https://chatgpt.com/','_blank','noopener');
 $('analyzeBtn').onclick=()=>void analyzeAi();$('previewAiBtn').onclick=()=>void previewAi();$('applyAiBtn').onclick=()=>void applyAi();$('undoAiBtn').onclick=()=>void undoAi();
 $('proposalJson').oninput=()=>{proposalToken=null;$('applyAiBtn').disabled=true;};$('transferCancel').onclick=()=>{transferStop=true;toast('Cancel requested');};
 document.addEventListener('keydown',e=>{if(document.querySelector('dialog[open]'))return;if(e.key==='Escape'){$('performanceModal').hidden=$('aiModal').hidden=$('exportModal').hidden=$('helpModal').hidden=true;return;}if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)||!$('aiModal').hidden||!$('exportModal').hidden||!$('helpModal').hidden||!$('performanceModal').hidden)return;
  if(e.ctrlKey&&e.key.toLowerCase()==='s'){e.preventDefault();void flushSave();return;}
  if(e.ctrlKey&&e.key.toLowerCase()==='z'){e.preventDefault();restoreHistory(e.shiftKey?redoStack:undoStack,e.shiftKey?undoStack:redoStack);return;}
  if(e.ctrlKey&&e.key.toLowerCase()==='y'){e.preventDefault();restoreHistory(redoStack,undoStack);return;}
  if(e.ctrlKey&&e.key.toLowerCase()==='d'){e.preventDefault();duplicateSelected();return;}
  if(e.key.toLowerCase()==='s'&&!e.ctrlKey){e.preventDefault();splitSelected();return;}
  if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();if(e.shiftKey)rippleDelete();else removeSelected();return;}
  if(e.code==='Space'){e.preventDefault();playPause();return;}
  if(e.key==='ArrowLeft'){e.preventDefault();seek(playhead-1/sequenceRate());}
  if(e.key==='ArrowRight'){e.preventDefault();seek(playhead+1/sequenceRate());}
 });
 // Browser Files never expose original filesystem paths; chunked local streaming
 // is essential for 4.5+ GB drag-and-drop without whole-file buffering.
 let dragCount=0;
 window.addEventListener('dragenter',e=>{if(e.dataTransfer?.types.includes('Files')){e.preventDefault();dragCount++;$('dropOverlay').hidden=false;}});
 window.addEventListener('dragover',e=>{if(e.dataTransfer?.types.includes('Files')){e.preventDefault();e.dataTransfer.dropEffect='copy';}});
 window.addEventListener('dragleave',e=>{if(e.dataTransfer?.types.includes('Files')){dragCount=Math.max(0,dragCount-1);if(!dragCount)$('dropOverlay').hidden=true;}});
 window.addEventListener('drop',e=>{if(e.dataTransfer?.types.includes('Files')){e.preventDefault();e.stopPropagation();dragCount=0;$('dropOverlay').hidden=true;const lane=e.target.closest('[data-lane]');let id=lane?.dataset?.lane,p=lane?clamp((e.clientX-lane.getBoundingClientRect().left)/zoom,0,1e12):null;if(!state?.desktop)void importDropped(e.dataTransfer.files,id,p);}});
}
(async()=>{setup();try{
 const [project,app]=await Promise.all([request('state'),request('app-info')]);
 document.querySelectorAll('[data-app-version]').forEach(el=>{el.textContent=app.version;});
 state=project;redraw();setupStudio();await setupNative();await recoveryInitialize();
}catch(e){toast('Editor failed to initialize: '+e.message,true);}})();
