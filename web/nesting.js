function playbackTracks(tracks,offset=0,prefix='',gain=1,muted=false,hidden=false){
  if(!prefix&&!tracks.some(t=>t.clips.some(c=>c.kind==='sequence')))return tracks;
  const out=[],solo=tracks.some(t=>t.solo);
  for(const t of tracks){
    const layer={...t,id:prefix+t.id,volume:gain*t.volume,hidden:hidden||t.hidden,muted:muted||t.muted||(solo&&!t.solo),solo:false};
    const project=c=>({...c,id:prefix+c.id,position:offset+c.position});
    if(!t.clips.some(c=>c.kind==='sequence')){out.push({...layer,clips:t.clips.map(project)});continue;}
    for(const c of t.clips.slice().sort((a,b)=>a.position-b.position).reverse()){
      const id=prefix+c.id;
      if(c.kind==='sequence')out.push(...playbackTracks(c.children,offset+c.position,id+'/',layer.volume,layer.muted,layer.hidden));
      else out.push({...layer,id:layer.id+'/'+id,clips:[project(c)]});
    }
  }
  return out;
}
function nestEdit(tracks,ids,op,fps,makeId){
  const all=structuredClone(tracks);
  const links=new Set(all.flatMap(t=>t.clips.filter(c=>ids.includes(c.id)&&c.linkId).map(c=>c.linkId)));
  const chosen=c=>ids.includes(c.id)||links.has(c.linkId);
  const rows=all.filter(t=>t.clips.some(chosen));
  const picked=rows.flatMap(t=>t.clips.filter(chosen));
  if(!picked.length)throw Error('Select clips to nest');
  if(rows.some(t=>t.locked||t.clips.some(c=>chosen(c)&&c.locked)))throw Error('Unlock the selected clips and tracks');
  const frame=t=>Math.round(t*fps);
  if(op==='expand'){
    if(picked.length!==1||picked[0].kind!=='sequence')throw Error('Select one nested sequence to expand');
    const clip=picked[0],host=rows[0],at=all.indexOf(host);
    const children=clip.children,childSolo=children.some(t=>t.solo);
    const newIds=[],linkMap=new Map();
    for(const child of children){
      child.id=makeId();child.volume*=host.volume;
      if(child.volume>3)throw Error('Lower the parent gain before expanding this sequence');
      child.muted=child.muted||host.muted||(childSolo&&!child.solo);child.solo=!!host.solo;child.hidden=child.hidden||host.hidden;
      for(const c of child.clips){c.id=makeId();c.position=(frame(c.position)+frame(clip.position))/fps;newIds.push(c.id);
        if(c.linkId){if(!linkMap.has(c.linkId))linkMap.set(c.linkId,makeId());c.linkId=linkMap.get(c.linkId);}}
    }
    host.clips=host.clips.filter(c=>c!==clip);all.splice(at,host.clips.length?0:1,...children);
    return {tracks:all,ids:newIds};
  }
  const begin=Math.min(...picked.map(c=>frame(c.position))),end=Math.max(...picked.map(c=>frame(c.position+(c.end-c.start)/c.speed)));
  const at=all.indexOf(rows[0]),bottom=all.indexOf(rows.at(-1));
  if(all.slice(at,bottom+1).some(t=>t.type==='video'&&t.clips.some(c=>!chosen(c)&&frame(c.position)<end&&frame(c.position+(c.end-c.start)/c.speed)>begin)))
    throw Error('Include overlapping layers between the selected tracks to preserve stacking order');
  const children=rows.map(t=>{
    const clips=t.clips.filter(chosen);
    t.clips=t.clips.filter(c=>!chosen(c));
    for(const c of clips)c.position=(frame(c.position)-begin)/fps;
    return {...t,id:makeId(),clips};
  });
  const c={id:makeId(),kind:'sequence',assetId:null,name:'Nested sequence',position:begin/fps,start:0,end:(end-begin)/fps,speed:1,children};
  all.splice(at,0,{id:makeId(),type:'video',name:'Sequences',solo:rows.some(t=>t.solo),locked:false,hidden:false,muted:false,volume:1,clips:[c]});
  return {tracks:all,ids:[c.id]};
}
if(typeof module!=='undefined')module.exports={nestEdit,playbackTracks};
