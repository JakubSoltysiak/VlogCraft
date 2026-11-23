import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from native_playback import CompletionTrace


class NativeCompletionTrace(unittest.TestCase):
    def test_keeps_first_terminal_status_and_the_detached_worker_teardown(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'completion.json'
            trace = CompletionTrace(path)
            worker = object()
            trace.start(worker, {'endFrame': 60, 'rate': '60/1'}, 1)
            with patch('native_playback.time.perf_counter_ns', side_effect=[10, 20]):
                trace.clock(0, True, 3)
                trace.clock(1000000, False, 3)

            terminal = {'event': 'status', 'generation': 3, 'completed_generation': 3,
                        'completed_sequence_frame': 59, 'eos': True}
            trace.status(dict(terminal, generation=2, completed_generation=2), 21, 22)
            trace.status(terminal, 30, 31)
            trace.status(terminal, 40, 41)

            teardown = {'event': 'completion_diagnostic', 'generation': 3,
                        'completion_stamps_us': {'generation': 3, 'producer_join_qpc': 80}}
            trace.teardown(worker, teardown, 81)
            trace.teardown(object(), teardown, 90)
            self.assertFalse(path.exists())
            trace.save()

            events = json.loads(path.read_text('utf8'))['worker']['events']
            self.assertEqual(events['first_playing_clock']['sent_ns'], 10)
            self.assertFalse(events['first_endpoint_clock']['playing'])
            self.assertEqual(events['first_terminal_status']['received_ns'], 30)
            self.assertEqual(events['first_terminal_status']['published_ns'], 31)
            self.assertEqual(events['producer_teardown']['received_ns'], 81)
