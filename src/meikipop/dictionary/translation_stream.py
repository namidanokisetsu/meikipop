"""Bounded SSE decoder for local chat-completion streams."""
import codecs
import json
import io
import socket
from time import monotonic


class ResponseSocket:
    """Poll cancellation below buffering, where read timeouts are retryable."""
    def __init__(self, sock, cancelled):
        self.sock, self.cancelled = sock, cancelled

    def makefile(self, mode):
        return io.BufferedReader(_SocketReader(self.sock.dup(), self.cancelled))


class _SocketReader(io.RawIOBase):
    def __init__(self, sock, cancelled):
        self.sock, self.cancelled = sock, cancelled
        self.deadline = monotonic() + 120
        self.sock.settimeout(.1)

    def readable(self):
        return True

    def readinto(self, buffer):
        while not self.cancelled.is_set():
            if monotonic() >= self.deadline:
                raise TimeoutError("Local translation timed out.")
            try:
                return self.sock.recv_into(buffer)
            except socket.timeout:
                continue
        raise OSError("Translation cancelled.")

    def close(self):
        self.sock.close()
        super().close()


def events(chunks, cancelled):
    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer, data, total = "", [], 0
    try:
        for chunk in chunks:
            if cancelled.is_set():
                raise RuntimeError("Translation cancelled.")
            total += len(chunk)
            if total > 1024 * 1024:
                raise RuntimeError("The local translation response was too large.")
            buffer += decoder.decode(chunk)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.rstrip("\r")
                if line.startswith("data:"):
                    data.append(line[5:].lstrip(" "))
                elif not line and data:
                    payload, data = "\n".join(data), []
                    if payload == "[DONE]":
                        return
                    yield json.loads(payload)
        decoder.decode(b"", final=True)
    except (ValueError, UnicodeError) as error:
        raise RuntimeError("The local server returned an invalid translation stream.") from error
    raise RuntimeError("The local translation stream ended early.")


def visible_text(text):
    """Do not display a split leading reasoning tag or its body."""
    text = text.lstrip()
    while text.startswith("<think>"):
        end = text.find("</think>")
        if end < 0:
            return ""
        text = text[end + 8:].lstrip()
    return "" if text and "<think>".startswith(text) else text


def read_translation(response, cancelled, on_text):
    accumulated, finish = "", None
    def chunks():
        while not cancelled.is_set():
            chunk = response.read1(8192)
            if not chunk:
                return
            yield chunk
        raise RuntimeError("Translation cancelled.")
    for event in events(chunks(), cancelled):
        try:
            choices = event["choices"]
            if not isinstance(choices, list) or "error" in event:
                raise ValueError()
            # llama.cpp ends usage-enabled streams with no choices.
            if not choices and isinstance(event.get("usage"), dict):
                continue
            choice = choices[0]
            finish = choice.get("finish_reason") or finish
            delta = choice["delta"].get("content", "")
            # Role and reasoning events may carry null instead of text.
            if delta is None:
                delta = ""
            if not isinstance(delta, str):
                raise ValueError()
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as error:
            raise RuntimeError("The local server returned an invalid translation stream.") from error
        accumulated += delta
        if delta:
            on_text(visible_text(accumulated))
    from .translation import _translation_content
    return _translation_content({"choices": [{"message": {"content": accumulated}, "finish_reason": finish}]})
