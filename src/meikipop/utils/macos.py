"""macOS permissions requested when their features start."""
import sys


class InputMonitoringPermissionError(RuntimeError):
    pass


def require_accessibility_permission() -> None:
    if sys.platform != "darwin":
        return
    from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
    if not AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
        raise RuntimeError(
            "Allow Meikipop in System Settings > Privacy & Security > Accessibility, then reopen Meikipop."
        )


def require_input_monitoring_permission() -> None:
    if sys.platform != "darwin":
        return
    from Quartz import CGPreflightListenEventAccess, CGRequestListenEventAccess
    if not CGPreflightListenEventAccess() and not CGRequestListenEventAccess():
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
        # Request when screen lookup starts, never during frame capture.
        if request_access:
            from Quartz import CGRequestScreenCaptureAccess
            if CGRequestScreenCaptureAccess():
                return
        raise RuntimeError(
            "Allow Meikipop in System Settings > Privacy & Security > Screen Recording, then reopen Meikipop."
        )
