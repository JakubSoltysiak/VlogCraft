"""Summarize local Phase 3B playback receipts with an explicit public field allowlist.

Example: python benchmarks/phase3b_handoff_evidence.py --trial frozen composition test-1 build/qa/test-1
Repeat --trial for each attempt, including failures. No application log, project, media path or clip ID is copied.
"""
import argparse
from collections import defaultdict
from fractions import Fraction
import json
import math
from pathlib import Path
import re
from statistics import median


def number(value):
    return value if type(value) in (float, int) and math.isfinite(value) else None


def numbers(row, keys):
    return {key: number(row.get(key)) for key in keys.split()}


def load(path):
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def distribution(values):
    values = [value for value in values if number(value) is not None]
    return {"count":len(values),"min":min(values),"median":median(values),"max":max(values)} if values else {"count":0}


def check(condition, value):
    """Missing metrics remain unknown, including 0/0 sample cases."""
    return None if value is None else bool(condition(value))


def gate(checks):
    return "failed" if False in checks.values() else "unverified" if None in checks.values() else "passed"


def digest(value):
    return value if isinstance(value,str) and re.fullmatch(r"[a-fA-F0-9]{64}",value) else None


def conditions(receipt, manifest):
    rows = (receipt.get("conditions") or {}).get("samples", [])
    window = receipt.get("window_condition") or receipt.get("window") or {}
    hardware = manifest.get("conditions") or {}
    known = ["visible","preview_center_unobscured","foreground_owned","minimized"]
    observations = {}
    for key in known:
        samples = [s[key] for s in window.get("samples",[]) if type(s.get(key)) is bool]
        observations[key+"_samples_true"] = sum(samples) if samples else None
    dpr = receipt.get("physical_alignment") or receipt.get("preview_geometry") or {}
    return {"ac_all": all(r.get("ac_power") is True for r in rows) if rows else None,
            "power_samples":len(rows),"physical_window_held":window.get("condition_held"),
            "window_samples":len(window.get("samples",[])),**observations,
            "window_dpi":number(dpr.get("window_dpi")), "browser_dpr":number(dpr.get("browser_dpr",dpr.get("dpr"))),
            "desktop_hz":number(hardware.get("desktop_hz",receipt.get("desktop_reported_refresh_hz"))),
            "desktop_pixels":[number(v) for v in hardware.get("physical_desktop_px",[])],
            "available_ram_MiB":distribution(s.get("available_memory_MiB") for s in rows),
            "machine_cpu_percent":distribution(s.get("system_cpu_percent") for s in rows)}


COUNTERS = ("completed_frames present_calls dxgi_present_count distinct_sequence_submissions skipped_sequence_frames "
            "skipped_after_source_wait skipped_after_gpu_wait skipped_without_queue_wait source_wait_iterations "
            "gpu_wait_iterations nonadvancing_redraws clock_backwards_frames repeated_source_layer_frames")
POOL = ("peak_decoder_count peak_source_queue_frames peak_inflight_gpu_frames gpu_slot_budget retained_texture_pools "
        "retained_surface_views retained_texture_estimated_MiB decoder_opens resumed_decoders peak_standby_surface_bytes "
        "standby_surface_budget_bytes peak_standby_reserved_bytes cold_prepares prepare_retries")
HIST = "count mean_ms p50_upper_ms p95_upper_ms p99_upper_ms max_ms overflow_100ms"
STAGES = ("open_file probe_stream open_codec receive_picture read_demux send_packet drain_codec "
          "seek_demux flush_codec gpu_available select_picture create_decoder status_report "
          "drain_compositor release_views retire_decoder draw_and_present open_producer dxgi_present "
          "device_lock_wait device_lock_owned").split()


