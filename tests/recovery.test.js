const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
test('draft bridge coalesces while retaining stable snapshots and excludes credentials',async()=>{
 const calls=[];let release;
 const context=vm.createContext({state:{desktop:true,name:'first',tracks:[],output:{},apiKey:'secret'},modified:1,
  playhead:2,zoom:70,selectedId:null,selectedAssetId:null,insTab:'clip',snap:true,useProxies:false,undoStack:[{tracks:[],apiKey:'secret'}],redoStack:[],
  $:id=>({value:id==='playbackEngine'?'native':'960'}),toast:()=>{},
  window:{pywebview:{api:{checkpoint:payload=>{calls.push(JSON.parse(payload));return new Promise(resolve=>release=()=>resolve({epoch:0,sequence:calls.at(-1).sequence,durable:true}));}}}}});
 vm.runInContext(fs.readFileSync('web/recovery.js','utf8'),context);
 vm.runInContext('recoveryCheckpoint(true)',context);
 await new Promise(resolve=>setImmediate(resolve));
 for(let n=0;n<100;n++){context.state.name='edit'+n;context.modified++;vm.runInContext('recoveryCheckpoint(true)',context);}
 assert.equal(calls.length,1);assert.equal(calls[0].document.name,'first');assert(!JSON.stringify(calls).includes('secret'));
 release();await new Promise(resolve=>setImmediate(resolve));assert.equal(calls.length,2);assert.equal(calls[1].document.name,'edit99');
 release();await vm.runInContext('recoverySettled()',context);
 assert.equal(vm.runInContext('recoveryPending',context),null);assert.equal(vm.runInContext('recoveryFlight',context),null);
 assert.equal(vm.runInContext('recoveryAckSequence',context),101);
});

test('UI-only coalescing retains the latest pending unsaved document',async()=>{
 const calls=[];let release;
 const c=vm.createContext({state:{desktop:true,name:'first',tracks:[],output:{}},modified:1,playhead:0,zoom:70,selectedId:null,selectedAssetId:null,insTab:'clip',snap:true,useProxies:false,undoStack:[],redoStack:[],
  $:()=>({value:'native'}),toast:()=>{},window:{pywebview:{api:{checkpoint:p=>{const message=JSON.parse(p);calls.push(message);return new Promise(resolve=>release=()=>resolve({epoch:0,sequence:message.sequence,durable:true}));}}}}});
 vm.runInContext(fs.readFileSync('web/recovery.js','utf8'),c);vm.runInContext('recoveryCheckpoint(true)',c);await new Promise(resolve=>setImmediate(resolve));
 c.state.name='unsaved';c.modified=2;vm.runInContext('recoveryCheckpoint(true);playhead=7;recoveryCheckpoint(false)',c);
 c.state.name='later mutation';release();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls[1].document.name,'unsaved');assert.equal(calls[1].ui.playhead,7);assert.equal(calls[1].revision,2);assert(calls[1].ui.history);
 release();await vm.runInContext('recoverySettled()',c);
});

test('a failed bridge retains the draft and does not enter an automatic retry loop',async()=>{
 let attempts=0,warnings=0;
 const c=vm.createContext({state:{desktop:true,name:'retain',tracks:[],output:{}},modified:1,playhead:0,zoom:70,selectedId:null,selectedAssetId:null,insTab:'clip',snap:true,useProxies:false,undoStack:[],redoStack:[],
  $:()=>({value:'native'}),toast:()=>warnings++,window:{pywebview:{api:{checkpoint:async p=>{attempts++;if(attempts===1)throw Error('injected');const m=JSON.parse(p);return {epoch:0,sequence:m.sequence,durable:true};}}}}});
 vm.runInContext(fs.readFileSync('web/recovery.js','utf8'),c);vm.runInContext('recoveryCheckpoint(true)',c);await vm.runInContext('recoverySettled()',c);
 await new Promise(resolve=>setImmediate(resolve));assert.equal(attempts,1);assert.equal(warnings,1);
 assert.equal(JSON.parse(vm.runInContext('recoveryPending.document',c)).name,'retain');
 vm.runInContext('recoveryCheckpoint(false)',c);await vm.runInContext('recoverySettled()',c);assert.equal(attempts,2);
 assert.equal(vm.runInContext('recoveryPending',c),null);
});

test('native gzip history round-trips all eighty snapshots and Unicode',async()=>{
 const c=vm.createContext({CompressionStream,DecompressionStream,Response,Blob,btoa,atob,Uint8Array});
 vm.runInContext(fs.readFileSync('web/recovery.js','utf8'),c);
 const original=JSON.stringify({undo:Array.from({length:80},(_,n)=>({name:'Łódź '+n,tracks:[{clips:[{id:'c',opacity:n/80}]}],output:{fps:'60000/1001'}})),redo:[]});
 c.input=original;const compressed=await vm.runInContext('recoveryEncodeHistory(input)',c);
 assert.equal(compressed.encoding,'gzip-base64');assert(compressed.data.length<original.length/2);
 c.history=compressed;const restored=await vm.runInContext('recoveryDecodeHistory(history)',c);assert.deepEqual(JSON.parse(JSON.stringify(restored)),JSON.parse(original));
 c.history={encoding:'gzip-base64',data:'invalid!'};await assert.rejects(vm.runInContext('recoveryDecodeHistory(history)',c));
});


test('recovery restores project inspector, snap and source controls consistently',async()=>{
 const tabs=['clip','project'].map(tab=>({dataset:{tab},classList:{toggle(name,value){this.active=value}}}));
 const nodes={programResolution:{value:'960',options:[{value:'960'}]},playbackEngine:{value:'live',options:[{value:'live'},{value:'rendered'}]},previewSource:{value:'auto',options:[{value:'auto'},{value:'original'}]},snapBtn:{classList:{toggle(name,value){this.active=value}},setAttribute(name,value){this[name]=value}}};
 const c=vm.createContext({state:{desktop:true},window:{},document:{querySelectorAll:()=>tabs},$:id=>nodes[id],
  playhead:0,zoom:70,selectedId:null,selectedAssetId:null,insTab:'clip',snap:true,useProxies:true,undoStack:[],redoStack:[],
  clamp:(v,a,b)=>Math.max(a,Math.min(b,v)),duration:()=>10,redraw:()=>{},nativeQualityOptions:()=>{},positionPlayhead:()=>{},syncPreview:()=>{},toast:()=>{},
  request:async path=>path==='desktop/recovery'?{epoch:4,restore:{insTab:'project',snap:false,useProxies:false,source:'original',engine:'rendered',resolution:'960',playhead:3,undo:[{tracks:[],name:'legacy'}],redo:[]}}:{ready:true}});
 vm.runInContext(fs.readFileSync('web/recovery.js','utf8'),c);await vm.runInContext('recoveryInitialize()',c);
 assert.equal(c.insTab,'project');assert.equal(c.playhead,3);assert.equal(tabs[1].classList.active,true);
 assert.equal(nodes.snapBtn.classList.active,false);assert.equal(nodes.snapBtn['aria-pressed'],'false');assert.equal(nodes.previewSource.value,'original');
 assert.equal(c.undoStack[0].name,'legacy');
});
