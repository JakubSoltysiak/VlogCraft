"""Reduce a native stall recorder file to allowlisted observations on its monotonic timeline."""

import argparse
from collections import Counter
import json
from pathlib import Path

STAGES = frozenset("""
    idle hardware_format open_file probe_stream open_codec close_decoder receive_picture
    drain_codec read_demux send_packet seek_demux flush_codec prepare_present dxgi_present
    dxgi_statistics poll_gpu compose_gpu flush_gpu write_status dispatch_messages
    wait_clock_deadline wait_source_retry wait_gpu_slot open_producer cancel_producer join_producer
    reset_producer prime_rewind adopt_rewind parkable_producer producer_guard producer_cv_wait
    decode_next producer_commit decode_texture_desc release_refill select_picture
""".split())
LANES = ("renderer", "source_1", "source_2", "source_3")
TRIGGER_US = 100_000
MAX_INTERVAL_US = 30_000
NO_PTS = -(1 << 63)
REQUEST_HEADER = (
    "sequence", "observed_us", "frame", "generation", "playing", "clock_us", "due_us",
    "layer_mask", "outcome", "last_returned_frame", "last_returned_generation", "gpu_pending",
)
REQUEST_LAYER = (
    "lane", "source", "decoder", "decode_epoch", "clip_tick", "clip_timebase_num", "clip_timebase_den",
    "stream_tick", "stream_timebase_num", "stream_timebase_den", "floor_pts", "successor_pts", "reason",
    "entered_us", "inspected_us", "queue_depth", "queue_pts_0", "queue_pts_1", "queue_pts_2", "queue_pts_3",
    "warm_count", "outgoing_tail_count", "eof", "refill_held", "packet_reads", "packet_submits",
    "decoded_pictures", "rewind_generation", "worker_epoch",
)
PICTURE_REASONS = ("opening", "missing_floor", "missing_successor", "live", "warm", "outgoing",
                   "before_first_picture", "terminal_eof", "producer_replaced")


def number(value):
    return value if type(value) is int else None


def counts(row, names):
    return {name: number(row.get(name)) for name in names.split()}


def stage(value):
    return value if isinstance(value, str) and value in STAGES else "other"


def stall_start(samples, frame, generation):
    for sample in samples:
        position, torn, mode_since, transport, loop, submission = sample[:6]
        start = max(mode_since, submission[2])
        if (not (torn & 1) and transport[2] and transport[1] == loop[1] == generation and
                submission[:2] == [frame, generation] and position - start >= TRIGGER_US):
            return start
    return None


