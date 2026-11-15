"""Control only the owned QA window; never change Windows display/power settings."""
import ctypes as ct
from ctypes import wintypes
import threading,time
from window_geometry import owned_window,Rect,Point

def request_focus(hwnd):
    """Focus an owned QA window; always detach temporary input queues."""
    u=ct.windll.user32;u.GetForegroundWindow.restype=ct.c_void_p
    if u.SetForegroundWindow(ct.c_void_p(hwnd)):return True
    foreground=u.GetForegroundWindow()
    if not foreground:return False
    current=ct.windll.kernel32.GetCurrentThreadId()
    other=u.GetWindowThreadProcessId(ct.c_void_p(foreground),None)
    attached=bool(u.AttachThreadInput(current,other,True)) if current!=other else False
    try:
        u.BringWindowToTop(ct.c_void_p(hwnd))
        return bool(u.SetForegroundWindow(ct.c_void_p(hwnd)))
    finally:
        if attached:u.AttachThreadInput(current,other,False)

def keep_visible(process,focus=True):
    hwnd=owned_window(process);u=ct.windll.user32
    previous_topmost=bool(u.GetWindowLongW(ct.c_void_p(hwnd),-20)&8)
    u.ShowWindow(ct.c_void_p(hwnd),9)
    assert u.SetWindowPos(ct.c_void_p(hwnd),ct.c_void_p(-1),0,0,0,0,0x1|0x2|0x10|0x40),'Cannot expose owned QA window'
    if focus:request_focus(hwnd)
    return hwnd,previous_topmost

def restore_window(token):
    hwnd,previous_topmost=token;u=ct.windll.user32
    if u.IsWindow(ct.c_void_p(hwnd)) and not previous_topmost:
        u.SetWindowPos(ct.c_void_p(hwnd),ct.c_void_p(-2),0,0,0,0,0x1|0x2|0x10)

