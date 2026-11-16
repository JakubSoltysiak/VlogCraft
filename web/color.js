/* Explicit technical interpretation, separate from existing SDR creative grades. */
function colorOutputFromControls(){
 const mode=$('colorOutput').value;
 if(mode==='legacy')return null;
 const result={version:1,workingSpace:'linear-rec2020-100nits',output:mode,sdrWhiteNits:$('sdrWhiteNits').valueAsNumber};
 if(!Number.isFinite(result.sdrWhiteNits))throw Error('Choose an SDR reference white');
 const gamut=$('masteringGamut').value;
 if(gamut!=='unknown')result.mastering={primaries:gamut==='p3'?[[.68,.32],[.265,.69],[.15,.06]]:[[.708,.292],[.17,.797],[.131,.046]],whitePoint:[.3127,.329],minLuminance:$('masteringMin').valueAsNumber,maxLuminance:$('masteringMax').valueAsNumber};
 if($('maxCLL').value||$('maxFALL').value){result.maxCLL=$('maxCLL').valueAsNumber;result.maxFALL=$('maxFALL').valueAsNumber;}
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
  if($('colorOutput').value==='hdr10')$('encoderChoice').value='libx265';
  $('colorDeliveryNote').textContent=$('colorOutput').value==='hdr10'?'HDR10: float32 linear Rec.2020 → 10-bit HEVC PQ. Supported: matching-aspect video, trims/speed, full-frame resize, opacity/fades, linear exposure and nested tracks. Other effects/transforms fail explicitly. HDR10+ is not authored.':'SDR output. Managed monitoring uses an explicit tone map; legacy projects retain the existing SDR compositor.';
 };
 $('colorOutput').onchange();
}
function inputColorControls(c,a){
 const m=a?.colorMetadata;return '<details class="fx-panel"><summary>Technical input color</summary><p class="dialog-note">Detected: '+esc([a?.colorPrimaries,a?.colorTransfer,a?.colorRange,m?.bitDepth?m.bitDepth+'-bit':'depth unknown'].filter(Boolean).join(' · '))+'</p>'+
 '<label>Interpretation<select id="inputColorProfile"><option value="">Source tags</option><option value="rec709">Rec.709</option><option value="pq2020">Rec.2020 PQ</option></select></label><label>Range<select id="inputColorRange"><option value="auto">Source range</option><option value="limited">Limited</option><option value="full">Full</option></select></label><label>Pixel aspect<select id="inputPixelAspect"><option value="source">Source metadata</option><option value="square">Explicitly interpret as square pixels</option></select></label>'+
 '<p class="dialog-note">Overrides apply to this clip without changing its source. They require managed color in Export → Color setup. HLG and Samsung Log transforms remain unsupported.</p>'+
 (state.output.color?field('Linear exposure (stops)','hdrExposure',c.hdrExposure||0,-8,8,.1):'')+'</details>';
}
function bindInputColor(){
 const c=sel()?.clip;if(!$('inputColorProfile')||!c)return;
 $('inputColorProfile').value=c.inputColor?.profile==='source'?'':c.inputColor?.profile||'';$('inputColorRange').value=c.inputColor?.range||'auto';$('inputPixelAspect').value=c.inputColor?.pixelAspect||'source';
 const change=()=>{
  const hit=sel();if(!hit||hit.track.locked||hit.clip.locked)return;
  if(!state.output.color){toast('Apply a managed color setup in Export before overriding input color.',true);renderInspector();return;}
  snapshot();const profile=$('inputColorProfile').value;
  const range=$('inputColorRange').value,pixelAspect=$('inputPixelAspect').value;
  if(profile||range!=='auto'||pixelAspect!=='source')hit.clip.inputColor={profile:profile||'source',range,pixelAspect};else delete hit.clip.inputColor;
  redraw();save();syncPreview(true);
 };
 $('inputColorProfile').onchange=change;$('inputColorRange').onchange=change;$('inputPixelAspect').onchange=change;
}
