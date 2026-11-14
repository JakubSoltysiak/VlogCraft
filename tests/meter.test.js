const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 let writes=0,value=-60;const meter={title:'',get value(){return value},set value(v){value=v;writes++}};
 const context={Float32Array,performance:{now:()=>context.now},now:0,peak:.1,$:()=>meter};
 vm.runInNewContext(fs.readFileSync('web/audio.js','utf8')+'\nbus={getFloatTimeDomainData:b=>{b[0]=peak;b[1]=0}};meterBuffer=new Float32Array(2);globalThis.measure=updateMeter;',context);
 return {context,meter,writes:()=>writes};
}
test('meter keeps a transient peak between display updates',()=>{
 const {context:c,meter,writes}=setup();c.measure();
 c.now=8;c.peak=.9;c.measure();c.now=16;c.peak=.2;c.measure();
 assert.equal(writes(),1);c.now=35;c.peak=.3;c.measure();
 assert.equal(writes(),2);assert(Math.abs(meter.value-20*Math.log10(.9))<1e-5);
});
test('meter sampling stays active while display mutations are bounded',()=>{
 const {context:c,writes}=setup();
 for(let i=0;i<100;i++){c.now=i;c.peak=.2+i/200;c.measure();}
 assert(writes()<=3);assert.equal(c.now,99);
});
