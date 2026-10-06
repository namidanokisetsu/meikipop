"""Handle Dock reopen events separately from initial app activation."""
from Foundation import NSAppleEventManager, NSObject
import objc


class MeikipopReopenHandler(NSObject):
    @objc.signature(b"v@:@@")
    def handleReopen_withReplyEvent_(self, event, reply):
        self.callback()


def install_reopen_handler(callback):
    handler = MeikipopReopenHandler.alloc().init()
    handler.callback = callback
    NSAppleEventManager.sharedAppleEventManager().setEventHandler_andSelector_forEventClass_andEventID_(
        handler, b"handleReopen:withReplyEvent:",
        int.from_bytes(b"aevt", "big"), int.from_bytes(b"rapp", "big"))
    return handler