def surface_visibility(process,hwnd=None):
    hwnd=hwnd or owned_window(process);u=ct.windll.user32
    u.GetForegroundWindow.restype=ct.c_void_p
    foreground=ct.c_ulong();u.GetWindowThreadProcessId(ct.c_void_p(u.GetForegroundWindow()),ct.byref(foreground))
    # The top-level client center is sufficient before native preparation. Once
    # prepared, use the native child's center so a partially covered app fails.
    from window_geometry import CALLBACK
    surfaces=[]
    def visit(child,_):
        name=ct.create_unicode_buffer(256);u.GetClassNameW(ct.c_void_p(child),name,256)
        if name.value=='VlogCraftNativePlayback' and u.IsWindowVisible(ct.c_void_p(child)):surfaces.append(child)
        return True
    callback=CALLBACK(visit);u.EnumChildWindows(ct.c_void_p(hwnd),callback,0)
    target=surfaces[0] if surfaces else hwnd
    u.SetThreadDpiAwarenessContext.restype=ct.c_void_p;previous=u.SetThreadDpiAwarenessContext(ct.c_void_p(-4))
    try:
        rect=Rect();surface_replaced=False
        if not u.GetWindowRect(ct.c_void_p(target),ct.byref(rect)):
            # A resolution/seek operation can destroy the enumerated child
            # before this observer reads it. Record the transition and inspect
            # the still-owned editor; never turn an API failure into success.
            if target==hwnd or u.IsWindow(ct.c_void_p(target)):raise ct.WinError()
            surface_replaced=True;target=hwnd
            if not u.GetWindowRect(ct.c_void_p(hwnd),ct.byref(rect)):raise ct.WinError()
        u.WindowFromPoint.restype=ct.c_void_p;u.WindowFromPoint.argtypes=[Point]
        hit=u.WindowFromPoint(Point((rect.left+rect.right)//2,(rect.top+rect.bottom)//2))
        # A browser child can receive hit tests over the native child. Compare
        # the root window rather than names/paths belonging to another app.
        u.GetAncestor.restype=ct.c_void_p;root=u.GetAncestor(ct.c_void_p(hit),2)
    finally:u.SetThreadDpiAwarenessContext(ct.c_void_p(previous))
    return {'visible':bool(u.IsWindowVisible(ct.c_void_p(hwnd))),
            'surface_replaced_during_sample':surface_replaced,
            'sampled_native_surface':target!=hwnd,
            'minimized':bool(u.IsIconic(ct.c_void_p(hwnd))),
            'editor_topmost':bool(u.GetWindowLongW(ct.c_void_p(hwnd),-20)&8),
            'preview_center_unobscured':root==hwnd,
            'foreground_owned':foreground.value==process.pid}

def cover_bounds(process,whole_editor):
    hwnd=owned_window(process);u=ct.windll.user32
    if not whole_editor:
        from window_geometry import CALLBACK
        surfaces=[]
        def visit(child,_):
            name=ct.create_unicode_buffer(256);u.GetClassNameW(ct.c_void_p(child),name,256)
            if name.value=='VlogCraftNativePlayback' and u.IsWindowVisible(ct.c_void_p(child)):surfaces.append(child)
            return True
        callback=CALLBACK(visit);u.EnumChildWindows(ct.c_void_p(hwnd),callback,0)
        assert len(surfaces)==1,'Expected one prepared native surface';hwnd=surfaces[0]
    u.SetThreadDpiAwarenessContext.restype=ct.c_void_p;previous=u.SetThreadDpiAwarenessContext(ct.c_void_p(-4))
    try:
        rect=Rect();assert u.GetWindowRect(ct.c_void_p(hwnd),ct.byref(rect))
        return rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top
    finally:u.SetThreadDpiAwarenessContext(ct.c_void_p(previous))

class Occluder:
    """Opaque system-class test window with its own bounded message-loop thread."""
    def __init__(self,bounds,focus=False,keyboard_focus=False):
        self.bounds=bounds;self.focus=focus;self.keyboard_focus=keyboard_focus;self.ready=threading.Event();self.stop=threading.Event();self.error=None
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
        assert self.ready.wait(5),'QA occluder did not initialize'
        if self.error:raise self.error
    def run(self):
        u=ct.windll.user32;hwnd=None
        u.SetThreadDpiAwarenessContext.restype=ct.c_void_p;previous=u.SetThreadDpiAwarenessContext(ct.c_void_p(-4))
        try:
            create=u.CreateWindowExW;create.restype=ct.c_void_p
            create.argtypes=[wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD,
                             ct.c_int,ct.c_int,ct.c_int,ct.c_int,ct.c_void_p,ct.c_void_p,ct.c_void_p,ct.c_void_p]
            # TOPMOST | TOOLWINDOW | NOACTIVATE; POPUP | VISIBLE | SS_BLACKRECT.
            hwnd=create(0x88 if self.focus else 0x08000088,'STATIC','VlogCraft QA occlusion',0x90000004,*self.bounds,None,None,None,None)
            if not hwnd:raise ct.WinError()
            assert u.SetWindowPos(ct.c_void_p(hwnd),ct.c_void_p(-1),*self.bounds,0x10|0x40)
            if self.focus:request_focus(hwnd)
            if self.keyboard_focus:u.SetActiveWindow(ct.c_void_p(hwnd));u.SetFocus(ct.c_void_p(hwnd))
            self.hwnd=hwnd
            self.ready.set();message=wintypes.MSG()
            while not self.stop.wait(.02):
                while u.PeekMessageW(ct.byref(message),None,0,0,1):
                    u.TranslateMessage(ct.byref(message));u.DispatchMessageW(ct.byref(message))
        except BaseException as exc:self.error=exc;self.ready.set()
        finally:
            if hwnd:u.DestroyWindow(ct.c_void_p(hwnd))
            u.SetThreadDpiAwarenessContext(ct.c_void_p(previous))
    def close(self):
        self.stop.set();self.thread.join(3);assert not self.thread.is_alive(),'QA occluder thread survived cleanup'

class WindowVisibility:
    def __init__(self,process,mode):
        self.process=process;self.mode=mode;self.rows=[];self.stop=threading.Event();self.token=None;self.cover=None
    def __enter__(self):
        try:
            if self.mode!='uncontrolled':self.token=keep_visible(self.process)
            if self.mode in ('preview-covered','editor-covered','editor-covered-unfocused'):
                background=self.mode=='editor-covered-unfocused'
                self.cover=Occluder(cover_bounds(self.process,self.mode!='preview-covered'),focus=background,keyboard_focus=background)
            elif self.mode in ('visible-unfocused','visible-browser-unfocused'):
                self.cover=Occluder((0,0,2,2),focus=True,keyboard_focus=self.mode=='visible-browser-unfocused')
                # WinForms may update Z order while delivering deactivation.
                # Reassert only this owned test window, without activating it.
                time.sleep(.15)
                ct.windll.user32.SetWindowPos(ct.c_void_p(self.token[0]),ct.c_void_p(-1),0,0,0,0,0x1|0x2|0x10)
            self.hwnd=owned_window(self.process);self.started=time.perf_counter();self.sample()
            self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start();return self
        except BaseException:
            if self.cover:self.cover.close()
            if self.token:restore_window(self.token)
            raise
    def sample(self):
        row={'seconds':time.perf_counter()-self.started,**surface_visibility(self.process,self.hwnd)}
        if self.cover:
            rect=Rect();ct.windll.user32.GetWindowRect(ct.c_void_p(self.cover.hwnd),ct.byref(rect))
            row['qa_cover_bounds']=[rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top]
        self.rows.append(row)
    def run(self):
        while not self.stop.wait(1):
            try:self.sample()
            except Exception as error:self.rows.append({'seconds':time.perf_counter()-self.started,'sampling_failed':True,'failure_type':type(error).__name__})
    def finish(self):
        self.stop.set();self.thread.join();expected=self.mode in ('visible','visible-unfocused','visible-browser-unfocused')
        foreground=self.mode not in ('visible-unfocused','visible-browser-unfocused','editor-covered-unfocused')
        stable=all(r.get('visible') and not r.get('minimized') and r.get('preview_center_unobscured')==expected and r.get('foreground_owned')==foreground for r in self.rows)
        return {'mode':self.mode,'samples':self.rows,'condition_held':stable if self.mode!='uncontrolled' else None,
                'scope':'Physical center hit-test and window state, not physical scanout. Owned QA topmost/cover windows only; no global Windows settings.'}
    def __exit__(self,*args):
        self.stop.set();self.thread.join()
        if self.cover:self.cover.close()
        if self.token:restore_window(self.token)
