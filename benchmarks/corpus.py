"""Small independent synthetic recordings for timeline/transport stress."""
from pathlib import Path
import subprocess
def distinct(folder,count=32):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    paths=[]
    for n in range(count):
        path=folder/f'independent-{n:03d}.mp4'
        if not path.is_file():
            subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','testsrc2=s=1280x720:r=60:d=2',
                '-f','lavfi','-i',f'sine=f={220+13*n}:r=48000:d=2','-vf',f'hue=h={n*11}',
                '-c:v','libx264','-threads','2','-preset','ultrafast','-g','30','-bf','2','-crf','23',
                '-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(path)],capture_output=True,check=True,timeout=30)
        paths.append(path.resolve())
    return paths
SETUP="""assets=>{
    stopPlayback();refreshPlayers();state.assets=assets;state.output.fps=60;useProxies=false;
    state.tracks=[{id:uid(),type:'video',name:'Distinct video',volume:1,hidden:false,muted:false,locked:false,clips:[]},
                  {id:uid(),type:'audio',name:'Distinct audio',volume:1,hidden:false,muted:false,locked:false,clips:[]}];
    for(let n=0;n<1200;n++){const a=assets[n%assets.length],c=clipFromAsset(a,n*.5,'video');c.start=(n%3)*.5;c.end=c.start+.5;c.audioDetached=true;state.tracks[0].clips.push(c);}
    for(let n=0;n<300;n++){const a=assets[(n*7)%assets.length],c=clipFromAsset(a,n*2,'audio');c.start=0;c.end=2;c.volume=.3;state.tracks[1].clips.push(c);}
    selectedId=null;playhead=0;redraw();
}"""
