"""Correlate a bounded, local DxgKrnl ETL with a native watchdog incident."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

from phase3b_stall_evidence import LANES, stall_start


def etl_clock(summary, label):
    match = re.search(label + r" time \(UTC\)\s*:\s*([\d/:]+)\.(\d{7})", summary)
    if not match:
        raise ValueError(f"Missing ETL {label} time")
    date = datetime.strptime(match[1], "%Y/%m/%d:%H:%M:%S").replace(tzinfo=timezone.utc)
    return (int(date.timestamp()) + 11644473600) * 10_000_000 + int(match[2])


def correlate(etl, capture, interval):
    stats = subprocess.check_output(["xperf", "-i", etl, "-a", "tracestats"], encoding="utf-8", errors="replace")
    lost = {kind: int(re.search(rf"Total # Lost {kind}\s*:\s*(\d+)", stats)[1])
            for kind in ("Buffers", "Events")}
    origin = etl_clock(stats, "Start")
    offset = (capture["start_filetime_100ns"] - origin) // 10
    start, end, frame, samples, scope = interval
    threads = {}
    for row in samples:
        if not start <= row[0] <= end:
            continue
        for n, lane in enumerate(LANES):
            activity = row[8+n][2]
            if not row[1] & (2 << n) and activity[7] and activity[8]:
                threads[activity[8]] = lane
    # Keep a margin for matching completions just after the end of the gap.
    command = ["xperf", "-i", etl, "-a", "dumper", "-range", str(max(0, offset+start-150000)),
               str(offset+end+150000), "-add_fieldnames"]
    starts = {}
    pairs = defaultdict(list)
    sequences = {}
    dma = {}
    execution = defaultdict(list)
    calls = {}
    api = defaultdict(list)
    buffer_calls = []
    returned_buffers = []
    fence_packets = {}
    cpu_waits = []
    counts = Counter()
    bounds = []
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace") as proc:
        for row in csv.reader(proc.stdout, skipinitialspace=True):
            if len(row) < 10 or not row[1].strip().isdigit():
                continue
            time = int(row[1]) - offset
            if not bounds:
                bounds.append(time)
            last_event = time
            tid = int(row[3])
            provider = "Microsoft-Windows-Direct3D11/ID3D11VideoContext_"
            if row[0].startswith(provider):
                method, _, op = row[0][len(provider):].partition("/win:")
                lane = threads.get(int(row[3]))
                if lane and method in ("DecoderBeginFrame", "DecoderEndFrame", "GetDecoderBuffer", "SubmitDecoderBuffers", "ReleaseDecoderBuffer"):
                    call = (lane, method)
                    if op == "Start":
                        args = dict(item.split(" : ", 1) for item in row[9:] if " : " in item)
                        calls[call] = time, args.get("Type"), args.get("pDecoder")
                    elif op == "Stop" and call in calls:
                        begin, kind, decoder = calls.pop(call)
                        if method == "GetDecoderBuffer":
                            returned = dict(item.split(" : ", 1) for item in row[9:] if " : " in item)
                            returned_buffers.append((lane, decoder, kind, returned.get("ppBuffer"), begin, time))
                        if begin <= end and time >= start:
                            api[call].append(time-begin)
                            if method == "GetDecoderBuffer" and kind is not None:
                                buffer_calls.append((time-begin, lane, int(kind,0), begin, time))
                continue
            name = row[0].removeprefix("Microsoft-Windows-DxgKrnl/")
            if name.startswith("WaitForSynchronizationObjectFromCpu/") and tid in threads:
                cpu_waits.append((time, threads[tid]))
            if name not in ("QueuePacket/win:Start", "QueuePacket/win:Stop", "DmaPacket/win:Start", "DmaPacket/win:Stop"):
                continue
            fields = dict(item.split(" : ", 1) for item in row[9:] if " : " in item)
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
                    fence_packets[key] = [time, lane, None]
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
        call = max(buffer_calls)
        slow = describe_buffer(call, samples)
        _, lane, _, begin, finish = call
        prior = [p for p in fence_packets.values() if p[1] == lane and p[0] < begin]
        packet = max(prior, key=lambda p:p[0], default=None)
        slow["previous_same_thread_fence_packet_stop_relative_to_call_start_us"] = (
            packet[2]-begin if packet and packet[2] is not None else None)
        slow["same_thread_dxg_cpu_wait_events_inside_call"] = sum(
            begin < time < finish and issuer == lane for time, issuer in cpu_waits)
        result = next((b for b in returned_buffers if b[0] == lane and b[4:] == (begin,finish)), None)
        slow["earlier_same_decoder_type_and_returned_address_in_window"] = (
            any(b[:4] == result[:4] and b[5] < begin for b in returned_buffers)
            if result and result[3] and int(result[3], 0) else None)
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


def describe_buffer(call, samples):
    duration, owner, kind, start, end = call
    bracketed = Counter()
    n = LANES.index(owner)
    for left, right in zip(samples, samples[1:]):
        dt = right[0]-left[0]
        if dt > 30000 or left[0] < start or right[0] > end:
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    capture = json.loads(args.capture.read_text(encoding="utf-8"))
    result = [correlate(args.etl, capture, interval) for interval in intervals(capture)]
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(result, file, indent=2)
        file.write("\n")


if __name__ == "__main__":
    main()