def overlaps(samples, start, finish):
    # A stable pair brackets an observation. Skip torn data and sparse pairs,
    # and require identical IDs and operation entry times at both ends.
    coverage = [Counter() for _ in LANES]
    progress = [Counter() for _ in LANES]
    owner_waiters = Counter()
    render_decoder = Counter()
    overall = Counter()
    for before, after in zip(samples, samples[1:]):
        interval = min(finish, after[0]) - max(start, before[0])
        if interval <= 0:
            continue
        if after[0] - before[0] > MAX_INTERVAL_US:
            overall["sparse_us"] += interval
            continue
        if (before[1] | after[1]) & 1:
            overall["torn_global_us"] += interval
            continue
        overall["globally_coherent_us"] += interval
        endpoints = (("gpu_submissions", before[6][0], after[6][0]),
                     ("gpu_completions", before[6][1], after[6][1]), ("present_returns", before[7], after[7]))
        whole_interval = start <= before[0] and after[0] <= finish
        if whole_interval:
            for key, left, right in endpoints:
                overall[key] += max(0, right - left)
        states = {}
        for index, (left, right) in enumerate(zip(before[8:], after[8:])):
            if (before[1] | after[1]) & (2 << index):
                continue
            activity, following = left[2], right[2]
            if not activity[7] or activity[7:] != following[7:] or left[3] != right[3]:
                continue
            if activity[0] == following[0] and left[0] == right[0]:
                states[index] = stage(left[0])
                coverage[index][states[index]] += interval
            if whole_interval:
                for name, x, y in (("packet_reads", left[6][2], right[6][2]),
                                   ("stage_entries", activity[1], following[1]),
                                   ("stage_exits", activity[2], following[2])):
                    progress[index][name] += max(0, y - x)
                if activity[6] >= 0 and following[6] >= activity[6]:
                    progress[index]["accounted_cpu_us"] += following[6] - activity[6]
        for owner, owner_stage in states.items():
            left, right = before[8+owner][7], after[8+owner][7]
            if left != right or not left[1]:
                continue
            for waiter, waiter_stage in states.items():
                left, right = before[8+waiter][7], after[8+waiter][7]
                if owner != waiter and left == right and left[0]:
                    owner_waiters[(LANES[owner], owner_stage, LANES[waiter], waiter_stage)] += interval
        if 0 in states:
            for index, decoder in states.items():
                if index:
                    render_decoder[(states[0], LANES[index], decoder)] += interval
    return {
        "coverage_by_lane": {lane: dict(coverage[i]) for i, lane in enumerate(LANES)},
        "observed_progress_by_lane": {lane: dict(progress[i]) for i, lane in enumerate(LANES)},
        "device_wait_overlaps": [
            {"owner_lane": owner, "owner_stage": owning, "waiter_lane": waiter, "waiter_stage": waiting, "observed_us": us}
            for (owner, owning, waiter, waiting), us in owner_waiters.most_common()
        ],
        "renderer_source_overlaps": [
            {"renderer_stage": renderer, "source_lane": lane, "source_stage": decoder, "observed_us": us}
            for (renderer, lane, decoder), us in render_decoder.most_common()
        ],
        **overall,
    }


def source_snapshots(samples):
    result = {}
    for index, name in enumerate(LANES[1:], 1):
        rows = [sample[8+index] for sample in samples
                if not sample[1] & (2 << index) and sample[8+index][2][7]]
        if rows:
            source = rows[-1][3]
            selections = [lane[5] for lane in rows]
            quotes = [dict(zip(("frame", "generation", "target_pts", "floor_pts", "next_pts", "path_code"), lane[5]))
                      for lane in (rows[0], rows[-1])]
            result[name] = {"source_ordinal": source[0], "decoder_ordinal": source[1], "stream_timebase": source[2:],
                            "queue_depth_range": [min(lane[4][3] for lane in rows), max(lane[4][3] for lane in rows)],
                            "warm_pictures_peak": max(lane[4][4] for lane in rows),
                            "outgoing_tail_pictures_peak": max(lane[4][5] for lane in rows),
                            "incoming_epoch_range": [min(lane[4][6] for lane in rows), max(lane[4][6] for lane in rows)],
                            "queue_ready_samples": sum(bool(lane[4][7]) for lane in rows),
                            "first_and_last_recorded_selection": quotes,
                            "selection_changes": sum(a != b for a, b in zip(selections, selections[1:]))}
    return result


