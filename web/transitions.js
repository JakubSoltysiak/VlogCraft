const boundaryNames={
  video:{dissolve:'Dissolve','dip-black':'Dip to black','dip-white':'Dip to white'},
  audio:{linear:'Linear crossfade','equal-power':'Equal-power crossfade'},
};
const boundaryDrag='application/x-vlogcraft-transition';

function previousBoundaryClip(track, right){
  const clips=[...track.clips].sort((a,b)=>a.position-b.position);
  return clips[clips.indexOf(right)-1];
}

function defaultBoundaryKey(type){
  return type==='video'?'defaultVideoTransition':'defaultAudioTransition';
}

function applyDefaultBoundary(track,right){
  const value=state.output[defaultBoundaryKey(track.type)],left=previousBoundaryClip(track,right);
  if(!value || !left || left.locked || (track.type==='video'&&!state.output.color))return;
  const cut=frameIndex(right.position), before=Math.floor(value.frames/2),after=value.frames-before;
  if(frameIndex(endOf(left))!==cut||cut-before<frameIndex(left.position)||cut+after>frameIndex(endOf(right)))return;
  const incoming=assetById(right.assetId),outgoing=assetById(left.assetId);
  const isStill=c=>c.kind==='image'||c.kind==='title';
  if(track.type==='audio'&&(!incoming?.hasAudio || !outgoing?.hasAudio))return;
  if(!isStill(left)&&(!outgoing||(outgoing.videoEnd||outgoing.duration)-left.end+1e-9<after/sequenceRate()*left.speed))return;
  if(!isStill(right)&&right.start+1e-9<before/sequenceRate()*right.speed)return;
  if(track.clips.some(c=>c!==left&&c!==right&&frameIndex(c.position)<cut+after&&frameIndex(endOf(c))>cut-before))return;
  if(left.transitionIn&&Math.ceil(left.transitionIn.frames/2)+frameIndex(left.position)>cut-before)return;
  right.transitionIn={...value,from:left.id};
}

function transitionsOnTimeline(){
  const contains=tracks=>tracks.some(t=>t.clips.some(c=>c.transitionIn||(c.kind==='sequence'&&contains(c.children))));
  return contains(state.tracks);
}

function boundaryBadge(track,clip){
  if(!clip.transitionIn)return '';
  const setting=clip.transitionIn, label=boundaryNames[track.type][setting.kind];
  if(!label)return '';
  const x=atFrame(frameIndex(clip.position)-Math.floor(setting.frames/2))*zoom;
  const width=Math.max(16,setting.frames/sequenceRate()*zoom);
  return `<button class="boundary-badge" type="button" data-boundary-track="${track.id}" data-boundary-clip="${clip.id}" style="left:${Math.max(0,x)}px;width:${width}px" aria-label="${label}, ${setting.frames} frames" title="${label} · ${setting.frames} frames">⋈</button>`;
}

function bindBoundaryMarkers(){
  $('timelineContent').querySelectorAll('[data-boundary-clip]').forEach(button=>{
    button.onpointerdown=event=>event.stopPropagation();
    button.onclick=event=>{
      event.stopPropagation();
      const track=trackById(button.dataset.boundaryTrack);
      const clip=track.clips.find(c=>c.id===button.dataset.boundaryClip);
      openBoundaryTransition(track,clip);
    };
  });
}

function dropBoundary(event,lane){
  if(!event.dataTransfer.types.includes(boundaryDrag))return false;
  event.preventDefault();event.stopPropagation();
  const x=event.clientX-lane.getBoundingClientRect().left;
  const track=trackById(lane.dataset.lane);
  const target=track?.clips.find(c=>Math.abs(c.position*zoom-x)<=16&&previousBoundaryClip(track,c));
  if(target)openBoundaryTransition(track,target);
  else toast('Drop the transition at the start of an incoming clip.',true);
  return true;
}

function setupBoundaryControl(){
  const button=$('boundaryBtn');
  button.onclick=()=>openBoundaryTransition();
  button.ondragstart=event=>{
    event.dataTransfer.setData(boundaryDrag,'choose');
    event.dataTransfer.effectAllowed='copy';
  };
}

