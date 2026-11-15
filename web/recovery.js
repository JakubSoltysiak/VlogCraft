/* Event-driven recovery drafts. History is lossless, local and bounded by the existing undo depth. */
let recoveryEpoch=0,recoverySequence=0,recoveryAckSequence=-1,recoveryPending=null,recoveryFlight=null;
async function recoveryEncodeHistory(text){
 if(typeof CompressionStream==='undefined')return {encoding:'json',data:text};
 const bytes=new Uint8Array(await new Response(new Blob([text]).stream().pipeThrough(new CompressionStream('gzip'))).arrayBuffer());
 const parts=[];for(let i=0;i<bytes.length;i+=32768)parts.push(String.fromCharCode(...bytes.subarray(i,i+32768)));
 return {encoding:'gzip-base64',data:btoa(parts.join(''))};
}
async function recoveryDecodeHistory(history){
 if(!history||typeof history.data!=='string')throw Error('Invalid recovery history');
 if(history.encoding==='json')return JSON.parse(history.data);
 if(history.encoding!=='gzip-base64'||typeof DecompressionStream==='undefined')throw Error('Unsupported recovery history');
 const bytes=Uint8Array.from(atob(history.data),c=>c.charCodeAt(0));
 return JSON.parse(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text());
}
function recoveryCheckpoint(changed=false){
 if(!state?.desktop||!window.pywebview?.api?.checkpoint)return;
 const ui={playhead,zoom,selectedId,selectedAssetId,insTab,snap,useProxies,engine:$('playbackEngine').value,resolution:$('programResolution').value,source:$('previewSource').value};
 const previous=recoveryPending;
 // Capture immutable data before asynchronous compression; UI-only changes
 // must not discard an unsent draft/history snapshot.
 const work={epoch:recoveryEpoch,sequence:++recoverySequence,revision:changed?modified:previous?.document?previous.revision:modified,ui:JSON.stringify(ui),
  document:changed?JSON.stringify({name:state.name,tracks:state.tracks,output:state.output}):previous?.document,
  history:changed?JSON.stringify({undo:undoStack.slice(-80).map(s=>({name:s.name,tracks:s.tracks,output:s.output})),redo:redoStack.slice(-80).map(s=>({name:s.name,tracks:s.tracks,output:s.output}))}):previous?.history};
 recoveryPending=work;recoveryDrain();
}
function recoveryDrain(){
 if(recoveryFlight||!recoveryPending)return;
 let failed=false;
 recoveryFlight=(async()=>{
  while(recoveryPending){
   const work=recoveryPending;recoveryPending=null;
   try{
    const message={epoch:work.epoch,sequence:work.sequence,revision:work.revision,ui:JSON.parse(work.ui)};
    if(work.document)message.document=JSON.parse(work.document);
    if(work.history)message.ui.history=await recoveryEncodeHistory(work.history);
    const result=await window.pywebview.api.checkpoint(JSON.stringify(message));
    if(result.durable&&result.epoch===recoveryEpoch)recoveryAckSequence=Math.max(recoveryAckSequence,result.sequence);
   }catch(error){
    // Retain the newest unacknowledged draft, but retry only on the next user
    // checkpoint rather than spinning forever on an unavailable disk/bridge.
    if(!recoveryPending)recoveryPending=work;
    else{
     if(!recoveryPending.document&&work.document){recoveryPending.document=work.document;recoveryPending.revision=work.revision;}
     if(!recoveryPending.history&&work.history)recoveryPending.history=work.history;
    }
    failed=true;toast('Recovery checkpoint unavailable. Save the project before closing.',true);break;
   }
  }
 })().finally(()=>{recoveryFlight=null;if(recoveryPending&&!failed)recoveryDrain();});
}
async function recoverySettled(){while(recoveryFlight)await recoveryFlight;}
async function recoveryInitialize(){
 if(!state?.desktop)return;
 const data=await request('desktop/recovery');recoveryEpoch=data.epoch;
 const ui=data.restore;let historyWarning=null;
 if(ui){
  if(Number.isFinite(ui.zoom))zoom=clamp(ui.zoom,8,800);
  if(typeof ui.snap==='boolean')snap=ui.snap;
  if(typeof ui.useProxies==='boolean')useProxies=ui.useProxies;
  selectedId=ui.selectedId||null;selectedAssetId=ui.selectedAssetId||null;
  if(['clip','project'].includes(ui.insTab))insTab=ui.insTab;
  document.querySelectorAll('[data-tab]').forEach(button=>button.classList.toggle('active',button.dataset.tab===insTab));
  $('snapBtn').classList.toggle('active',snap);
  if([...$('previewSource').options].some(o=>o.value===ui.source))$('previewSource').value=ui.source;
  let history=ui;
  if(ui.history){
   try{history=await recoveryDecodeHistory(ui.history);}
   catch(error){history={};historyWarning='Recovery history could not be loaded. Your project is restored; the previous checkpoint history is retained.';}
  }
  if(Array.isArray(history.undo))undoStack=history.undo.slice(-80);
  if(Array.isArray(history.redo))redoStack=history.redo.slice(-80);
  if([...$('programResolution').options].some(o=>o.value===ui.resolution))$('programResolution').value=ui.resolution;
  if([...$('playbackEngine').options].some(o=>o.value===ui.engine&&!o.disabled))$('playbackEngine').value=ui.engine;
  redraw();playhead=clamp(Number(ui.playhead)||0,0,duration());nativeQualityOptions();positionPlayhead();syncPreview(true);
 }
 recoveryCheckpoint(!historyWarning);await recoverySettled();await request('desktop/recovery/ready','POST',{epoch:recoveryEpoch});
 if(historyWarning)toast(historyWarning,true);else if(data.warning)toast(data.warning,true);else if(ui)toast('Editor view recovered. Your project is restored; playback is paused.');
}
