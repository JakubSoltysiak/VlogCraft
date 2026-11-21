const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const ctx = vm.createContext({});
vm.runInContext(fs.readFileSync('web/animation.js','utf8'),ctx);

const settings = preset => ({preset,duration:1,direction:'left',easing:'smooth'});
const plain = value => JSON.parse(JSON.stringify(value));
const clip = {kind:'image',position:12,start:0,end:5,speed:1,opacity:.8,scale:1,x:0,y:0};

test('preset range is frame aligned, ending on the last displayed frame',()=>{
  const keys=plain(ctx.motionKeys(clip,settings('fade-out'),60,false)).opacity;
  assert.equal(keys[1].time,299/60);
  assert.equal(keys[0].value,.8);
  assert.equal(keys[1].value,0);
  assert.equal(keys[0].preset,true);
  assert.deepEqual(keys[0].handles,[.42,0,.58,1]);
});

test('project motion preserves manual curves and does not touch unsupported HDR',()=>{
  const manual=[{time:0,value:1,mode:'linear'}];
  const keyed={...clip,keys:{scale:manual}};
  assert.equal(ctx.motionKeys(keyed,settings('zoom-in'),60,false),null);
  assert.deepEqual(plain(ctx.motionKeys(keyed,settings('fade-in'),60,false)).scale,manual);
  assert.equal(ctx.motionKeys({...clip,kind:'video'},settings('ken-burns'),60,true),null);
  assert.equal(ctx.motionKeys({...clip,kind:'video'},settings('fade-in'),60,true).opacity.length,2);
});

test('replacing or clearing a preset retains manual keys',()=>{
  const original={...clip,keys:{x:[{time:3,value:.1,mode:'linear'}]}};
  const first=ctx.motionKeys(original,settings('zoom-in'),60,false);
  const replaced=ctx.motionKeys({...original,keys:first},settings('fade-both'),60,false);
  assert.equal(replaced.scale,undefined);
  assert.deepEqual(plain(ctx.withoutGeneratedMotion(replaced)),original.keys);
});
