"""QA-only hidden launches and Windows job ownership; never imported by the editor.

The scope belongs to the running test supervisor, not its observation connection.
Closing a Codex connection therefore does not close a running scope. On Windows,
assign a suspended child before its first instruction can launch descendants.
"""
import ctypes as ct
import os
import subprocess
import time
import psutil

_original_popen = subprocess.Popen

def standard_environment():
    """Resolve missing Windows user folders from the OS, never from guessed paths."""
    env=dict(os.environ);restored=[]
    if os.name=='nt':
        shell=ct.WinDLL('shell32');shell.SHGetFolderPathW.argtypes=[ct.c_void_p,ct.c_int,ct.c_void_p,ct.c_ulong,ct.c_wchar_p]
        for key,folder in (('APPDATA',26),('LOCALAPPDATA',28),('USERPROFILE',40)):
            if not env.get(key):
                value=ct.create_unicode_buffer(32768)
                status=shell.SHGetFolderPathW(None,folder,None,0,value)
                if status or not value.value:raise RuntimeError('Windows known folder unavailable for '+key)
                env[key]=value.value;restored.append(key)
    return env,restored

def terminal_windows():
    """Visible console/Terminal handles only; never collect titles or command lines."""
    if os.name != 'nt': return {}
    from ctypes import wintypes as wt
    user=ct.WinDLL('user32',use_last_error=True)
    callback_type=ct.WINFUNCTYPE(wt.BOOL,wt.HWND,ct.c_ssize_t)
    user.IsWindowVisible.argtypes=[wt.HWND];user.GetClassNameW.argtypes=[wt.HWND,wt.LPWSTR,ct.c_int]
    user.GetWindowThreadProcessId.argtypes=[wt.HWND,ct.POINTER(wt.DWORD)]
    user.EnumWindows.argtypes=[callback_type,ct.c_ssize_t]
    found={}
    def visit(hwnd,_):
        if user.IsWindowVisible(hwnd):
            name=ct.create_unicode_buffer(256);user.GetClassNameW(hwnd,name,256)
            if name.value in ('ConsoleWindowClass','CASCADIA_HOSTING_WINDOW_CLASS'):
                pid=wt.DWORD();user.GetWindowThreadProcessId(hwnd,ct.byref(pid));found[int(hwnd)]=pid.value
        return True
    callback=callback_type(visit)
    if not user.EnumWindows(callback,0):raise ct.WinError(ct.get_last_error())
    return found

def hide_console_children():
    """Opt-in test-driver policy. GUI windows remain visible; all output is retained."""
    if os.name != 'nt' or getattr(subprocess.Popen, '_qa_hidden', False):
        return
    class HiddenPopen(_original_popen):
        _qa_hidden = True
        def __init__(self, *args, **kwargs):
            kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)
    subprocess.Popen = HiddenPopen

