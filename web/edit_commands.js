let multiple=new Set();
function editingIds(){
  if(!selectedId)return [];
  return multiple.has(selectedId)?[...multiple]:[selectedId];
}
function chosenClip(id){return id===selectedId || (multiple.has(selectedId)&&multiple.has(id));}
function commitEdit(command,args={},ids=editingIds()){
  try{
    const change=editTimeline(state.tracks,state.assets,sequenceRate(),ids,command,args,uid);
    snapshot();state.tracks=change.tracks;multiple=new Set(change.ids);selectedId=change.ids[0]||null;
    redraw();save();return true;
  }catch(error){toast(error.message,true);redraw();return false;}
}
function commandDialog(){
  const current=sel();if(!current)return toast('Select a timeline clip',true);
  const dialog=document.createElement('dialog');dialog.className='motion-dialog';
  dialog.innerHTML='<form><h2>Timeline edit</h2><div class="property"><label>Operation</label><select name="command"><option value="roll">Roll outgoing cut</option><option value="slip">Slip source range</option><option value="slide">Slide between adjacent clips</option><option value="move">Move selection</option><option value="extractAudio">Separate and link camera audio</option><option value="link">Link selected clips</option><option value="unlink">Unlink selection</option></select></div><div class="property offset"><label>Offset in sequence frames</label><input name="offset" type="number" step="1" value="1"></div><p>Ctrl-click clips to select across tracks. Negative offsets move earlier.</p><div class="property-actions"><button type="button" class="button secondary">Cancel</button><button class="button primary">Apply</button></div></form>';
  document.body.appendChild(dialog);
  const form=dialog.querySelector('form'),f=form.elements;
  f.command.onchange=()=>dialog.querySelector('.offset').hidden=['link','unlink','extractAudio'].includes(f.command.value);
  dialog.querySelector('[type=button]').onclick=()=>dialog.close();
  form.onsubmit=e=>{e.preventDefault();if(commitEdit(f.command.value,{frames:f.offset.valueAsNumber}))dialog.close();};
  dialog.onclose=()=>dialog.remove();dialog.showModal();
}
