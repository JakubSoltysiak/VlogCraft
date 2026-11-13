"""Use the owned native window and actual WebView2 DPI instead of emulated DPR1."""
import ctypes as ct,psutil
def actual_display(page,process):
 family={process.pid,*[p.pid for p in psutil.Process(process.pid).children(recursive=True)]};windows=[]
 def visit(hwnd,unused):
  pid=ct.c_ulong();ct.windll.user32.GetWindowThreadProcessId(hwnd,ct.byref(pid))
  text=ct.create_unicode_buffer(256);ct.windll.user32.GetWindowTextW(hwnd,text,256)
  if pid.value in family and text.value.startswith('VlogCraft Studio • '):windows.append(hwnd)
  return True
 callback=ct.WINFUNCTYPE(ct.c_bool,ct.c_void_p,ct.c_void_p)(visit);ct.windll.user32.EnumWindows(callback,0)
 assert windows,'Owned native window unavailable'
 ct.windll.user32.ShowWindow(ct.c_void_p(windows[0]),3)
 page.wait_for_timeout(500)
 dpi=ct.windll.user32.GetDpiForWindow(ct.c_void_p(windows[0]));scale=dpi/96
 class Rect(ct.Structure):_fields_=[('left',ct.c_long),('top',ct.c_long),('right',ct.c_long),('bottom',ct.c_long)]
 rect=Rect();set_dpi=ct.windll.user32.SetThreadDpiAwarenessContext;set_dpi.restype=ct.c_void_p
 previous=set_dpi(ct.c_void_p(-4))
 ct.windll.user32.GetClientRect(ct.c_void_p(windows[0]),ct.byref(rect))
 set_dpi(ct.c_void_p(previous))
 session=page.context.new_cdp_session(page)
 session.send('Emulation.setDeviceMetricsOverride',{'width':round(rect.right/scale),'height':round(rect.bottom/scale),'deviceScaleFactor':scale,'mobile':False})
 page.wait_for_timeout(500)
 return {'window_dpi':dpi,'native_client_width':rect.right,'native_client_height':rect.bottom,'method':'Measured native client and matching CDP DPR',**page.evaluate('({device_pixel_ratio:devicePixelRatio,css_width:innerWidth,css_height:innerHeight})')}
