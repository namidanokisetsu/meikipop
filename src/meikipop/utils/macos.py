"""macOS screen-capture permission checks, imported only when OCR is enabled."""
import sys


class InputMonitoringPermissionError(RuntimeError):
    pass


def require_input_monitoring_permission() -> None:
    if sys.platform != "darwin":
        return
    from Quartz import CGPreflightListenEventAccess
    if not CGPreflightListenEventAccess():
        raise InputMonitoringPermissionError(
            "Allow Meikipop in System Settings > Privacy & Security > Input Monitoring, then reopen Meikipop."
        )


def require_screen_capture_permission(*, request_access: bool = False) -> None:
    if sys.platform != "darwin":
        return
    try:
        from Quartz import CGPreflightScreenCaptureAccess
    except ImportError as error:
        raise RuntimeError("Screen capture needs Meikipop's macOS dependencies.") from error
    if not CGPreflightScreenCaptureAccess():
        # Request only from the user's explicit Enable Screen Lookup action,
        # never from a repeated frame capture or startup.
        if request_access:
            from Quartz import CGRequestScreenCaptureAccess
            if CGRequestScreenCaptureAccess():
                return
        raise RuntimeError(
            "Allow Meikipop in System Settings > Privacy & Security > Screen Recording, then reopen Meikipop."
        )
