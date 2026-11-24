"""Correlate local D3D11, DxgKrnl and optional scheduler ETLs with a watchdog incident."""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

from phase3b_stall_evidence import LANES, MAX_INTERVAL_US, stall_start


EVENT_MARGIN_US = 150000
SCHEDULING_STATES = {"1": "ready", "3": "standby", "5": "waiting"}
SCHEDULER_COLUMNS = {
    "CSwitch": {"newprocessname(pid)", "newtid", "oldprocessname(pid)",
                "oldtid", "oldstate", "waitreason"},
    "ReadyThread": {"rdytid"},
}
KERNEL_THREAD_GUID = "3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c"


def etl_clock(summary, label):
    match = re.search(label + r" time \(UTC\)\s*:\s*([\d/:]+)\.(\d{7})", summary)
    if not match:
        raise ValueError(f"Missing ETL {label} time")
    date = datetime.strptime(match[1], "%Y/%m/%d:%H:%M:%S").replace(tzinfo=timezone.utc)
    return (int(date.timestamp()) + 11644473600) * 10_000_000 + int(match[2])


def trace_stats(etl):
    return subprocess.check_output(["xperf", "-i", etl, "-a", "tracestats"],
                                   encoding="utf-8", errors="replace", stderr=subprocess.DEVNULL)


def trace_loss(stats):
    result = {}
    for kind in ("Buffers", "Events"):
        match = re.search(rf"Total # Lost {kind}\s*:\s*(\d+)", stats)
        result[kind] = int(match[1]) if match else None
    return result


def dumper_command(etl, start, end):
    return ["xperf", "-i", etl, "-a", "dumper", "-range",
            str(max(0, start - EVENT_MARGIN_US)), str(end + EVENT_MARGIN_US), "-add_fieldnames"]


def traced_process(text):
    match = re.search(r"\(\s*(\d+)\s*\)$", text)
    return int(match[1]) if match else None


def thread_id(text):
    return int(text, 16 if text.lower().startswith("0x") else 10)


def scheduler_rows(rows, pid, tid):
    """Read the classic xperf dumper tables; the CSwitch columns vary by WPT version."""
    headers = {}
    malformed = Counter()
    seen = Counter()
    switches, ready = [], []
    first_switch = last_switch = None
    for row in rows:
        if len(row) < 2:
            continue
        name, timestamp = row[0].strip(), row[1].strip()
        if (name in ("UnknownEvent/Classic", "InvalidEvent/Classic") and len(row) >= 7
                and row[5].strip("{} ").lower() == KERNEL_THREAD_GUID):
            opcode = thread_id(row[6].strip())
            if opcode in (36, 50):
                malformed["CSwitch" if opcode == 36 else "ReadyThread"] += 1
        if name not in SCHEDULER_COLUMNS:
            continue
        if timestamp == "TimeStamp":
            columns = {re.sub(r"\s+", "", label).lower(): index for index, label in enumerate(row)}
            if SCHEDULER_COLUMNS[name] <= columns.keys():
                headers[name] = columns
            continue
        try:
            time = int(timestamp)
            if name not in headers:
                raise ValueError("Scheduler table header is absent")
            columns = headers[name]
            fields = {key: row[index].strip() for key, index in columns.items() if index < len(row)}
            if name == "ReadyThread":
                # ThreadID is the event's issuing thread. Rdy TID is the thread it makes ready.
                target = thread_id(fields["rdytid"])
                target_pid = traced_process(fields.get("rdyprocessname(pid)", ""))
                flags = thread_id(fields.get("flag", fields.get("flags", "0")))
                if target == tid and target_pid in (None, pid) and not flags & 0x6:
                    ready.append(time)
            else:
                incoming = thread_id(fields["newtid"])
                outgoing = thread_id(fields["oldtid"])
                if incoming == tid and traced_process(fields["newprocessname(pid)"]) == pid:
                    switches.append((time, "in", None, None))
                if outgoing == tid and traced_process(fields["oldprocessname(pid)"]) == pid:
                    state = fields["oldstate"].lower()
                    reason = fields["waitreason"]
                    reason = reason if re.fullmatch(r"[A-Za-z0-9_]+", reason) else "unresolved"
                    switches.append((time, "out", SCHEDULING_STATES.get(state, state), reason))
                first_switch = min(first_switch, time) if first_switch is not None else time
                last_switch = max(last_switch, time) if last_switch is not None else time
            seen[name] += 1
        except (IndexError, KeyError, ValueError):
            malformed[name] += 1
    return seen, malformed, (first_switch, last_switch), switches, ready


