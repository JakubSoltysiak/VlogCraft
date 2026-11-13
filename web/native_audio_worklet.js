/* Bounded PCM consumer. Sample count, not UI wall time, owns experimental transport. */
class VlogCraftPCM extends AudioWorkletProcessor {
 constructor(){
  super();this.capacity=96000;this.ring=new Float32Array(this.capacity*2);this.reset(0);this.report=0;
  this.port.onmessage=event=>{
   const m=event.data;
   if(m.type==='reset')this.reset(m.generation);
   else if(m.generation===this.generation){
    if(m.type==='play')this.playing=m.playing;
    else if(m.type==='end')this.ended=true;
    else if(m.type==='push'){
     const data=new Int16Array(m.data),frames=data.length/2;
     if(this.queued+frames>this.capacity){this.port.postMessage({error:'PCM queue capacity exceeded',generation:this.generation});return;}
     for(let i=0;i<frames;i++){const at=((this.write+i)%this.capacity)*2;this.ring[at]=data[i*2]/32768;this.ring[at+1]=data[i*2+1]/32768;}
     this.write=(this.write+frames)%this.capacity;this.queued+=frames;
    }
   }
  };
 }
 reset(generation){this.generation=generation;this.read=0;this.write=0;this.queued=0;this.samples=0;this.playing=false;this.ended=false;this.underruns=0;this.sampleContextEnd=0;this.segments=[];this.flowing=false;}
 process(inputs,outputs){
  const output=outputs[0];if(!output.length)return true;const count=output[0].length;let used=0;
  if(this.playing){
   used=Math.min(count,this.queued);
   for(let i=0;i<used;i++){const at=((this.read+i)%this.capacity)*2;output[0][i]=this.ring[at];if(output[1])output[1][i]=this.ring[at+1];}
   if(used&&!this.flowing){this.segments.push([currentTime,currentTime,this.samples,this.samples]);if(this.segments.length>128)this.segments.shift();}
   if(used){const segment=this.segments[this.segments.length-1];segment[1]=currentTime+used/sampleRate;segment[3]=this.samples+used;}
   this.read=(this.read+used)%this.capacity;this.queued-=used;this.samples+=used;
   if(used)this.sampleContextEnd=currentTime+used/sampleRate;
   if(used<count&&!this.ended)this.underruns++;
  }
  this.flowing=this.playing&&used===count;
  if(++this.report>=8){this.report=0;this.port.postMessage({generation:this.generation,samples:this.samples,queued:this.queued,contextEnd:this.sampleContextEnd,segments:this.segments,underruns:this.underruns,waiting:this.playing&&!this.ended&&this.queued===0,finished:this.ended&&this.queued===0});}
  return true;
 }
}
registerProcessor('vlogcraft-pcm',VlogCraftPCM);
