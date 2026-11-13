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

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
RELEASE = ROOT / 'release'
VERSION = '3.4.7'
WIX_NS = 'http://schemas.microsoft.com/wix/2006/wi'
UPGRADE_CODE = '09FA364C-4D7B-4B43-A1CF-7D82A0B62F02'
ET.register_namespace('', WIX_NS)


def element(parent, tag, **attrs):
    return ET.SubElement(parent, '{' + WIX_NS + '}' + tag, attrs)


def identifier(prefix, path):
    return prefix + hashlib.sha256(str(path).casefold().encode()).hexdigest()[:28]


def build(wix,experimental_native=False):
    os.chdir(ROOT)
    RELEASE.mkdir(exist_ok=True)
    BUILD.mkdir(exist_ok=True)
    icon = BUILD / 'studio.ico'
    image = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    pen.rounded_rectangle((6, 6, 250, 250), radius=50, fill='#142536')
    pen.polygon([(44, 68), (80, 68), (124, 157), (175, 64), (210, 64), (141, 190), (110, 190)], fill='#99dfce')
    pen.rounded_rectangle((154, 179, 213, 189), radius=5, fill='#f2b678')
    image.save(icon, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    notices=BUILD/'notices'
    notices.mkdir(exist_ok=True)
    for name in ('pywebview','pythonnet','clr-loader','bottle','proxy_tools','opencv-python-headless',
                 'numpy','Pillow','cffi','typing-extensions','pycparser'):
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
                    '--icon', str(icon), '--add-data', 'web;web', '--add-data',str(notices)+';notices',
                    '--add-data', str(engine / 'ffmpeg.exe') + ';engine',
                    '--add-data', str(engine / 'ffprobe.exe') + ';engine',
                    '--add-data', str(engine.parent / 'LICENSE') + ';engine',
                    '--collect-data', 'webview', '--exclude-module', 'playwright',
                    '--exclude-module', 'tkinter', 'desktop.py'], check=True)
    bundle = ROOT / 'dist' / 'VlogCraftStudio'
    if experimental_native:
        import json
        runtime=ROOT/'build/tools/architecture'
        sdk=runtime/'ffmpeg-shared/ffmpeg-9.0.2-full_build-shared'
        executable=runtime/'VlogCraftNative.exe'
        if not executable.is_file() or not (sdk/'bin').is_dir():
            raise RuntimeError('Build the optional native runtime with tools/setup_architecture_lab.py first')
        target=bundle/'_internal/engine/native';target.mkdir(parents=True,exist_ok=True)
        shutil.copy2(executable,target/executable.name)
        for name in ('VlogCraftProbe.exe','VlogCraftStorageProbe.exe'):shutil.copy2(runtime/name,target/name)
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
    element(product, 'Icon', Id='studio.ico', SourceFile=str(icon))
    element(product, 'Property', Id='ARPPRODUCTICON', Value='studio.ico')
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
        element(c, 'Shortcut', Id=label + 'Link', Name='VlogCraft Studio',
                Target='[INSTALLDIR]VlogCraftStudio.exe', WorkingDirectory='INSTALLDIR', Icon='studio.ico')
        element(c, 'RegistryValue', Root='HKCU', Key=r'Software\VlogCraft\Studio', Name=label,
                Type='integer', Value='1', KeyPath='yes')
    element(product, 'WixVariable', Id='WixUILicenseRtf', Value=str(ROOT/'packaging'/'notice.rtf'))
    element(product, 'UIRef', Id='WixUI_FeatureTree')
    source = BUILD / 'studio.wxs'
    ET.ElementTree(root).write(source, encoding='utf-8', xml_declaration=True)
    obj = BUILD / 'studio.wixobj'
    subprocess.run([str(wix / 'candle.exe'), '-nologo', '-out', str(obj), str(source)], check=True)
    subprocess.run([str(wix / 'light.exe'), '-nologo', '-sval', '-spdb', '-ext', 'WixUIExtension',
                    '-out', str(RELEASE / f'VlogCraft-Studio-{".".join(VERSION.split(".")[:2])}-x64.msi'), str(obj)], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--wix', type=Path, default=BUILD / 'tools' / 'wix')
    parser.add_argument('--experimental-native',action='store_true',help='Bundle the already compiled local native runtime; keep the default renderer')
    options=parser.parse_args();build(options.wix,options.experimental_native)
