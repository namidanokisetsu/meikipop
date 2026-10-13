import io
import hashlib
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from PyQt6.QtWidgets import QApplication
from meikipop.scripts import setup_stroke_order_font as setup
from meikipop.utils import stroke_order_font as font


class StrokeOrderFontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = {name: f"fixture:{name}".encode() for name in font.FILES}
        self.expected = {name: hashlib.sha256(data).hexdigest() for name, data in self.files.items()}
        for context in (patch.dict(font.FILES, self.expected, clear=True), patch.object(font, "_verified", None),
                        patch.object(font, "_registered", None)):
            context.start(); self.addCleanup(context.stop)

    def archive(self, extra=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as bundle:
            for name, data in self.files.items():
                bundle.writestr(f"{font.PACKAGE}/{name}", data)
            if extra:
                bundle.writestr(*extra)
        return stream.getvalue()

    def download(self, payload):
        response = io.BytesIO(payload)
        response.headers = {"Content-Length": str(len(payload))}
        return patch.object(setup, "urlopen", return_value=response)

    def test_explicit_install_retains_license_and_reuses_local_font_offline(self):
        payload = self.archive()
        with self.download(payload) as download, patch.object(setup, "ARCHIVE_SHA256", hashlib.sha256(payload).hexdigest()):
            destination = Path(setup.install(directory=self.root))
            download.assert_called_once()
        self.assertTrue(font.font_ready(self.root))
        for name, data in self.files.items():
            self.assertEqual((destination / name).read_bytes(), data)
        with patch.object(setup, "urlopen", side_effect=AssertionError("Runtime must be offline")):
            self.assertEqual(setup.install(directory=self.root), str(destination))

    def test_archive_hash_failure_does_not_replace_previous_installation(self):
        target = font.font_directory(self.root)
        target.mkdir(parents=True)
        previous = target / next(iter(self.files))
        previous.write_bytes(b"previous")
        with self.download(self.archive()), self.assertRaisesRegex(ValueError, "verification"):
            setup.install(directory=self.root)
        self.assertEqual(previous.read_bytes(), b"previous")
        self.assertEqual(list(target.parent.glob('.stroke-order-*')), [])

    def test_publication_failure_restores_previous_installation(self):
        target = font.font_directory(self.root)
        target.mkdir(parents=True)
        previous = target / next(iter(self.files))
        previous.write_bytes(b"previous")
        payload = self.archive()
        original_replace = Path.replace
        def replace(source, destination):
            if source.name == "installed":
                raise OSError("Publication failed")
            return original_replace(source, destination)
        with self.download(payload), patch.object(setup, "ARCHIVE_SHA256", hashlib.sha256(payload).hexdigest()), \
                patch.object(Path, "replace", replace), self.assertRaisesRegex(OSError, "Publication failed"):
            setup.install(directory=self.root)
        self.assertEqual(previous.read_bytes(), b"previous")
        self.assertEqual(list(target.parent.glob('.stroke-order-*')), [])

    def test_cancelled_download_never_publishes_font(self):
        cancelled = threading.Event()
        payload = self.archive()
        with self.download(payload), patch.object(setup, "ARCHIVE_SHA256", hashlib.sha256(payload).hexdigest()), \
                self.assertRaises(InterruptedError):
            setup.install(lambda text: cancelled.set() if not text.endswith(' · 0%') else None, cancelled, self.root)
        self.assertFalse(font.font_directory(self.root).exists())
        self.assertEqual(list((self.root / 'fonts').glob('.stroke-order-*')), [])
        with patch.object(setup, "urlopen") as download, self.assertRaises(InterruptedError):
            setup.install(cancelled=cancelled, directory=self.root)
        download.assert_not_called()

    def test_unsafe_archive_or_changed_font_is_rejected_before_publication(self):
        unsafe = self.root / "unsafe.zip"
        unsafe.write_bytes(self.archive(("../outside.ttf", b"unsafe")))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            setup.extract_font(unsafe, self.root / "output")
        self.assertFalse((self.root / "output").exists())
        payload = self.archive()
        with self.download(payload), patch.object(setup, "ARCHIVE_SHA256", hashlib.sha256(payload).hexdigest()), \
                patch.dict(font.FILES, {'LICENCE.txt': 'incorrect'}), self.assertRaisesRegex(ValueError, "verification"):
            setup.install(directory=self.root)
        self.assertFalse(font.font_directory(self.root).exists())

    def test_declared_and_actual_download_size_limits(self):
        payload = self.archive()
        with self.download(payload), patch.object(setup, "MAX_DOWNLOAD", 8), self.assertRaisesRegex(ValueError, "too large"):
            setup.install(directory=self.root)
        response = io.BytesIO(payload)
        response.headers = {}
        with patch.object(setup, "urlopen", return_value=response), patch.object(setup, "MAX_DOWNLOAD", 8), \
                self.assertRaisesRegex(ValueError, "too large"):
            setup.install(directory=self.root)
        self.assertFalse(font.font_directory(self.root).exists())

    def test_lazy_registration_and_unsupported_character_fallback_are_offline(self):
        with patch('PyQt6.QtGui.QFontDatabase.addApplicationFont') as add:
            self.assertEqual(font.stroke_order_family('祈', self.root), '')
            add.assert_not_called()
        target = font.font_directory(self.root)
        target.mkdir(parents=True)
        for name, data in self.files.items():
            (target / name).write_bytes(data)
        raw = Mock()
        raw.supportsCharacter.side_effect = lambda code: code == ord('祈')
        with patch('PyQt6.QtGui.QFontDatabase.addApplicationFont', return_value=7) as add, \
                patch('PyQt6.QtGui.QFontDatabase.applicationFontFamilies', return_value=['Fixture Stroke']), \
                patch('PyQt6.QtGui.QRawFont.fromFont', return_value=raw), \
                patch.object(setup, 'urlopen', side_effect=AssertionError('Runtime must be offline')):
            self.assertEqual(font.stroke_order_family('祈', self.root), 'Fixture Stroke')
            self.assertEqual(font.stroke_order_family('𠮷', self.root), '')
            self.assertEqual(font.stroke_order_family('', self.root), 'Fixture Stroke')
            add.assert_called_once()
        (target / next(iter(self.files))).write_bytes(b'changed')
        self.assertFalse(font.font_ready(self.root))
