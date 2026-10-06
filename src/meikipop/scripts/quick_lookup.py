"""Lightweight, cross-platform desktop entrypoint; OCR and models stay lazy."""
import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Meikipop dictionary search")
    parser.add_argument("text", nargs="?", default="")
    parser.add_argument("--library", help="Dictionary library directory")
    parser.add_argument("--hotkey", nargs="?", const="default", help="Enable an optional search shortcut")
    parser.add_argument("--background", action="store_true", help="Start in the tray")
    parser.add_argument("--no-ocr", action="store_true", help="Run dictionary search without screen lookup")
    parser.add_argument("--setup", action="store_true", help="Open the setup wizard")
    parser.add_argument("--setup-morphology", metavar="LANGUAGE", help=argparse.SUPPRESS)
    parser.add_argument("--setup-ocr", choices=("paddle", "meikiocr"), help=argparse.SUPPRESS)
    parser.add_argument("--check-runtime", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    background = args.background or (not args.text and sys.platform != "darwin")

    if args.setup_ocr:
        from meikipop.scripts.setup_ocr import setup_models
        setup_models(args.setup_ocr)
        return 0
    if args.setup_morphology:
        from meikipop.language.stanza_analyzer import setup_models
        setup_models(language=args.setup_morphology)
        return 0

    if args.check_runtime:
        # Packaging smoke check; never creates a window or requests permissions.
        from meikipop.scripts.translation_server import server_command
        if "127.0.0.1" not in server_command("llama-server", "model.gguf"):
            raise RuntimeError("Local translation setup is incomplete.")
        from meikipop.gui.first_run import SetupWizard
        from meikipop.gui.dictionary_manager import SetupDialog
        if getattr(sys, "frozen", False):
            import json
            from pathlib import Path
            import tempfile
            import threading
            import zipfile
            from meikipop.dictionary.import_job import background_import
            with tempfile.TemporaryDirectory() as folder:
                archive = Path(folder) / "fixture.zip"
                with zipfile.ZipFile(archive, "w") as bundle:
                    bundle.writestr("index.json", json.dumps({"title": "Runtime check", "format": 3, "sourceLanguage": "en"}))
                    bundle.writestr("term_bank_1.json", json.dumps([["test", "", "", "", 0, ["fixture"]]]))
                message, imported = background_import([archive], Path(folder) / "library", "en", None,
                                                     lambda text: None, threading.Event())
                if not imported:
                    raise RuntimeError(message)
            import stanza
            import torch
            if sys.platform == "win32":
                import paddle
                import paddleocr
                import meikiocr
        if sys.platform == "darwin":
            import Vision
            import Quartz
            if not Vision.VNRecognizeTextRequest or not Quartz.CGPreflightScreenCaptureAccess:
                raise RuntimeError("Native screen lookup runtime is incomplete.")
        return 0

    from PyQt6.QtCore import QSettings, QTimer
    from PyQt6.QtGui import QActionGroup, QFont, QIcon
    from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QStyle
    from meikipop.gui.quick_lookup import QuickLookupWindow
    from meikipop.utils.paths import paths
    from meikipop.utils.logger import setup_logging

    setup_logging()

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Meikipop")
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 10))
    app.setQuitOnLastWindowClosed(False)
    from meikipop.gui.single_instance import SingleInstance
    instance = SingleInstance(paths.data_dir, app)
    if not instance.start(args.text, background):
        return 0
    app.aboutToQuit.connect(instance.shutdown)
    from meikipop.gui.first_run import needs_setup, show_setup
    settings = QSettings("Meikipop", "QuickLookup")
    settings.setFallbacksEnabled(False)
    first_run = args.setup or needs_setup(settings)
    if first_run:
        settings.setValue("setup/pending", True)
    window = QuickLookupWindow(args.library, settings=settings)
    def open_requested(text=""):
        if sys.platform == "darwin" and not text:
            window.open_settings()
        else:
            window.open_search(text)
    instance.requested.connect(open_requested)
    if sys.platform == "darwin":
        from meikipop.gui.desktop_access import DesktopAccess
        desktop_access = DesktopAccess(window, app)
    from meikipop.gui.text_triggers import TextTriggers
    text_triggers = TextTriggers(window)
    app.aboutToQuit.connect(text_triggers.shutdown)
    icon = QIcon(paths.get_resource_path("icon.ico"))
    if icon.isNull():
        icon = app.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
    app.setWindowIcon(icon)
    window.setWindowIcon(icon)
    tray_icon = QIcon(icon)
    if sys.platform == "darwin":
        tray_icon.setIsMask(True)
    tray = QSystemTrayIcon(tray_icon, app)
    tray.setToolTip("Meikipop")
    window.tray_geometry = tray.geometry
    menu = QMenu()
    menu.addAction("Search", lambda: window.open_search())
    profiles = menu.addMenu(window.source.currentText())
    window.mode_changed.connect(lambda *_: profiles.setTitle(window.source.currentText()))
    profile_group = QActionGroup(profiles)
    def populate_profiles():
        profiles.clear()
        for index in range(window.source.count()):
            code = window.source.itemData(index)
            action = profiles.addAction(window.source.itemText(index))
            action.setCheckable(True)
            action.setChecked(code == window.preferred_foreign)
            profile_group.addAction(action)
            action.triggered.connect(lambda _, code=code: window.set_mode(code))
    profiles.aboutToShow.connect(populate_profiles)
    menu.addAction("Settings", window.open_settings)
    menu.addAction("Setup wizard", lambda: show_setup(window))
    menu.addSeparator()
    menu.addAction("Quit", app.quit)
    tray.setContextMenu(menu)
    if sys.platform != "darwin":
        tray.activated.connect(lambda reason: window.open_search()
                               if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()
    app.aboutToQuit.connect(window.shutdown)
    from meikipop.scripts.translation_server import shutdown_server
    app.aboutToQuit.connect(lambda: shutdown_server(permanent=True))

    ocr = None
    if not args.no_ocr:
        try:
            from meikipop.gui.unified_ocr import UnifiedOCR
            ocr = UnifiedOCR(window)
        except (ImportError, RuntimeError) as error:
            window.scan_toggle.setEnabled(False)
            window.scan_toggle.setToolTip(str(error))
    else:
        window.scan_toggle.setEnabled(False)
    binding = args.hotkey
    if binding == "default":
        binding = "<cmd>+<shift>+d" if sys.platform == "darwin" else "<ctrl>+<shift>+d"
    try:
        window.restore_shortcut(window.settings.value("hotkey", "") if first_run and binding is None else binding)
    except (ValueError, OSError, RuntimeError) as error:
        window.show_message(str(error))
    if first_run:
        QTimer.singleShot(0, lambda: show_setup(window))
    elif not background:
        QTimer.singleShot(0, lambda: open_requested(args.text))
    return app.exec()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
