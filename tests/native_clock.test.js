const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/native_preview.js','utf8');
function transportContext(){
 const sandbox={setTimeout,performance,sequenceRate:()=>60};
 vm.runInNewContext(source+'\nglobalThis.samplesAt=nativeSamplesAt;globalThis.blocks=nativePCMBlocks;',sandbox);
 return sandbox;
}
const ctx=transportContext();
test('coalesced network PCM is split below the ring capacity without losing bytes',()=>{
 const input=new Uint8Array(1536000);input[0]=123;input[input.length-1]=77;
 const parts=[...ctx.blocks(input,input.length)];
 assert.equal(parts.reduce((sum,p)=>sum+p.byteLength,0),input.byteLength);
 assert(parts.every(p=>p.byteLength<=32768&&p.byteLength%4===0));
 assert.equal(new Uint8Array(parts[0])[0],123);assert.equal(new Uint8Array(parts.at(-1)).at(-1),77);
});
test('audio clock excludes pause and underrun gaps without moving backward',()=>{
 const segments=[[1,2,0,48000],[3,4,48000,96000]];
 assert.equal(ctx.samplesAt(segments,.5),0);assert.equal(ctx.samplesAt(segments,1.5),24000);
 assert.equal(ctx.samplesAt(segments,2.5),48000);assert.equal(ctx.samplesAt(segments,3.5),72000);
 assert.equal(ctx.samplesAt(segments,5),96000);
});
test('rapid seeks keep the newest destination and advance backend generation in order',async()=>{
 const ctx=transportContext();
 let generation=2;const seeks=[],audio=[];
 ctx.request=async(path,data,body)=>{assert.equal(path,'native/seek');seeks.push(body.frame);assert.equal(body.generation,generation);await new Promise(r=>setTimeout(r,5));return {generation:++generation};};
 ctx.isPlaying=false;
 vm.runInNewContext('nativePause=()=>{};nativeAudio=async(frame)=>recordAudio(frame);globalThis.scrub=async()=>{nativeState.generation=2;await Promise.all([nativeSeek(10),nativeSeek(20),nativeSeek(30)]);return nativeState.generation;};',Object.assign(ctx,{recordAudio:frame=>audio.push(frame)}));
 assert.equal(await ctx.scrub(),4);assert.deepEqual(seeks,[10,30]);assert.deepEqual(audio,[30]);
});

test('ruler preview seeks anchor the playhead and prepare PCM only at release',async()=>{
 const ctx=transportContext(),seeks=[],audio=[],port=[];
 ctx.isPlaying=false;
 ctx.request=async(path,method,{frame,generation})=>{
  assert.equal(path,'native/seek');seeks.push(frame);return {generation:generation+1};
 };
 Object.assign(ctx,{recordAudio:frame=>audio.push(frame),recordPort:m=>port.push(m.type)});
 vm.runInNewContext(`
  nativePause=()=>{};
  nativeAudio=async frame=>recordAudio(frame);
  nativeState.node={port:{postMessage:recordPort,close(){}},disconnect(){}};
  nativeState.ack={segments:[[0,1,0,48000]]};
  globalThis.drag=async()=>{
   await nativeSeek(120,true);
   nativeState.seeking=false;
   const held=nativeClock();
   await nativeSeek(180,true);
   await nativeSeek(180);
   return held;
  };
 `,ctx);
 assert.equal(await ctx.drag(),2);
 assert.deepEqual(port,['dispose']);
 assert.deepEqual(seeks,[120,180]);
 assert.deepEqual(audio,[180]);
});

test('a failed obsolete request cannot fail the latest seek',async()=>{
 const ctx=transportContext(),audio=[];
 ctx.isPlaying=false;
 ctx.request=async(path,method,{frame,generation})=>{
  if(frame===1)throw Error('older request failed');
  return {generation:generation+1};
 };
 ctx.recordAudio=frame=>audio.push(frame);
 vm.runInNewContext(`
  nativePause=()=>{};
  nativeAudio=async frame=>recordAudio(frame);
  globalThis.seekPair=()=>Promise.all([nativeSeek(1,true),nativeSeek(2)]);
 `,ctx);
 await ctx.seekPair();
 assert.deepEqual(audio,[2]);
});
