"""Record endpoint timing around an unchanged protected Phase 3B playback run."""

import argparse
from collections import deque
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

import native_playback as protected
from phase3b_stall_campaign import digest, media_stats, serial, WORKER


HOST_TRACE = 'VLOGCRAFT_COMPLETION_TRACE'
NATIVE_STAMPS = (
    'sequence_end_deadline_qpc', 'last_picture_deadline_qpc', 'final_draw_return_qpc',
    'final_gpu_observed_qpc', 'first_clock_eos_qpc', 'gpu_drained_qpc', 'producer_join_qpc',
)
PUBLISHED_BROWSER_PROBE = """()=>{
    if(typeof nativeTraceAudio==='function')throw Error('Use the built-in probe on this package');
    nativeState.completionTrace={};
    const play=nativePlayPause, audio=nativeAudio, stop=stopPlayback;
    nativePlayPause=function(...args){
        if(!isPlaying)nativeState.completionTrace={generation:nativeState.generation,play_call_ms:performance.now()};
        return play.apply(this,args);
    };
    nativeAudio=async function(...args){
        const result=await audio.apply(this,args),port=nativeState.node?.port;
        const receive=port?.onmessage;
        if(!receive)return result;
        port.onmessage=function(event){
            receive.call(this,event);
            const trace=nativeState.completionTrace,ack=event.data;
            if(trace.generation!==ack.generation||nativeState.ack!==ack)return;
            const name=ack.finished?'pcm_finished_ack':ack.samples>0?'pcm_started_ack':null;
            if(!name||trace[name])return;
            const received=performance.now(),output=mixer.getOutputTimestamp?.();
            trace[name]={received_ms:received,samples:ack.samples,underruns:ack.underruns,context_end:ack.contextEnd,
                context_start:ack.segments?.[0]?.[0],output_context:output?.contextTime,output_ms:output?.performanceTime};
        };
        return result;
    };
    stopPlayback=function(...args){
        const trace=nativeState.completionTrace;
        const terminal=isPlaying&&nativeSelected()&&trace.generation===nativeState.generation&&playhead>=nativeDuration();
        if(terminal)trace.gui_stop_invoked_ms=performance.now();
        const result=stop.apply(this,args);
        if(terminal)trace.gui_stopped_ms=performance.now();
        return result;
    };
}"""


