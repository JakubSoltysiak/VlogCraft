/* Desktop commands and media job feedback. The server owns paths and cache state. */
let linking = false;
let readyProxies = new Set(),readyAudio=new Set();
function audioUrl(id){return readyAudio.has(id)?'/audio/'+id+'?v='+(assetById(id)?.cacheId||id):seekUrl(id);}
let useProxies = localStorage.getItem('useProxies') !== 'false';

async function importNative(paths) {
  if (linking) return toast('An import is already running', true);
  linking = true;
  transferStop = false;
  let imported = 0;
  const errors = [];
  try {
    await flushSave();
    for (const path of paths) {
      if (transferStop) break;
      const name = path.split(/[\\/]/).pop();
      transferUI('Linking media', name, 100 * imported / paths.length);
      $('transferStats').textContent = (imported + 1) + ' / ' + paths.length;
      const result = await request('import', 'POST', {paths:[path], autoProxy:useProxies});
      errors.push(...result.errors);
      for (const asset of result.assets) {
        if (!state.assets.some(a => a.id === asset.id)) state.assets.push(asset);
        if (!transferStop) addAsset(asset);
      }
      imported++;
    }
    await flushSave();
    toast(errors[0] || (transferStop ? 'Import stopped' : 'Linked ' + imported + ' file(s)'), !!errors.length);
  } catch (error) {
    toast(error.message, true);
  } finally {
    linking = false;
    $('transferOverlay').hidden = true;
    redraw();
    setTimeout(renderAssets, 900);
  }
}

function refreshPlayers() {
  invalidateRendered();
  clearPlaybackCache();
  for (const player of activePlayers.values()) {
    player.media?.pause?.();releaseStrip(player.media);
    player.wrap.remove();
  }
  for (const player of audioPlayers.values()) { player.pause();releaseStrip(player); player.remove(); }
  activePlayers.clear();
  audioPlayers.clear();
  syncPreview(true);
}

async function watchMediaJobs() {
  try {
    const jobs = await request('jobs');
    const proxy = jobs.proxy;
    const audio=new Set(jobs.readyAudio||[]),audioChanged=[...audio].some(id=>!readyAudio.has(id));
    readyAudio=audio;
    if(audioChanged)for(const [id,media] of audioPlayers){const c=programTracks.flatMap(t=>t.clips).find(c=>c.id===id);
      if(c&&readyAudio.has(c.assetId)){media.src=audioUrl(c.assetId);syncPreview(true);}}
    if(jobs.motion.status==='rendering' && $('motionInfo'))$('motionInfo').textContent='Analyzing source frames · '+jobs.motion.percent+'%';
    const ready = new Set(jobs.readyProxies);
    const changed = [...ready].some(id => !readyProxies.has(id)) || ready.size !== readyProxies.size;
    readyProxies = ready;
    if (changed && useProxies) refreshPlayers();
    $('diskHint').textContent = proxy.status === 'rendering' ? 'Proxy ' + proxy.percent + '% · ' + proxy.queued + ' queued'
      : proxy.status === 'error' ? 'Proxy failed' : ready.size + ' proxies';
    $('diskHint').title = proxy.error || proxy.message || '';
    $('stopProxy').hidden = proxy.status !== 'rendering';
  } catch (error) {
    $('diskHint').textContent = 'Job status unavailable';
  } finally {
    setTimeout(watchMediaJobs, 1500);
  }
}

function setupStudio() {
  $('previewSource').value = useProxies ? 'auto' : 'original';
  $('previewSource').onchange = e => {
    useProxies = e.target.value === 'auto';
    localStorage.setItem('useProxies', String(useProxies));
    refreshPlayers();
  };
  $('stopProxy').onclick = () => request('job/cancel','POST',{job:'proxy'}).catch(e => toast(e.message,true));
  if (state.desktop) {
    $('projectMenu').hidden = false;
    $('projectMenu').onchange = async e => {
      const action = e.target.value;
      e.target.selectedIndex = 0;
      try { await flushSave(); await request('desktop','POST',{action}); }
      catch (error) { toast(error.message,true); }
    };
    $('linkBtn').onclick = $('firstImport').onclick = async () => {
      try { const result = await request('desktop','POST',{action:'media'}); if(result.paths.length) await importNative(result.paths); }
      catch(error) { toast(error.message,true); }
    };
    document.querySelector('.drop-card p').textContent = 'Link original files to this project.';
  }
  $('assetList').addEventListener('click', async e => {
    const id = e.target.closest('[data-relink]')?.dataset.relink;
    if (!id) return;
    try {
      await flushSave();
      const result = await request('relink','POST',{assetId:id});
      if (result.cancelled) return;
      Object.assign(assetById(id),result.asset,{missing:false});
      refreshPlayers();
      redraw();
    } catch (error) { toast(error.message,true); }
  });
  const grip = $('panelResize');
  grip.onpointerdown = e => {
    grip.setPointerCapture(e.pointerId);
    const panel = document.querySelector('.timeline-panel');
    const top = e.clientY, height = panel.offsetHeight;
    grip.onpointermove = move => panel.style.height = Math.max(180,Math.min(innerHeight-330,height+top-move.clientY)) + 'px';
    grip.onpointerup = grip.onpointercancel = () => { grip.onpointermove = null; };
  };
  if (state.recovered) toast('Recovered the previous saved revision. The primary project file was unreadable.',true);
  new ResizeObserver(sizeMonitor).observe(document.querySelector('.viewer-body'));
  watchMediaJobs();
}

