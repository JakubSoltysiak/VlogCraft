"""Qualify the private per-user MSI lifecycle and preserve project/settings bytes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ['LOCALAPPDATA'])/'VlogCraft Studio'
EXE=Path(os.environ['LOCALAPPDATA'])/'Programs'/'VlogCraft Studio'/'VlogCraftStudio.exe'


def inventory():
    result={}
    if DATA.exists():
        for path in DATA.rglob('*'):
            if path.is_file() and path.suffix.lower() in ('.vlogcraft','.json','.bak'):
                result[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def msi(action,path,log):
    args=['msiexec',action,str(path),'/qn','/norestart','/L*v',str(log)]
    if action=='/i':args.append('ADDLOCAL=Editor,DesktopShortcut')
    result=subprocess.run(args,creationflags=subprocess.CREATE_NO_WINDOW,timeout=240)
    if result.returncode not in (0,3010):raise RuntimeError(f'MSI {action} returned {result.returncode}; see {log}')
    return result.returncode


def main(msi_path,results):
    results.mkdir(parents=True,exist_ok=True)
    sentinel=DATA/'Projects'/'Codex-33-lifecycle-sentinel.vlogcraft'
    sentinel.parent.mkdir(parents=True,exist_ok=True)
    document=json.dumps({'name':'Release retention sentinel','version':3,'tracks':[]}).encode()
    with sentinel.open('xb') as file:file.write(document)
    before=inventory()
    report={}
    try:
        report['upgrade_exit']=msi('/i',msi_path,results/'upgrade.log')
        assert EXE.is_file()
        assert inventory()==before,'Project/settings bytes changed on upgrade'
        report['upgrade_preserved_projects_settings']=True
        report['uninstall_exit']=msi('/x',msi_path,results/'uninstall.log')
        assert not EXE.exists()
        assert inventory()==before,'Project/settings bytes changed on uninstall'
        report['uninstall_preserved_projects_settings']=True
        for link in (Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/VlogCraft Studio.lnk',Path.home()/'Desktop/VlogCraft Studio.lnk'):
            assert not link.exists(),str(link)
        report['removed_executable_shortcuts']=True
        report['reinstall_exit']=msi('/i',msi_path,results/'reinstall.log')
        assert EXE.is_file()
        assert inventory()==before,'Project/settings bytes changed on reinstall'
        report['reinstall_preserved_projects_settings']=True
        script=r"""$w=New-Object -ComObject WScript.Shell
$paths=@((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\VlogCraft Studio.lnk'),(Join-Path ([Environment]::GetFolderPath('Desktop')) 'VlogCraft Studio.lnk'))
$paths | ForEach-Object { @{path=$_;exists=(Test-Path -LiteralPath $_);target=$w.CreateShortcut($_).TargetPath} } | ConvertTo-Json
"""
        shortcuts=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',script],text=True))
        assert all(p['exists'] and Path(p['target'])==EXE for p in shortcuts),shortcuts
        report['shortcuts']=shortcuts
        report['protected_file_count']=len(before)
        report['msi_sha256']=hashlib.sha256(msi_path.read_bytes()).hexdigest()
        (results/'lifecycle.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
    finally:
        if sentinel.is_file() and sentinel.read_bytes()==document:sentinel.unlink()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('msi',type=Path);p.add_argument('results',type=Path)
    args=p.parse_args();main(args.msi.resolve(),args.results.resolve())
