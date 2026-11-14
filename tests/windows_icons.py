"""Inspect MSI, installed shortcuts, shell extraction and the live WinForms icon."""
import argparse,ctypes as c,hashlib,json,os,struct,sys
from ctypes import wintypes as w
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks'))
from windows_session import session
from icon_assets import verify_assets,verify_executable

def msi_icon(path):
    m=c.WinDLL('msi');db=w.UINT();view=w.UINT();record=w.UINT()
    m.MsiOpenDatabaseW.argtypes=[w.LPCWSTR,w.LPCWSTR,c.POINTER(w.UINT)]
    m.MsiDatabaseOpenViewW.argtypes=[w.UINT,w.LPCWSTR,c.POINTER(w.UINT)]
    assert m.MsiOpenDatabaseW(str(path.resolve()),None,c.byref(db))==0
    try:
        assert m.MsiDatabaseOpenViewW(db,'SELECT `Data` FROM `Icon`',c.byref(view))==0
        assert m.MsiViewExecute(view,0)==0 and m.MsiViewFetch(view,c.byref(record))==0
        result=bytearray()
        while True:
            buffer=c.create_string_buffer(65536);size=w.DWORD(len(buffer))
            assert m.MsiRecordReadStream(record,1,buffer,c.byref(size))==0
            if not size.value:break
            result.extend(buffer.raw[:size.value])
        m.MsiCloseHandle(record);record=w.UINT()
        assert m.MsiViewFetch(view,c.byref(record))==259,'Unexpected extra MSI icon'
        return bytes(result)
    finally:
        for handle in (record,view,db):
            if handle.value:m.MsiCloseHandle(handle)

def draw(handle,size):
    user=c.windll.user32;gdi=c.windll.gdi32
    user.DestroyIcon.argtypes=[w.HICON]
    gdi.CreateCompatibleDC.restype=w.HDC;gdi.CreateCompatibleDC.argtypes=[w.HDC]
    gdi.DeleteDC.argtypes=[w.HDC];gdi.DeleteObject.argtypes=[w.HANDLE]
    gdi.CreateDIBSection.restype=w.HBITMAP
    gdi.CreateDIBSection.argtypes=[w.HDC,c.c_void_p,w.UINT,c.POINTER(c.c_void_p),w.HANDLE,w.DWORD]
    gdi.SelectObject.restype=w.HANDLE;gdi.SelectObject.argtypes=[w.HDC,w.HANDLE]
    user.DrawIconEx.argtypes=[w.HDC,c.c_int,c.c_int,w.HICON,c.c_int,c.c_int,w.UINT,w.HBRUSH,w.UINT]
    dc=gdi.CreateCompatibleDC(None);bits=c.c_void_p()
    info=struct.pack('<IiiHHIIiiII',40,size,-size,1,32,0,size*size*4,0,0,0,0)
    bitmap=gdi.CreateDIBSection(dc,c.c_char_p(info),0,c.byref(bits),None,0);assert bitmap
    old=gdi.SelectObject(dc,bitmap)
    try:
        c.memset(bits,0,size*size*4)
        assert user.DrawIconEx(dc,0,0,handle,size,size,0,None,3)
        return Image.frombytes('RGBA',(size,size),c.string_at(bits,size*size*4),'raw','BGRA').convert('RGB')
    finally:
        gdi.SelectObject(dc,old);gdi.DeleteObject(bitmap);gdi.DeleteDC(dc)

def expected_handle(size):
    c.windll.user32.LoadImageW.restype=w.HANDLE
    c.windll.user32.LoadImageW.argtypes=[w.HINSTANCE,w.LPCWSTR,w.UINT,c.c_int,c.c_int,w.UINT]
    value=c.windll.user32.LoadImageW(None,str(ROOT/'web/branding/vlogcraft-approved.ico'),1,size,size,0x10)
    assert value;return value

def icon_dimensions(icon):
    class Info(c.Structure):
        _fields_=[('icon',w.BOOL),('x',w.DWORD),('y',w.DWORD),('mask',w.HBITMAP),('color',w.HBITMAP)]
    class Bitmap(c.Structure):
        _fields_=[('type',w.LONG),('width',w.LONG),('height',w.LONG),('stride',w.LONG),('planes',w.WORD),('bits',w.WORD),('data',c.c_void_p)]
    c.windll.user32.GetIconInfo.argtypes=[w.HICON,c.POINTER(Info)]
    c.windll.gdi32.GetObjectW.argtypes=[w.HANDLE,c.c_int,c.c_void_p]
    c.windll.gdi32.DeleteObject.argtypes=[w.HANDLE]
    info=Info();assert c.windll.user32.GetIconInfo(icon,c.byref(info))
    bitmap=Bitmap();assert c.windll.gdi32.GetObjectW(info.color,c.sizeof(bitmap),c.byref(bitmap))
    for handle in (info.mask,info.color):
        if handle:c.windll.gdi32.DeleteObject(handle)
    assert bitmap.width==bitmap.height
    return bitmap.width