function openBoundaryTransition(track=sel()?.track,right=sel()?.clip){
  const dialog=document.createElement('dialog');
  dialog.className='motion-dialog';
  dialog.innerHTML=`<form>
    <h2>Boundary transition</h2>
    <div class="property"><label>Apply to <select id="boundaryScope"><option value="selection">Selected incoming clips</option><option value="track">Selected track</option><option value="project">Whole project</option><option value="default">Newly placed clips</option></select></label></div>
    <div class="property"><label>Track type <select id="boundaryType"><option value="video">Video</option><option value="audio">Audio</option></select></label></div>
    <div class="property"><label>Transition <select id="boundaryKind"></select></label></div>
    <div class="prop-row"><div class="property"><label>Duration (frames)<input id="boundaryFrames" type="number" required min="2" max="360" value="12"></label></div>
    <div class="property" id="boundaryEaseField"><label>Easing <select id="boundaryEase"><option value="linear">Linear</option><option value="smooth">Ease in/out</option></select></label></div></div>
    <div class="property" id="boundaryLinkedField"><label>Camera audio <select id="boundaryLinked"><option value="none">Leave audio unchanged</option><option value="linear">Linear crossfade</option><option value="equal-power">Equal-power crossfade</option></select></label></div>
    <p class="dialog-note">The transition uses source frames on both sides of the cut. Shorten it or trim more source if there is insufficient footage. Video transitions use managed color and Composited playback.</p>
    <p id="boundaryStatus" class="dialog-note" role="status"></p>
    <div class="property-actions"><button type="button" class="button secondary">Close</button><button id="boundaryApply" class="button primary">Apply</button></div>
  </form>`;
  document.body.appendChild(dialog);
  const type=$('boundaryType'), scope=$('boundaryScope'), preset=$('boundaryKind'), status=$('boundaryStatus');
  const choose=()=>{
    const audio=type.value==='audio', value=scope.value==='default'
      ? state.output[defaultBoundaryKey(type.value)]
      : right?.transitionIn;
    preset.replaceChildren(...Object.entries(boundaryNames[type.value]).map(([id,label])=>new Option(label,id)),
                          new Option('Remove transition','remove'));
    if(value&&boundaryNames[type.value][value.kind]){
      preset.value=value.kind;
      $('boundaryFrames').value=value.frames;
      $('boundaryEase').value=value.ease;
      $('boundaryLinked').value=value.audio||'none';
    }
    $('boundaryEaseField').hidden=audio;
    $('boundaryLinkedField').hidden=audio||scope.value==='default';
  };
  type.value=track?.type||'video';
  if(!right)scope.value='project';
  type.onchange=scope.onchange=choose;
  choose();
  dialog.querySelector('[type=button]').onclick=()=>dialog.close();
  dialog.querySelector('form').onsubmit=async event=>{
    event.preventDefault();
    $('boundaryApply').disabled=true;
    try{
      const kind=preset.value, noTransition=kind==='remove';
      const settings={kind,frames:$('boundaryFrames').valueAsNumber,ease:type.value==='video'?$('boundaryEase').value:'linear'};
      if(scope.value==='default'){
        snapshot();
        if(noTransition)delete state.output[defaultBoundaryKey(type.value)];
        else state.output[defaultBoundaryKey(type.value)]=settings;
        await flushBoundaryEdit();
        dialog.close();toast('Default transition updated');return;
      }
      if(type.value==='video')settings.audio=$('boundaryLinked').value;
      const chosen=new Set([right?.id,...editingIds()]);
      const edits=[];
      for(const candidate of state.tracks){
        if(candidate.type!==type.value||(scope.value==='track'&&candidate!==track))continue;
        for(const incoming of candidate.clips){
          if(incoming.kind==='sequence'||(scope.value==='selection'&&!chosen.has(incoming.id)))continue;
          const outgoing=previousBoundaryClip(candidate,incoming);
          if(noTransition&&!incoming.transitionIn)continue;
          if(!noTransition&&(!outgoing||outgoing.kind==='sequence'))continue;
          edits.push({track:candidate.id,clip:incoming.id,transition:noTransition?null:{...settings,from:outgoing.id}});
        }
      }
      if(!edits.length)throw Error('Select an incoming clip at an eligible boundary.');
      await flushSave();
      const result=await request('transition/check','POST',{edits});
      if(result.accepted.length){
        snapshot();
        for(const edit of result.accepted){
          const clip=trackById(edit.track).clips.find(c=>c.id===edit.clip);
          if(edit.transition)clip.transitionIn=edit.transition;
          else delete clip.transitionIn;
        }
        await flushBoundaryEdit();
      }
      if(result.skipped.length){
        status.textContent=result.accepted.length+' changed · '+result.skipped.length+' skipped. '+result.skipped[0];
      }else{
        dialog.close();
        toast('Updated '+result.accepted.length+' transition(s)');
      }
    }catch(error){status.textContent=error.message;}
    finally{$('boundaryApply').disabled=false;}
  };
  dialog.onclose=()=>dialog.remove();
  dialog.showModal();
}

async function flushBoundaryEdit(){
  redraw();save();await flushSave();
}