def stall_window(gap):
    """Union intervals within each stage. Distinct stages/threads can cover the same wall time."""
    begin,end=gap["begin_us"],gap["end_us"]
    stages=defaultdict(list)
    for event in gap["stages"]:
        if event.get("stage") in STAGES:
            stages[event["stage"]].append(event)
    coverage={}
    for stage,events in stages.items():
        intervals=sorted((max(begin,e["start_us"]),min(end,e["start_us"]+e["duration_us"])) for e in events)
        total=0;right=begin
        for start,finish in intervals:
            total+=max(0,finish-max(right,start))
            right=max(right,finish)
        coverage[stage]={"observations":len(events),"covered_wall_us":total,
                         "longest_call":numbers(max(events,key=lambda e:e["duration_us"]),
                                              "frame source decoder generation decode_epoch queue_depth source_tick timebase_num timebase_den clock_us start_us duration_us")}
    return {**numbers(gap,"frame lost begin_us end_us matching_recent_events"),
            "retained_events":len(gap["stages"]),"overlapping_by_stage":coverage}


def stage_summary(trace):
    misses = trace.get("bounded_missed_events",[])
    # Recent ring and longest-event reservoir overlap. Deduplicate their shared entries.
    stages = {}
    for item in [*trace.get("recent_stages",[]),*trace.get("longest_stages",[])]:
        if item.get("stage") in STAGES:
            key = tuple(item.get(k) for k in ("stage","start_us","duration_us","decoder","generation","frame","decode_epoch"))
            stages[key] = item
    by_stage = {}
    for stage in STAGES:
        group = [item for item in stages.values() if item["stage"]==stage]
        if group:
            largest = max(group,key=lambda e:e["duration_us"])
            by_stage[stage] = {"retained_count":len(group),"largest":numbers(largest,
                "start_us duration_us frame generation source decoder decode_epoch queue_depth source_tick timebase_num timebase_den clock_us")}
    return {"bounded_missed_event_count":len(misses),
            "largest_missed_events":[numbers(item,"frame lost loop_gap_ms source_selection_ms clock_age_ms "
                 "clock_adjustment_us previous_present_ms context_wait_ms source_wait gpu_wait")
                | {flag:item[flag] for flag in ("source_wait","gpu_wait") if type(item.get(flag)) is bool}
                for item in sorted(misses,key=lambda row:row["lost"],reverse=True)[:5]],
            **numbers(trace,"stage_threshold_us stage_event_count"),
            "retained_stage_maxima":by_stage,
            "largest_miss_windows":[stall_window(w) for w in trace.get("largest_miss_windows",[])]}


