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
    queue_full producer_eof refill_deferred
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
REFILL_REASONS = ("active", "selection", "renderer", "reset", "cancel", "eof", "expired", "error")
RENDERER_OWNERSHIP_TORN = 32
SOURCE_OWNERSHIP_TORN = 64
SURFACE_MASK = (1 << 64) - 1


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
    per_lane_device_wait = Counter()
    per_lane_device_ownership = Counter()
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
        for index, (left, right) in enumerate(zip(before[8:8+len(LANES)], after[8:8+len(LANES)])):
            if (before[1] | after[1]) & (2 << index):
                continue
            activity, following = left[2], right[2]
            if not activity[7] or activity[7:] != following[7:] or left[3] != right[3]:
                continue
            if activity[0] == following[0] and left[0] == right[0]:
                states[index] = stage(left[0])
                coverage[index][states[index]] += interval
            device = left[7]
            if device == right[7]:
                if device[0]:
                    per_lane_device_wait[LANES[index]] += interval
                if device[1]:
                    per_lane_device_ownership[LANES[index]] += interval
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
        "device_wait_us_by_lane": dict(per_lane_device_wait),
        "device_owned_us_by_lane": dict(per_lane_device_ownership),
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
        queued = [pts for pts in queue if pts != NO_PTS]
        headroom = max(queued) - target if queued and target is not None else None
        terminal = (target is not None and floor is not None and floor <= target and successor is None and
                    name in ("terminal_eof", "outgoing"))
        layers.append({**layer, "layer": index + 1, "selected": selected, "reason": name,
                       "queued_pts": queued, "queue_headroom_pts": headroom, "interval_covers_target": bracket,
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


def pacing_lane(sample, index):
    lane = sample[8 + index]
    if sample[1] & (1 | (2 << index)) or not lane[2][7] or len(lane) < 9:
        return None
    return lane


def pacing_window(samples, start, finish, generation, *, request_us=None):
    presents = {}
    holds = {}
    for sample in samples:
        renderer = pacing_lane(sample, 0)
        if renderer is not None:
            begin, frame, gen, last_begin, last_end, last_frame, last_gen = renderer[8]
            if begin > 0 and gen == generation:
                presents.setdefault((begin, frame), [None, begin])[1] = max(begin, sample[0])
            if 0 < last_begin <= last_end and last_gen == generation:
                presents[(last_begin, last_frame)] = [last_end, last_end]
        for index in range(1, len(LANES)):
            lane = pacing_lane(sample, index)
            if lane is None:
                continue
            begin, end, reason, target, farthest, epoch, count = lane[8]
            if begin <= 0 or count <= 0:
                continue
            key = (index, lane[3][0], lane[3][1], epoch, count, begin)
            hold = holds.setdefault(key, {
                "lane": LANES[index], "source_ordinal": lane[3][0], "decoder_ordinal": lane[3][1],
                "stream_timebase": lane[3][2:], "hold_epoch": epoch, "hold_count": count,
                "begin_us": begin, "end_us": None, "release_reason": None,
                "target_pts": target, "farthest_queued_pts": farthest, "headroom_pts": farthest - target,
            })
            hold["observed_through_us"] = sample[0]
            if end >= begin:
                hold["end_us"] = end
                hold["release_reason"] = REFILL_REASONS[reason] if 0 < reason < len(REFILL_REASONS) else "other"
    candidates = [(begin, frame, end, through) for (begin, frame), (end, through) in presents.items()
                  if begin < finish and through > start]
    selected = sorted(candidates, key=lambda item: item[3] - item[0], reverse=True)[:3]
    predecessor = max((item for item in candidates if request_us is not None and
                       item[2] is not None and item[2] <= request_us), key=lambda item: item[2], default=None)
    if predecessor is not None and predecessor not in selected:
        selected.append(predecessor)
    intervals = []
    for begin, frame, end, through in sorted(selected):
        coverage = overlaps(samples, begin, through)
        related = []
        for hold in holds.values():
            end_or_sample = hold["end_us"] if hold["end_us"] is not None else hold["observed_through_us"]
            overlap = min(through, end_or_sample) - max(begin, hold["begin_us"])
            if overlap > 0:
                related.append({**hold, "observed_overlap_us": overlap,
                                "known_held_at_present_return": end is not None and end_or_sample >= end})
        intervals.append({
            "frame": frame, "generation": generation, "begin_us": begin, "end_us": end,
            "observed_through_us": through, "completed_duration_us": end - begin if end is not None else None,
            "latest_completed_before_request": (begin, frame, end, through) == predecessor,
            "refill_holds": related, "sampled_interval": coverage,
        })
    return {
        "retained_present_intervals": len(candidates),
        "reported_present_intervals": intervals,
        "present_selection": "Three longest observed intervals and the latest completed Present before the request, when retained.",
        "pacing_scope": "Lane tuples are sampled independently. Open intervals end at the last valid observation. Progress and lock coverage exclude torn or sparse pairs. Intervening edges can be overwritten.",
    }


def picture_mask(pictures, pool, capacity):
    mask = 0
    for key, slice_index, _pts in pictures:
        if key == pool and 0 <= slice_index < capacity:
            mask |= 1 << slice_index
    return mask


def pictures(values, start):
    return [values[index:index + 3] for index in range(start, len(values), 3)]


def query_state(query, submitted):
    entered, returned, result = query[2:]
    if entered < submitted:
        return "no_check_observed"
    if not returned:
        return "check_in_progress"
    return {0: "ready", 1: "unready"}.get(result, "other_hresult")


def ownership_window(samples, start, finish):
    pools = {}
    pending = {}
    checks = {}
    retirements = set()
    coverage = Counter()
    zero_pending_samples = []
    max_cache_views = max_cache_pools = 0
    for sample in samples:
        timestamp, torn = sample[:2]
        if not start <= timestamp <= finish or len(sample) < 13:
            continue
        coverage["samples"] += 1
        if torn & (1 | RENDERER_OWNERSHIP_TORN):
            coverage["torn_renderer_samples"] += 1
            continue
        selected, cache, slots = sample[12]
        count, views, cached_pools, _cache_observed = cache
        max_cache_views = max(max_cache_views, views)
        max_cache_pools = max(max_cache_pools, cached_pools)
        slot_pictures = []
        pending_slots = []
        for index, (holds, check, retired) in enumerate(slots[:count]):
            active, frame, generation, submitted = holds[:4]
            check_frame, check_generation, entered = check[:3]
            if start <= entered <= finish and entered > 0:
                checks[index, check_frame, check_generation, entered] = query_state(check, entered)
            retired_frame, retired_generation, released = retired
            if start <= released <= finish and released > 0:
                retirements.add((index, retired_frame, retired_generation, released))
            # A retirement and a slot state can straddle the sampling read.
            if active and not (retired[:2] == holds[1:3] and released >= submitted):
                slot_pictures.extend(pictures(holds, 4))
                same_submission = check[:2] == holds[1:3] and entered >= submitted
                state = query_state(check, submitted) if same_submission else "no_check_observed"
                pending_slots.append((index, frame, generation, submitted, entered if same_submission else None, state))

        # Application updates and slot reads are independent. Exclude
        # snapshots whose pending count disagrees with the renderer counters.
        counters = sample[6]
        if len(pending_slots) != counters[0] - counters[1]:
            coverage["transition_samples"] += 1
            continue
        coverage["coherent_renderer_samples"] += 1
        if not pending_slots:
            zero_pending_samples.append(timestamp)
        for index, frame, generation, submitted, entered, state in pending_slots:
            span = pending.setdefault((index, frame, generation, submitted), {
                "slot": index, "frame": frame, "generation": generation, "submitted_observed_us": submitted,
                "first_sample_us": timestamp, "last_sample_us": timestamp, "last_check_entered_us": entered,
                "sampled_query_states": Counter(),
            })
            span["last_sample_us"] = timestamp
            span["last_check_entered_us"] = entered
            span["sampled_query_states"][state] += 1

        selected_pictures = pictures(selected, 1)
        for index, name in enumerate(LANES[1:], 1):
            lane = sample[8 + index]
            if torn & ((2 << index) | (SOURCE_OWNERSHIP_TORN << index)) or not lane[2][7] or len(lane) < 11:
                continue
            pool, capacity, current, queued, warm, tail, untracked, _producer_observed = lane[9]
            if not pool or not 0 < capacity <= 2048:
                continue
            source, decoder = lane[3][:2]
            scratch = lane[10]
            producer_mask = (current | queued | warm | tail) & SURFACE_MASK
            scratch_mask = picture_mask([scratch[:3]], pool, capacity)
            selected_mask = picture_mask(selected_pictures, pool, capacity)
            slot_mask = picture_mask(slot_pictures, pool, capacity)
            outside_slots = producer_mask | scratch_mask | selected_mask
            union = outside_slots | slot_mask
            group = pools.setdefault((name, source, decoder, pool, capacity), {
                "lane": name, "source_ordinal": source, "decoder_ordinal": decoder,
                "pool_ordinal": len(pools) + 1, "pool_array_size": capacity,
                "first_sample_us": timestamp, "last_sample_us": timestamp, "samples": 0,
                "untracked_producer_samples": 0, "all_slices_app_referenced_samples": 0,
                "first_and_last_decoder_received_count": [scratch[4], scratch[4]],
                "first_and_last_decoder_output_pts": None,
                "peak_unique_slices": Counter(), "minimum_unaccounted_slices": capacity,
            })
            group["last_sample_us"] = timestamp
            group["samples"] += 1
            group["untracked_producer_samples"] += bool(untracked)
            group["all_slices_app_referenced_samples"] += union.bit_count() == capacity
            group["first_and_last_decoder_received_count"][1] = scratch[4]
            if scratch_mask and scratch[2] != NO_PTS:
                if group["first_and_last_decoder_output_pts"] is None:
                    group["first_and_last_decoder_output_pts"] = [scratch[2], scratch[2]]
                group["first_and_last_decoder_output_pts"][1] = scratch[2]
            group["minimum_unaccounted_slices"] = min(group["minimum_unaccounted_slices"], capacity - union.bit_count())
            masks = {"current": current & SURFACE_MASK, "queue": queued & SURFACE_MASK, "warm": warm & SURFACE_MASK,
                     "rewind_tail": tail & SURFACE_MASK, "producer": producer_mask, "decoder_output": scratch_mask,
                     "selected": selected_mask, "gpu_slots": slot_mask, "gpu_slots_only": slot_mask & ~outside_slots,
                     "app_union": union}
            for name, mask in masks.items():
                group["peak_unique_slices"][name] = max(group["peak_unique_slices"][name], mask.bit_count())
    if not coverage:
        return {}
    longest = sorted(pending.values(), key=lambda row: row["last_sample_us"] - row["first_sample_us"],
                     reverse=True)[:6]
    ordered_retirements = sorted(retirements, key=lambda row: row[3])
    endpoints = ordered_retirements if len(ordered_retirements) < 2 else [ordered_retirements[0], ordered_retirements[-1]]
    return {
        "coverage": dict(coverage), "source_pools": list(pools.values()),
        "zero_pending_samples": len(zero_pending_samples),
        "first_and_last_zero_pending_sample_us": [zero_pending_samples[0], zero_pending_samples[-1]]
        if zero_pending_samples else [],
        "peak_cached_views_observed": max_cache_views, "peak_cached_texture_pools_observed": max_cache_pools,
        "observed_query_attempts": dict(Counter(checks.values())), "observed_retirements": len(retirements),
        "first_and_last_retirements": [
            {"slot": slot, "frame": frame, "generation": generation, "released_us": released}
            for slot, frame, generation, released in endpoints
        ],
        "longest_observed_pending_spans": longest,
        "scope": ("Surface counts deduplicate D3D11 slices within each pool. Unaccounted slices can be held by the "
                  "codec or driver. COM views are excluded. Tuples are sampled independently and intermediate "
                  "checks and retirements can be overwritten. Pending slots alone do not show ongoing GPU execution."),
    }


def playing_backsteps(requests, generation):
    spans = []
    count = 0
    for index, (before, after) in enumerate(zip(requests, requests[1:])):
        if (after["sequence"] != before["sequence"] + 1 or after["frame"] >= before["frame"] or
                any(row["generation"] != generation or not row["playing"] for row in (before, after))):
            continue
        count += 1
        if len(spans) == 6:
            continue
        following = requests[index + 2] if index + 2 < len(requests) else None
        if (following and following["sequence"] == after["sequence"] + 1 and
                following["generation"] == generation and following["playing"]):
            spans.append([before, after, following])
        else:
            spans.append([before, after])
    return {"count": count, "reported_spans": spans}


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
        "retained_watchdog_samples": len(samples),
        "torn_watchdog_samples": sum(bool(sample[1]) for sample in samples),
        "largest_retained_watchdog_gap_us": max((b[0] - a[0] for a, b in zip(samples, samples[1:])), default=None),
    }
    backsteps = playing_backsteps(requests, generation)
    if backsteps["count"]:
        result["retained_playing_backsteps"] = backsteps
    miss_index = next((i for i, row in enumerate(requests)
                       if row["generation"] == generation and row["playing"] and row["layer_mask"] and
                       not row["all_layers_selected"] and row["last_returned_generation"] == generation and
                       row["frame"] > row["last_returned_frame"] >= 0 and
                       (row["frame"] == frame if exact_frame else row["frame"] > frame)), None)
    if miss_index is None:
        return result
    miss = requests[miss_index]
    successor_miss = next((row for row in requests[miss_index:] if row["generation"] == generation and
                           row["playing"] and row["layer_mask"] == 7 and
                           row["deadline_due_at_clock_sample"] and
                           row["last_returned_generation"] == generation and row["frame"] > row["last_returned_frame"] >= 0 and
                           not any(layer.get("incomplete") for layer in row["layers"]) and
                           any(layer["reason"] == "missing_successor" for layer in row["layers"])), None)
    following = []
    for row in requests[miss_index + 1:]:
        if row["generation"] != generation or not row["playing"]:
            break
        following.append(row)
    matched = [row for row in following if row["layer_mask"] == miss["layer_mask"]]
    ready = next((row for row in matched if row["all_layers_selected"]), None)
    verified = next((row for row in matched if row["all_source_intervals_verified"]), None)
    first_inspection = min((layer["entered_us"] for layer in miss["layers"] if "entered_us" in layer),
                           default=miss["observed_us"])
    result.update(
        requests_before_miss=miss_index,
        first_missing_request=miss,
        first_retained_three_layer_missing_successor=successor_miss,
        preceding_requests=requests[max(0, miss_index - 3):miss_index],
        first_all_layers_selected=ready,
        first_all_intervals_verified=verified,
        ready_on_missed_frame=next((row for row in matched if row["frame"] == miss["frame"] and
                                    row["all_layers_selected"]), None),
        last_unready_before_first_ready=next((row for row in reversed(following)
                                             if not row["all_layers_selected"] and
                                             (ready is None or row["sequence"] < ready["sequence"])), None),
        watchdog_near_first_layer_inspection=watchdog_observations(samples, first_inspection),
        watchdog_near_first_missing_request=watchdog_observations(samples, miss["observed_us"]),
        watchdog_near_first_ready_request=watchdog_observations(samples, ready["observed_us"]) if ready else [],
    )
    if samples and any(len(sample[8]) > 8 for sample in samples):
        focus = successor_miss or miss
        inspect = min((layer["entered_us"] for layer in focus["layers"] if "entered_us" in layer),
                      default=focus["observed_us"])
        result["pacing_near_first_missing_request"] = pacing_window(
            samples, inspect - 180_000, inspect + 30_000, generation, request_us=inspect)
        ownership = ownership_window(samples, inspect - 30_000,
                                     max(inspect + 30_000, ready["observed_us"] if ready else samples[-1][0]))
        if ownership:
            result["ownership_near_first_missing_request"] = ownership
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
    if interval and any(len(sample[8]) > 8 for sample in interval):
        span["pacing_during_gap"] = pacing_window(samples, start, end, record["generation"])
        ownership = ownership_window(samples, start, end)
        if ownership:
            span["ownership_during_gap"] = ownership
    return span


def reduce_record(raw):
    if raw.get("version") != 1:
        raise ValueError("Unsupported Phase 3B native stall recorder version")
    result = {
        **counts(raw, "version polls max_poll_gap_us torn_samples trigger_count shared_device_ordinal live_write_failures"),
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
        result["source_request_scope"] = (
            "One renderer selection request per tuple with separate guarded layer inspection times. "
            "Adjacent watchdog observations are sampled independently. Repeated equal selection outcomes may be coalesced."
        )
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
