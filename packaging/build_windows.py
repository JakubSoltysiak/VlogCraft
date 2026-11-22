"""Run with the build venv's Python from the repository root."""
import argparse
import hashlib
import importlib.metadata
import os
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_version import VERSION

BUILD = ROOT / 'build'
RELEASE = ROOT / 'release'
WIX_NS = 'http://schemas.microsoft.com/wix/2006/wi'
UPGRADE_CODE = '09FA364C-4D7B-4B43-A1CF-7D82A0B62F02'
ET.register_namespace('', WIX_NS)


def element(parent, tag, **attrs):
    return ET.SubElement(parent, '{' + WIX_NS + '}' + tag, attrs)


def identifier(prefix, path):
    return prefix + hashlib.sha256(str(path).casefold().encode()).hexdigest()[:28]


def executable_version():
    file = BUILD/'studio-version.txt'
    parts = tuple(map(int,VERSION.split('.'))) + (0,)
    file.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={parts}, prodvers={parts}, mask=0x3f,
    flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', 'VlogCraft Studio'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('ProductName', 'VlogCraft Studio'),
      StringStruct('ProductVersion', '{VERSION}')
    ])]),
    VarFileInfo([VarStruct('Translation', [1033,1200])])
  ]
)\n""",encoding='utf-8')
    return file


def build(wix,experimental_native=False,experimental_project_export=False):
    os.chdir(ROOT)
    RELEASE.mkdir(exist_ok=True)
    BUILD.mkdir(exist_ok=True)
    sys.path.insert(0, str(ROOT / 'tools'))
    from build_branding import build as build_branding
    build_branding()
    icon = ROOT / 'web/branding/vlogcraft-approved.ico'
    notices=BUILD/'notices'
    notices.mkdir(exist_ok=True)
    for name in ('pywebview','pythonnet','clr-loader','bottle','proxy_tools','opencv-python-headless',
                 'numpy','Pillow','cffi','typing-extensions','pycparser','psutil'):
        dist=importlib.metadata.distribution(name)
        for entry in dist.files or []:
            if ('license' in entry.name.lower() or 'copying' in entry.name.lower()) and entry.suffix.lower() not in ('.py','.pyc'):
                original=Path(dist.locate_file(entry))
                if original.is_file():
                    dest=notices/name/str(entry).replace('..','_')
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(original,dest)
    shutil.copy2(Path(sys.base_prefix)/'LICENSE.txt',notices/'Python-LICENSE.txt')
    engine = Path(shutil.which('ffmpeg')).parent
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--noupx',
                    '--log-level', 'WARN', '--onedir', '--windowed', '--name', 'VlogCraftStudio',
                    '--icon', str(icon), '--version-file', str(executable_version()),
                    '--add-data', 'web;web', '--add-data',str(notices)+';notices',
                    '--add-data', str(engine / 'ffmpeg.exe') + ';engine',
                    '--add-data', str(engine / 'ffprobe.exe') + ';engine',
                    '--add-data', str(engine.parent / 'LICENSE') + ';engine',
                    '--collect-data', 'webview', '--exclude-module', 'playwright',
                    '--exclude-module', 'sitecustomize', '--exclude-module', 'benchmarks',
                    '--exclude-module', 'tkinter', 'desktop.py'], check=True)
    bundle = ROOT / 'dist' / 'VlogCraftStudio'
    if experimental_native or experimental_project_export:
        import json
        runtime=ROOT/'build/tools/architecture'
        sdk=runtime/'ffmpeg-shared/ffmpeg-9.0.2-full_build-shared'
        binaries=[]
        if experimental_native:
            binaries.extend(('VlogCraftNative.exe','VlogCraftProbe.exe','VlogCraftStorageProbe.exe'))
        if experimental_project_export:
            binaries.extend(('VlogCraftProject.exe','hdr-statistics.dll'))
        if not all((runtime/name).is_file() for name in binaries) or not (sdk/'bin').is_dir():
            raise RuntimeError('Build the selected optional native runtime with tools/setup_architecture_lab.py first')
        target=bundle/'_internal/engine/native';target.mkdir(parents=True,exist_ok=True)
        for name in binaries:shutil.copy2(runtime/name,target/name)
        for library in (sdk/'bin').glob('*.dll'):shutil.copy2(library,target/library.name)
        for license_file in sdk.glob('LICENSE*'):shutil.copy2(license_file,target/license_file.name)
        manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir() if p.is_file()}
        (target/'runtime.json').write_text(json.dumps({'files':manifest,'experimental':True,'default':False},indent=2))
    root = ET.Element('{' + WIX_NS + '}Wix')
    product = element(root, 'Product', Id='*', Name='VlogCraft Studio', Language='1033',
                      Version=VERSION, Manufacturer='VlogCraft Private', UpgradeCode=UPGRADE_CODE)
    element(product, 'Package', InstallerVersion='500', Compressed='yes', InstallScope='perUser', Platform='x64')
    element(product, 'MajorUpgrade', DowngradeErrorMessage='A newer VlogCraft Studio is installed.')
    element(product, 'MediaTemplate', EmbedCab='yes', CompressionLevel='medium')
    element(product, 'Icon', Id='VlogCraftApproved.ico', SourceFile=str(icon))
    element(product, 'Property', Id='ARPPRODUCTICON', Value='VlogCraftApproved.ico')
    target = element(product, 'Directory', Id='TARGETDIR', Name='SourceDir')
    local = element(target, 'Directory', Id='LocalAppDataFolder')
    apps = element(local, 'Directory', Id='UserPrograms', Name='Programs')
    install = element(apps, 'Directory', Id='INSTALLDIR', Name='VlogCraft Studio')
    menu = element(target, 'Directory', Id='ProgramMenuFolder')
    desktop = element(target, 'Directory', Id='DesktopFolder')
    core = element(product, 'Feature', Id='Editor', Title='VlogCraft Studio', Level='1', Absent='disallow')
    optional = element(product, 'Feature', Id='DesktopShortcut', Title='Desktop shortcut', Level='1')
    dirs = {bundle: install}
    def component(directory, key, feature):
        cid = identifier('C', key)
        guid = str(uuid.uuid5(uuid.UUID(UPGRADE_CODE), str(key).casefold()))
        element(feature, 'ComponentRef', Id=cid)
        return element(directory, 'Component', Id=cid, Guid=guid, Win64='yes')
    for path in sorted(bundle.rglob('*')):
        relative = path.relative_to(bundle)
        if path.is_dir():
            dirs[path] = element(dirs[path.parent], 'Directory', Id=identifier('D', relative), Name=path.name)
        else:
            c = component(dirs[path.parent], relative, core)
            element(c, 'File', Id=identifier('F', relative), Source=str(path), KeyPath='yes')
    for directory, label, feature in ((menu, 'StartMenu', core), (desktop, 'Desktop', optional)):
        c = component(directory, label, feature)
        shortcut = element(c, 'Shortcut', Id=label + 'Link', Name='VlogCraft Studio',
                Target='[INSTALLDIR]VlogCraftStudio.exe', WorkingDirectory='INSTALLDIR', Icon='VlogCraftApproved.ico', IconIndex='0')
        element(shortcut, 'ShortcutProperty', Key='System.AppUserModel.ID', Value='VlogCraft.Studio')
        element(c, 'RegistryValue', Root='HKCU', Key=r'Software\VlogCraft\Studio', Name=label,
                Type='integer', Value='1', KeyPath='yes')
    element(product, 'WixVariable', Id='WixUILicenseRtf', Value=str(ROOT/'packaging'/'notice.rtf'))
    element(product, 'UIRef', Id='WixUI_FeatureTree')
    source = BUILD / 'studio.wxs'
    ET.ElementTree(root).write(source, encoding='utf-8', xml_declaration=True)
    obj = BUILD / 'studio.wixobj'
    subprocess.run([str(wix / 'candle.exe'), '-nologo', '-out', str(obj), str(source)], check=True)
    subprocess.run([str(wix / 'light.exe'), '-nologo', '-sval', '-spdb', '-ext', 'WixUIExtension',
                    '-out', str(RELEASE / f'VlogCraft-Studio-{VERSION}-x64.msi'), str(obj)], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--wix', type=Path, default=BUILD / 'tools' / 'wix')
    parser.add_argument('--experimental-native',action='store_true',help='Bundle the already compiled local native runtime; keep the default renderer')
    parser.add_argument('--experimental-project-export',action='store_true',help='Bundle the opt-in project renderer for development qualification')
    options=parser.parse_args();build(options.wix,options.experimental_native,options.experimental_project_export)
