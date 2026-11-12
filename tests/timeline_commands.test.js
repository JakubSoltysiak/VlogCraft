const {test}=require('node:test');
const assert=require('node:assert/strict');
const {editTimeline}=require('../web/edit_ops.js');
const {nestEdit,playbackTracks}=require('../web/nesting.js');
test('nest, move and expand preserve offsets and child source handles',()=>{
  const input=sequence();
  let uid=0;const makeId=()=>String(++uid);
  const nested=nestEdit(input,['B','C'],'nest',fps,makeId);
  const group=nested.tracks[0].clips[0];assert.equal(group.kind,'sequence');assert.equal(frame(group.position),10);
  const moved=run(nested.tracks,nested.ids,'move',{frames:4}).tracks;
  const expanded=nestEdit(moved,[group.id],'expand',fps,makeId);
  assert.deepEqual(summary(expanded.tracks),[[14,50,60],[24,70,85]]);
  assert.deepEqual(summary(playbackTracks(moved)),[[14,50,60],[24,70,85]]);
});
const fps=30000/1001;
const sec=n=>n/fps;
const frame=t=>Math.round(t*fps);
const assets=[{id:'v',duration:40,kind:'video',hasAudio:true}];
function clip(id,position,start,end){return {id,assetId:'v',kind:'video',position:sec(position),start:sec(start),end:sec(end),speed:1};}
function sequence(){return [{id:'t',type:'video',clips:[clip('A',0,20,30),clip('B',10,50,60),clip('C',20,70,85)]}];}
function run(tracks,ids,op,args){return editTimeline(tracks,assets,fps,ids,op,args);}
function summary(tracks){return tracks[0].clips.map(c=>[frame(c.position),frame(c.start),frame(c.end)]);}
test('roll, slip and slide use distinct source handles and preserve the outer edit',()=>{
  let s=sequence();
  assert.deepEqual(summary(run(s,['B'],'roll',{frames:2}).tracks),[[0,20,30],[10,50,62],[22,72,85]]);
  assert.deepEqual(summary(run(s,['B'],'slip',{frames:-3}).tracks),[[0,20,30],[10,47,57],[20,70,85]]);
  assert.deepEqual(summary(run(s,['B'],'slide',{frames:3}).tracks),[[0,20,33],[13,50,60],[23,73,85]]);
  assert.deepEqual(summary(s),[[0,20,30],[10,50,60],[20,70,85]]);
});
test('insert opens a gap inside a shot and overwrite preserves the tail',()=>{
  const add=clip('new',0,10,13);
  const s=sequence();
  const a=run(s,[],'insert',{at:4,trackId:'t',clip:add}).tracks;
  assert.deepEqual(summary(a).sort((a,b)=>a[0]-b[0]),[[0,20,24],[4,10,13],[7,24,30],[13,50,60],[23,70,85]]);
  const b=run(s,[],'overwrite',{at:8,trackId:'t',clip:add}).tracks;
  assert.deepEqual(summary(b).sort((a,b)=>a[0]-b[0]),[[0,20,28],[8,10,13],[11,51,60],[20,70,85]]);
});
test('separated camera audio follows linked movement, splits and deletes',()=>{
  const s=run(sequence(),['B'],'extractAudio',{}).tracks;
  const v=s[0].clips[1],a=s[1].clips[0];assert.ok(v.audioDetached);assert.equal(a.linkId,v.linkId);
  const moved=run(s,['B'],'move',{frames:2}).tracks;
  assert.equal(frame(moved[1].clips[0].position),12);
  const split=run(moved,['B'],'split',{at:17});assert.equal(split.ids.length,2);
  const right=split.tracks[0].clips.at(-1),audioRight=split.tracks[1].clips.at(-1);
  assert.equal(right.linkId,audioRight.linkId);assert.notEqual(right.linkId,v.linkId);
  assert.equal(run(split.tracks,[right.id],'delete',{}).tracks[1].clips.length,1);
});
test('lock and handle conflicts reject atomically',()=>{
  const s=sequence();s[0].clips[2].locked=true;const original=structuredClone(s);
  assert.throws(()=>run(s,['B'],'slide',{frames:2}),/locked/);
  assert.deepEqual(s,original);
  assert.throws(()=>run(s,['A','B'],'move',{frames:-2}),/remain/);
  assert.deepEqual(s,original);
});
test('selected clips can link and unlink without changing source times',()=>{
  const linked=run(sequence(),['A','C'],'link',{}).tracks;
  assert.equal(linked[0].clips[0].linkId,linked[0].clips[2].linkId);
  assert.equal(run(linked,['A'],'duplicate',{}).ids.length,2);
  const independent=run(linked,['A'],'unlink',{}).tracks;
  assert.equal(run(independent,['A'],'delete',{}).tracks[0].clips.length,2);
});
