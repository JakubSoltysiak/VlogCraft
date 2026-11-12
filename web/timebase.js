const sequenceRates = [ ['24000/1001','23.976'],[24,'24'],[25,'25'],['30000/1001','29.97'],[30,'30'],[50,'50'],['60000/1001','59.94'],[60,'60'],[100,'100'],['120000/1001','119.88'],[120,'120'] ];
function rateValue(value) {
  const [n,d=1]=String(value).split('/').map(Number);
  return n/d;
}
function rateChoice(value){return value.includes('/')?value:Number(value);}
function sequenceRate(){return rateValue(state?.output?.fps||30);}
function frameIndex(seconds){return Math.round(seconds*sequenceRate());}
function atFrame(frame){return frame/sequenceRate();}
function frameTime(seconds){return atFrame(frameIndex(seconds));}
function rateLabel(value){return sequenceRates.find(([r])=>String(r)===String(value))?.[1]||String(value);}
function rateOptions(value){return sequenceRates.map(([v,label])=>'<option value="'+v+'" '+(String(value)===String(v)?'selected':'')+'>'+label+'</option>').join('');}
function timecode(seconds){
  const fps=Math.round(sequenceRate()),frames=frameIndex(seconds);
  const whole=Math.floor(frames/fps);
  return [Math.floor(whole/3600),Math.floor(whole%3600/60),whole%60,frames%fps].map(n=>String(n).padStart(2,'0')).join(':');
}
