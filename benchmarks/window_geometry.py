"""Compare the HWND's physical bounds with the browser monitor at native DPI."""
import ctypes as ct
import psutil

class Rect(ct.Structure):_fields_=[('left',ct.c_long),('top',ct.c_long),('right',ct.c_long),('bottom',ct.c_long)]
class Point(ct.Structure):_fields_=[('x',ct.c_long),('y',ct.c_long)]
CALLBACK=ct.WINFUNCTYPE(ct.c_bool,ct.c_void_p,ct.c_void_p)

def owned_window(process):
 family={process.pid,*[p.pid for p in psutil.Process(process.pid).children(recursive=True)]};found=[]
 def visit(hwnd,_):
  pid=ct.c_ulong();ct.windll.user32.GetWindowThreadProcessId(ct.c_void_p(hwnd),ct.byref(pid))
  if pid.value in family:
   title=ct.create_unicode_buffer(256);ct.windll.user32.GetWindowTextW(ct.c_void_p(hwnd),title,256)
   if title.value.startswith('VlogCraft Studio • '):found.append(hwnd)
  return True
 callback=CALLBACK(visit);ct.windll.user32.EnumWindows(callback,0)
 assert len(found)==1,'Expected one owned editor window'
 return found[0]

def alignment(page,process):
 hwnd=owned_window(process);u=ct.windll.user32;surfaces=[]
 def visit(child,_):
  name=ct.create_unicode_buffer(256);u.GetClassNameW(ct.c_void_p(child),name,256)
  if name.value=='VlogCraftNativePlayback' and u.IsWindowVisible(ct.c_void_p(child)):surfaces.append(child)
  return True
 callback=CALLBACK(visit);u.EnumChildWindows(ct.c_void_p(hwnd),callback,0)
 assert len(surfaces)==1,'Expected one visible native video surface'
 set_dpi=u.SetThreadDpiAwarenessContext;set_dpi.restype=ct.c_void_p;previous=set_dpi(ct.c_void_p(-4))
 try:
  origin=Point();u.ClientToScreen(ct.c_void_p(hwnd),ct.byref(origin));rect=Rect();u.GetWindowRect(ct.c_void_p(surfaces[0]),ct.byref(rect))
 finally:set_dpi(ct.c_void_p(previous))
 dpi=u.GetDpiForWindow(ct.c_void_p(hwnd));scale=dpi/96;web=page.evaluate('nativeRect()')
 expected=[round(web[k]*scale) for k in ('x','y','width','height')]
 actual=[rect.left-origin.x,rect.top-origin.y,rect.right-rect.left,rect.bottom-rect.top]
 return {'window_dpi':dpi,'browser_dpr':web['dpr'],'expected_client_pixels':expected,'actual_client_pixels':actual,
         'absolute_error_pixels':[abs(a-b) for a,b in zip(expected,actual)],'scope':'Default browser zoom; physical HWND/client coordinates, independent of the reported emulated DPR.'}

def resize(process,width=2100,height=1300):
 hwnd=owned_window(process);u=ct.windll.user32;set_dpi=u.SetThreadDpiAwarenessContext;set_dpi.restype=ct.c_void_p;previous=set_dpi(ct.c_void_p(-4))
 try:assert u.SetWindowPos(ct.c_void_p(hwnd),None,0,0,width,height,0x2|0x4)
 finally:set_dpi(ct.c_void_p(previous))
