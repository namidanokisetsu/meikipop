from contextlib import nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from meikipop.ocr import macos_vision
from meikipop.utils.macos import require_screen_capture_permission


def observation(text, ranges=None, box=((0.1, 0.2), (0.8, 0.1))):
    candidate = Mock()
    candidate.string.return_value = text
    candidate.boundingBoxForRange_error_.side_effect = (
        lambda span, error: (SimpleNamespace(boundingBox=lambda: (ranges or {}).get(span, box)), None)
    )
    return SimpleNamespace(topCandidates_=lambda count: [candidate], boundingBox=lambda: box), candidate


class VisionGeometryTests(unittest.TestCase):
    def test_turkish_words_preserve_whitespace_context_and_native_boxes(self):
        source, candidate = observation(
            "  oğlum  kitap ve kitap  ",
            {(2, 5): ((0.1, 0.2), (0.1, 0.1)), (18, 5): ((0.7, 0.2), (0.2, 0.1))},
        )
        result = macos_vision._paragraph(source, "tr-TR", (1000, 300))
        self.assertEqual(result.full_text, "oğlum  kitap ve kitap")
        self.assertEqual("".join(word.text + word.separator for word in result.words), result.full_text)
        self.assertEqual([word.text for word in result.words], ["oğlum", "kitap", "ve", "kitap"])
        self.assertAlmostEqual(result.box.center_y, 0.75)
        self.assertAlmostEqual(result.words[0].box.center_x, 0.15)
        self.assertFalse(result.is_vertical)
        self.assertEqual(candidate.boundingBoxForRange_error_.call_args_list[0].args[0], (2, 5))

    def test_japanese_ranges_count_utf16_and_merge_shared_native_boxes(self):
        source, candidate = observation("𠮷野家です")
        result = macos_vision._paragraph(source, "ja-JP", (500, 100))
        ranges = [call.args[0] for call in candidate.boundingBoxForRange_error_.call_args_list]
        self.assertEqual(ranges, [(0, 2), (2, 1), (3, 1), (4, 1), (5, 1)])
        self.assertEqual(len(result.words), 1)
        self.assertEqual(result.words[0].text, "𠮷野家です")

    def test_missing_word_box_preserves_complete_context(self):
        source, candidate = observation("kitap ve kitap")
        candidate.boundingBoxForRange_error_.side_effect = None
        candidate.boundingBoxForRange_error_.return_value = (None, "unavailable")
        result = macos_vision._paragraph(source, "tr", (500, 100))
        self.assertEqual(result.words[0].text, "kitap ve kitap")
        self.assertEqual(result.words[0].box, result.box)

    def test_language_matches_platform_region_and_explicit_script(self):
        self.assertEqual(macos_vision._language_id("tr", ["en-US", "tr-TR"]), "tr-TR")
        self.assertEqual(macos_vision._language_id("zh_Hant", ["zh-Hans", "zh-Hant"]), "zh-Hant")
        with self.assertRaisesRegex(RuntimeError, "typed or selected text"):
            macos_vision._language_id("tr", ["en-US", "ja-JP"])

    def test_empty_observations_are_ignored(self):
        source, _ = observation(" \n ")
        self.assertIsNone(macos_vision._paragraph(source, "tr", (500, 100)))
        self.assertIsNone(macos_vision._paragraph(SimpleNamespace(topCandidates_=lambda count: []), "tr", (500, 100)))


class VisionBridgeTests(unittest.TestCase):
    def bridge(self, supported=("ja-JP", "tr-TR", "en-US")):
        request = Mock()
        request.supportedRecognitionLanguagesAndReturnError_.return_value = (supported, None)
        request.results.return_value = [observation("kitap ve kitap")[0]]
        handler = Mock()
        handler.performRequests_error_.return_value = (True, None)
        vision = SimpleNamespace(
            VNRequestTextRecognitionLevelAccurate=0,
            VNRecognizeTextRequest=Mock(),
            VNImageRequestHandler=Mock(),
        )
        vision.VNRecognizeTextRequest.alloc.return_value.init.return_value = request
        vision.VNImageRequestHandler.alloc.return_value.initWithData_options_.return_value = handler
        modules = {
            "objc": SimpleNamespace(autorelease_pool=nullcontext),
            "Vision": vision,
            "Foundation": SimpleNamespace(NSData=SimpleNamespace(dataWithBytes_length_=lambda data, size: data)),
        }
        return request, handler, modules

    def test_recognize_converts_native_results_and_uses_requested_language(self):
        request, handler, modules = self.bridge()
        with patch.object(macos_vision.sys, "platform", "darwin"), patch.dict(sys.modules, modules):
            result = macos_vision.recognize(Image.new("RGB", (800, 200)), "tr")
        request.setRecognitionLanguages_.assert_called_once_with(["tr-TR"])
        handler.performRequests_error_.assert_called_once_with([request], None)
        self.assertEqual(result[0].full_text, "kitap ve kitap")

    def test_unsupported_language_fails_before_running_recognition(self):
        _, handler, modules = self.bridge(("en-US",))
        with patch.object(macos_vision.sys, "platform", "darwin"), patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(RuntimeError, "does not support"):
                macos_vision.recognize(Image.new("RGB", (10, 10)), "tr")
        handler.performRequests_error_.assert_not_called()

    def test_native_failure_becomes_actionable_error(self):
        _, handler, modules = self.bridge()
        handler.performRequests_error_.return_value = (False, SimpleNamespace(localizedDescription=lambda: "fixture"))
        with patch.object(macos_vision.sys, "platform", "darwin"), patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(RuntimeError, "screen recognition failed: fixture"):
                macos_vision.recognize(Image.new("RGB", (10, 10)), "ja")

    def test_non_mac_rejected_without_native_imports(self):
        with patch.object(macos_vision.sys, "platform", "win32"):
            with self.assertRaisesRegex(RuntimeError, "macOS only"):
                macos_vision.recognize(Image.new("RGB", (10, 10)))

    def test_screen_capture_permission_check_never_requests_access(self):
        quartz = SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: False)
        with patch("meikipop.utils.macos.sys.platform", "darwin"), patch.dict(sys.modules, {"Quartz": quartz}):
            with self.assertRaisesRegex(RuntimeError, "Screen Recording"):
                require_screen_capture_permission()

    def test_user_can_explicitly_request_screen_capture_permission(self):
        request = Mock(return_value=True)
        quartz = SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: False, CGRequestScreenCaptureAccess=request)
        with patch("meikipop.utils.macos.sys.platform", "darwin"), patch.dict(sys.modules, {"Quartz": quartz}):
            require_screen_capture_permission(request_access=True)
        request.assert_called_once_with()


