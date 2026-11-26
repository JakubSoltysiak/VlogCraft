/* Explicit technical interpretation, separate from existing SDR creative grades. */
function colorOutputFromControls(){
 const mode=$('colorOutput').value;
 if(mode==='legacy')return null;
 const result={version:1,workingSpace:'linear-rec2020-100nits',output:mode,sdrWhiteNits:$('sdrWhiteNits').valueAsNumber};
 if(!Number.isFinite(result.sdrWhiteNits))throw Error('Choose an SDR reference white');
 const gamut=$('masteringGamut').value;
 if(mode==='hdr10' && gamut!=='unknown')result.mastering={primaries:gamut==='p3'?[[.68,.32],[.265,.69],[.15,.06]]:[[.708,.292],[.17,.797],[.131,.046]],whitePoint:[.3127,.329],minLuminance:$('masteringMin').valueAsNumber,maxLuminance:$('masteringMax').valueAsNumber};
 if(mode==='hdr10' && ($('maxCLL').value||$('maxFALL').value)){result.maxCLL=$('maxCLL').valueAsNumber;result.maxFALL=$('maxFALL').valueAsNumber;}
 return result;
}
async function validatedColorFromControls(){
 const color=colorOutputFromControls();
 return color?(await request('color/validate','POST',{color})).color:null;
}
function initColorControls(){
 const c=state.output.color;
 $('colorOutput').value=c?.output||'legacy';$('sdrWhiteNits').value=c?.sdrWhiteNits||100;
 $('masteringGamut').value=c?.mastering?(c.mastering.primaries[0][0]===.68?'p3':'2020'):'unknown';
 $('masteringMin').value=c?.mastering?.minLuminance??.005;$('masteringMax').value=c?.mastering?.maxLuminance??1000;
 $('maxCLL').value=c?.maxCLL??'';$('maxFALL').value=c?.maxFALL??'';
 $('applyColorSetup').onclick=async()=>{
  try{
   const color=await validatedColorFromControls();
   // Validate through the normal save path before showing the chosen setup as accepted.
   const proposed={...state.output,color,encoder:color?.output==='hdr10'?'libx265':state.output.encoder};
   // A failed disk publication retains the unsaved edit, undo and recovery draft,
   // as ordinary timeline edits do; never roll back only the live view.
   snapshot();state.output=proposed;save();await flushSave();
   if(color)$('playbackEngine').value='rendered';
   redraw();syncPreview(true);toast(color?'Managed color applied. Composited monitoring is SDR tone-mapped; native PQ remains opt-in.':'Legacy SDR setup applied.');
  }catch(error){toast(error.message,true);}
 };
 $('colorOutput').onchange=()=>{
  const hdr=$('colorOutput').value==='hdr10';
  if(hdr)$('encoderChoice').value='libx265';
  for(const id of ['masteringGamut','masteringMin','masteringMax','maxCLL','maxFALL']){
   const label=$(id).closest?.('label');if(label)label.hidden=!hdr;
  }
  if($('hdrMetadataNote'))$('hdrMetadataNote').hidden=!hdr;
  const white=$('sdrWhiteNits').closest?.('label');if(white)white.hidden=$('colorOutput').value==='legacy';
  if(typeof updateEncoderControls==='function')updateEncoderControls();
  $('colorDeliveryNote').textContent=$('colorOutput').value==='hdr10'?'Managed PQ uses float32 linear Rec.2020 and 10-bit HEVC output. Render timeline delivers static HDR10. Edited Master authors dynamic metadata at export.':'SDR output. Managed monitoring uses an explicit tone map; legacy projects retain the existing SDR compositor.';
 };
 $('colorOutput').onchange();
}
function inputColorControls(c,a){
 if(c.kind==='image')return '<details class="fx-panel"><summary>Technical input color</summary>'+
 '<label>Interpretation<select id="inputColorProfile"><option value="">Embedded profile</option><option value="srgb">Interpret as sRGB</option></select></label>'+
 '<p class="dialog-note">Managed color reads embedded sRGB and Display P3 profiles. Untagged photographs use sRGB.</p>'+
 (state.output.color?field('Linear exposure (stops)','hdrExposure',c.hdrExposure||0,-8,8,.1):'')+'</details>';
 const m=a?.colorMetadata;
 const index=a?.codec==='hevc' && a.colorTransfer==='smpte2084' && a.colorPrimaries==='bt2020';
 const observed=m?.dynamicHDR10PlusDetected?'HDR10+ sample detected':'';
 return '<details class="fx-panel"><summary>Technical input color</summary><p class="dialog-note">Detected: '+esc([a?.colorPrimaries,a?.colorTransfer,a?.colorRange,m?.bitDepth?m.bitDepth+'-bit':'depth unknown',observed].filter(Boolean).join(' · '))+'</p>'+
 '<label>Interpretation<select id="inputColorProfile"><option value="">Source tags</option><option value="rec709">Rec.709</option><option value="pq2020">Rec.2020 PQ</option></select></label><label>Range<select id="inputColorRange"><option value="auto">Source range</option><option value="limited">Limited</option><option value="full">Full</option></select></label><label>Pixel aspect<select id="inputPixelAspect"><option value="source">Source metadata</option><option value="square">Explicitly interpret as square pixels</option></select></label>'+
 '<p class="dialog-note">Overrides apply to this clip without changing its source. They require managed color in Export → Color setup. HLG and Samsung Log transforms remain unsupported.</p>'+
 (index?'<button type="button" id="indexHdr10Plus" class="button secondary">Scan HDR10+ metadata</button> <button type="button" id="cancelHdr10Plus" class="button secondary" hidden>Cancel scan</button><p id="hdr10PlusStatus" class="dialog-note" role="status"></p>':'')+
 (state.output.color?field('Linear exposure (stops)','hdrExposure',c.hdrExposure||0,-8,8,.1):'')+'</details>';
}
function bindInputColor(){
 const c=sel()?.clip,profileControl=$('inputColorProfile'),rangeControl=$('inputColorRange'),aspectControl=$('inputPixelAspect');
 if(!profileControl||!c)return;
 profileControl.value=c.inputColor?.profile==='source'?'':c.inputColor?.profile||'';
 if(rangeControl)rangeControl.value=c.inputColor?.range||'auto';
 if(aspectControl)aspectControl.value=c.inputColor?.pixelAspect||'source';
 const change=()=>{
  const hit=sel();if(!hit||hit.track.locked||hit.clip.locked)return;
  if(!state.output.color){toast('Apply a managed color setup in Export before overriding input color.',true);renderInspector();return;}
  snapshot();const profile=profileControl.value;
  const range=rangeControl?.value||(profile==='srgb'?'full':'auto'),pixelAspect=aspectControl?.value||'source';
  if(profile||range!=='auto'||pixelAspect!=='source')hit.clip.inputColor={profile:profile||'source',range,pixelAspect};else delete hit.clip.inputColor;
  redraw();save();syncPreview(true);
 };
 profileControl.onchange=change;
 if(rangeControl)rangeControl.onchange=change;
 if(aspectControl)aspectControl.onchange=change;
 const scan=$('indexHdr10Plus');
 if(scan)bindHdr10PlusScan(c.assetId,scan,$('cancelHdr10Plus'),$('hdr10PlusStatus'));
}

