function openMotion() {
  const {clip,track}=sel();
  if (track.locked||clip.locked) return toast('Unlock the video track before editing motion',true);
  const asset=assetById(clip.assetId);
  const targets=state.tracks.filter(t=>t.type==='video'&&!t.locked).flatMap(t=>t.clips)
    .filter(c=>c.id!==clip.id && !c.locked && c.position<endOf(clip) && endOf(c)>clip.position);
  const dialog=document.createElement('dialog');
  dialog.className='motion-dialog';
  dialog.innerHTML=`<h2>Motion analysis</h2><div class="property"><label>Operation</label><select id="motionMode"><option value="stabilize">Stabilize camera translation</option><option value="track">Track a detail onto another layer</option></select></div>
    <div id="motionFrame"><img alt="First source frame"><i hidden></i></div>
    <div class="property" id="motionStrength"><label>Smoothing strength</label><input type="range" min="0" max="1" step=".05" value=".8"></div>
    <div class="property" id="motionTarget" hidden><label>Attach movement to</label><select>${targets.map(c=>`<option value="${c.id}">${esc(c.text||assetById(c.assetId)?.name||'Layer')} · ${timecode(c.position)}</option>`).join('')}</select></div>
    <p id="motionInfo" role="status"></p><div class="property-actions"><button class="button secondary" id="motionClose">Close</button><button class="button primary" id="motionRun">Analyze</button><button class="button primary" id="motionApply" hidden>Apply keyframes</button></div>`;
  document.body.appendChild(dialog);
  const mode=$('motionMode'), image=dialog.querySelector('img'), cross=dialog.querySelector('i');
  let point=null, result=null, busy=false;
  image.src='/api/motion/frame?clip='+encodeURIComponent(clip.id)+'&v='+encodeURIComponent(clip.start);
  function reset(){
    result=null;$('motionApply').hidden=true;
    $('motionStrength').hidden=mode.value!=='stabilize';$('motionTarget').hidden=mode.value!=='track';
    $('motionInfo').textContent=mode.value==='stabilize'?'Estimate camera movement, smooth it and zoom to compensate for shifted edges.':
      targets.length?'Click a high-contrast detail in the first source frame.':'Add an overlapping title or image on another video track first.';
    $('motionRun').disabled=mode.value==='track'&&(!point||!targets.length);
  }
  mode.onchange=reset;dialog.querySelector('input').oninput=reset;
  image.onclick=e=>{
    if(busy||mode.value!=='track')return;
    const r=image.getBoundingClientRect();point=[(e.clientX-r.left)/r.width,(e.clientY-r.top)/r.height];
    cross.hidden=false;cross.style.left=point[0]*100+'%';cross.style.top=point[1]*100+'%';reset();
  };
  $('motionClose').onclick=async()=>{
    if(busy){await request('job/cancel','POST',{job:'motion'});return;}
    dialog.close();
  };
  dialog.oncancel=e=>{if(busy){e.preventDefault();$('motionClose').click();}};
  dialog.onclose=()=>dialog.remove();
  $('motionRun').onclick=async()=>{
    busy=true;mode.disabled=true;dialog.querySelector('input').disabled=true;
    $('motionRun').disabled=true;$('motionApply').hidden=true;$('motionClose').textContent='Cancel analysis';
    $('motionInfo').textContent='Reading source frames…';
    try{
      await flushSave();
      result=await request('motion','POST',{clipId:clip.id,mode:mode.value,point,strength:Number(dialog.querySelector('input').value)});
      $('motionInfo').textContent=result.samples+' frames analyzed · '+result.points.length+' motion samples retained';
      $('motionApply').hidden=false;
    }catch(error){$('motionInfo').textContent=error.message;}
    finally{busy=false;mode.disabled=false;dialog.querySelector('input').disabled=false;$('motionRun').disabled=false;$('motionClose').textContent='Close';}
  };
  $('motionApply').onclick=()=>{
    if(!result)return;
    const stabilizing=mode.value==='stabilize';
    const target=stabilizing?clip:targets.find(c=>c.id===$('motionTarget').querySelector('select').value);
    if(!target)return;
    const aspect=asset.width/asset.height, canvas=state.output.width/state.output.height;
    const fit=clip.fit==='cover'?Math.max:Math.min;
    const extent=[fit(1,aspect/canvas)*clip.scale,fit(1,canvas/aspect)*clip.scale];
    let zoom=1;
    if(stabilizing){
      for(const p of result.points)zoom=Math.max(zoom,1+2*Math.abs(p[1]),1+2*Math.abs(p[2]));
      zoom=Math.min(zoom,3/clip.scale);
    }
    const keys={...target.keys};
    for(const [index,prop] of ['x','y'].entries()){
      const clock=t=>target.start+((clip.position+(t-clip.start)/clip.speed)-target.position)*target.speed;
      const raw=result.points.map(p=>({time:clock(p[0]),value:clamp(target[prop]+p[index+1]*extent[index]*zoom,-2,2),mode:'linear'}));
      const begin=Math.max(target.start,clock(clip.start)),end=Math.min(target.end,clock(clip.end));
      const inside=raw.filter(k=>k.time>begin+1e-7 && k.time<end-1e-7);
      keys[prop]=[{time:begin,value:curveValue(raw,target[prop],begin),mode:'linear'},...inside,
        {time:end,value:curveValue(raw,target[prop],end),mode:'linear'}];
    }
    snapshot();target.keys=keys;if(stabilizing)target.scale*=zoom;
    selectedId=target.id;seek(Math.max(clip.position,target.position));redraw();save();dialog.close();
    toast('Motion applied. Adjust the position keys in the inspector or undo the edit.');
  };
  reset();dialog.showModal();
}
