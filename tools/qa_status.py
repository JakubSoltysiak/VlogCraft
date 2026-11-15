"""Offline status command and optional no-console Tk viewer for development QA."""
import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.qa_progress import DEFAULT,Tracker,snapshot

def display(d):
    count=d['counts'];total=d['total'];pct=d['completion_percent']
    head=(f'{pct:.1f}%' if pct is not None else 'Final total unknown')
    filled=int((pct if pct is not None else d['discovered_completion_percent'])/5)
    lines=['VLOGCRAFT STUDIO — QA PROGRESS','',('█'*filled+'░'*(20-filled))+'  '+head,
           f"Completed: {d['completed']} / {total if total is not None else 'unknown'} ({d['discovered']} discovered)",
           f"Passed: {count['passed']}   Failed: {count['failed']}   Skipped: {count['skipped']}   Cancelled: {count['cancelled']}",
           f"Running: {count['running']}   Remaining pending: {d['remaining']}",
           f"Attempts: {d['attempts']}   Historical failed attempts: {d['historical_failed_attempts']}",
           '',f"Phase: {d['phase']}",f"Qualification: {d['qualification']}",f"Last update: {d['last_update']}"]
    for r in d['running']:
        elapsed=r['elapsed_seconds'];expected=r.get('expected_seconds')
        fmt=lambda n:f'{int(n)//60:02}:{int(n)%60:02}'
        lines+=['',r['name'],f"Elapsed: {fmt(elapsed)}"+(f' / declared {fmt(expected)}' if expected else ' / duration unknown'),
                f"Controller: {'alive' if r['controller_alive'] else 'exited' if r['controller_alive'] is False else 'unknown'}; {r['observation_status']}",
                f"Heartbeat age: {r['heartbeat_age_seconds']:.1f}s; activity age: {r['activity_age_seconds']:.1f}s"]
    if not d['running']:lines+=['','No test is currently recorded as running.']
    lines+=['',d['counting_scope'],'Heartbeat/activity are not proof of logical frame progress.']
    return '\n'.join(lines)

def view(a):
    import tkinter as tk
    from tkinter import ttk
    root=tk.Tk();root.title('VlogCraft Studio — QA progress');root.geometry('940x540');root.configure(bg='#101722')
    selected=tk.StringVar();chooser=ttk.Combobox(root,textvariable=selected,state='readonly');chooser.pack(fill='x',padx=14,pady=10)
    content=tk.Frame(root,bg='#101722');content.pack(fill='both',expand=True,padx=14,pady=8)
    scroll=ttk.Scrollbar(content);scroll.pack(side='right',fill='y')
    label=tk.Text(content,bg='#101722',fg='#d7e8fa',wrap='word',font=('Consolas',11),state='disabled',yscrollcommand=scroll.set)
    label.pack(side='left',fill='both',expand=True);scroll.config(command=label.yview)
    def set_text(value):
        position=label.yview();label.config(state='normal');label.delete('1.0','end');label.insert('1.0',value);label.config(state='disabled')
        label.yview_moveto(position[0])
    updates=0;last_good=None;started=time.monotonic();scheduled=None
    def refresh():
        nonlocal updates,last_good,scheduled
        if scheduled is not None:root.after_cancel(scheduled);scheduled=None
        try:
            d=snapshot(a.status,selected.get() or a.run_id);chooser['values']=d['run_ids'];selected.set(d['run_id']);last_good=d
            set_text(display(d));updates+=1
        except (OSError,ValueError,KeyError) as error:
            set_text('Status unavailable: '+type(error).__name__+'\n\n'+(display(last_good) if last_good else 'No QA run has written status yet.'))
        if a.smoke_seconds and time.monotonic()-started>=a.smoke_seconds:
            if a.receipt:a.receipt.write_text(json.dumps({'refreshes':updates,'last_good_status':last_good is not None,'closed_normally':True}))
            root.destroy();return
        scheduled=root.after(1000 if a.smoke_seconds else 2000,refresh)
    chooser.bind('<<ComboboxSelected>>',lambda e:refresh());refresh();root.mainloop()

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser();p.add_argument('--status',type=Path,default=DEFAULT);p.add_argument('--run-id');p.add_argument('--view',action='store_true')
    p.add_argument('--plan',nargs='*');p.add_argument('--title',default='Local QA');p.add_argument('--import-legacy',type=Path)
    p.add_argument('--json',action='store_true');p.add_argument('--smoke-seconds',type=float);p.add_argument('--receipt',type=Path);a=p.parse_args()
    if a.plan is not None:Tracker(a.status,a.run_id,a.title).plan(a.plan,complete=True)
    if a.import_legacy:Tracker(a.status,a.run_id,a.title).import_legacy(json.loads(a.import_legacy.read_text('utf8')))
    if a.view:view(a)
    else:
        d=snapshot(a.status,a.run_id);print(json.dumps(d,indent=2) if a.json else display(d))
if __name__=='__main__':main()