def source_request(raw):
    width = len(REQUEST_HEADER) + 3 * len(REQUEST_LAYER)
    if not isinstance(raw, list) or len(raw) != width or any(type(value) is not int for value in raw):
        return None
    header = dict(zip(REQUEST_HEADER, raw))
    mask = header["layer_mask"]
    if (header["sequence"] <= 0 or mask not in (0, 1, 3, 7) or
            header["outcome"] & ~(mask | 8)):
        return None
    ready = header["outcome"] & mask
    layers = []
    for index in range(mask.bit_count()):
        start = len(REQUEST_HEADER) + index * len(REQUEST_LAYER)
        layer = dict(zip(REQUEST_LAYER, raw[start:start + len(REQUEST_LAYER)]))
        reason = layer.pop("reason")
        name = PICTURE_REASONS[reason] if 0 <= reason < len(PICTURE_REASONS) else "unknown"
        selected = bool(ready & (1 << index))
        if name in ("unknown", "producer_replaced") or not 1 <= layer["lane"] <= 3:
            layers.append({"layer": index + 1, "reason": name, "selected": selected, "incomplete": True})
            continue
        queue = [layer.pop(f"queue_pts_{i}") for i in range(4)]
        for key in ("stream_tick", "floor_pts", "successor_pts"):
            if layer[key] == NO_PTS:
                layer[key] = None
        for key in ("eof", "refill_held"):
            layer[key] = bool(layer[key])
        target, floor, successor = (layer[key] for key in ("stream_tick", "floor_pts", "successor_pts"))
        bracket = None if None in (target, floor, successor) else floor <= target < successor
        terminal = (target is not None and floor is not None and floor <= target and successor is None and
                    name in ("terminal_eof", "outgoing"))
        layers.append({**layer, "layer": index + 1, "selected": selected, "reason": name,
                       "queued_pts": [pts for pts in queue if pts != NO_PTS], "interval_covers_target": bracket,
                       "terminal_interval": terminal})
    return {**header, "layers": layers, "ready_layer_mask": ready, "all_layers_selected": bool(mask) and ready == mask,
            "gpu_slot_available": bool(header["outcome"] & 8),
            "deadline_due_at_clock_sample": header["clock_us"] + 1 >= header["due_us"],
            "all_source_intervals_verified": bool(layers) and all(
                layer["selected"] and (layer.get("interval_covers_target") or layer.get("terminal_interval"))
                for layer in layers)}


def watchdog_observations(samples, at):
    left = next((sample for sample in reversed(samples) if sample[0] <= at), None)
    right = next((sample for sample in samples if sample[0] > at), None)
    observations = []
    for sample in (left, right):
        if sample is None or abs(sample[0] - at) > MAX_INTERVAL_US:
            continue
        timestamp, torn = sample[:2]
        observations.append({
            "sample_us": timestamp, "relative_to_request_us": timestamp - at, "torn_mask": torn,
            "requested_frame": None if torn & 1 else sample[4][0],
            "generation": None if torn & 1 else sample[4][1],
            "gpu_submitted": None if torn & 1 else sample[6][0],
            "gpu_completed": None if torn & 1 else sample[6][1],
            "lanes": {name: {"stage": stage(lane[0]), "stage_entered_us": lane[2][0],
                             "device_waiting": bool(lane[7][0]), "device_owned": bool(lane[7][1]),
                             "device_state_since_us": lane[7][2]}
                      for index, (name, lane) in enumerate(zip(LANES, sample[8:]))
                      if not torn & (2 << index) and lane[2][7]},
        })
    return observations


