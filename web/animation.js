let animationProperty = 'x';
let copiedCurve = null;
const parameterLimits = {x:[-2,2], y:[-2,2], volume:[0,3],scale:[.1,3],opacity:[0,1],rotation:[-360,360],maskRadius:[.01,1],brightness:[-1,1],contrast:[0,2],saturation:[0,3]};
const motionPresets = {
  'fade-in':'Fade in','fade-out':'Fade out','fade-both':'Fade in and out',
  'zoom-in':'Smooth zoom in','zoom-out':'Smooth zoom out','pan':'Pan',
  'ken-burns':'Ken Burns','slide-in':'Slide in','slide-out':'Slide out',
};
const smoothHandles = [.42,0,.58,1];
function sourceClock(clip) {
  return clip.start + (playhead - clip.position) * clip.speed;
}
function curveValue(keys, fallback, at) {
  if (!keys?.length) return fallback;
  if (at <= keys[0].time) return keys[0].value;
  let low = 0, high = keys.length;
  while (low + 1 < high) {
    const mid = (low + high) >> 1;
    if (keys[mid].time <= at) low = mid; else high = mid;
  }
  const a = keys[low], b = keys[low + 1];
  if (!b) return a.value;
  let u = (at - a.time) / (b.time - a.time);
  if (a.mode === 'hold') u = 0;
  if (a.mode === 'ease-in') u *= u;
  if (a.mode === 'ease-out') u *= 2-u;
  if (a.mode === 'bezier') {
    const [x1,y1,x2,y2] = a.handles || [.25,.1,.25,1];
    const cubic = (t,p,q) => 3*(1-t)**2*t*p + 3*(1-t)*t*t*q + t**3;
    let l=0, r=1;
    for (let i=0; i<22; i++) {
      const t=(l+r)/2;
      if (cubic(t,x1,x2)<u) l=t; else r=t;
    }
    u=cubic((l+r)/2,y1,y2);
  }
  return a.value + (b.value-a.value)*u;
}
function animated(c, prop) {
  const def={x:0,y:0,scale:1,opacity:1,rotation:0,maskRadius:.5,brightness:0,contrast:1,saturation:1,volume:1};
  return curveValue(c.keys?.[prop], c[prop]??def[prop], sourceClock(c));
}
function animationControls(c) {
  const properties=c.kind==='audio'?['volume']:c.kind==='title'?['x','y','opacity']:
    ['x','y','scale','rotation','opacity','brightness','contrast','saturation',...(c.mask==='ellipse'?['maskRadius']:[]),...(assetById(c.assetId)?.hasAudio?['volume']:[])];
  if (!properties.includes(animationProperty)) animationProperty=properties[0];
  const keys = c.keys?.[animationProperty] || [];
  const key = keys.find(k=>Math.abs(k.time-sourceClock(c))<.00001);
  const labels={x:'Horizontal position',y:'Vertical position',volume:'Audio gain',scale:'Scale',rotation:'Rotation (degrees)',opacity:'Opacity',maskRadius:'Mask radius',brightness:'Brightness',contrast:'Contrast',saturation:'Saturation'};
  const [lo,hi]=parameterLimits[animationProperty];
  return `<details id="animationPanel" ${sessionStorage.curvesOpen==='yes'?'open':''}><summary>Keyframe animation</summary>
    <div class="property"><label>Parameter</label><select id="curveProperty">${properties.map(p=>`<option value="${p}" ${p===animationProperty?'selected':''}>${labels[p]}</option>`).join('')}</select></div>
    <p class="dialog-note">${keys.length<2?'Add two keys with different values to create motion.':keys.length+' keyframes · source time in seconds'}</p>
    <div class="property"><label for="curveKeyList">Keyframe</label><select id="curveKeyList"><option value="">New key</option>${keys.map((item,index)=>`<option value="${index}" ${item===key?'selected':''}>${item.time.toFixed(4)} s · ${round(item.value)}</option>`).join('')}</select></div>
    <canvas id="curvePlot" width="384" height="96" title="Click to seek along the clip"></canvas>
    <div class="property"><label for="curveTime">Source time (s)</label><input id="curveTime" type="number" min="${c.start}" max="${c.end}" step="any" value="${Math.max(c.start,Math.min(c.end,sourceClock(c))).toFixed(8)}"></div>
    <div class="prop-row"><div class="property"><label>Value</label><input id="curveValue" type="number" min="${lo}" max="${hi}" step=".01" value="${key?.value??round(animated(c,animationProperty))}"></div>
    <div class="property"><label>Interpolation</label><select id="curveMode">${['linear','hold','ease-in','ease-out','bezier'].map(v=>`<option ${v===key?.mode?'selected':''}>${v}</option>`).join('')}</select></div></div>
    <div class="property" id="curveHandlesRow" ${key?.mode==='bezier'?'':'hidden'}><label>Bézier handles (x1, y1, x2, y2)</label><input id="curveHandles" value="${(key?.handles||[.25,.1,.25,1]).join(', ')}"></div>
    <div class="property-actions"><button class="text-button" id="keySet">${key?'Update key':'Add key'}</button><button class="text-button" id="keyRemove">Remove key</button>
    <button class="text-button" id="curveCopy">Copy curve</button><button class="text-button" id="curvePaste">Paste</button></div></details>`;
}
function bindAnimation() {
  const panel=$('animationPanel');
  if(!panel)return;
  panel.ontoggle=()=>{sessionStorage.curvesOpen=panel.open?'yes':'no';};
  const {clip:c,track}=sel();
  const prop=animationProperty, keys=c.keys?.[prop]||[];
  const plot=$('curvePlot'),ctx=plot.getContext('2d'),w=plot.width,h=plot.height;
  const [lo,hi]=parameterLimits[prop];
  const y=v=>h-5-(v-lo)/(hi-lo)*(h-10);
  ctx.fillStyle='#0b131b';ctx.fillRect(0,0,w,h);
  ctx.lineWidth=2;ctx.strokeStyle='#82cdbd';ctx.beginPath();
  for(let i=0;i<w;i++){const v=curveValue(keys,animated(c,prop),c.start+(c.end-c.start)*i/(w-1));if(i===0)ctx.moveTo(i,y(v));else ctx.lineTo(i,y(v));}
  ctx.stroke();ctx.fillStyle='#f4bb80';
  for(const k of keys){ctx.fillRect((k.time-c.start)/(c.end-c.start)*(w-1)-3,y(k.value)-3,6,6);}
  plot.onclick=e=>{
    const rect=plot.getBoundingClientRect();
    let at=c.start+(e.clientX-rect.left)/rect.width*(c.end-c.start);
    const nearest=keys.reduce((best,k)=>Math.abs(k.time-at)<Math.abs(best-at)?k.time:best,Infinity);
    if(Math.abs(nearest-at)/(c.end-c.start)*rect.width<7)at=nearest;
    seek(c.position+(at-c.start)/c.speed);renderInspector();
  };
  $('curveProperty').onchange=e=>{animationProperty=e.target.value;renderInspector();};
  $('curveKeyList').onchange=e=>{
    const chosen=e.target.value===''?null:keys[Number(e.target.value)];
    if(!chosen){$('keySet').textContent='Add key';return;}
    seek(c.position+(chosen.time-c.start)/c.speed);
    $('curveTime').value=chosen.time;
    $('curveValue').value=chosen.value;
    $('curveMode').value=chosen.mode;
    $('curveHandles').value=(chosen.handles||smoothHandles).join(', ');
    $('curveHandlesRow').hidden=chosen.mode!=='bezier';
    $('keySet').textContent='Update key';
  };
  $('curveMode').onchange=e=>{$('curveHandlesRow').hidden=e.target.value!=='bezier';};
  const replace=next=>{
    if(track.locked||c.locked)return toast('Unlock the track to edit keyframes',true);
    snapshot();c.keys={...c.keys,[prop]:next};renderInspector();syncPreview(true);save();
  };
  $('keySet').onclick=()=>{
    const time=$('curveTime').valueAsNumber,value=$('curveValue').valueAsNumber,mode=$('curveMode').value;
    if(time<c.start-1e-8||time>c.end+1e-8)return toast('Place the playhead inside the selected clip',true);
    if(!Number.isFinite(value)||value<lo||value>hi)return toast('Enter a value from '+lo+' to '+hi,true);
    const key={time:Math.max(0,time),value,mode};
    if(mode==='bezier'){
      const handles=$('curveHandles').value.split(',').map(s=>s.trim()===''?NaN:Number(s));
      if(handles.length!==4||handles.some(v=>!Number.isFinite(v)||v<0||v>1))return toast('Enter four handle coordinates between 0 and 1',true);
      key.handles=handles;
    }
    const chosen=$('curveKeyList').value;
    const selected=chosen===''?null:keys[Number(chosen)];
    if(keys.some(k=>k!==selected&&Math.abs(k.time-time)<=.00001)){
      return toast('A key already exists there. Select it to edit its value.',true);
    }
    replace([...keys.filter(k=>k!==selected&&Math.abs(k.time-time)>.00001),key].sort((a,b)=>a.time-b.time));
    seek(c.position+(key.time-c.start)/c.speed);
    renderInspector();
  };
  $('keyRemove').onclick=()=>{
    const chosen=$('curveKeyList').value;
    if(chosen==='')return toast('Choose a keyframe to remove',true);
    replace(keys.filter((_,index)=>index!==Number(chosen)));
  };
  $('curveCopy').onclick=()=>{copiedCurve={prop,start:c.start,keys:structuredClone(keys)};toast('Curve copied');};
  $('curvePaste').onclick=()=>{
    if(copiedCurve?.prop!==prop)return toast('Copy a curve for this parameter first',true);
    replace(copiedCurve.keys.map(({preset,...k})=>({...k,time:k.time-copiedCurve.start+c.start})).filter(k=>k.time>=0));
  };
}

