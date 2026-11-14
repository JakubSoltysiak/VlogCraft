let mixer=null,bus=null,meterBuffer=null,transportClock=null;
const strips=new Map();
function initializeMixer(){
  if(!mixer){
    mixer=new AudioContext();bus=mixer.createAnalyser();bus.fftSize=512;bus.connect(mixer.destination);
    meterBuffer=new Float32Array(bus.fftSize);
  }
  return mixer.resume();
}
function transportNow(){return transportClock?transportClock.currentTime*1000:performance.now();}
function updateMeter(){
  const meter=$('masterMeter');if(!meter||!bus)return;
  bus.getFloatTimeDomainData(meterBuffer);let peak=0;
  for(const x of meterBuffer)peak=Math.max(peak,Math.abs(x));
  updateMeter.peak=Math.max(updateMeter.peak||0,peak);
  const now=performance.now();if(now-(updateMeter.lastPaint??-Infinity)<1000/30)return;
  const db=20*Math.log10(Math.max(.001,updateMeter.peak));updateMeter.peak=0;updateMeter.lastPaint=now;
  if(Number(meter.value)!==db)meter.value=db;const title=db.toFixed(1)+' dBFS';if(meter.title!==title)meter.title=title;
}
function mixSource(media,c,gain){
  if(!mixer){media.volume=clamp(gain,0,1);return;}
  let strip=strips.get(media);
  if(!strip){
    const source=mixer.createMediaElementSource(media),bass=mixer.createBiquadFilter(),treble=mixer.createBiquadFilter();
    bass.type='lowshelf';bass.frequency.value=160;treble.type='highshelf';treble.frequency.value=4200;
    const comp=mixer.createDynamicsCompressor(),pan=mixer.createStereoPanner(),level=mixer.createGain();
    source.connect(bass);bass.connect(treble);treble.connect(comp);comp.connect(pan);pan.connect(level);level.connect(bus);
    strip={source,bass,treble,comp,pan,level};strips.set(media,strip);
  }
  media.volume=1;strip.bass.gain.value=c.bass||0;strip.treble.gain.value=c.treble||0;
  strip.comp.threshold.value=-18;strip.comp.knee.value=0;strip.comp.ratio.value=c.compress||1;
  strip.comp.attack.value=.005;strip.comp.release.value=.12;strip.pan.pan.value=c.pan||0;
  strip.level.gain.setTargetAtTime(gain,mixer.currentTime,.004);
}
function releaseStrip(media){
  const strip=strips.get(media);if(strip){for(const node of Object.values(strip))node.disconnect();strips.delete(media);}
}
function syncMediaTime(media,target,speed,force){
  const drift=target-(media.currentTime||0),hard=Math.max(.09,2/sequenceRate());
  if(force || (!media.seeking && Math.abs(drift)>hard)){
    try{media.currentTime=Math.max(0,target);}catch{}
  }
  const correction=isPlaying&&!force&&Math.abs(drift)<hard?clamp(drift*.32,-.02,.02):0;
  media.playbackRate=clamp(speed*(1+correction),.1,4);
}
function mixerControls(c,track){
  const voices=state.tracks.filter(t=>t.id!==track.id && t.clips.some(k=>assetById(k.assetId)?.hasAudio&&!k.audioDetached));
  return '<details class="fx-panel"><summary>Channel strip and levels</summary>'+
    range('Pan','pan',c.pan||0,-1,1,.02,false)+range('Low shelf (dB)','bass',c.bass||0,-18,18,.5,false)+
    range('High shelf (dB)','treble',c.treble||0,-18,18,.5,false)+range('Compressor ratio','compress',c.compress||1,1,16,.5,false)+
    '<div class="property-actions"><button class="text-button" id="normalizeClip">Peak normalize to −1 dBFS</button></div>'+
    (voices.length?'<div class="property"><label>Dialogue track</label><select id="dialogueTrack">'+voices.map(t=>'<option value="'+t.id+'">'+esc(t.name)+'</option>').join('')+'</select></div><button class="text-button" id="duckClip">Duck music to dialogue</button>':'')+
    '<p class="dialog-note">Normalization sets clip gain. Ducking replaces the gain curve with editable keys.</p></details>';
}
async function analyzeLevels(mode){
  const hit=sel();if(!hit)return;
  const id=hit.clip.id,original=JSON.stringify(hit.clip);
  const button=$(mode==='duck'?'duckClip':'normalizeClip');button.disabled=true;
  try{
    await flushSave();
    const result=await request('audio/analyze','POST',{mode,clipId:id,voiceTrack:$('dialogueTrack')?.value});
    const now=sel();
    if(!now||now.clip.id!==id||JSON.stringify(now.clip)!==original||now.track.locked||now.clip.locked)
      throw Error('The clip changed during analysis');
    snapshot();
    if(mode==='duck'){now.clip.keys={...now.clip.keys,volume:result.keys};toast('Added gain keys for '+result.regions+' dialogue region(s)');}
    else{now.clip.volume=result.gain;if(now.clip.keys)delete now.clip.keys.volume;toast('Measured peak '+result.peakDb.toFixed(1)+' dBFS'+(result.capped?' · gain limited to 3×':''));}
    redraw();save();
  }catch(e){toast(e.message,true);}
  finally{button.disabled=false;}
}