def playback(receipt, trace):
    base = receipt.get("base",{})
    last = receipt.get("last",{})
    final = receipt.get("drained_last") or last
    delta = {}
    for key in COUNTERS.split():
        start, end = number(base.get(key)), number(last.get(key))
        delta[key] = end-start if start is not None and end is not None else None
    raw_timing = last.get("timings",{})
    timings = {kind:numbers(raw_timing[kind],HIST) for kind in (
        "playback_present_interval","present_call","composition_gpu","context_wait","source_selection",
        "submit_cpu","completion_observation","wake_overshoot") if kind in raw_timing}
    for stats in timings.values():
        if not stats["count"]:
            for key in ("mean_ms","p50_upper_ms","p95_upper_ms","p99_upper_ms","max_ms"):
                stats[key]=None
    resources=receipt.get("resources",{})
    gpu=resources.get("gpu") or {}
    observer=receipt.get("gpu_counter_observer","")
    pdh=False if observer.startswith("disabled") else True if observer.startswith("legacy high-frequency") else None
    runtime=(receipt.get("runtime_trace") or {}).get("samples",[])
    memory={}
    for role in ["host","webview","native","ffmpeg","other"]:
        group=[sample["groups"][role] for sample in runtime if role in sample.get("groups",{})]
        if group:
            memory[role]={key:distribution(item.get(key) for item in group) for key in ("rss_MiB","private_commit_MiB")}
    seconds=number(receipt.get("seconds"))
    measured=number(receipt.get("measured_seconds"))
    rate=receipt.get("rate")
    rate=str(Fraction(rate)) if rate else None
    expected=round(Fraction(str(seconds))*Fraction(rate)) if seconds and rate else None
    intervals=timings.get("playback_present_interval",{})
    mean_ms=intervals.get("mean_ms")
    dims=lambda k:[number(val) for val in receipt.get(k,[])]
    return {"seconds":seconds,"rate":rate,"source_px":dims("original_resolution"),"composition_px":dims("program_resolution"),
            "actual_surface_px":[number(last.get("surface_width")),number(last.get("surface_height"))],
            "source_rewind_schedule":"staggered" if receipt.get("source_rewind_schedule")=="staggered diagnostic" else "original",
            "proxy":receipt.get("proxies"),"switch_sources":receipt.get("source_switches"),"cut_s":number(receipt.get("cut_seconds")),
            **numbers(receipt,"video_tracks audio_tracks measured_seconds distinct_sequence_fps samples expected_samples underruns"),
            "expected_last_frame":expected-1 if expected else None,
            "expected_distinct_sequence_frames":expected,"initial_distinct_submissions":number(base.get("distinct_sequence_submissions")),
            "last_observed_distinct_submissions":number(last.get("distinct_sequence_submissions")),
            "post_wait_distinct_submissions":number(final.get("distinct_sequence_submissions")),
            "wall_duration_minus_nominal_ms":(measured-seconds)*1000 if measured is not None and seconds is not None else None,
            "native_consecutive_active_present_rate":1000/mean_ms if mean_ms and mean_ms>0 else None,
            "initial_active_present_intervals":number(base.get("timings",{}).get("playback_present_interval",{}).get("count")),
            "active_present_intervals":intervals.get("count"),
            "completed_last_frame":number(final.get("completed_sequence_frame")),"reached_end":receipt.get("reached_end"),
            "counter_delta":delta,"native_timings_ms":timings,"decoder_and_texture_pool":numbers(last,POOL),
            "final_decoder_statistics":[numbers(p,"seeks decoded_frames decode_wall_seconds queued_frames warm_cache_frames "
                                         "warm_budget_frames warm_cache_hits hardware_pool_frames deferred_refills "
                                         "early_rewinds adopted_rewinds rewind_tail_hits peak_queue_plus_tail") for p in last.get("decoder_statistics",[])],
            "peak_summed_working_set_MiB":number(resources.get("peak_summed_working_set_MiB")),"role_memory":memory,
            "gpu_allocation_peaks_MiB":{k:number(gpu.get("peak_process_gpu_memory_MiB",{}).get(k))
                                        for k in ("Dedicated Usage","Shared Usage")},
            "gpu_observer_cost":numbers(gpu.get("observer_cost",{}),"sample_calls total_wall_seconds mean_sample_wall_ms maximum_sample_wall_ms"),
            "runtime_observer":bool(receipt.get("runtime_trace")),"gpu_pdh_observer":pdh,"trace":stage_summary(trace) if trace else None}


def soundness(row, data):
    values = data["counter_delta"]
    gap = data["native_timings_ms"].get("playback_present_interval",{}).get("max_ms")
    expected = data["expected_samples"]
    completed = data["completed_last_frame"]
    return {"functional_receipt":check(lambda v:v==0,row["supervisor_exit"]),
            "ended":data["reached_end"],"window_held":row["conditions"]["physical_window_held"],
            "ac_all":row["conditions"]["ac_all"],"no_survivors":check(lambda v:v==0,row["owned_survivors"]),
            "no_underruns":check(lambda v:v==0,data["underruns"]),
            "exact_pcm":(data["samples"]==expected) if expected is not None and expected>0 and data["samples"] is not None else None,
            "exact_last_frame":(completed==data["expected_last_frame"]) if completed is not None and data["expected_last_frame"] is not None else None,
            "at_least_59_5_fps":check(lambda v:v>=59.5,data["distinct_sequence_fps"]),
            "under_30_skips":check(lambda v:v<30,values["skipped_sequence_frames"]),
            "at_most_100ms_gap":check(lambda v:v<=100,gap)}