def scheduler_spans(begin, end, switches, ready):
    """Use consecutive switch edges, with ReadyThread as a wait-to-ready boundary."""
    known = []
    ready = sorted(ready)
    ordered = sorted(switches, key=lambda event: event[0])
    for before, after in zip(ordered, ordered[1:]):
        left, right = max(begin, before[0]), min(end, after[0])
        if left >= right:
            continue
        if before[1] == "in" and after[1] == "out":
            known.append((left, right, "running", None))
        elif before[1] == "out" and after[1] == "in":
            state, reason = before[2:]
            if state in ("ready", "standby"):
                known.append((left, right, "ready", None))
            if state == "waiting":
                first = bisect_left(ready, before[0])
                after_last = bisect_right(ready, after[0])
                if after_last - first == 1:
                    wake = max(left, min(ready[first], right))
                    if left < wake:
                        known.append((left, wake, "waiting", reason))
                    if wake < right:
                        known.append((wake, right, "ready", None))
    segments = []
    cursor = begin
    for left, right, state, reason in known:
        if cursor < left:
            segments.append(scheduler_segment(cursor - begin, left - begin, "unknown"))
        segments.append(scheduler_segment(left - begin, right - begin, state, reason))
        cursor = right
    if cursor < end:
        segments.append(scheduler_segment(cursor - begin, end - begin, "unknown"))
    return segments


def scheduler_segment(start, end, state, reason=None):
    result = {"start_us": start, "end_us": end, "state": state}
    if reason is not None:
        result["wait_reason"] = reason
    return result


def scheduler_evidence(etl, api_stats, api_origin, begin, end, pid, tid):
    report = {
        "status": "unavailable", "reason": "scheduler ETL was not supplied",
        "lost": None, "etl_header_covers_call": None, "switch_events_bracket_call": None,
        "running_us": None, "ready_us": None, "waiting_us": None, "unknown_us": end - begin,
        "call_relative_state_spans": [scheduler_segment(0, end - begin, "unknown")],
    }
    if etl is None:
        return report
    try:
        stats = trace_stats(etl)
        report["lost"] = trace_loss(stats)
        origin = etl_clock(stats, "Start")
        call_start = api_origin + begin * 10
        call_end = api_origin + end * 10
        report["etl_header_covers_call"] = origin <= call_start <= call_end <= etl_clock(stats, "End")
        if any(value != 0 for summary in (report["lost"], trace_loss(api_stats))
               for value in summary.values()):
            report["reason"] = "ETL reports loss or has unavailable loss counters"
            return report
        clock = r"^Clock type\s*:\s*PerfCounter\s*$"
        boot = r"^Boot time\s*:\s*([\d/:]+\.\d{7})\s*$"
        api_boot = re.search(boot, api_stats, re.MULTILINE)
        scheduler_boot = re.search(boot, stats, re.MULTILINE)
        if (not all(re.search(clock, summary, re.MULTILINE) for summary in (api_stats, stats))
                or not api_boot or not scheduler_boot or api_boot[1] != scheduler_boot[1]):
            report["reason"] = "ETLs did not identify the same boot and performance-counter clock"
            return report
        if not report["etl_header_covers_call"]:
            report["reason"] = "scheduler ETL header does not cover the call"
            return report
        if pid is None:
            report["reason"] = "D3D11 event process identity could not be verified"
            return report
        start_us, end_us = (call_start - origin) // 10, (call_end - origin) // 10
        command = dumper_command(etl, start_us, end_us)
        with subprocess.Popen(command, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                              errors="replace", stderr=subprocess.DEVNULL) as proc:
            seen, malformed, (first, last), switches, ready = scheduler_rows(
                csv.reader(proc.stdout, skipinitialspace=True), pid, tid)
            if proc.wait():
                raise RuntimeError("xperf failed to decode scheduler events")
    except (OSError, subprocess.CalledProcessError, ValueError, RuntimeError):
        report["reason"] = "xperf could not read scheduler trace statistics or events"
        return report
    report.update({
        "decoded_event_counts": dict(seen),
        "undecodable_event_counts": dict(malformed),
        "switch_events_bracket_call": first is not None and first <= start_us <= end_us <= last,
        "same_thread_switches_inside_call": sum(start_us < event[0] < end_us for event in switches),
        "same_thread_ready_events_inside_call": sum(start_us < time < end_us for time in ready),
    })
    if not report["switch_events_bracket_call"] or malformed["CSwitch"]:
        report["reason"] = "valid context switches do not bracket the call or the switch stream is incomplete"
        return report
    spans = scheduler_spans(start_us, end_us, switches, [] if malformed["ReadyThread"] else ready)
    times = Counter()
    reasons = Counter()
    for span in spans:
        duration = span["end_us"] - span["start_us"]
        times[span["state"]] += duration
        if "wait_reason" in span:
            reasons[span["wait_reason"]] += duration
    if times["unknown"] == end - begin:
        report["reason"] = "no same-thread scheduler edges provided an attributable span"
        return report
    report.update({
        "status": "partial" if times["unknown"] else "observed",
        "reason": "some spans lacked matching state edges" if times["unknown"] else None,
        "running_us": times["running"], "ready_us": times["ready"], "waiting_us": times["waiting"],
        "unknown_us": times["unknown"], "wait_reason_us": dict(reasons),
        "call_relative_state_spans": spans,
        "scope": ("Running measures time scheduled on a CPU. It includes possible DPC/ISR time. "
                  "Scheduler wait reasons identify a state transition. The waited object and "
                  "code executing on the CPU are unresolved."),
    })
    return report


