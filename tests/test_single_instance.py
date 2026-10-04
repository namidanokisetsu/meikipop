import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from unittest.mock import Mock
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from meikipop.gui.single_instance import SingleInstance


class SingleInstanceTests(unittest.TestCase):
    def test_second_launch_forwards_text_without_owning_global_hooks(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            first, second = SingleInstance(folder), SingleInstance(folder)
            requested = Mock()
            first.requested.connect(requested)
            try:
                self.assertTrue(first.start())
                self.assertFalse(second.start('猫'))
                QTest.qWait(50)
                requested.assert_called_once_with('猫')
                self.assertFalse(second.start(background=True))
                QTest.qWait(20)
                requested.assert_called_once()
                first.shutdown()
                self.assertTrue(second.start())
            finally:
                first.shutdown()
                second.shutdown()