def summarize_trial(arm, workload, label, directory):
    if not all(re.fullmatch(r"[A-Za-z0-9][-A-Za-z0-9_.]{0,80}",s) for s in (arm,workload,label)):
        raise ValueError("Choose short public aliases for arm, workload and trial")
    meta=load(directory.with_name(directory.name+"-conditions.json"))
    supervisor=load(directory.with_name(directory.name+"-supervisor")/"supervisor.json")
    row={"arm":arm,"workload":workload,"trial":label,"host_sha256":digest(meta.get("executable_sha256")),
         "worker_sha256":digest(meta.get("native_worker_sha256")),
         "supervisor_exit":number(supervisor.get("exit_code")),
         "owned_survivors":number(supervisor.get("process_ownership",{}).get("remaining_owned_processes"))}
    for name in ("native-playback","seeks","scrub","handoff-verification","memory"):
        receipt=load(directory/(name+".json"))
        if receipt:break
    else:
        row["outcome"]="failed" if row["supervisor_exit"] not in (0,None) else "unverified"
        row["receipt_missing"]=True
        return row
    row["conditions"]=conditions(receipt,meta)
    if name=="native-playback":
        data=playback(receipt,load(directory/"native-misses.json"));row["playback"]=data
        row["screen"]=soundness(row,data)
        row["outcome"]=gate(row["screen"])
    else:
        row["outcome"]=gate({"supervisor_success":check(lambda v:v==0,row["supervisor_exit"]),
                             "no_survivors":check(lambda v:v==0,row["owned_survivors"])})
        if name=="seeks":
            row["seek"]={**numbers(receipt,"first_ready_ms seek_p50_ms seek_p95_ms"),
                         "samples":[numbers(x,"target_seconds milliseconds") for x in receipt.get("seek_samples",[])]}
        elif name=="scrub":
            def gesture(r):
                return {**numbers(r,"newest_picture_ms requested audioFetches checkpoints underruns post_release_frames_before_target"),
                        "timed_out":r.get("timed_out"),"ui_ms":numbers(r.get("gesture_ui_cost_ms") or {},"median p95 maximum")}
            row["paused"]=[gesture(r) for r in receipt.get("paused",[])];row["playing"]=gesture(receipt.get("playing",{}))
        elif name=="handoff-verification":
            row["handoff"]={"passed":receipt.get("passed"),"paused_checks":len(receipt.get("paused",[])),
                            "playing_checks":len(receipt.get("playing",[])),"held_pts_checks":sum(
                                s.get("held_vfr") is True for s in [*receipt.get("paused",[]),*receipt.get("playing",[])]),
                            **numbers(receipt,"physical_color_checks peak_live_decoders peak_queue_frames standby_peak_bytes standby_budget_bytes"),
                            "window_held":receipt.get("window_held"),"cancelled_during_seek":receipt.get("cancelled_during_seek"),
                            "audio":numbers(receipt.get("audio",{}),"samples underruns")}
        else:
            row["editing"]={**numbers(receipt,"seconds timeline_seconds audio_underruns_observed"),
                           "edit_batches":len(receipt.get("editing_batches",[])),"forced_gc":receipt.get("forced_gc"),
                           "renderer_samples":[{"seconds":number(r.get("seconds")),"stage":r["stage"],
                               **numbers(r.get("WebView_roles",{}).get("renderer",{}),"rss_MiB private_commit_MiB")}
                               for r in receipt.get("rows",[]) if r.get("stage") in (
                                   "prepared","active","end","stopped","natural_idle","native_released")]}
    return row


def comparison_contract(row):
    p=row["playback"];c=row["conditions"]
    return {"seconds":p["seconds"],"source_px":tuple(p["source_px"]),"composition_px":tuple(p["composition_px"]),
            "actual_surface_px":tuple(p["actual_surface_px"]),"active_video":p["video_tracks"],"active_audio":p["audio_tracks"],
            "rate":p["rate"],"cut_s":p["cut_s"],"switch_sources":p["switch_sources"],"proxy":p["proxy"],
            "source_rewind_schedule":p.get("source_rewind_schedule","original"),
            "runtime_observer":p["runtime_observer"],"gpu_pdh_observer":p["gpu_pdh_observer"],
            "native_trace":p["trace"] is not None,"refresh_hz":c["desktop_hz"],
            "actual_window_dpi":c["window_dpi"],"window_held":c["physical_window_held"],"ac_all":c["ac_all"]}