def correlate(etl, capture, interval, scheduler_etl=None):
    stats = trace_stats(etl)
    lost = trace_loss(stats)
    origin = etl_clock(stats, "Start")
    offset = (capture["start_filetime_100ns"] - origin) // 10
    start, end, frame, samples, scope = interval
    thread_lanes = defaultdict(set)
    for row in samples:
        if not start <= row[0] <= end:
            continue
        for n, lane in enumerate(LANES):
            activity = row[8+n][2]
            if not row[1] & (2 << n) and activity[7] and activity[8]:
                thread_lanes[activity[8]].add(lane)
    threads = {tid: next(iter(lanes)) for tid, lanes in thread_lanes.items() if len(lanes) == 1}
    # Keep a margin for matching completions just after the end of the gap.
    command = dumper_command(etl, offset+start, offset+end)
    starts = {}
    pairs = defaultdict(list)
    sequences = {}
    dma = {}
    execution = defaultdict(list)
    calls = {}
    api = defaultdict(list)
    buffer_calls = []
    buffer_stops = []
    fence_packets = {}
    cpu_waits = []
    counts = Counter()
    bounds = []
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                          errors="replace", stderr=subprocess.DEVNULL) as proc:
        for row in csv.reader(proc.stdout, skipinitialspace=True):
            if len(row) < 10 or not row[1].strip().isdigit():
                continue
            time = int(row[1]) - offset
            if not bounds:
                bounds.append(time)
            last_event = time
            try:
                tid = thread_id(row[3].strip())
            except ValueError:
                continue
            provider = "Microsoft-Windows-Direct3D11/ID3D11VideoContext_"
            if row[0].startswith(provider):
                method, _, op = row[0][len(provider):].partition("/win:")
                lane = threads.get(tid)
                if lane and method in ("DecoderBeginFrame", "DecoderEndFrame", "GetDecoderBuffer", "SubmitDecoderBuffers", "ReleaseDecoderBuffer"):
                    pid = traced_process(row[2])
                    call = (pid, tid, method)
                    if op == "Start":
                        fields = payload(row)
                        calls.setdefault(call, []).append((time, fields.get("Type"), fields.get("pDecoder")))
                    elif op == "Stop" and call in calls:
                        begin, kind, decoder = calls[call].pop()
                        if not calls[call]:
                            del calls[call]
                        if time < begin:
                            continue
                        if begin <= end and time >= start:
                            api[lane, method].append(time - begin)
                        if method == "GetDecoderBuffer" and kind is not None:
                            stop = payload(row)
                            buffer_stops.append((pid, tid, decoder, kind, begin, time, stop))
                            if begin <= end and time >= start:
                                call_span = (time - begin, lane, thread_id(kind), begin, time)
                                buffer_calls.append((call_span, buffer_stops[-1]))
                continue
            name = row[0].removeprefix("Microsoft-Windows-DxgKrnl/")
            if name.startswith("WaitForSynchronizationObjectFromCpu/") and tid in threads:
                cpu_waits.append((time, tid))
            if name not in ("QueuePacket/win:Start", "QueuePacket/win:Stop", "DmaPacket/win:Start", "DmaPacket/win:Stop"):
                continue
            fields = payload(row)
            if name.startswith("DmaPacket"):
                sequence = fields.get("ulQueueSubmitSequence")
                if name.endswith("Start"):
                    lane = sequences.get((fields.get("hQueuePacketContext"), sequence))
                    if lane:
                        dma[fields.get("hContext"), fields.get("uliSubmissionId"), sequence] = (time, lane)
                else:
                    prior = dma.pop((fields.get("hContext"), fields.get("uliCompletionId"), sequence), None)
                    if prior:
                        execution[prior[1]].append(time - prior[0])
                continue
            key = tuple(fields.get(k) for k in ("hContext", "SubmitSequence", "pQueuePacket"))
            if not all(key):
                continue
            if name.endswith("Start"):
                lane = threads.get(tid)
                if lane and "ProgressFenceValue" in fields:
                    fence_packets[key] = [time, tid, None]
                if lane and start <= time <= end:
                    starts[key] = (time, lane)
                    sequences[key[:2]] = lane
                    counts[lane] += 1
            else:
                if key in fence_packets:
                    fence_packets[key][2] = time
                if key in starts:
                    before, lane = starts.pop(key)
                    pairs[lane].append(time - before)
        if proc.wait():
            raise RuntimeError("xperf failed to decode the interval")
    slow = None
    if buffer_calls:
        call, stop = max(buffer_calls, key=lambda record: record[0])
        pid, tid, decoder, kind, begin, finish, fields = stop
        slow = describe_buffer(call, samples)
        slow["call_start_relative_to_interval_start_us"] = begin - start
        packet = max((p for p in fence_packets.values() if p[1] == tid and p[0] < begin),
                     key=lambda p: p[0], default=None)
        slow["previous_same_thread_fence_packet_start_relative_to_call_start_us"] = (
            packet[0] - begin if packet else None)
        slow["previous_same_thread_fence_packet_stop_relative_to_call_start_us"] = (
            packet[2] - begin if packet and packet[2] is not None else None)
        slow["same_thread_dxg_cpu_wait_events_inside_call"] = sum(
            begin < time < finish and issuer == tid for time, issuer in cpu_waits)
        slow["get_decoder_buffer_stop_fields"] = sorted(
            set(fields).intersection(("m_Ret", "pBufferSize", "ppBuffer")))
        ppbuffer = fields.get("ppBuffer")
        slow["earlier_same_decoder_type_and_stop_ppbuffer_in_window"] = (
            any(b[:4] == (pid, tid, decoder, kind) and b[5] < begin and b[6].get("ppBuffer") == ppbuffer
                for b in buffer_stops)
            if decoder and ppbuffer and thread_id(ppbuffer) else None)
        slow["earlier_same_decoder_type_and_returned_address_in_window"] = None
        slow["input_buffer_identity"] = (
            "The provider Stop event contains an output-parameter field named ppBuffer. "
            "This trace does not resolve the returned physical buffer or a unique buffer-to-fence link.")
        slow["thread_cpu_observation"] = describe_thread_cpu(call, samples, tid)
        slow["scheduler"] = scheduler_evidence(scheduler_etl, stats, origin, offset + begin, offset + finish, pid, tid)
    return {
        "frame": frame, "interval": scope, "duration_us": end-start, "lost": lost,
        "etl_header_covers_interval": origin <= origin+(offset+start)*10 <= origin+(offset+end)*10 <= etl_clock(stats,"End"),
        "events_bracket_interval": bool(bounds and bounds[0] <= start and last_event >= end),
        "video_api_calls_overlapping_interval": [
            {"lane": lane, "call": call, "pairs": len(spans), "max_wall_us": max(spans)}
            for (lane, call), spans in sorted(api.items())],
        "longest_decoder_input_buffer_call": slow,
        "queue_packets_by_issuing_lane": {lane: {"starts": counts[lane], "matched_stops": len(pairs[lane]),
            "max_submit_to_stop_us": max(pairs[lane], default=None), "matched_dma_intervals": len(execution[lane]),
            "max_dma_span_us": max(execution[lane], default=None)} for lane in LANES},
        "clock_alignment": "Native recorder construction FILETIME aligned to ETL UTC. Sub-millisecond ordering is unresolved.",
        "scope": "Exact context, submission sequence and packet identity match. Queue lifetime includes scheduling. A GPU event query is a separate observation."
    }


