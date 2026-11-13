const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ctx={setTimeout,performance};vm.runInNewContext(fs.readFileSync('web/native_preview.js','utf8')+'\nglobalThis.samplesAt=nativeSamplesAt;globalThis.blocks=nativePCMBlocks;',ctx);
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
 let generation=2;const seeks=[],audio=[];
 ctx.request=async(path,data,body)=>{assert.equal(path,'native/seek');seeks.push(body.frame);assert.equal(body.generation,generation);await new Promise(r=>setTimeout(r,5));return {generation:++generation};};
 ctx.isPlaying=false;
 vm.runInNewContext('nativePause=()=>{};nativeAudio=async(frame)=>recordAudio(frame);globalThis.scrub=async()=>{nativeState.generation=2;await Promise.all([nativeSeek(10),nativeSeek(20),nativeSeek(30)]);return nativeState.generation;};',Object.assign(ctx,{recordAudio:frame=>audio.push(frame)}));
 assert.equal(await ctx.scrub(),4);assert.deepEqual(seeks,[10,30]);assert.deepEqual(audio,[30]);
});