def paired(before,after):
    result={"before":before["trial"],"after":after["trial"]}
    if "playback" not in before or "playback" not in after:
        return {**result,"comparable":False,"reason":"missing playback receipt"}
    a,b=comparison_contract(before),comparison_contract(after)
    mismatches=[k for k in a if a[k]!=b[k]]
    unknown=[k for k in a if a[k] is None or b[k] is None or
             isinstance(a[k],tuple) and (not a[k] or None in a[k]) or
             isinstance(b[k],tuple) and (not b[k] or None in b[k])]
    if mismatches or unknown or not all(a[k] is True for k in ("window_held","ac_all")):
        return {**result,"comparable":False,"mismatches":mismatches,"unverified_contract":unknown}
    def measures(row):
        p=row["playback"];delta=p["counter_delta"];interval=p["native_timings_ms"].get("playback_present_interval",{})
        return {"distinct_fps":p["distinct_sequence_fps"],"skips":delta["skipped_sequence_frames"],
                "source_wait_skips":delta["skipped_after_source_wait"],"max_active_gap_ms":interval.get("max_ms"),
                "p95_upper_ms":interval.get("p95_upper_ms"),"p99_upper_ms":interval.get("p99_upper_ms"),
                "peak_summed_working_set_MiB":p["peak_summed_working_set_MiB"]}
    old,new=measures(before),measures(after)
    return {**result,"comparable":True,"after_minus_before":{
        k:new[k]-v if v is not None and new[k] is not None else None for k,v in old.items()}}


def aggregates(rows):
    groups=defaultdict(list)
    for row in rows:
        data=row.get("playback")
        if data:
            key=(row["arm"],row["workload"],tuple(comparison_contract(row).items()),row["worker_sha256"],row["host_sha256"])
            groups[key].append(row)
    result=[]
    for group in groups.values():
        first=group[0];data=first["playback"]
        recordings=[r["playback"] for r in group]
        result.append({"arm":first["arm"],"workload":first["workload"],"trials":[r["trial"] for r in group],
                       "worker_sha256":first["worker_sha256"],"seconds":data["seconds"],"composition_px":data["composition_px"],
                       "actual_surface_px":data["actual_surface_px"],"runtime_observer":data["runtime_observer"],
                       "has_miss_trace":data["trace"] is not None,
                       "screens":{s:sum(r["outcome"]==s for r in group) for s in ("passed","failed","unverified")},
                       "fps":distribution(d["distinct_sequence_fps"] for d in recordings),
                       "skips":distribution(d["counter_delta"]["skipped_sequence_frames"] for d in recordings),
                       "max_gap_ms":distribution(d["native_timings_ms"].get("playback_present_interval",{}).get("max_ms") for d in recordings),
                       "peak_summed_working_set_MiB":distribution(d["peak_summed_working_set_MiB"] for d in recordings)})
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial",nargs=4,action="append",required=True,metavar=("ARM","WORKLOAD","LABEL","DIRECTORY"))
    parser.add_argument("--pair",nargs=2,action="append",default=[],metavar=("BEFORE","AFTER"),
                        help="Calculate matched playback deltas for these trial labels")
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    trials=[summarize_trial(arm,workload,alias,Path(folder)) for arm,workload,alias,folder in args.trial]
    if len({r["trial"] for r in trials})!=len(trials):parser.error("Every trial needs a unique alias")
    by_label={row["trial"]:row for row in trials}
    if any(label not in by_label for labels in args.pair for label in labels):parser.error("Unknown pair label")
    report={"native_endpoint":"Distinct sequence submissions / observed playback wall time; presentation timing is between DXGI submissions.",
            "histograms":"p50/p95/p99 are native bucket upper bounds. Stage maxima cover the bounded trace only.",
            "memory":"Private commit, working set and GPU counters are separate. Shared GPU and UMA mappings can overlap.",
            "cohorts":"All observed scores are included, including failed screens. Missing receipts remain individual attempts.",
            "trials":trials,"playback_groups":aggregates(trials),
            "paired_playback":[paired(by_label[before],by_label[after]) for before,after in args.pair]}
    text=json.dumps(report,indent=2,allow_nan=False)+"\n"
    if args.output:args.output.write_text(text,encoding="utf-8")
    else:print(text,end="")
