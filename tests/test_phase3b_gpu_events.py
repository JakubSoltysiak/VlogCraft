import csv
from io import StringIO
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from phase3b_gpu_events import (
    correlate, describe_buffer, describe_thread_cpu, etl_clock, intervals,
    scheduler_evidence, scheduler_rows, scheduler_spans,
)


SWITCH_HEADER = (
    "CSwitch, TimeStamp, New Process Name ( PID), New TID, NPri, NQnt, TmSinceLast, WaitTime, "
    "Old Process Name ( PID), Old TID, OPri, OQnt, OldState, Wait Reason, "
    "Swapable, InSwitchTime, CPU, IdealProc, OldRemQnt, NewPriDecr, PrevCState\n"
)
READY_HEADER = (
    "ReadyThread, TimeStamp, Process Name ( PID), ThreadID, Rdy Process Name ( PID), "
    "Rdy TID, AdjustReason, AdjustIncrement, InDPC\n"
)


def switch(time, incoming, outgoing, state="Running", reason="Executive"):
    return (f"CSwitch, {time}, worker.exe ( 123), {incoming}, 8, -1, 0, 0, "
            f"worker.exe ( 123), {outgoing}, 8, -1, {state}, {reason}, NonSwap, 0, 3, 3, 0, 0, 1\n")


def trace_summary(start="0000000", lost_events=0):
    return ("Clock type           : PerfCounter\n"
            "Boot time            : 2026/11/23:22:00:00.0000000\n"
            f"Start time (UTC)     : 2026/11/24:00:00:00.{start}\n"
            "End time (UTC)       : 2026/11/24:00:00:01.0000000\n"
            "Total # Lost Buffers : 0\n"
            f"Total # Lost Events  : {lost_events}\n")


def fake_dumper(rows):
    child = MagicMock()
    child.__enter__.return_value.stdout = StringIO(rows)
    child.__enter__.return_value.wait.return_value = 0
    return child


def native_cpu_sample(time, cpu, tid=42, torn=0, source=1):
    devices = [0, 0, 0]
    lane = ["stage", "stage", [0, 0, 0, 0, 0, 0, cpu, 1, tid], [source], [], [], [], devices]
    other = ["stage", "stage", [0] * 9, [], [], [], [], devices]
    return [time, torn, *([0] * 6), other, lane, other, other]