class ProcessScope:
    def __init__(self):
        self.processes = []
        self.closed = False
        self.report = None
        self.job = None
        self._terminals_before=terminal_windows()
        if os.name == 'nt':
            from ctypes import wintypes as wt
            size = ct.c_size_t
            class Basic(ct.Structure):
                _fields_ = [('process_time',ct.c_longlong),('job_time',ct.c_longlong),('flags',wt.DWORD),
                            ('minimum_ws',size),('maximum_ws',size),('active_limit',wt.DWORD),
                            ('affinity',size),('priority',wt.DWORD),('scheduling',wt.DWORD)]
            class IO(ct.Structure):
                _fields_ = [(n,ct.c_ulonglong) for n in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
            class Extended(ct.Structure):
                _fields_ = [('basic',Basic),('io',IO),('process_memory',size),('job_memory',size),('peak_process_memory',size),('peak_job_memory',size)]
            self.kernel = ct.WinDLL('kernel32',use_last_error=True)
            k = self.kernel
            k.CreateJobObjectW.argtypes = [ct.c_void_p,wt.LPCWSTR]; k.CreateJobObjectW.restype = wt.HANDLE
            k.SetInformationJobObject.argtypes = [wt.HANDLE,ct.c_int,ct.c_void_p,wt.DWORD]; k.SetInformationJobObject.restype = wt.BOOL
            k.AssignProcessToJobObject.argtypes = [wt.HANDLE,wt.HANDLE]; k.AssignProcessToJobObject.restype = wt.BOOL
            k.QueryInformationJobObject.argtypes = [wt.HANDLE,ct.c_int,ct.c_void_p,wt.DWORD,ct.c_void_p]; k.QueryInformationJobObject.restype = wt.BOOL
            k.CloseHandle.argtypes = [wt.HANDLE]; k.CloseHandle.restype = wt.BOOL
            k.OpenThread.argtypes = [wt.DWORD,wt.BOOL,wt.DWORD]; k.OpenThread.restype = wt.HANDLE
            k.ResumeThread.argtypes = [wt.HANDLE]; k.ResumeThread.restype = wt.DWORD
            self.job = k.CreateJobObjectW(None,None)
            if not self.job: raise ct.WinError(ct.get_last_error())
            info = Extended(); info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k.SetInformationJobObject(self.job,9,ct.byref(info),ct.sizeof(info)):
                error = ct.WinError(ct.get_last_error()); k.CloseHandle(self.job); self.job = None; raise error

    def launch(self, command, **kwargs):
        if self.closed: raise RuntimeError('QA process scope is closed')
        if os.name == 'nt':
            kwargs['creationflags'] = kwargs.get('creationflags',0) | subprocess.CREATE_NO_WINDOW | 4  # CREATE_SUSPENDED
        proc = subprocess.Popen(command,**kwargs)
        self.processes.append(proc)
        if self.job:
            try:
                if not self.kernel.AssignProcessToJobObject(self.job,int(proc._handle)):
                    raise ct.WinError(ct.get_last_error())
                # Popen closes the primary thread handle. Before first resume,
                # this new process has exactly one thread, owned by this PID.
                threads = psutil.Process(proc.pid).threads()
                if len(threads) != 1: raise RuntimeError('Unexpected suspended process thread count')
                thread = self.kernel.OpenThread(2,False,threads[0].id)  # THREAD_SUSPEND_RESUME
                if not thread: raise ct.WinError(ct.get_last_error())
                try:
                    if self.kernel.ResumeThread(thread) != 1: raise RuntimeError('QA primary thread was not suspended once')
                finally: self.kernel.CloseHandle(thread)
            except BaseException:
                proc.kill(); proc.wait(); raise
        return proc

    def members(self):
        if self.job:
            from ctypes import wintypes as wt
            for capacity in (64,512,4096):
                class IDs(ct.Structure):
                    _fields_ = [('assigned',wt.DWORD),('count',wt.DWORD),('ids',ct.c_size_t*capacity)]
                ids = IDs()
                if self.kernel.QueryInformationJobObject(self.job,3,ct.byref(ids),ct.sizeof(ids),None):
                    return [int(ids.ids[n]) for n in range(ids.count)]
                if ct.get_last_error() != 234: raise ct.WinError(ct.get_last_error())
            raise RuntimeError('QA job membership exceeded the bounded query capacity')
        members = []
        for proc in self.processes:
            if proc.poll() is None:
                try: members.extend([proc.pid,*[p.pid for p in psutil.Process(proc.pid).children(recursive=True)]])
                except psutil.Error: pass
        return list(set(members))

    def close(self):
        if self.closed: return self.report
        self.closed = True
        failure=None;ids=[];owned=[];terminals_at_close={};terminals_after={};roles={}
        try:
            ids=self.members();terminals_at_close=terminal_windows()
        except BaseException as error:
            failure=error
            # Diagnostic failure must never keep a Windows job handle open.
            ids=[p.pid for p in self.processes if p.poll() is None]
        for pid in ids:
            try:
                member=psutil.Process(pid);owned.append(member);name=member.name().lower()
                role=name if name in ('vlogcraftstudio.exe','vlogcraftnative.exe','msedgewebview2.exe','ffmpeg.exe','ffprobe.exe','python.exe','pythonw.exe','node.exe','conhost.exe','openconsole.exe','windowsterminal.exe') else 'other'
                roles[role]=roles.get(role,0)+1
            except psutil.Error: pass
        if self.job:
            self.kernel.CloseHandle(self.job); self.job = None
        else:
            for proc in reversed(owned):
                try: proc.terminate()
                except psutil.Error: pass
        _,alive = psutil.wait_procs(owned,timeout=5)
        for proc in self.processes:
            if proc.poll() is not None: proc.wait()
            for pipe in (proc.stdin,proc.stdout,proc.stderr):
                if pipe is not None and not pipe.closed: pipe.close()
        try:terminals_after=terminal_windows()
        except BaseException as error:
            if failure is None:failure=error
        self.report = {'Windows_job':os.name=='nt','job_members_at_cleanup':len(ids),
                       'remaining_owned_processes':len(alive),'unrelated_processes_targeted':0,
                       'forced_member_roles':roles,
                       'visible_terminal_windows_before':len(self._terminals_before),
                       'owned_visible_terminal_windows_at_cleanup':sum(pid in ids for pid in terminals_at_close.values()),
                       'visible_terminal_windows_after':len(terminals_after) if failure is None else None,
                       'new_visible_terminal_windows_after':len(set(terminals_after)-set(self._terminals_before)) if failure is None else None,
                       'diagnostic_failure_type':type(failure).__name__ if failure else None,
                       'terminal_scope':'Before/after snapshots; no titles, global window changes or termination of unowned terminals. Brief intermediate flashes are not excluded by snapshots.'}
        if alive: raise RuntimeError('Owned QA processes survived cleanup')
        if failure is not None:raise failure
        return self.report

    def __enter__(self): return self
    def __exit__(self,*args): self.close()
