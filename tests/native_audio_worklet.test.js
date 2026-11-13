const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function create(){
 let Type;const messages=[],ctx={AudioWorkletProcessor:class{constructor(){this.port={postMessage:m=>messages.push(m)};}},sampleRate:48000,currentTime:0,registerProcessor:(name,type)=>Type=type};
 vm.runInNewContext(fs.readFileSync('web/native_audio_worklet.js','utf8'),ctx);
 const node=new Type(),send=m=>node.port.onmessage({data:m});
 return {node,send,messages,ctx};
}
test('PCM preserves stereo samples, freezes on underrun and rejects stale generations',()=>{
 const {node,send}=create();send({type:'reset',generation:3});
 send({type:'push',generation:2,data:new Int16Array([1000,1000]).buffer});assert.equal(node.queued,0);
 send({type:'push',generation:3,data:new Int16Array([16384,-16384,8192,-8192]).buffer});send({type:'play',generation:3,playing:true});
 const out=[new Float32Array(128),new Float32Array(128)];node.process([], [out]);
 assert.equal(out[0][0],.5);assert.equal(out[1][0],-.5);assert.equal(out[0][1],.25);assert.equal(out[0][2],0);
 assert.equal(node.samples,2);assert.equal(node.underruns,1);node.process([],[[new Float32Array(128),new Float32Array(128)]]);
 assert.equal(node.samples,2);send({type:'end',generation:3});assert.equal(node.ended,true);
});
test('PCM ring is bounded and pause preserves its queue',()=>{
 const {node,send,messages}=create();send({type:'push',generation:0,data:new Int16Array(192000).buffer});assert.equal(node.queued,96000);
 send({type:'push',generation:0,data:new Int16Array(2).buffer});assert.equal(node.queued,96000);assert.equal(messages.length,1);
 node.process([],[[new Float32Array(128),new Float32Array(128)]]);assert.equal(node.samples,0);assert.equal(node.queued,96000);
});
