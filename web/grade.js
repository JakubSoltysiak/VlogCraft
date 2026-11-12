const gradeCache=new Map();
function gradeTable(c){
  if(!c.lutId&&!Object.keys(c.look||{}).length)return null;
  const key=JSON.stringify([c.lutId||null,c.look||{}]);
  if(!gradeCache.has(key)){
    if(gradeCache.size>8)gradeCache.delete(gradeCache.keys().next().value);
    gradeCache.set(key,null);
    fetch('/api/grade/table',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lutId:c.lutId,look:c.look||{}})})
      .then(async r=>{if(!r.ok)throw Error('Could not load color transform');
        gradeCache.set(key,{key,n:Number(r.headers.get('X-Grid-Size')),data:new Uint8Array(await r.arrayBuffer())});
        syncPreview(true);
      }).catch(e=>toast(e.message,true));
  }
  return gradeCache.get(key);
}
function sampleLookup(data,i,table){
  const {n,data:lut}=table;
  const r=data[i]*(n-1)/255,g=data[i+1]*(n-1)/255,b=data[i+2]*(n-1)/255;
  const x=Math.min(n-2,Math.floor(r)),y=Math.min(n-2,Math.floor(g)),z=Math.min(n-2,Math.floor(b));
  const tx=r-x,ty=g-y,tz=b-z,base=3*(x+n*(y+n*z));
  for(let c=0;c<3;c++){
    const k=base+c,s=3*n,v=3*n*n;
    const lo=((1-tx)*lut[k]+tx*lut[k+3])*(1-ty)+((1-tx)*lut[k+s]+tx*lut[k+s+3])*ty;
    const hi=((1-tx)*lut[k+v]+tx*lut[k+v+3])*(1-ty)+((1-tx)*lut[k+v+s]+tx*lut[k+v+s+3])*ty;
    data[i+c]=lo*(1-tz)+hi*tz;
  }
}
function gradeDialog(){
  const {clip:c,track}=sel();if(track.locked||c.locked)return toast('Unlock the clip to grade it',true);
  const dlg=document.createElement('dialog');dlg.className='motion-dialog grading-dialog';
  const working=structuredClone(c.look||{});let lutId=c.lutId||null;
  dlg.innerHTML='<h2>Color grade</h2><div class="grade-grid"><section><label>RGB curve <select class="compact-select" id="curveChannel"><option>master</option><option>red</option><option>green</option><option>blue</option></select></label><canvas id="rgbCurve" width="260" height="160" title="Drag a control point to adjust its output"></canvas></section><section><label>Color balance</label><div class="wheels"></div></section></div><div class="property"><label>3D LUT</label><select id="gradeLut"></select><input type="file" id="importLut" accept=".cube" aria-label="Import SDR cube LUT"></div><div class="property-actions"><button class="button secondary" id="gradeCancel">Cancel</button><button class="button secondary" id="gradeReset">Reset grade</button><button class="button primary" id="gradeApply">Apply grade</button></div>';
  document.body.appendChild(dlg);
  const curve=$('rgbCurve'),ctx=curve.getContext('2d'),channels=$('curveChannel'),axis=[0,.25,.5,.75,1];
  const gradient={master:'#e8edef',red:'#ed8e8f',green:'#91d0ac',blue:'#91b9ed'};
  function draw(){
    const values=working[channels.value]||axis;
    ctx.fillStyle='#101820';ctx.fillRect(0,0,260,160);ctx.lineWidth=1;ctx.strokeStyle='#344452';
    for(let i=0;i<5;i++){ctx.beginPath();ctx.moveTo(6+i*62,5);ctx.lineTo(6+i*62,155);ctx.moveTo(6,5+i*37.5);ctx.lineTo(254,5+i*37.5);ctx.stroke();}
    ctx.strokeStyle=gradient[channels.value];ctx.beginPath();values.forEach((v,i)=>{const x=6+i*62,y=155-v*150;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
    ctx.fillStyle=ctx.strokeStyle;values.forEach((v,i)=>{ctx.beginPath();ctx.arc(6+62*i,155-v*150,4,0,2*Math.PI);ctx.fill();});
  }
  channels.onchange=draw;
  curve.onpointerdown=e=>{curve.setPointerCapture(e.pointerId);const rect=curve.getBoundingClientRect();const i=clamp(Math.round(((e.clientX-rect.left)/rect.width*260-6)/62),0,4);
    const change=ev=>{const values=working[channels.value]||axis.slice();values[i]=clamp((155-160*(ev.clientY-rect.top)/rect.height)/150,0,1);working[channels.value]=values;draw();};change(e);curve.onpointermove=change;
    curve.onpointerup=curve.onpointercancel=()=>curve.onpointermove=null;};
  function wheels(){
    const host=dlg.querySelector('.wheels');host.replaceChildren();
    for(const band of ['shadows','midtones','highlights']){
      const label=document.createElement('label');label.textContent=band;const disc=document.createElement('div'),dot=document.createElement('i');
      disc.className='color-wheel';disc.title='Drag to shift '+band+' color';disc.append(dot);label.append(disc);host.append(label);
      const paint=()=>{const [x,y]=working[band]||[0,0];dot.style.left=(50+48*x)+'%';dot.style.top=(50+48*y)+'%';};paint();
      disc.onpointerdown=e=>{disc.setPointerCapture(e.pointerId);const rect=disc.getBoundingClientRect();
        const update=ev=>{let x=2*(ev.clientX-rect.left)/rect.width-1,y=2*(ev.clientY-rect.top)/rect.height-1,r=Math.max(1,Math.hypot(x,y));working[band]=[x/r,y/r];paint();};update(e);disc.onpointermove=update;disc.onpointerup=disc.onpointercancel=()=>disc.onpointermove=null;};
    }
  }
  function choices(){const menu=$('gradeLut');menu.replaceChildren(new Option('None',''),...Object.entries(state.luts||{}).map(([k,v])=>new Option(v.name,k)));menu.value=lutId||'';}
  $('gradeLut').onchange=e=>{lutId=e.target.value||null;};
  $('importLut').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{
    const r=await request('lut/import','POST',{name:file.name,text:await file.text()});state.luts??={};state.luts[r.id]={name:r.name,size:r.size};lutId=r.id;if(dlg.open)choices();
  }catch(err){toast(err.message,true);}};
  $('gradeCancel').onclick=()=>dlg.close();$('gradeReset').onclick=()=>{for(const k of Object.keys(working))delete working[k];lutId=null;choices();wheels();draw();};
  $('gradeApply').onclick=()=>{snapshot();c.look=working;c.lutId=lutId;redraw();save();dlg.close();};
  dlg.onclose=()=>dlg.remove();choices();wheels();draw();dlg.showModal();
}
function drawScopes(image){
  const canvas=$('scopeCanvas');if(canvas.hidden)return;
  const ctx=canvas.getContext('2d'),scratch=document.createElement('canvas');
  scratch.width=192;scratch.height=108;const sampler=scratch.getContext('2d',{willReadFrequently:true});
  sampler.drawImage(image,0,0,192,108);const data=sampler.getImageData(0,0,192,108).data;
  const w=canvas.width,h=canvas.height,mode=$('scopeChoice').value;
  ctx.fillStyle='#101820';ctx.fillRect(0,0,w,h);const hist=new Uint32Array(256);
  ctx.fillStyle='#88cfad55';
  for(let p=0;p<data.length;p+=4){const r=data[p],g=data[p+1],b=data[p+2],y=.2126*r+.7152*g+.0722*b;hist[Math.round(y)]++;
    if(mode==='waveform')ctx.fillRect((p/4%192)/192*w,h-1-y/255*(h-1),1,1);
    else if(mode==='vectorscope')ctx.fillRect(w/2+(b-y)*.5389/255*h,h/2-(r-y)*.635/255*h,1,1);
  }
  if(mode==='histogram'){const max=Math.max(...hist);ctx.fillStyle='#8ad5b6';hist.forEach((v,i)=>ctx.fillRect(i*w/256,h-h*v/max,w/256,h*v/max));}
  ctx.strokeStyle='#8196a755';ctx.beginPath();
  if(mode==='vectorscope'){ctx.moveTo(w/2,0);ctx.lineTo(w/2,h);ctx.moveTo(w/2-h/2,h/2);ctx.lineTo(w/2+h/2,h/2);}
  else{for(const k of [.25,.5,.75]){ctx.moveTo(0,h*k);ctx.lineTo(w,h*k);}}ctx.stroke();
}