function bindHdr10PlusScan(assetId,scan,cancel,label){
 let generation=0;
 async function refresh(action){
  const run=++generation;
  try{
   let result;
   do{
    result=await request('color/index/'+action,'POST',{assetId});
    if(run!==generation || !scan.isConnected)return;
    scan.disabled=result.status==='indexing' || result.status==='ready';
    cancel.hidden=result.status!=='indexing';
    if(result.status==='ready'){
     label.textContent=result.dynamicFrames
      ? result.dynamicFrames.toLocaleString()+' HDR10+ frames among '+result.frames.toLocaleString()+' decoded frames.'
      : 'No supported HDR10+ metadata detected in '+result.frames.toLocaleString()+' frames.';
     if(result.rejectedFrames)label.textContent+=' '+result.rejectedFrames.toLocaleString()+' frames contain unsupported or malformed metadata.';
     if(result.nonconformingDistributionFrames)label.textContent+=' Metadata is preserved for '+result.nonconformingDistributionFrames.toLocaleString()+' frames with nonconforming distribution values. These frames are blocked from metadata reuse.';
    }else if(result.status==='indexing')label.textContent=result.frames
     ? 'Scanning the original video · '+result.frames.toLocaleString()+' frames read'
     : 'Scanning the original video…';
    else label.textContent=result.error || (result.status==='cancelled'?'Scan cancelled.':'');
    if(result.status==='indexing')await new Promise(resolve=>setTimeout(resolve,600));
    action='status';
   }while(result.status==='indexing' && run===generation && scan.isConnected);
  }catch(error){
   if(run===generation && scan.isConnected){scan.disabled=false;cancel.hidden=true;label.textContent=error.message;}
  }
 }
 scan.onclick=()=>void refresh('start');
 cancel.onclick=()=>void refresh('cancel');
 void refresh('status');
}
