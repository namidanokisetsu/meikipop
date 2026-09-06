import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QApplication
from meikipop.gui.region_selector import RegionSelector


class RegionSelectorTests(unittest.TestCase):
    def test_selection_uses_physical_mouse_coordinates(self):
        app = QApplication.instance() or QApplication([])
        with patch("pynput.mouse.Controller") as controller, \
                patch("meikipop.gui.region_selector.QCursor.pos", return_value=QPoint(50, 50)):
            selector = RegionSelector()
            try:
                controller.return_value.position = (100, 100)
                selector.mousePressEvent(None)
                controller.return_value.position = (300, 200)
                selector.mouseReleaseEvent(None)
                self.assertEqual(selector.selection_rect, QRect(QPoint(100, 100), QPoint(300, 200)))
            finally:
                selector.close()
                selector.deleteLater()
                app.processEvents()