function sizeMonitor(){
  if(!state)return;
  const body=document.querySelector('.viewer-body'), style=getComputedStyle(body);
  const width=body.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight);
  const height=body.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom);
  const ratio=state.output.width/state.output.height;
  const stage=$('previewStage');
  stage.style.width=Math.max(1,Math.min(width,height*ratio))+'px';
  stage.style.aspectRatio=String(ratio);
}
async function openExport(){
  openModal('exportModal');
  $('exportWorkflow').value='render';
  $('nativeProjectExport').hidden=true;
  $('useNativeProjectExport').checked=false;
  $('nativeProjectPolicy').value='master';
  $('nativeProjectPolicy').onchange=updateExportWorkflow;
  $('comparisonMaster').value='';
  $('exportWorkflow').dataset.nativeProjectAvailable='';
  $('useNativeProjectExport').onchange=updateExportWorkflow;
  $('browseComparisonMaster').onclick=async ()=>{
    try{
      const result=await request('export/comparison-master','POST',{});
      if(!result.cancelled)$('comparisonMaster').value=result.path;
    }catch(error){toast(error.message,true);}
  };
  delete $('exportWorkflow').dataset.previousColor;
  delete $('exportWorkflow').dataset.previousEncoder;
  initColorControls();
  $('exportWorkflow').onchange=updateExportWorkflow;
  updateExportWorkflow();
  const out=state.output;
  const preset=[1280,1920,2560,3840,7680].includes(out.width)&&out.height===out.width*9/16;
  $('exportResolution').value=preset?String(out.width):'custom';
  $('customDimensions').hidden=preset;
  $('exportResolution').onchange=e=>{$('customDimensions').hidden=e.target.value!=='custom';};
  $('outputWidth').value=out.width;$('outputHeight').value=out.height;
  $('exportFps').innerHTML=rateOptions(out.fps);
  const quality=$('exportCrf');
  const crf=out.crf??20;
  quality.querySelector('[data-project-value]')?.remove();
  if(!Array.from(quality.options).some(option=>Number(option.value)===crf)){
    const saved=new Option('Project quality · CRF '+crf,crf);
    saved.dataset.projectValue='true';
    quality.add(saved);
  }
  quality.value=crf;
  $('exportPreset').value=out.preset||'medium';
  $('outputBitrate').value=out.bitrate||0;
  $('exportEstimate').textContent=out.width+' × '+out.height+' · '+out.fps+' fps · '+duration().toFixed(2)+' seconds';
  const choice=$('encoderChoice');
  choice.onchange=updateEncoderControls;
  $('outputBitrate').oninput=updateEncoderControls;
  choice.disabled=true;choice.replaceChildren(new Option('Checking local encoders…',''));
  $('startRender').disabled=true;
  try{
    const [available,nativeProject,jobs]=await Promise.all([request('encoders'),request('export/native-project'),request('jobs')]);
    $('exportWorkflow').dataset.nativeProjectAvailable=nativeProject.available&&available.libx265?'yes':'';
    $('nativeProjectMixedNote').textContent=nativeProject.available
      ? `Radeon 890M · UHD60 Slow CRF 20 · 60 Mb/s project setting · two x265 pool workers. Up to ${nativeProject.mixedMaxFrames} pictures and ${nativeProject.mixedMaxSpans} render spans. Studio compares every decoded picture, HDR10+ payload and audio sample with your master.` : '';
    choice.replaceChildren(...Object.entries(available).map(([id,label])=>new Option(label,id)));
    for(const option of $('exportWorkflow').options){
      if(['hdr10plus-master','samsung-hdr10plus','youtube-hdr'].includes(option.value))option.disabled=!available.libx265;
    }
    choice.value=available[out.encoder]?out.encoder:'libx264';
    if(!choice.value)choice.selectedIndex=0;
    if(state.output.color?.output==='hdr10')choice.value='libx265';
    $('startRender').disabled=!choice.value || jobs.export.status==='rendering';
    if(jobs.export.status==='interrupted')paintExportJob(jobs.export);
  }catch(error){toast('Encoder check failed: '+error.message,true);}
  finally{updateExportWorkflow();}
}