def payload(row):
    return dict(item.split(" : ", 1) for item in row[9:] if " : " in item)


def describe_thread_cpu(call, samples, tid):
    _, lane, _, begin, end = call
    index = LANES.index(lane)
    covered = accounted = spans = 0
    for left, right in zip(samples, samples[1:]):
        elapsed = right[0] - left[0]
        if not (begin <= left[0] < right[0] <= end and elapsed <= MAX_INTERVAL_US):
            continue
        if (left[1] | right[1]) & (1 | (2 << index)):
            continue
        before, after = left[8+index], right[8+index]
        first, last = before[2], after[2]
        if (not first[7] or first[7:] != last[7:] or first[8] != tid or before[3] != after[3]
                or first[6] < 0 or last[6] < first[6]):
            continue
        covered += elapsed
        accounted += last[6] - first[6]
        spans += 1
    return {
        "consecutive_sample_intervals": spans,
        "bracketed_wall_us": covered,
        "accounted_cpu_us": accounted if spans else None,
        "scope": ("Sampled cumulative GetThreadTimes user and kernel CPU within the call. "
                  "Sample skew and accounting resolution apply. CPU time does not distinguish "
                  "waiting from ready-to-run time and excludes unsampled edges of the call."),
    }


def describe_buffer(call, samples):
    duration, owner, kind, start, end = call
    bracketed = Counter()
    n = LANES.index(owner)
    for left, right in zip(samples, samples[1:]):
        dt = right[0]-left[0]
        if not 0 < dt <= MAX_INTERVAL_US or left[0] < start or right[0] > end:
            continue
        owned = left[8+n][7]
        if (left[1]|right[1]) & (1 | (2 << n)) or owned != right[8+n][7] or not owned[1]:
            continue
        for i, lane in enumerate(LANES):
            waiting = left[8+i][7]
            if not (left[1]|right[1]) & (2 << i) and waiting == right[8+i][7] and waiting[0]:
                bracketed[lane] += dt
    return {"lane": owner, "buffer_type": kind, "wall_us": duration,
            "bracketed_shared_device_wait_us_by_peer": dict(bracketed)}


