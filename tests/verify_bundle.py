"""Prove packaged Python/web code and installed copy match the current source build."""
import argparse,hashlib,json,marshal,types
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader
ROOT=Path(__file__).resolve().parents[1]
MODULES=['app_version','server','export_scratch','render_engine','color_management','hdr_render','hdr_layers','hdr10plus_index','hdr10plus_export','hdr10plus_bitstream',
         'hdr10plus_authoring','hdr10plus_fast','hdr10plus_master','native_project_plan','native_project_render',
         'preview_cache','preview_dependencies','source_frames','timing','timeline_transitions','project_store',
         'animation','sequences','video_effects','grading','audio_cache','audio_edit','waveform',
         'motion','review_packet','timeline_proposal','ai_bridge','encoders','native_plan','native_playback','performance_profile','desktop_recovery']
def normalize(code):
 return code.replace(co_filename='<source>',co_consts=tuple(normalize(c) if isinstance(c,types.CodeType) else c for c in code.co_consts))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main(a):
 archive=CArchiveReader(str(a.bundle/'VlogCraftStudio.exe'));pyz=archive.open_embedded_archive('PYZ.pyz')
 checks={}
 checks['qa_modules_excluded']=not any(name=='sitecustomize' or name=='benchmarks' or name.startswith('benchmarks.') for name in pyz.toc)
 from icon_assets import verify_assets,verify_executable
 checks['approved_brand_assets']=verify_assets()
 checks['approved_exe_icon']=verify_executable(a.bundle/'VlogCraftStudio.exe')
 for name in MODULES:
  expected=compile((ROOT/(name+'.py')).read_bytes(),str(ROOT/(name+'.py')),'exec')
  checks[name]=normalize(pyz.extract(name))==normalize(expected)
 checks['desktop']=normalize(marshal.loads(archive.extract('desktop')))==normalize(compile((ROOT/'desktop.py').read_bytes(),str(ROOT/'desktop.py'),'exec'))
 checks['web']=all(digest(p)==digest(a.bundle/'_internal/web'/p.relative_to(ROOT/'web')) for p in (ROOT/'web').rglob('*') if p.is_file())
 runtime=a.bundle/'_internal/engine/native'
 if runtime.is_dir():
  manifest=json.loads((runtime/'runtime.json').read_text())['files'];checks['native_runtime']=all(digest(runtime/name)==sha for name,sha in manifest.items())
  if a.installed:checks['installed_native_runtime']=all(digest(a.installed/'_internal/engine/native'/name)==sha for name,sha in manifest.items())
 if a.installed:
  checks['installed_icon']=verify_executable(a.installed/'VlogCraftStudio.exe')
  checks['installed_executable']=digest(a.bundle/'VlogCraftStudio.exe')==digest(a.installed/'VlogCraftStudio.exe')
  checks['installed_web']=all(digest(p)==digest(a.installed/'_internal/web'/p.relative_to(ROOT/'web')) for p in (ROOT/'web').rglob('*') if p.is_file())
 a.result.parent.mkdir(parents=True,exist_ok=True);a.result.write_text(json.dumps(checks,indent=2));print(json.dumps(checks))
 assert all(checks.values()),checks
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('bundle',type=Path);p.add_argument('result',type=Path);p.add_argument('--installed',type=Path);main(p.parse_args())
