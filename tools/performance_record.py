"""Bind sanitized local performance evidence to the exact relevant source tree."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=['render_engine.py','native_plan.py','native_playback.py','performance_profile.py','desktop.py','server.py',
 'web/app.js','web/index.html','web/native_preview.js','web/native_audio_worklet.js','web/performance.js','web/rendered_preview.js',
 *[str(p.relative_to(ROOT)).replace('\\','/') for p in sorted((ROOT/'native').glob('*')) if p.suffix in ('.cpp','.h')]]
def fingerprint():
 h=hashlib.sha256()
 for name in sorted(FILES):
  data=(ROOT/name).read_bytes().replace(b'\r\n',b'\n');h.update(name.encode()+b'\0'+data+b'\0')
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('record',type=Path);p.add_argument('--stamp',action='store_true');a=p.parse_args()
 data=json.loads(a.record.read_text('utf8'))
 if a.stamp:
  data['source_fingerprint']=fingerprint();data['fingerprint_method']='SHA256 sorted relevant relative path + NUL + LF-normalized source + NUL'
  a.record.write_text(json.dumps(data,indent=2)+'\n',encoding='utf8')
 else:
  assert data.get('source_fingerprint')==fingerprint(),'Performance evidence does not match the relevant source tree; run the impacted performance profile and update the record'
  print(json.dumps({'performance_record_matches_source':True,'qualification':data.get('qualification','partial')}))
if __name__=='__main__':main()