function withoutGeneratedMotion(curves={}){
  return Object.fromEntries(Object.entries(curves).map(([property,keys])=>
    [property,keys.filter(key=>key.preset!==true)]).filter(([,keys])=>keys.length));
}

function motionKeys(clip,settings,fps,managed){
  const name=settings.preset;
  if(!motionPresets[name] || !['image','video'].includes(clip.kind) || clip.locked)return null;
  const fade=name.startsWith('fade-');
  if(managed && (!fade || clip.kind!=='video'))return null;
  const speed=clip.speed||1;
  const endFrame=Math.round((clip.position+(clip.end-clip.start)/speed)*fps);
  const span=endFrame-Math.round(clip.position*fps)-1;
  if(span<1)return null;
  const ticks=Math.min(span,Math.max(1,Math.round(settings.duration*fps)));
  const manual=withoutGeneratedMotion(clip.keys);
  const generated={};
  const apply=(property,points)=>{
    generated[property]=points.map(([frame,value])=>({
      time:clip.start+frame*speed/fps,value,preset:true,
      mode:settings.easing==='smooth'?'bezier':'linear',
      ...(settings.easing==='smooth'?{handles:[...smoothHandles]}:{}),
    }));
  };
  if(fade){
    const opacity=clip.opacity??1;
    if(name==='fade-in')apply('opacity',[[0,0],[ticks,opacity]]);
    if(name==='fade-out')apply('opacity',[[span-ticks,opacity],[span,0]]);
    if(name==='fade-both'){
      if(span<2)return null;
      const edge=Math.min(ticks,Math.floor(span/2));
      apply('opacity',[[0,0],[edge,opacity],...(span-edge>edge?[[span-edge,opacity]]:[]),[span,0]]);
    }
  }else{
    const scale=clip.scale??1;
    const zoom=Math.min(3,scale*1.12);
    const property=['up','down'].includes(settings.direction)?'y':'x';
    const sign=['left','up'].includes(settings.direction)?-1:1;
    const center=clip[property]??0;
    const offset=amount=>Math.max(-2,Math.min(2,center+amount*sign));
    if(name==='zoom-in'||name==='ken-burns')apply('scale',[[0,scale],[ticks,zoom]]);
    if(name==='zoom-out')apply('scale',[[0,zoom],[ticks,scale]]);
    if(name==='ken-burns'||name==='pan')apply(property,[[0,center],[ticks,offset(.06)]]);
    if(name==='slide-in')apply(property,[[0,offset(1.2)],[ticks,center]]);
    if(name==='slide-out')apply(property,[[span-ticks,center],[span,offset(1.2)]]);
  }
  if(Object.keys(generated).some(property=>manual[property]?.length))return null;
  return {...manual,...generated};
}