def save(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')


def calibration(evaluate):
    candidates = []
    for _ in range(5):
        before = time.perf_counter_ns()
        browser = evaluate('performance.now()')
        after = time.perf_counter_ns()
        # Allow for reduced WebView performance.now() precision.
        candidates.append((before / 1e6 - browser - .1, after / 1e6 - browser + .1))
    lower, upper = max(x[0] for x in candidates), min(x[1] for x in candidates)
    return {'lower_ms': lower, 'upper_ms': upper, 'sample_count': len(candidates),
            'sample_bounds_ms': candidates}


def observe_session(session, results, published_browser_probe=False):
    @contextmanager
    def observe(*args, **kwargs):
        with session(*args, **kwargs) as items:
            page = items[0]
            evaluate = page.evaluate
            wait = page.wait_for_timeout
            trace = {'before': calibration(evaluate),
                     'browser_probe_source': 'published browser runtime wrappers' if published_browser_probe else 'built-in milestones'}
            evaluate(PUBLISHED_BROWSER_PROBE if published_browser_probe else 'nativeState.completionTrace = {}')
            recent = deque(maxlen=8)
            recent_waits = deque(maxlen=8)
            max_gap_ms = None
            max_call_ms = None

            def observed_evaluate(*args, **kwargs):
                nonlocal max_gap_ms, max_call_ms
                before = time.perf_counter_ns()
                data = evaluate(*args, **kwargs)
                after = time.perf_counter_ns()
                if isinstance(data, dict) and 'measured_seconds' in data and 'playing' in data:
                    elapsed_ms = data['measured_seconds'] * 1000
                    if recent:
                        max_gap_ms = max(max_gap_ms or 0, elapsed_ms - recent[-1]['elapsed_ms'])
                    max_call_ms = max(max_call_ms or 0, (after - before) / 1e6)
                    recent.append({'elapsed_ms': elapsed_ms, 'playing': data['playing'],
                                   'reached_end': data['reached_end'], 'native_wall_seconds': data['last'].get('wall_seconds'),
                                   'before_ns': before, 'after_ns': after})
                return data

            def observed_wait(timeout):
                before = time.perf_counter_ns()
                result = wait(timeout)
                after = time.perf_counter_ns()
                if timeout == 250:
                    recent_waits.append({'requested_ms': timeout, 'before_ns': before, 'after_ns': after})
                return result

            try:
                with patch.object(page, 'evaluate', observed_evaluate), patch.object(page, 'wait_for_timeout', observed_wait):
                    yield items
            finally:
                trace.update(observer_tail=list(recent), max_observer_gap_ms=max_gap_ms,
                             max_observer_call_ms=max_call_ms, observer_wait_tail=list(recent_waits))
                try:
                    trace['browser'] = evaluate("""()=>({bench_start_ms:window.nativeBench?.start,
                        milestones:nativeState.completionTrace,last_metrics:{
                        generation:nativeState.metrics?.generation,completed_sequence_frame:nativeState.metrics?.completed_sequence_frame,
                        eos:nativeState.metrics?.eos,completion_stamps_us:nativeState.metrics?.completion_stamps_us}})""")
                    trace['after'] = calibration(evaluate)
                except Exception as error:
                    trace['collection_error'] = type(error).__name__
                save(results / 'completion-browser.private.json', trace)

    return observe


def estimate_audio_ms(ack, endpoint):
    context = ack.get(endpoint)
    output = ack.get('output_ms')
    output_context = ack.get('output_context')
    if context is not None and output and output_context is not None:
        return output + (context - output_context) * 1000
    return None


def summarize(browser_trace, host_trace, receipt):
    browser = browser_trace.get('browser', {})
    ui = browser.get('milestones', {})
    start = browser.get('bench_start_ms')
    host = host_trace.get('worker') or {}
    host_events = host.get('events', {})
    # Use the local offset intersection if the two calibrations agree. Keep
    # the bound explicit and omit the combined clock if they disagree.
    points = [browser_trace[k] for k in ('before', 'after') if k in browser_trace]
    lower = max((point['lower_ms'] for point in points), default=0)
    upper = min((point['upper_ms'] for point in points), default=-1)
    offset = (lower + upper) / 2 if len(points) == 2 and lower <= upper else None
    elapsed = receipt.get('measured_seconds')
    observer = browser_trace.get('observer_tail', [])

    def since_start(moment):
        return round(moment - start, 3) if moment is not None and start is not None else None

    def host_since_start(moment):
        return since_start(moment - offset) if moment is not None and offset is not None else None

    endpoint_audio = estimate_audio_ms(ui.get('pcm_finished_ack', {}), 'context_end')
    first_audio = estimate_audio_ms(ui.get('pcm_started_ack', {}), 'context_start')
    timing = {
        'gui_play_requested': since_start(ui.get('play_requested_ms')),
        'gui_play_invoked': since_start(ui.get('play_call_ms')),
        'pcm_audible_start_estimate': since_start(first_audio),
        'pcm_audible_end_estimate': since_start(endpoint_audio),
        'pcm_first_samples_ack': since_start(ui.get('pcm_started_ack', {}).get('received_ms')),
        'pcm_finished_ack': since_start(ui.get('pcm_finished_ack', {}).get('received_ms')),
        'gui_audio_clock_endpoint': since_start(ui.get('audio_clock_endpoint', {}).get('observed_ms')),
        'gui_endpoint': since_start(ui.get('gui_endpoint_ms')),
        'gui_stop_invoked': since_start(ui.get('gui_stop_invoked_ms')),
        'gui_stopped': since_start(ui.get('gui_stopped_ms')),
        'gui_first_final_picture_status': since_start(ui.get('final_picture_status', {}).get('received_ms')),
        'gui_first_final_native_status': since_start(ui.get('terminal_status', {}).get('received_ms')),
        'observer_terminal_sample': round(elapsed * 1000, 3) if elapsed is not None and receipt.get('reached_end') else None,
    }
    for key in ('first_playing_clock', 'first_endpoint_clock'):
        stamp = host_events.get(key, {}).get('sent_ns')
        timing[f'host_{key}_sent'] = host_since_start(stamp / 1e6) if stamp is not None else None
    stamps = {}
    playing_generation = host.get('playing_generation')
    for key in ('first_final_picture_status', 'first_eos_status', 'first_terminal_status'):
        event = host_events.get(key, {})
        if not event or event.get('generation') != playing_generation:
            continue
        timing[f'host_{key}_received'] = host_since_start(event['received_ns'] / 1e6)
        timing[f'host_{key}_published'] = host_since_start(event['published_ns'] / 1e6)
        native = event.get('completion_stamps_us') or {}
        if native.get('generation') == playing_generation:
            if native.get('status_write_qpc'):
                timing[f'native_{key}_write'] = host_since_start(native['status_write_qpc'] / 1000)
            for name in NATIVE_STAMPS:
                if native.get(name):
                    stamps.setdefault(name, native[name])
    teardown = host_events.get('producer_teardown', {}).get('completion_stamps_us') or {}
    if teardown.get('generation') == playing_generation:
        for name in NATIVE_STAMPS:
            if teardown.get(name):
                stamps.setdefault(name, teardown[name])
    timing.update({f'native_{name.removesuffix("_qpc")}': host_since_start(stamps[name] / 1000) if name in stamps else None
                   for name in NATIVE_STAMPS})
    deltas = {}
    for key, earlier, later in (
        ('gui_stop_after_audible_end_estimate', 'pcm_audible_end_estimate', 'gui_stopped'),
        ('observer_after_gui_stop', 'gui_stopped', 'observer_terminal_sample'),
        ('native_submission_after_last_deadline', 'native_last_picture_deadline', 'native_final_draw_return'),
        ('native_gpu_observation_after_submission', 'native_final_draw_return', 'native_final_gpu_observed'),
        ('native_status_after_eos', 'native_first_clock_eos', 'native_first_terminal_status_write'),
        ('host_pipe_after_native_status', 'native_first_terminal_status_write', 'host_first_terminal_status_received'),
        ('host_update_after_receipt', 'host_first_terminal_status_received', 'host_first_terminal_status_published'),
        ('gui_status_after_host_update', 'host_first_terminal_status_published', 'gui_first_final_native_status'),
    ):
        deltas[key] = round(timing[later] - timing[earlier], 3) if None not in (timing.get(earlier), timing.get(later)) else None
    observer_last_gap = observer_between_calls = observer_last_call = previous_result_delivery = None
    terminal_poll_wait = None
    if len(observer) >= 2:
        previous, last = observer[-2:]
        observer_last_gap = round(last['elapsed_ms'] - previous['elapsed_ms'], 3)
        observer_between_calls = round((last['before_ns'] - previous['after_ns']) / 1e6, 3)
        observer_last_call = round((last['after_ns'] - last['before_ns']) / 1e6, 3)
        previous_python_return = host_since_start(previous['after_ns'] / 1e6)
        if previous_python_return is not None:
            previous_result_delivery = round(previous_python_return - previous['elapsed_ms'], 3)
        for waited in browser_trace.get('observer_wait_tail', []):
            if previous['after_ns'] <= waited['before_ns'] <= waited['after_ns'] <= last['before_ns']:
                terminal_poll_wait = round((waited['after_ns'] - waited['before_ns']) / 1e6, 3)
    return {
        'measurement': {k: receipt.get(k) for k in ('seconds', 'measured_seconds', 'distinct_sequence_fps', 'samples',
                        'expected_samples', 'underruns', 'reached_end', 'failed')},
        'endpoint': {k: receipt.get('last', {}).get(k) for k in ('completed_sequence_frame', 'skipped_sequence_frames', 'eos')},
        'relative_ms_from_protected_start': timing, 'elapsed_ms': deltas,
        'browser_host_clock_bound_ms': round((upper - lower) / 2, 3) if offset is not None else None,
        'browser_probe_source': browser_trace.get('browser_probe_source'),
        'browser_completion_trace': ui.get('generation') is not None, 'host_completion_trace': bool(host),
        'native_completion_trace': bool(stamps),
        'last_observer_gap_ms': observer_last_gap,
        'last_observer_between_cdp_calls_ms': observer_between_calls,
        'last_observer_cdp_call_ms': observer_last_call,
        'previous_observer_result_delivery_ms': previous_result_delivery,
        'last_observer_wait_for_timeout_250_ms': terminal_poll_wait,
        'maximum_observer_gap_ms': browser_trace.get('max_observer_gap_ms'),
        'maximum_observer_cdp_call_ms': browser_trace.get('max_observer_call_ms'),
    }


def run(args):
    results = args.results.resolve()
    results.mkdir(parents=True)
    host_trace = results / 'completion-host.private.json'
    native = args.executable.parent / WORKER
    fixture_stats = media_stats(args.media)
    save(results / 'completion-fingerprints.json', {
        'host_sha256': digest(args.executable), 'worker_sha256': digest(native),
        'fixture_stats_before': fixture_stats,
    })
    options = argparse.Namespace(executable=args.executable, media=args.media, results=results,
        seconds=60, width=3840, rate='60/1', cut=.5, layers=3, window_mode='visible', trace=True,
        switch_sources=False, stagger_source_rewinds=False, ui_source=False, legacy_viewport=False,
        legacy_focus_emulation=False, actual_display=False, large_surface=False, diagnostic_no_gpu_counters=False)
    try:
        with patch.dict(os.environ, {HOST_TRACE: str(host_trace)}), \
             patch.object(protected, 'session', observe_session(protected.session, results, args.published_browser_probe)):
            protected.main(options)
    finally:
        def read(path):
            return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}

        summary = summarize(read(results / 'completion-browser.private.json'), read(host_trace),
                            read(results / 'native-playback.json'))
        summary['fixture_stats_held'] = media_stats(args.media) == fixture_stats
        save(results / 'completion-summary.json', summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('media', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--published-browser-probe', action='store_true',
                        help='Observe PCM receipt and GUI Stop on older packaged builds without built-in timing')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('The protected fixture requires Windows')
    with serial():
        run(args)


if __name__ == '__main__':
    main()