class MacFocusTests(unittest.TestCase):
    def test_legacy_popup_uses_appkit_to_restore_frontmost_app(self):
        from meikipop.gui import popup

        active = Mock()
        workspace = Mock()
        workspace.sharedWorkspace.return_value.frontmostApplication.return_value = active
        appkit = SimpleNamespace(NSWorkspace=workspace, NSApplicationActivateAllWindows=1)
        state = SimpleNamespace(_previous_active_window_on_mac=None)
        with patch.object(popup, "IS_MACOS", True), patch.object(popup, "AppKit", appkit):
            popup.Popup._store_active_window_on_mac(state)
            self.assertIs(state._previous_active_window_on_mac, active)
            popup.Popup._restore_focus_on_mac(state)
        active.activateWithOptions_.assert_called_once_with(1)
        self.assertIsNone(state._previous_active_window_on_mac)


class MacBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Initialize platform-dependent stdlib imports before mocking Darwin.
        from meikipop.scripts import translation_server
        cls.server = translation_server

    def test_runtime_check_validates_native_libraries_without_permissions(self):
        from meikipop.scripts.quick_lookup import main

        quartz = SimpleNamespace(CGPreflightScreenCaptureAccess=Mock())
        modules = {"ctranslate2": None, "sentencepiece": None,
                   "Vision": SimpleNamespace(VNRecognizeTextRequest=Mock()), "Quartz": quartz}
        with patch("sys.platform", "darwin"), patch.dict(sys.modules, modules):
            self.assertEqual(main(["--check-runtime"]), 0)
        quartz.CGPreflightScreenCaptureAccess.assert_not_called()

    def test_runtime_check_fails_if_native_vision_was_not_bundled(self):
        from meikipop.scripts.quick_lookup import main

        modules = {"Vision": SimpleNamespace(VNRecognizeTextRequest=None),
                   "Quartz": SimpleNamespace(CGPreflightScreenCaptureAccess=Mock())}
        with patch("sys.platform", "darwin"), patch.dict(sys.modules, modules), self.assertRaisesRegex(RuntimeError, "incomplete"):
            main(["--check-runtime"])

    def test_bundle_targets_unified_ui_and_preserves_dictionary_resources(self):
        root = Path(__file__).resolve().parents[1]
        spec = (root / "meikipop.macos.spec").read_text(encoding="utf-8")
        self.assertIn("src/meikipop/scripts/quick_lookup.py", spec)
        self.assertIn("src/meikipop/scripts/deconjugator.json", spec)
        self.assertIn("'Vision'", spec)
        workflow = (root / ".github/workflows/build-macos.yml").read_text(encoding="utf-8")
        self.assertIn("runner: macos-15-intel", workflow)
        self.assertIn("arch: arm64", workflow)
        self.assertIn("arch: x86_64", workflow)


@unittest.skipUnless(sys.platform == "darwin", "Native Apple Vision needs macOS")
class NativeVisionSmokeTests(unittest.TestCase):
    def test_recognizes_rendered_text_without_screen_capture(self):
        from PIL import ImageDraw, ImageFont

        image = Image.new("RGB", (900, 180), "white")
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 72)
        ImageDraw.Draw(image).text((30, 35), "MEIKIPOP 123", font=font, fill="black")
        result = macos_vision.recognize(image, "en")
        self.assertIn("MEIKIPOP", " ".join(paragraph.full_text.upper() for paragraph in result))


if __name__ == "__main__":
    unittest.main()
