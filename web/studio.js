/* Desktop commands and media job feedback. The server owns paths and cache state. */
let linking = false;
let readyProxies = new Set();
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
  const out=state.output;
  const preset=[1280,1920,2560,3840].includes(out.width)&&out.height===out.width*9/16;
  $('exportResolution').value=preset?String(out.width):'custom';
  $('customDimensions').hidden=preset;
  $('exportResolution').onchange=e=>{$('customDimensions').hidden=e.target.value!=='custom';};
  $('outputWidth').value=out.width;$('outputHeight').value=out.height;
  $('exportFps').innerHTML=rateOptions(out.fps);$('exportCrf').value=out.crf||20;$('exportPreset').value=out.preset||'medium';
  $('outputBitrate').value=out.bitrate||0;
  $('exportEstimate').textContent=out.width+' × '+out.height+' · '+out.fps+' fps · '+duration().toFixed(2)+' seconds';
  const choice=$('encoderChoice');
  choice.disabled=true;choice.replaceChildren(new Option('Checking local encoders…',''));
  $('startRender').disabled=true;
  try{
    const available=await request('encoders');
    choice.replaceChildren(...Object.entries(available).map(([id,label])=>new Option(label,id)));
    choice.value=available[out.encoder]?out.encoder:'libx264';
    if(!choice.value)choice.selectedIndex=0;
    $('startRender').disabled=!choice.value || (await request('jobs')).export.status==='rendering';
  }catch(error){toast('Encoder check failed: '+error.message,true);}
  finally{choice.disabled=false;}
}
