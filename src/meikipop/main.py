# meikipop/main.py
import argparse
import signal
import sys
import threading
from collections import deque

from PyQt6.QtCore import qInstallMessageHandler
from PyQt6.QtWidgets import QApplication

from meikipop.utils.logger import setup_logging
from meikipop.config.config import config, APP_NAME, APP_VERSION
from meikipop.dictionary.lookup import Lookup
from meikipop.gui.input import InputLoop
from meikipop.gui.popup import Popup
from meikipop.gui.tray import TrayIcon
from meikipop.ocr.hit_scan import HitScanner
from meikipop.ocr.ocr import OcrProcessor
from meikipop.screenshot.screenmanager import ScreenManager
from meikipop.utils.lastest_queue import LatestValueQueue
from meikipop.audio.playback import PronunciationAudioService
from meikipop.utils.startup import refresh_startup_registration


def qt_message_handler(mode, context, message):
    # Check if the message is the specific warning we want to suppress.
    if "QWindowsWindow::setGeometry" in message and "Unable to set geometry" in message:
        return  # Silently ignore this specific warning.
    if original_handler:
        original_handler(mode, context, message)

# This global variable will hold the original message handler.
original_handler = None


class SharedState:
    def __init__(self):
        self.running = True

        # events and queues
        self.screenshot_trigger_event = threading.Event()
        self._screenshot_requests = deque()
        self._screenshot_request_lock = threading.Lock()
        self.ocr_queue = LatestValueQueue()
        self.hit_scan_queue = LatestValueQueue()
        self.lookup_queue = LatestValueQueue()

        # screen lock - used by screen manager and popup
        self.screen_lock = threading.RLock()
        self._activation_lock = threading.Lock()
        self._activation_id = 0
        self._activation_active = False

    def set_activation(self, activation_id, active):
        with self._activation_lock:
            self._activation_id = activation_id
            self._activation_active = active

    def activation_snapshot(self):
        with self._activation_lock:
            return self._activation_id, self._activation_active

    def request_screenshot(self, activation_id=None):
        """Queue activation screenshots; coalesce untagged background scans."""
        with self._screenshot_request_lock:
            if activation_id is not None or None not in self._screenshot_requests:
                self._screenshot_requests.append(activation_id)
        self.screenshot_trigger_event.set()

    def consume_screenshot_request(self):
        with self._screenshot_request_lock:
            request = self._screenshot_requests.popleft() if self._screenshot_requests else None
            has_more = bool(self._screenshot_requests)
        if has_more:
            self.screenshot_trigger_event.set()
        if request is not None:
            return request
        current_id, active = self.activation_snapshot()
        return current_id if active else 0


def run_gui():
    setup_logging()
    refresh_startup_registration(config.start_with_windows)
    shared_state = SharedState()

    global original_handler
    original_handler = qInstallMessageHandler(qt_message_handler)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    input_loop = InputLoop(shared_state)
    popup_window = Popup(shared_state, input_loop)
    audio_service = PronunciationAudioService(shared_state, app)

    screen_manager = ScreenManager(shared_state, input_loop)  # trigger region selection
    lookup = Lookup(shared_state, popup_window)  # load dictionary
    lookup.audio_service = audio_service

    ocr_processor = OcrProcessor(shared_state, screen_manager)
    hit_scanner = HitScanner(shared_state, input_loop, screen_manager)
    tray_icon = TrayIcon(screen_manager, ocr_processor, popup_window, input_loop, lookup)

    for t in [lookup, hit_scanner, ocr_processor, screen_manager, input_loop]:
        t.start()

    ready_message = f"""
    --------------------------------------------------
    {APP_NAME}.{APP_VERSION} is running in the background.

      - To configure or change scan area: Right-click the icon in your system tray.
      - To exit: Press Ctrl+C in this terminal.

    --------------------------------------------------
    """
    if sys.stdout is not None:
        print(ready_message)

    def signal_handler(sig, frame):
        QApplication.quit()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    exit_code = app.exec()

    shared_state.running = False
    shared_state.screenshot_trigger_event.set()
    shared_state.ocr_queue.put(None)
    shared_state.hit_scan_queue.trigger()
    shared_state.lookup_queue.put(None)
    input_loop.stop()
    audio_service.shutdown()
    for thread in [lookup, hit_scanner, ocr_processor, screen_manager, input_loop]:
        thread.join(timeout=3)
    sys.exit(exit_code)


def main():
    parser = argparse.ArgumentParser(
        prog="meikipop",
        description="Universal Japanese OCR popup dictionary"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("build-dict", help="Build the dictionary from source files")

    import_html_parser = subparsers.add_parser("import-yomitan-dict-html", help="Import Yomitan dictionary (HTML format)")
    import_html_parser.add_argument("dictionary_files", nargs='+', help="Path(s) to the dictionary zip file(s)")

    import_text_parser = subparsers.add_parser("import-yomitan-dict-text", help="Import Yomitan dictionary (text format)")
    import_text_parser.add_argument("dictionary_files", nargs='+', help="Path(s) to the dictionary zip file(s)")

    args = parser.parse_args()

    if args.command == "build-dict":
        from meikipop.scripts.build_dictionary import main as build_main
        build_main()
    elif args.command == "import-yomitan-dict-html":
        from meikipop.scripts.import_yomitan_dict_html import main as import_html_main
        import_html_main([*args.dictionary_files])
    elif args.command == "import-yomitan-dict-text":
        from meikipop.scripts.import_yomitan_dict_text import main as import_text_main
        import_text_main([*args.dictionary_files])
    else:
        run_gui()


if __name__ == "__main__":
    main()
