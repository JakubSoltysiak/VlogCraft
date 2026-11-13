"""Fetch pinned optional lab tools into ignored build storage; never install globally."""
import argparse,hashlib,json,subprocess,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPECS={
 'ffmpeg-shared':('https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full-shared.7z','4d2060a8b34a940aa47d785142055bb92a63053781e55f2ace4546edd519a8f5'),
 'zig':('https://ziglang.org/download/0.17.1/zig-x86_64-windows-0.17.1.zip','b03f477a1943673e02aca0f570e8030dffd536ce1f45cbc4d3326ec31159562e'),
 'shotcut':('https://github.com/mltframework/shotcut/releases/download/v26.9.27/shotcut-win64-26.9.27.zip','1f8c50ce7b125a2f0dcb60777b358e86baf03b8515982612b6adae10a83d93a5')
}
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as file:
  while chunk:=file.read(1024*1024):h.update(chunk)
 return h.hexdigest()
def setup(name,folder):
 url,sha=SPECS[name];archive=folder/url.rsplit('/',1)[-1]
 if not archive.is_file() or digest(archive)!=sha:
  with urllib.request.urlopen(url,timeout=60) as response,archive.open('wb') as file:
   while chunk:=response.read(1024*1024):file.write(chunk)
 if digest(archive)!=sha:raise RuntimeError(name+' archive checksum differs from qualified build')
 destination=folder/name;destination.mkdir(exist_ok=True)
 stamp=destination/'qualified-archive.json'
 if not stamp.is_file() or json.loads(stamp.read_text()).get('sha256')!=sha:
  if archive.suffix=='.zip':
   with zipfile.ZipFile(archive) as entries:
    for entry in entries.infolist():
     if not (destination/entry.filename).resolve().is_relative_to(destination.resolve()):raise ValueError('Archive path escapes lab storage')
    entries.extractall(destination)
  else:subprocess.run(['tar','-xf',str(archive),'-C',str(destination)],check=True)
  stamp.write_text(json.dumps({'url':url,'sha256':sha},indent=2))
 print(json.dumps({'component':name,'sha256':sha}),flush=True)
def build(folder):
 sdk=folder/'ffmpeg-shared/ffmpeg-9.0.2-full_build-shared'
 zig=folder/'zig/zig-x86_64-windows-0.17.1/zig.exe'
 cmd=[str(zig),'c++','-std=c++17','-O2','-target','x86_64-windows-gnu',
      str(ROOT/'experiments/native_d3d11/main.cpp'),'-I'+str(sdk/'include'),'-L'+str(sdk/'lib'),
      '-lavformat','-lavcodec','-lavutil','-lswscale','-ld3d11','-ldxgi','-o',str(folder/'native_d3d11.exe')]
 subprocess.run(cmd,cwd=ROOT,check=True)
 print(json.dumps({'native_binary_sha256':digest(folder/'native_d3d11.exe')}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--component',choices=list(SPECS),action='append');p.add_argument('--build-native',action='store_true')
 a=p.parse_args();folder=ROOT/'build/tools/architecture';folder.mkdir(parents=True,exist_ok=True)
 for component in a.component or SPECS:setup(component,folder)
 if a.build_native:build(folder)
