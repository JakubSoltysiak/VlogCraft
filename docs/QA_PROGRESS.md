# Local QA progress

This is a development tool. It is offline, outside the editor interface and excluded from production packaging. The persistent file is **build/qa/status.json**; it stays ignored alongside private QA artifacts.

Double-click **tools/qa_status.pyw** on Windows with the Python file association, or run this from an existing PowerShell in the repository:

```powershell
.venv/Scripts/pythonw.exe tools/qa_status.pyw
```

This opens a small graphical viewer without another terminal. The run selector includes retained historical results. Closing the viewer does not stop tests. To read status in an existing terminal, use:

```powershell
.venv/Scripts/python.exe tools/qa_status.py
.venv/Scripts/python.exe tools/qa_status.py --json
```

The viewer shows completed/total cases, percentage, pass/fail/skip/cancel counts, running/pending cases, phase, current names, elapsed/declared duration, timestamps and controller/heartbeat/activity status. A completed case can be failed; 100% completed does not mean qualification passed. These are **QA command cases**, which may contain many individual Python/JavaScript tests. Their individual results remain in logs.

## Launch and retry

```powershell
.venv/Scripts/python.exe benchmarks/run_qa.py --results build/qa/example-01 --name "Example QA" -- .venv/Scripts/python.exe -c "print('complete')"
```

The existing QUICK, STANDARD and FULL profiles register their steps before starting and update the same file. The enclosing supervisor is not counted again as a profile test. Custom controllers can use `benchmarks.qa_progress.Tracker`: `plan`, `start`, `heartbeat`, `finish`. Dynamic registration is supported. If the final plan is unknown, the final total and completion percentage stay unknown; the discovered-case count remains available.

For a known shared plan:

```powershell
.venv/Scripts/python.exe tools/qa_status.py --run-id my-qualification --title "Local qualification" --plan smoke recovery export
.venv/Scripts/python.exe benchmarks/run_qa.py --run-id my-qualification --case-id smoke --phase correctness --results build/qa/smoke-01 -- .venv/Scripts/python.exe -c "print('complete')"
```

Retry with the same run/case IDs and a **new results directory**. Attempts append to the case; the total does not increase. Historical failures stay stored even if the latest retry passes. Existing result directories cannot be overwritten. Use technical case names without source filenames or private paths. Old named command ledgers can be imported once with `--import-legacy`; exact repeated case IDs are grouped, and previously separate numbered attempts remain distinct records.

## Heartbeat and interruption

The executing supervisor updates status about every two seconds, independently of Codex and the viewer. It samples only owned process CPU/I/O activity, without GPU/PDH polling or frame callbacks. Declared workload duration is an estimate beside elapsed wall time, not proof of frame completion. A fresh heartbeat with no recent activity is labelled possibly idle/stalled. A dead controller or stale heartbeat is shown explicitly; it is never invented as a pass or cancelled result. A busy process can still be logically stuck, so logs and benchmark artifacts remain authoritative.

Writers use a cross-process lock and atomic replacement. Windows sharing conflicts receive bounded retries; corrupt JSON is reported and preserved. Tracker-write errors are retained in the supervisor report and do not terminate an already-running benchmark. Process containment, timeout/cancellation and logs remain owned by the running QA supervisor; an observation disconnect does not cancel its work. No global terminal or process-name cleanup is performed.
