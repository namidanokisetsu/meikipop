"""Presentation adapters for legacy dictionaries without semantic sections."""
import re


def _section(label, content):
    kind = {"Meaning": "glosses", "意味": "glosses", "Explanation": "explanation",
            "解説": "explanation", "Example sentences": "examples"}.get(label, "extra-info")
    return {"tag": "div", "data": {"content": kind}, "content": [
        {"tag": "div", "data": {"content": "section-heading"}, "content": label},
        {"tag": "div", "content": content}]}


def normalize_definitions(definitions, source):
    result = []
    for definition in definitions:
        if source == "Bunpro Dictionary" and isinstance(definition, dict):
            content = definition.get("content")
            if definition.get("type") == "structured-content" and isinstance(content, list):
                if content and all(isinstance(child, dict) and child.get("tag") == "a" for child in content):
                    result.append({"type": "structured-content", "content": {
                        "tag": "div", "data": {"content": "attribution"}, "content": content}})
                    continue
                sections, label, children = [], None, []
                for child in content:
                    heading = re.fullmatch(r"【\s*(.*?)\s*】", child) if isinstance(child, str) else None
                    if heading:
                        if label is not None:
                            sections.append(_section(label, children))
                        elif children:
                            sections.extend(children)
                        label, children = heading[1], []
                    else:
                        children.append(child)
                if label is not None:
                    sections.append(_section(label, children))
                    definition = {"type": "structured-content", "content": sections}
        elif source.startswith("日本語文法辞典") and isinstance(definition, str):
            chunks = re.split(r"(?m)^\s*\[([^\]\n]+)\][ \t]*\n?", definition)
            if len(chunks) > 1:
                sections = [{"tag": "div", "data": {"content": "extra-info"}, "content": chunks[0].strip()}]
                sections.extend(_section(chunks[i], chunks[i + 1].strip())
                                for i in range(1, len(chunks) - 1, 2))
                definition = {"type": "structured-content", "content": sections}
        result.append(definition)
    return tuple(result)
