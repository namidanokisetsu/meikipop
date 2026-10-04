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
    parser.add_argument("--check-runtime", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.check_runtime:
        # Packaging smoke check; never creates a window or requests permissions.
        from meikipop.scripts.translation_server import server_command
        if "127.0.0.1" not in server_command("llama-server", "model.gguf"):
            raise RuntimeError("Local translation setup is incomplete.")
        if sys.platform == "darwin":
            import Vision
            import Quartz
            if not Vision.VNRecognizeTextRequest or not Quartz.CGPreflightScreenCaptureAccess:
                raise RuntimeError("Native screen lookup runtime is incomplete.")
        return 0

    from PyQt6.QtCore import QTimer
    from PyQt6.QtGui import QActionGroup, QFont, QIcon
    from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QStyle
    from meikipop.gui.quick_lookup import QuickLookupWindow
    from meikipop.utils.paths import paths

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Meikipop")
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 10))
    app.setQuitOnLastWindowClosed(False)
    from meikipop.gui.single_instance import SingleInstance
    instance = SingleInstance(paths.data_dir, app)
    if not instance.start(args.text, args.background):
        return 0
    app.aboutToQuit.connect(instance.shutdown)
    window = QuickLookupWindow(args.library)
    instance.requested.connect(window.open_search)
    from meikipop.gui.text_triggers import TextTriggers
    text_triggers = TextTriggers(window)
    app.aboutToQuit.connect(text_triggers.shutdown)
    icon = QIcon(paths.get_resource_path("icon.ico"))
    if icon.isNull():
        icon = app.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
    app.setWindowIcon(icon)
    window.setWindowIcon(icon)
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("Meikipop")
    window.tray_geometry = tray.geometry
    menu = QMenu()
    menu.addAction("Search", window.open_search)
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
    menu.addSeparator()
    menu.addAction("Quit", app.quit)
    tray.setContextMenu(menu)
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
        window.restore_shortcut(binding)
    except (ValueError, OSError, RuntimeError) as error:
        window.show_message(str(error))
    if not args.background or not QSystemTrayIcon.isSystemTrayAvailable():
        QTimer.singleShot(0, lambda: window.open_search(args.text))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
