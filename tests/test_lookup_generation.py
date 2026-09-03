import threading
import time
import unittest

from meikipop.dictionary.lookup import DictionaryEntry, Lookup
from meikipop.pipeline import PipelineValue
from meikipop.utils.lastest_queue import LatestValueQueue


class _Shared:
    def __init__(self):
        self.running = True
        self.lookup_queue = LatestValueQueue()
        self.activation_id = 1

    def activation_snapshot(self):
        return self.activation_id, True


class _Popup:
    def __init__(self):
        self.deliveries = []

    def set_latest_data(self, value):
        self.deliveries.append(value)


class LookupGenerationTests(unittest.TestCase):
    def setUp(self):
        self.shared = _Shared()
        self.popup = _Popup()
        self.lookup = Lookup.__new__(Lookup)
        threading.Thread.__init__(self.lookup, daemon=True, name="LookupTest")
        self.lookup.shared_state = self.shared
        self.lookup.popup_window = self.popup
        self.lookup.last_hit_result = None
        self.lookup.last_activation_id = None
        self.lookup.audio_service = None
        self.lookup.lookup = lambda text: [DictionaryEntry(1, text, "", [], 1, ())]
        self.lookup.start()

    def tearDown(self):
        self.shared.running = False
        self.shared.lookup_queue.put(None)
        self.lookup.join(2)

    def _wait_for(self, count):
        deadline = time.monotonic() + 1
        while len(self.popup.deliveries) < count and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(len(self.popup.deliveries), count)

    def test_same_text_dedupes_within_activation_but_delivers_next_activation(self):
        self.shared.lookup_queue.put(PipelineValue(1, "同じ"))
        self._wait_for(1)
        self.shared.lookup_queue.put(PipelineValue(1, "同じ"))
        time.sleep(0.03)
        self.assertEqual(len(self.popup.deliveries), 1)

        self.shared.activation_id = 2
        self.shared.lookup_queue.put(PipelineValue(2, "同じ"))
        self._wait_for(2)

    def test_late_old_activation_is_discarded(self):
        self.shared.activation_id = 2
        self.shared.lookup_queue.put(PipelineValue(1, "古い"))
        time.sleep(0.03)
        self.assertEqual(self.popup.deliveries, [])


if __name__ == "__main__":
    unittest.main()
