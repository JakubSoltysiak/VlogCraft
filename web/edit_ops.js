/* All operations edit a private copy. A rejected edit leaves the caller's timeline intact. */
function editTimeline(tracks, assetList, fps, ids, command, args={}, makeId=()=>crypto.randomUUID().replaceAll('-','')) {
  const result=structuredClone(tracks);
  const assets=new Map(assetList.map(a=>[a.id,a]));
  const entries=result.flatMap(track=>track.clips.map(clip=>({track,clip})));
  const chosen=new Set(ids);
  const links=new Set(entries.filter(e=>chosen.has(e.clip.id)&&e.clip.linkId).map(e=>e.clip.linkId));
  const selection=entries.filter(e=>chosen.has(e.clip.id)||links.has(e.clip.linkId));
  const selected=selection.map(e=>e.clip.id);
  const frame=t=>Math.round(t*fps), seconds=n=>n/fps;
  const first=c=>frame(c.position), last=c=>frame(c.position+(c.end-c.start)/c.speed);
  const n=args.frames??0;
  if(!Number.isSafeInteger(n))throw Error('Enter a whole number of sequence frames');
  function unlocked(t,c){
    if(c?.kind==='sequence' && !['move','delete','duplicate'].includes(command))throw Error('Expand the sequence to edit its source ranges');
    if(t.locked||c?.locked)throw Error('The edit touches a locked clip or track');
  }
  function validate(c){
    if(first(c)<0||last(c)<=first(c)||c.start< -1e-9)throw Error('At least one frame of media must remain');
    const a=assets.get(c.assetId);
    if(a && a.kind!=='image' && c.end>a.duration+1e-7)throw Error('The edit exceeds the source handle');
  }
  function left(c,at){
    const d=seconds(at-first(c))*c.speed;
    if(c.kind==='title'||c.kind==='image'){
      c.end-=d;
      if(c.keys && d!==0)for(const [prop,keys] of Object.entries(c.keys)){
        const current=interpolate(keys,c[prop],d);
        c.keys[prop]=[{time:0,value:current,mode:'linear'},...keys.filter(k=>k.time>d).map(k=>({...k,time:k.time-d}))];
      }
    }else c.start+=d;
    c.position=seconds(at);validate(c);
  }
  function right(c,at){
    c.end=c.start+seconds(at-first(c))*c.speed;validate(c);
  }
  function split(t,c,at,linkMap){
    if(at<=first(c)||at>=last(c))throw Error('Place the playhead inside each selected clip');
    const tail=structuredClone(c);tail.id=makeId();
    left(tail,at);right(c,at);c.fadeOut=0;tail.fadeIn=0;
    if(c.linkId){
      if(!linkMap.has(c.linkId))linkMap.set(c.linkId,makeId());
      tail.linkId=linkMap.get(c.linkId);
    }
    t.clips.push(tail);return tail;
  }
  function neighbor(t,c,before){
    const matches=t.clips.filter(other=>other!==c && (before?last(other)===first(c):first(other)===last(c)));
    if(matches.length!==1)throw Error('This edit needs a single adjacent clip at the cut');
    const other=matches[0];unlocked(t,other);
    if(other.linkId)throw Error('Unlink the adjacent clip before changing its handle independently');
    return other;
  }
  if(command==='insert'||command==='overwrite'){
    const track=result.find(t=>t.id===args.trackId);if(!track)throw Error('Choose a destination track');
    unlocked(track);
    const fresh=structuredClone(args.clip);const at=args.at;
    if(!Number.isSafeInteger(at)||at<0)throw Error('Invalid insertion frame');
    fresh.position=seconds(at);validate(fresh);
    const end=last(fresh),span=end-at;
    for(const c of track.clips.slice()){
      const a=first(c),b=last(c);
      if(b<=at||(command==='overwrite'&&a>=end))continue;
      unlocked(track,c);
      if(c.linkId)throw Error('The edit would separate linked media. Choose another range or unlink it.');
      if(command==='insert'){
        if(a>=at)c.position=seconds(a+span);
        else split(track,c,at,new Map()).position=seconds(end);
      }else if(a<at && b>end){
        const tail=structuredClone(c);tail.id=makeId();left(tail,end);right(c,at);track.clips.push(tail);
      }else if(a<at)right(c,at);
      else if(b>end)left(c,end);
      else track.clips.splice(track.clips.indexOf(c),1);
    }
    track.clips.push(fresh);return {tracks:result,ids:[fresh.id]};
  }
  if(!selection.length)throw Error('Select a timeline clip');
  for(const {track,clip} of selection)unlocked(track,clip);
  const idMap=new Map();
  const nextIds=[];
  const groupStart=Math.min(...selection.map(e=>first(e.clip)));
  const groupEnd=Math.max(...selection.map(e=>last(e.clip)));
  const groupLink=command==='link'?makeId():null;
  if(command==='link' && selection.length<2)throw Error('Select two or more clips to link');
  for(const {track,clip:c} of selection){
    switch(command){
      case 'move':
        c.position=seconds(first(c)+n);validate(c);break;
      case 'trimLeft':left(c,first(c)+n);break;
      case 'trimRight':right(c,last(c)+n);break;
      case 'split':nextIds.push(split(track,c,args.at,idMap).id);break;
      case 'slip':
        if(c.kind==='image'||c.kind==='title')throw Error('Slip requires timed source media');
        c.start+=seconds(n)*c.speed;c.end+=seconds(n)*c.speed;validate(c);break;
      case 'roll':{
        const after=neighbor(track,c,false),boundary=last(c)+n;
        right(c,boundary);left(after,boundary);break;
      }
      case 'slide':{
        const before=neighbor(track,c,true),after=neighbor(track,c,false);
        right(before,first(c)+n);left(after,last(c)+n);c.position=seconds(first(c)+n);validate(c);break;
      }
      case 'delete':track.clips.splice(track.clips.indexOf(c),1);break;
      case 'duplicate':{
        const copy=structuredClone(c);copy.id=makeId();copy.position=seconds(first(c)+groupEnd-groupStart);
        if(copy.linkId){if(!idMap.has(copy.linkId))idMap.set(copy.linkId,makeId());copy.linkId=idMap.get(copy.linkId);}
        track.clips.push(copy);nextIds.push(copy.id);break;
      }
      case 'link':c.linkId=groupLink;break;
      case 'unlink':delete c.linkId;break;
      case 'extractAudio':{
        if(c.kind!=='video'||!assets.get(c.assetId)?.hasAudio||c.audioDetached||c.linkId)throw Error('Select an unlinked video with camera audio');
        let dest=result.find(t=>t.type==='audio'&&!t.locked && !t.clips.some(x=>last(x)>first(c)&&first(x)<last(c)));
        if(!dest){dest={id:makeId(),type:'audio',name:'Camera audio',muted:false,hidden:false,locked:false,volume:1,clips:[]};result.push(dest);}
        const audio=structuredClone(c);audio.id=makeId();audio.kind='audio';audio.linkId=c.linkId=makeId();c.audioDetached=true;
        dest.clips.push(audio);nextIds.push(c.id,audio.id);break;
      }
      default:throw Error('Unknown timeline operation');
    }
  }
  return {tracks:result,ids:command==='delete'?[]:nextIds.length?nextIds:selected};
}
function interpolate(keys,fallback,time){
  return typeof curveValue==='function'?curveValue(keys,fallback,time):fallback;
}
if(typeof module!=='undefined')module.exports={editTimeline};