class GPUEventEvidence(unittest.TestCase):
    def test_filetime_precision_and_date_rollover(self):
        stats = ("Start time (UTC)     : 2026/11/23:23:59:59.9999999\n"
                 "End time (UTC)       : 2026/11/24:00:00:00.0000001")
        self.assertEqual(etl_clock(stats, "End") - etl_clock(stats, "Start"), 2)

    def test_wait_attribution_requires_stable_bracketed_edges(self):
        def sample(time, torn=0, owner_since=80):
            devices = ([0, 0, 0], [0, 1, owner_since], [1, 0, 90], [0, 0, 0])
            return [time, torn, *([0]*6), *([[0]*7+[device] for device in devices])]

        rows = [sample(500), sample(4000), sample(7000, 8), sample(9000), sample(10000, owner_since=9500)]
        call = (15000, "source_1", 6, 0, 15000)
        observation = describe_buffer(call, rows)
        self.assertEqual(observation["bracketed_shared_device_wait_us_by_peer"], {"source_2": 3500})

    def test_no_invented_span_without_a_missing_request(self):
        self.assertEqual(intervals({"incidents": [], "first_source_miss": {
            "frame": -1, "generation": -1, "requests": [], "samples": []}}), [])

    def test_scheduler_uses_classic_header_and_ready_target_not_issuer(self):
        text = (
            SWITCH_HEADER + READY_HEADER
            + switch(100, 42, 1)
            + switch(130, 1, 42, "Waiting", "WrQueue")
            + "ReadyThread, 145, worker.exe (123), 42, worker.exe (123), 88, 0, 1, 0\n"
            + "ReadyThread, 160, other.exe (55), 99, worker.exe (123), 42, 0, 1, 0\n"
            + switch(180, 42, 1)
            + switch(190, 1, 42, "Ready", "WrPreempted")
            + switch(215, 42, 1)
            + switch(250, 1, 42, "Waiting", "WrQueue")
        )
        seen, malformed, bounds, switches, ready = scheduler_rows(csv.reader(StringIO(text)), 123, 42)
        self.assertEqual(seen, {"CSwitch": 6, "ReadyThread": 2})
        self.assertEqual(malformed, {})
        self.assertEqual(bounds, (100, 250))
        self.assertEqual(ready, [160])
        self.assertEqual(scheduler_spans(110, 240, switches, ready), [
            {"start_us": 0, "end_us": 20, "state": "running"},
            {"start_us": 20, "end_us": 50, "state": "waiting", "wait_reason": "WrQueue"},
            {"start_us": 50, "end_us": 70, "state": "ready"},
            {"start_us": 70, "end_us": 80, "state": "running"},
            {"start_us": 80, "end_us": 105, "state": "ready"},
            {"start_us": 105, "end_us": 130, "state": "running"},
        ])

    def test_wait_without_unique_wake_and_unbracketed_edges_remain_unknown(self):
        switches = [
            (10, "in", None, None), (20, "out", "waiting", "UserRequest"),
            (50, "in", None, None), (70, "out", "deferredready", "Executive"),
            (80, "in", None, None),
        ]
        for ready in ([], [30, 40]):
            self.assertEqual(scheduler_spans(0, 90, switches, ready), [
                {"start_us": 0, "end_us": 10, "state": "unknown"},
                {"start_us": 10, "end_us": 20, "state": "running"},
                {"start_us": 20, "end_us": 50, "state": "unknown"},
                {"start_us": 50, "end_us": 70, "state": "running"},
                {"start_us": 70, "end_us": 90, "state": "unknown"},
            ])

    @patch("phase3b_gpu_events.subprocess.Popen")
    @patch("phase3b_gpu_events.trace_stats", return_value=trace_summary(start="0000055"))
    def test_scheduler_uses_separate_etl_origin_and_checks_loss(self, stats, popen):
        api_stats = trace_summary()
        origin = etl_clock(api_stats, "Start")
        kernel = SWITCH_HEADER + switch(85, 42, 1) + switch(195, 1, 42, "Waiting", "WrQueue")
        popen.return_value = fake_dumper(kernel)
        evidence = scheduler_evidence("sched.etl", api_stats, origin, 100, 200, 123, 42)
        self.assertEqual(evidence["status"], "observed")
        self.assertEqual(evidence["running_us"], 100)
        self.assertEqual(evidence["unknown_us"], 0)
        denied = scheduler_evidence(None, api_stats, origin, 100, 200, 123, 42)
        self.assertEqual(denied["status"], "unavailable")
        self.assertIsNone(denied["running_us"])
        self.assertEqual(denied["unknown_us"], 100)
        stats.return_value = trace_summary(lost_events=1)
        lost = scheduler_evidence("sched.etl", api_stats, origin, 100, 200, 123, 42)
        self.assertEqual(lost["lost"], {"Buffers": 0, "Events": 1})
        self.assertEqual(lost["unknown_us"], 100)
        self.assertEqual(popen.call_count, 1)

    def test_thread_cpu_counts_only_coherent_interior_samples_of_issuing_thread(self):
        samples = [
            native_cpu_sample(0, 100),
            native_cpu_sample(10, 120),
            native_cpu_sample(20, 125),
            native_cpu_sample(30, 130, torn=4),
            native_cpu_sample(40, 135),
            native_cpu_sample(50, 140, tid=43),
            native_cpu_sample(60, 150, source=2),
            native_cpu_sample(80, 155),
            native_cpu_sample(90, 160),
        ]
        evidence = describe_thread_cpu((80, "source_1", 0, 5, 85), samples, 42)
        self.assertEqual(evidence["consecutive_sample_intervals"], 1)
        self.assertEqual(evidence["bracketed_wall_us"], 10)
        self.assertEqual(evidence["accounted_cpu_us"], 5)

    @patch("phase3b_gpu_events.subprocess.Popen")
    @patch("phase3b_gpu_events.trace_stats", return_value=trace_summary())
    def test_slow_call_has_sampled_cpu_without_kernel_etl_and_keeps_pointer_local(self, _, popen):
        def event(time, tid, op, fields):
            name = f"Microsoft-Windows-Direct3D11/ID3D11VideoContext_GetDecoderBuffer/win:{op}"
            return f"{name}, {time}, worker.exe (123), {tid}, 0, 0, 0, 0, 0, {fields}\n"

        start = "Type : 0, pDecoder : 0xDEADBEEF"
        stop = "m_Ret : 0, pBufferSize : 64, ppBuffer : 0x123ABC"
        rows = event(50, 42, "Start", start) + event(60, 42, "Stop", stop)
        rows += event(110, 42, "Start", start) + event(120, 43, "Stop", stop) + event(190, 42, "Stop", stop)
        popen.return_value = fake_dumper(rows)
        capture = {"start_filetime_100ns": etl_clock(trace_summary(), "Start")}
        samples = [native_cpu_sample(t, t // 10) for t in (100, 130, 160, 200)]
        result = correlate("api.etl", capture, (100, 200, 7, samples, "test"))
        call = result["longest_decoder_input_buffer_call"]
        self.assertEqual(call["wall_us"], 80)
        self.assertEqual(call["thread_cpu_observation"]["accounted_cpu_us"], 3)
        self.assertEqual(call["get_decoder_buffer_stop_fields"], ["m_Ret", "pBufferSize", "ppBuffer"])
        self.assertTrue(call["earlier_same_decoder_type_and_stop_ppbuffer_in_window"])
        self.assertIsNone(call["earlier_same_decoder_type_and_returned_address_in_window"])
        self.assertEqual(call["scheduler"]["status"], "unavailable")
        self.assertNotIn("0xDEADBEEF", repr(result))
        self.assertNotIn("0x123ABC", repr(result))
