/* Explicit local diagnostics. Applying the suggestion changes only preview resolution. */
let performanceReport=null;
async function performanceTest(){
 $('performanceRun').disabled=true;$('performanceApply').disabled=true;$('performanceResult').textContent='Measuring locally…';
 try{
  let report=await request('performance/start','POST',{storage:$('performanceDisk').checked});
  while(report.status==='running'){await new Promise(r=>setTimeout(r,250));report=await request('performance/status');}
  if(report.status!=='complete')throw Error(report.reason||'Local diagnostics unavailable');
  performanceReport=report;const h=report.hardware,n=h.native;
  const gpu=h.gpu?.[0],cpu=h.cpu?.[0],disk=h.storage?.[0],storage=report.storage_test;
  const lines=[cpu?.Name?.trim(),gpu?.Name+' · driver '+gpu?.DriverVersion,disk?.FriendlyName+' · '+disk?.BusType,
   h.ac_power?'AC power':'Battery power',n?'Active display: '+n.active_refresh_hz+' Hz':'Display timing unavailable',
   storage?.available?'Bounded storage test: '+Math.round(storage.sequential_read_MiB_s)+' MiB/s read, '+Math.round(storage.sequential_write_MiB_s)+' MiB/s write':'Storage benchmark not run',
   'Suggested Composited/Native monitor: '+report.recommendation.preview_width+' px wide. '+report.recommendation.reason,
   'Native remains experimental. This diagnostic does not qualify actual playback, HDR or NPU acceleration.'];
  $('performanceResult').textContent=lines.filter(Boolean).join('\n');$('performanceApply').disabled=false;
 }catch(error){$('performanceResult').textContent=error.message;}
 finally{$('performanceRun').disabled=false;}
}
function applyPerformancePreview(){
 if(!performanceReport)return;
 const select=$('programResolution');select.value=performanceReport.recommendation.preview_width;select.onchange();
 toast('Monitor size saved for Composited/Native preview. Change it in the monitor resolution menu.');
}
