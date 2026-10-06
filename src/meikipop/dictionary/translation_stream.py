"""Bounded SSE decoder for local chat-completion streams."""
import codecs
import json


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
            choice = event["choices"][0]
            finish = choice.get("finish_reason") or finish
            delta = choice["delta"].get("content", "")
            if not isinstance(delta, str):
                raise ValueError()
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as error:
            raise RuntimeError("The local server returned an invalid translation stream.") from error
        accumulated += delta
        if delta:
            on_text(visible_text(accumulated))
    from .translation import _translation_content
    return _translation_content({"choices": [{"message": {"content": accumulated}, "finish_reason": finish}]})