def intervals(capture):
    results = []
    candidates = [i for i in capture["incidents"] if i["recovered"] and not i["transition"]]
    if candidates:
        incident = max(candidates, key=lambda x: x["observed_age_us"])
        frame = incident["last_frame"]
        start = stall_start(incident["samples"], frame, incident["generation"])
        if start is not None:
            results.append((start, start+incident["observed_age_us"], frame, incident["samples"], "longest recovered watchdog incident"))
    miss = capture["first_source_miss"]
    rows = [r for r in miss["requests"] if r[3] == miss["generation"] and r[4] and r[2] >= miss["frame"]]
    first = next((r for r in rows if r[2] == miss["frame"] and r[7] != (r[8] & 7)), None)
    if first:
        after = [r for r in rows if r[0] >= first[0]]
        ready = next((r for r in after if r[7] == (r[8] & 7)), None)
        end = (ready or after[-1])[1]
        if end > first[1]:
            scope = "first source miss to first ready request" if ready else "first source miss to last retained unready request"
            results.append((first[1], end, first[2], miss["samples"], scope))
        samples = miss["samples"]
        prior = [row for row in samples if row[0] <= first[1] and row[3][2] and row[3][1] == first[3]]
        if prior:
            results.append((max(prior[0][0], first[1]-120000), first[1], first[2], samples,
                            "up to 120 ms before first missing request"))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("etl", type=Path)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--scheduler-etl", type=Path, help="Parallel WPR kernel trace from the same playback")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    capture = json.loads(args.capture.read_text(encoding="utf-8"))
    result = [correlate(args.etl, capture, interval, args.scheduler_etl) for interval in intervals(capture)]
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(result, file, indent=2)
        file.write("\n")


if __name__ == "__main__":
    main()