function applyDefaultMotion(clip){
  const settings=state.output.defaultMotion;
  if(!settings)return;
  const keys=motionKeys(clip,settings,sequenceRate(),!!state.output.color);
  if(keys)clip.keys=keys;
}

function motionPresetDialog(){
  const dialog=document.createElement('dialog');
  dialog.className='motion-dialog';
  dialog.innerHTML=`<form>
    <h2>Motion presets</h2>
    <div class="property"><label for="motionScope">Apply to</label><select id="motionScope">
      <option value="selection">Selected clips</option><option value="track">Selected track</option>
      <option value="project">Whole project</option><option value="default">Newly placed clips</option>
    </select></div>
    <div class="property"><label for="motionPreset">Preset</label><select id="motionPreset">
      ${Object.entries(motionPresets).map(([id,label])=>`<option value="${id}">${label}</option>`).join('')}
      <option value="clear">Remove applied presets</option>
    </select></div>
    <div class="prop-row"><div class="property"><label for="motionDuration">Duration (s)</label><input id="motionDuration" type="number" min=".05" max="30" step="any" value="1" required></div>
    <div class="property"><label for="motionEase">Easing</label><select id="motionEase"><option value="smooth">Smooth</option><option value="linear">Linear</option></select></div></div>
    <div class="property"><label for="motionDirection">Direction</label><select id="motionDirection">
      <option value="left">Left</option><option value="right">Right</option><option value="up">Up</option><option value="down">Down</option>
    </select></div>
    <p class="dialog-note">Presets generate editable keys. Locked clips and properties with manual keys are skipped. Managed HDR supports opacity fades on video.</p>
    <div class="property-actions"><button type="button" class="button secondary">Cancel</button><button class="button primary">Apply</button></div>
  </form>`;
  document.body.appendChild(dialog);
  const scope=$('motionScope');
  if(!sel())scope.value='project';
  const previous=state.output.defaultMotion;
  if(previous){
    $('motionPreset').value=previous.preset;
    $('motionDuration').value=previous.duration;
    $('motionDirection').value=previous.direction;
    $('motionEase').value=previous.easing;
  }
  dialog.querySelector('[type=button]').onclick=()=>dialog.close();
  dialog.querySelector('form').onsubmit=event=>{
    event.preventDefault();
    const settings={preset:$('motionPreset').value,duration:$('motionDuration').valueAsNumber,
                    direction:$('motionDirection').value,easing:$('motionEase').value};
    if(scope.value==='default'){
      snapshot();
      if(settings.preset==='clear')delete state.output.defaultMotion;
      else state.output.defaultMotion=settings;
      save();dialog.close();toast('Default motion updated');return;
    }
    const ids=new Set(editingIds());
    const selectedTrack=sel()?.track;
    const updates=[];
    let skipped=0;
    for(const track of state.tracks){
      if(scope.value==='track'&&track!==selectedTrack)continue;
      for(const clip of track.clips){
        if(scope.value==='selection'&&!ids.has(clip.id))continue;
        if(track.locked||clip.locked){skipped++;continue;}
        const keys=settings.preset==='clear'?withoutGeneratedMotion(clip.keys):
          motionKeys(clip,settings,sequenceRate(),!!state.output.color);
        if(keys&&JSON.stringify(keys)!==JSON.stringify(clip.keys||{}))updates.push([clip,keys]);
        else if(keys===null)skipped++;
      }
    }
    if(!updates.length){toast('No eligible clips changed'+(skipped?' · '+skipped+' skipped':''),true);return;}
    snapshot();
    for(const [clip,keys] of updates)clip.keys=keys;
    redraw();save();dialog.close();
    toast('Updated '+updates.length+' clip(s)'+(skipped?' · '+skipped+' skipped':''));
  };
  dialog.onclose=()=>dialog.remove();
  dialog.showModal();
}
