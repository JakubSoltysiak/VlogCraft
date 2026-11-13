"""Generated moving sources only. Optional large fixtures allocate ~12 GB."""
import argparse,json,subprocess,hashlib
from pathlib import Path
def create(path,command):
 if path.exists():raise FileExistsError('Refusing to overwrite an existing fixture: '+str(path))
 subprocess.run(['ffmpeg','-nostdin','-v','error',*command,str(path)],capture_output=True,check=True,timeout=240)
 print(json.dumps({'name':path.name,'bytes':path.stat().st_size}),flush=True)
def main(a):
 a.folder.mkdir(parents=True,exist_ok=True)
 if a.large_pairs:
  for n in range(2):
   path=a.folder/f'allocated-over5gib-{n}.mov'
   create(path,['-f','lavfi','-i',f'testsrc2=s=3840x2160:r=60:d=6','-f','lavfi','-i',f'sine=f={330+n*110}:r=48000:d=6',
     '-vf',f'hue=h={n*67}','-c:v','rawvideo','-pix_fmt','uyvy422','-threads','2','-c:a','pcm_s16le'])
   assert path.stat().st_size>5*1024**3
 else:
  for n in range(3):
   create(a.folder/f'h264-4k60-{n}.mp4',['-f','lavfi','-i','testsrc2=s=3840x2160:r=60:d=6','-f','lavfi','-i',f'sine=f={330+n*110}:r=48000:d=6',
    '-vf',f'hue=h={n*67}','-c:v','libx264','-threads','4','-preset','veryfast','-g','60','-bf','3','-crf','20',
    '-pix_fmt','yuv420p','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-c:a','aac','-movflags','+faststart'])
  create(a.folder/'hevc10-4k5994.mp4',['-f','lavfi','-i','testsrc2=s=3840x2160:r=60000/1001:d=6',
    '-c:v','libx265','-pix_fmt','yuv420p10le','-preset','ultrafast','-x265-params','pools=4:frame-threads=2:log-level=error',
    '-g','60','-bf','3','-crf','22','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709'])
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('--large-pairs',action='store_true');main(p.parse_args())