function updateExportWorkflow(){
  const workflow=$('exportWorkflow'),mode=workflow.value;
  const preserving=mode==='hdr10plus-copy',samsung=mode==='samsung-hdr10plus',youtube=mode==='youtube-hdr';
  const master=mode==='hdr10plus-master'||samsung;
  const profile=samsung||youtube,managed=master||youtube;
  $('exportRenderSettings').hidden=preserving;
  $('exportCopyRequirements').hidden=!preserving;
  $('exportMasterRequirements').hidden=!master;
  $('nativeProjectExport').hidden=mode!=='hdr10plus-master'||!workflow.dataset.nativeProjectAvailable;
  const native=$('useNativeProjectExport').checked;
  const first=$('nativeProjectPolicy').value==='first';
  const mixed=$('nativeProjectPolicy').value==='mixed';
  $('nativeProjectPolicyRow').hidden=!native;
  $('nativeProjectComparison').hidden=!native||first;
  $('nativeProjectFirstNote').hidden=!native||!first;
  $('nativeProjectMixedNote').hidden=!native||!mixed;
  $('exportProfileNote').hidden=!profile;
  $('exportProfileNote').textContent=samsung
    ? '3840 × 2160 at 60 fps · HEVC Main10 HDR10+ · CRF 17 · Samsung device playback is pending.'
    : youtube ? '3840 × 2160 at 60 fps · HEVC Main10 HDR10 · CRF 20 · AAC stereo. YouTube processes its own HDR versions.' : '';
  $('exportResolution').closest('label').hidden=profile;
  $('exportFps').closest('label').hidden=profile;
  $('customDimensions').hidden=profile||$('exportResolution').value!=='custom';
  $('applyColorSetup').hidden=managed;
  $('colorOutput').disabled=managed;
  $('encoderChoice').disabled=managed;
  if(managed){
    if(workflow.dataset.previousColor===undefined){
      workflow.dataset.previousColor=$('colorOutput').value;
      workflow.dataset.previousEncoder=$('encoderChoice').value;
    }
    $('colorOutput').value='hdr10';
  }else if(workflow.dataset.previousColor!==undefined){
    $('colorOutput').value=workflow.dataset.previousColor;
    if(workflow.dataset.previousEncoder)$('encoderChoice').value=workflow.dataset.previousEncoder;
    delete workflow.dataset.previousColor;
    delete workflow.dataset.previousEncoder;
  }
  $('colorOutput').onchange();
}

function openProjectStorage(){
  const dialog=document.createElement('dialog');
  dialog.className='motion-dialog';
  dialog.innerHTML='<h2>Project storage</h2><dl id="storageCategories"></dl>'+
    '<p class="dialog-note">Original sources, backups and recovery data stay available. Temporary exports are handled by the export job.</p>'+
    '<div class="property-actions"><button type="button" id="clearRemovedThumbs" class="button secondary">Clear thumbnails of removed media</button>'+
    '<button type="button" id="clearAbandonedExports" class="button secondary">Clear abandoned export scratch</button>'+
    '<button type="button" id="closeStorage" class="button primary">Close</button></div>';
  document.body.appendChild(dialog);
  async function refresh(){
    try{
      const data=await request('storage');
      const container=dialog.querySelector('dl');
      container.replaceChildren();
      for(const [label,bytes] of Object.entries(data.bytes)){
        const name=document.createElement('dt'),value=document.createElement('dd');
        name.textContent=label;
        value.textContent=fileSize(bytes);
        container.append(name,value);
      }
    }catch(error){toast('Storage usage: '+error.message,true);}
  }
  $('clearRemovedThumbs').onclick=async()=>{
    if(!confirm('Clear cached thumbnails for removed library items?'))return;
    try{
      const result=await request('storage/clear-removed-thumbnails','POST',{confirmed:true});
      toast('Cleared '+result.count+' cached thumbnail(s)');
      await refresh();
    }catch(error){toast(error.message,true);}
  };
  $('clearAbandonedExports').onclick=async()=>{
    if(!confirm('Remove registered inactive export intermediates? Linked sources and active render jobs are protected.'))return;
    try{
      const result=await request('storage/clear-export-scratch','POST',{confirmed:true});
      toast('Cleared '+result.count+' abandoned export job(s)');
      await refresh();
    }catch(error){toast(error.message,true);}
  };
  $('closeStorage').onclick=()=>dialog.close();
  dialog.onclose=()=>dialog.remove();
  dialog.showModal();
  void refresh();
}

function updateEncoderControls(){
  const hdr=$('colorOutput').value==='hdr10';
  const cpu=hdr || ['libx264','libx265','libsvtav1'].includes($('encoderChoice').value);
  $('cpuExportPreset').hidden=!cpu;
  const fixed=['samsung-hdr10plus','youtube-hdr'].includes($('exportWorkflow').value);
  $('outputBitrate').closest('label').hidden=hdr || fixed;
  $('cpuExportQuality').hidden=fixed || !cpu || (!hdr && $('outputBitrate').valueAsNumber>0);
  $('exportBitrateNote').hidden=fixed;
  $('exportBitrateNote').textContent=hdr
    ? 'HDR10 uses HEVC Main10 constant-quality encoding. CRF sets quality and the picture content determines file size.'
    : cpu ? 'Set 0 to use CRF quality mode. A nonzero value sets the target bitrate instead.'
          : 'Hardware encoding uses a target bitrate. Set 0 to use 35 Mb/s.';
}
