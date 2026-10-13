"""Keep console helpers from taking focus in Windows tray launches."""
import sys
from threading import Lock

_lock = Lock()


def configure_windowed_helpers():
    if sys.platform != "win32" or sys.stdout is not None:
        return
    import inspect
    import subprocess
    with _lock:
        if getattr(subprocess.Popen, "_meikipop_windowless", False):
            return
        creationflags_index = list(inspect.signature(subprocess.Popen).parameters).index("creationflags")

        class WindowlessPopen(subprocess.Popen):
            _meikipop_windowless = True

            def __init__(self, *args, **kwargs):
                positional = len(args) > creationflags_index
                flags = args[creationflags_index] if positional else kwargs.get("creationflags", 0)
                if not flags & (subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS):
                    flags |= subprocess.CREATE_NO_WINDOW
                    if positional:
                        args = list(args)
                        args[creationflags_index] = flags
                    else:
                        kwargs["creationflags"] = flags
                super().__init__(*args, **kwargs)

        subprocess.Popen = WindowlessPopen
