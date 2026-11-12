let animationProperty = 'x';
let copiedCurve = null;
const parameterLimits = {x:[-2,2], y:[-2,2], volume:[0,3]};
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
  return curveValue(c.keys?.[prop], c[prop], sourceClock(c));
}
function animationControls(c) {
  const properties = c.kind === 'audio' ? ['volume'] : assetById(c.assetId)?.hasAudio ? ['x','y','volume'] : ['x','y'];
  if (!properties.includes(animationProperty)) animationProperty=properties[0];
  const keys = c.keys?.[animationProperty] || [];
  const key = keys.find(k=>Math.abs(k.time-sourceClock(c))<.00001);
  const labels={x:'Horizontal position',y:'Vertical position',volume:'Audio gain'};
  const [lo,hi]=parameterLimits[animationProperty];
  return `<details id="animationPanel" ${sessionStorage.curvesOpen==='yes'?'open':''}><summary>Keyframe animation</summary>
    <div class="property"><label>Parameter</label><select id="curveProperty">${properties.map(p=>`<option value="${p}" ${p===animationProperty?'selected':''}>${labels[p]}</option>`).join('')}</select></div>
    <canvas id="curvePlot" width="384" height="96" title="Click to seek along the clip"></canvas>
    <div class="prop-row"><div class="property"><label>Value</label><input id="curveValue" type="number" min="${lo}" max="${hi}" step=".01" value="${round(animated(c,animationProperty))}"></div>
    <div class="property"><label>Interpolation</label><select id="curveMode">${['linear','hold','ease-in','ease-out','bezier'].map(v=>`<option ${v===key?.mode?'selected':''}>${v}</option>`).join('')}</select></div></div>
    <div class="property" id="curveHandlesRow" ${key?.mode==='bezier'?'':'hidden'}><label>Bézier handles (x1, y1, x2, y2)</label><input id="curveHandles" value="${(key?.handles||[.25,.1,.25,1]).join(', ')}"></div>
    <div class="property-actions"><button class="text-button" id="keySet">Set key</button><button class="text-button" id="keyRemove">Remove key</button>
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
  for(let i=0;i<w;i++){const v=curveValue(keys,c[prop],c.start+(c.end-c.start)*i/(w-1));if(i===0)ctx.moveTo(i,y(v));else ctx.lineTo(i,y(v));}
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
  $('curveMode').onchange=e=>{$('curveHandlesRow').hidden=e.target.value!=='bezier';};
  const replace=next=>{
    if(track.locked||c.locked)return toast('Unlock the track to edit keyframes',true);
    snapshot();c.keys={...c.keys,[prop]:next};renderInspector();syncPreview(true);save();
  };
  $('keySet').onclick=()=>{
    const time=sourceClock(c),value=$('curveValue').valueAsNumber,mode=$('curveMode').value;
    if(time<c.start-1e-8||time>c.end+1e-8)return toast('Place the playhead inside the selected clip',true);
    if(!Number.isFinite(value)||value<lo||value>hi)return toast('Enter a value from '+lo+' to '+hi,true);
    const key={time:Math.max(0,time),value,mode};
    if(mode==='bezier'){
      const handles=$('curveHandles').value.split(',').map(s=>s.trim()===''?NaN:Number(s));
      if(handles.length!==4||handles.some(v=>!Number.isFinite(v)||v<0||v>1))return toast('Enter four handle coordinates between 0 and 1',true);
      key.handles=handles;
    }
    replace([...keys.filter(k=>Math.abs(k.time-time)>.00001),key].sort((a,b)=>a.time-b.time));
  };
  $('keyRemove').onclick=()=>replace(keys.filter(k=>Math.abs(k.time-sourceClock(c))>.00001));
  $('curveCopy').onclick=()=>{copiedCurve={prop,start:c.start,keys:structuredClone(keys)};toast('Curve copied');};
  $('curvePaste').onclick=()=>{
    if(copiedCurve?.prop!==prop)return toast('Copy a curve for this parameter first',true);
    replace(copiedCurve.keys.map(k=>({...k,time:k.time-copiedCurve.start+c.start})).filter(k=>k.time>=0));
  };
}