def request_window(raw, *, generation, frame, exact_frame=False):
    retained = raw.get("requests", [])
    samples = raw.get("samples", [])
    requests = [row for values in retained if (row := source_request(values)) is not None]
    pairs = list(zip(requests, requests[1:]))
    result = {
        "retained_requests": len(retained), "invalid_requests": len(retained) - len(requests),
        "overwritten_requests": number(raw.get("overwritten" if exact_frame else "overwritten_requests")),
        "missing_request_sequences": sum(max(0, b["sequence"] - a["sequence"] - 1) for a, b in pairs),
        "nonincreasing_request_sequences": sum(b["sequence"] <= a["sequence"] for a, b in pairs),
        "largest_retained_request_gap_us": max((b["observed_us"] - a["observed_us"] for a, b in pairs), default=None),
    }
    miss_index = next((i for i, row in enumerate(requests)
                       if row["generation"] == generation and row["playing"] and row["layer_mask"] and
                       not row["all_layers_selected"] and row["last_returned_generation"] == generation and
                       row["frame"] > row["last_returned_frame"] >= 0 and
                       (row["frame"] == frame if exact_frame else row["frame"] > frame)), None)
    if miss_index is None:
        return result
    miss = requests[miss_index]
    following = []
    for row in requests[miss_index + 1:]:
        if row["generation"] != generation or not row["playing"]:
            break
        following.append(row)
    matched = [row for row in following if row["layer_mask"] == miss["layer_mask"]]
    ready = next((row for row in matched if row["all_layers_selected"]), None)
    verified = next((row for row in matched if row["all_source_intervals_verified"]), None)
    result.update(
        requests_before_miss=miss_index,
        first_missing_request=miss,
        preceding_requests=requests[max(0, miss_index - 3):miss_index],
        first_all_layers_selected=ready,
        first_all_intervals_verified=verified,
        ready_on_missed_frame=next((row for row in matched if row["frame"] == miss["frame"] and
                                    row["all_layers_selected"]), None),
        last_unready_before_first_ready=next((row for row in reversed(following)
                                             if not row["all_layers_selected"] and
                                             (ready is None or row["sequence"] < ready["sequence"])), None),
        watchdog_near_first_missing_request=watchdog_observations(samples, miss["observed_us"]),
        watchdog_near_first_ready_request=watchdog_observations(samples, ready["observed_us"]) if ready else [],
    )
    return result


def reduce_incident(record):
    samples = record["samples"]
    start = stall_start(samples, record["last_frame"], record["generation"])
    end = start + record["observed_age_us"] if start is not None else None
    interval = [row for row in samples if start is not None and start <= row[0] <= end]
    coherent = [row for row in interval if not row[1] & 1]
    stage_samples = {
        lane: dict(Counter(stage(row[8+index][0]) for row in interval
                           if not row[1] & (2 << index) and row[8+index][2][7]))
        for index, lane in enumerate(LANES)
    }
    span = {
        **counts(record, "last_frame generation observed_age_us dropped_middle_samples"),
        **{key: bool(record[key]) for key in ("recovered", "transition", "truncated")},
        "retained_samples": len(samples),
        "torn_samples": sum(bool(row[1]) for row in samples),
        "largest_retained_poll_gap_us": max((b[0] - a[0] for a, b in zip(samples, samples[1:])), default=None),
        "prefix_us": max(0, start - samples[0][0]) if start is not None else None,
        "post_stall_us": max(0, samples[-1][0] - end) if end is not None else None,
        "attributed_intervals": overlaps(samples, start, end) if interval else {},
        "stage_sample_counts": stage_samples,
        "source_state": source_snapshots(interval),
    }
    if coherent:
        first, last = coherent[0], coherent[-1]
        span["first_and_last_loop_observations"] = [
            dict(zip(("target_frame", "generation", "audio_us", "next_audio_deadline_us", "heartbeat_us"), row[4]))
            for row in (first, last)]
    if "requests" in record:
        span["source_request_window"] = request_window(record, generation=record["generation"], frame=record["last_frame"])
    return span


def reduce_record(raw):
    if raw.get("version") != 1:
        raise ValueError("Unsupported Phase 3B native stall recorder version")
    result = {
        **counts(raw, "version polls max_poll_gap_us torn_samples trigger_count shared_device_ordinal"),
        "maximum_coherent_pair_interval_us": MAX_INTERVAL_US,
        "incidents": [reduce_incident(item) for item in raw["incidents"]],
    }
    if "source_request_counts" in raw:
        result["source_request_counts"] = dict(zip(("published", "read_through_sequence", "lost"),
                                                   map(number, raw["source_request_counts"])))
        miss = raw["first_source_miss"]
        result["first_source_miss"] = {
            **counts(miss, "frame generation"),
            **request_window(miss, generation=miss["generation"], frame=miss["frame"], exact_frame=True),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.capture.read_text(encoding="utf-8-sig"))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(reduce_record(raw), stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
