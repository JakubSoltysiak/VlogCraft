const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(values){
 const nodes=Object.fromEntries(Object.entries(values).map(([k,v])=>[k,{value:String(v),valueAsNumber:Number(v)}]));
 const context=vm.createContext({$:id=>nodes[id],Number,Error});vm.runInContext(fs.readFileSync('web/color.js','utf8'),context);return context;
}
test('unknown static mastering/content-light values are omitted, not fabricated',()=>{
 const c=fixture({colorOutput:'hdr10',sdrWhiteNits:100,masteringGamut:'unknown',maxCLL:'',maxFALL:''});
 const result=JSON.parse(JSON.stringify(c.colorOutputFromControls()));
 assert.equal(result.output,'hdr10');assert.equal(result.workingSpace,'linear-rec2020-100nits');assert.equal(result.mastering,undefined);assert.equal(result.maxCLL,undefined);
});
test('chosen mastering display and light declarations remain distinct from source tags',()=>{
 const c=fixture({colorOutput:'hdr10',sdrWhiteNits:203,masteringGamut:'p3',masteringMin:.005,masteringMax:1000,maxCLL:900,maxFALL:200});
 const r=JSON.parse(JSON.stringify(c.colorOutputFromControls()));assert.deepEqual(r.mastering.primaries[0],[.68,.32]);assert.equal(r.maxCLL,900);assert.equal(r.sdrWhiteNits,203);
});
test('legacy SDR selection adds no managed color contract',()=>{
 assert.equal(fixture({colorOutput:'legacy'}).colorOutputFromControls(),null);
});
