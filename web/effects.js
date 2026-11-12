function effectControls(c){
  return '<details class="fx-panel"><summary>Color, mask and chroma key</summary>'+
    range('Brightness','brightness',c.brightness??0,-1,1,.01,false)+range('Contrast','contrast',c.contrast??1,0,2,.01,false)+range('Saturation','saturation',c.saturation??1,0,3,.01,false)+
    '<div class="property"><label>Mask</label><select data-prop="mask"><option value="none">None</option><option value="ellipse" '+(c.mask==='ellipse'?'selected':'')+'>Ellipse</option></select></div>'+
    range('Mask radius','maskRadius',c.maskRadius??.5,.01,1,.01)+range('Edge feather','feather',c.feather??.1,0,1,.01)+
    '<div class="property"><label><input type="checkbox" data-prop="chroma" '+(c.chroma?'checked':'')+'> Chroma key</label></div>'+
    '<div class="property"><label>Key color</label><input type="color" data-prop="keyColor" value="'+(c.keyColor||'#00ff00')+'"></div>'+
    range('Similarity','similarity',c.similarity??.16,.01,1,.01)+range('Key blend','keyBlend',c.keyBlend??.08,0,1,.01)+'</details>';
}
function liveEffects(player,c){
  const m=player.media;
  const transform='translate('+animated(c,'x')*100+'%,'+animated(c,'y')*100+'%) rotate('+animated(c,'rotation')+'deg) scale('+animated(c,'scale')+')';
  const color=(gradeFilters[c.grade]||'')+' brightness('+Math.max(0,1+animated(c,'brightness'))+') contrast('+animated(c,'contrast')+') saturate('+animated(c,'saturation')+')';
  let surface=m;
  const lut=gradeTable(c);
  if((c.chroma||lut) && (m.videoWidth||m.naturalWidth) && (m.readyState===undefined||m.readyState>=2)){
    if(!player.keySurface){
      player.keySurface=document.createElement('canvas');player.keySurface.className='key-surface';player.wrap.appendChild(player.keySurface);
    }
    const canvas=player.keySurface;
    const stamp=[m.currentTime,c.chroma,lut?.key,c.keyColor,c.similarity,c.keyBlend].join('/');
    if(stamp!==player.keyStamp || canvas.hidden){
      const sw=m.videoWidth||m.naturalWidth,sh=m.videoHeight||m.naturalHeight;
      const w=Math.min(sw,480),h=Math.max(1,Math.round(w*sh/sw));
      if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
      const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(m,0,0,w,h);
      const pixels=ctx.getImageData(0,0,w,h),d=pixels.data;
      const key=parseInt((c.keyColor||'#00ff00').slice(1),16),r=key>>16,g=(key>>8)&255,b=key&255;
      const threshold=c.similarity??.16,blend=c.keyBlend??.08;
      for(let i=0;i<d.length;i+=4){
        if(lut)sampleLookup(d,i,lut);
        if(!c.chroma)continue;
        const distance=Math.hypot(d[i]-r,d[i+1]-g,d[i+2]-b)/441.67296;
        d[i+3]*=blend>0?clamp((distance-threshold)/blend,0,1):Number(distance>threshold);
      }
      ctx.putImageData(pixels,0,0);player.keyStamp=stamp;
    }
    canvas.hidden=false;m.style.opacity='0';surface=canvas;
  }else{if(player.keySurface)player.keySurface.hidden=true;m.style.opacity='1';}
  surface.style.objectFit=c.fit==='cover'?'cover':'contain';surface.style.filter=color;surface.style.transform=transform;
  const remaining=100*(1-clamp((playhead-c.position)/(c.wipeDuration||.5),0,1))+'%';
  const edges={right:'0 '+remaining+' 0 0',left:'0 0 0 '+remaining,down:'0 0 '+remaining+' 0',up:remaining+' 0 0 0'};
  surface.style.clipPath=edges[c.wipe]?'inset('+edges[c.wipe]+')':'none';
  const radius=animated(c,'maskRadius')*100;
  surface.style.maskImage=c.mask==='ellipse'?'radial-gradient(ellipse '+radius+'% '+radius+'% at center,#000 '+(100*(1-(c.feather??.1)))+'%,transparent 100%)':'none';
}