def compare(handle,size):
    import numpy as np
    expected=expected_handle(size)
    try:
        error=float(np.abs(np.asarray(draw(handle,size),dtype=float)-np.asarray(draw(expected,size),dtype=float)).mean())
        assert error==0,('Icon differs from approved artwork',size,error)
        return error
    finally:c.windll.user32.DestroyIcon(expected)

def main(a):
    a.results.mkdir(parents=True,exist_ok=True)
    assert verify_assets() and verify_executable(a.executable)
    data=msi_icon(a.msi);assert data==(ROOT/'web/branding/vlogcraft-approved.ico').read_bytes()
    import subprocess
    script=r"""
$w=New-Object -ComObject WScript.Shell
$shell=New-Object -ComObject Shell.Application
$paths=@((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\VlogCraft Studio.lnk'),(Join-Path ([Environment]::GetFolderPath('Desktop')) 'VlogCraft Studio.lnk'))
$paths | ForEach-Object {
 $link=$w.CreateShortcut($_)
 $item=$shell.NameSpace((Split-Path -LiteralPath $_)).ParseName((Split-Path -Leaf $_))
 @{target=$link.TargetPath;icon=$link.IconLocation;app_id=$item.ExtendedProperty('System.AppUserModel.ID')}
} | ConvertTo-Json
"""
    links=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',script],text=True))
    errors=[]
    shell=c.windll.shell32
    shell.ExtractIconExW.argtypes=[w.LPCWSTR,c.c_int,c.POINTER(w.HICON),c.POINTER(w.HICON),w.UINT]
    for link in links:
        assert Path(link['target']).resolve()==a.executable.resolve()
        assert link['app_id']=='VlogCraft.Studio',link['app_id']
        icon,index=link['icon'].rsplit(',',1)
        assert Path(icon).read_bytes()==data
        big=w.HICON();small=w.HICON()
        assert shell.ExtractIconExW(str(a.executable),0,c.byref(big),c.byref(small),1)==2 and big and small
        try:errors.extend([compare(big,32),compare(small,16)])
        finally:
            c.windll.user32.DestroyIcon(big);c.windll.user32.DestroyIcon(small)
    live={}
    with session(a.executable,a.results/'window',offline=True) as (page,proc,project,browser_errors):
        import psutil
        family={proc.pid,*[p.pid for p in psutil.Process(proc.pid).children(recursive=True)]}
        handles=[]
        def visit(hwnd,_):
            pid=w.DWORD();c.windll.user32.GetWindowThreadProcessId(hwnd,c.byref(pid))
            title=c.create_unicode_buffer(256);c.windll.user32.GetWindowTextW(hwnd,title,256)
            if pid.value in family and title.value=='VlogCraft Studio • '+project.stem:handles.append(hwnd)
            return True
        callback=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)(visit);c.windll.user32.EnumWindows(callback,0)
        assert len(handles)==1
        c.windll.user32.SendMessageW.restype=w.LPARAM
        c.windll.user32.SendMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
        for kind,label in ((1,'taskbar_big'),(0,'window_small')):
            icon=c.windll.user32.SendMessageW(handles[0],0x7f,kind,0);assert icon,label
            size=icon_dimensions(icon)
            actual=draw(icon,size);expected=expected_handle(size)
            try:reference=draw(expected,size)
            finally:c.windll.user32.DestroyIcon(expected)
            actual.save(a.results/(label+'-actual.png'));reference.save(a.results/(label+'-expected.png'))
            live[label]={'native_size':size,'mean_error_255':compare(icon,size)}
        assert page.locator('link[rel=icon]').get_attribute('href')=='branding/vlogcraft-approved.ico'
        assert page.locator('.approved-brand').count()==2
        assert page.locator('.approved-brand').evaluate_all('(images)=>images.every(i=>i.complete&&i.naturalWidth>0)')
        assert not browser_errors
        page.locator('.topbar').screenshot(path=str(a.results/'header.png'))
    installed_icons=list(a.executable.parent.rglob('*.ico'))
    assert len(installed_icons)==1 and installed_icons[0].name=='vlogcraft-approved.ico',[p.name for p in installed_icons]
    report={'approved_source_preserved':True,'sizes':[16,24,32,48,64,128,256],'msi_icon_exact':True,
            'exe_seven_resources_exact':True,'shortcut_icon_bytes_exact':True,'shortcut_app_id':True,
            'shell_icon_mean_errors_255':errors,'live_icon_mean_errors_255':live,'web_branding':True,'old_installed_icon_files':0}
    (a.results/'icons.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('msi',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
