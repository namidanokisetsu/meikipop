"""Turkish desktop lookup and explicit offline data/model setup."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


def print_json(value):
    # Redirected Windows stdout otherwise uses a code page missing Turkish letters.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-turkish-dict")
    build.add_argument("--source", type=Path)
    build.add_argument("--output", type=Path)
    setup = sub.add_parser("setup-turkish-model", help="Explicitly download the pinned Turkish models")
    setup.add_argument("--model-dir", type=Path)
    wordnet = sub.add_parser("setup-turkish-wordnet", help="Build the locked offline KeNet pack")
    wordnet.add_argument("--source", type=Path)
    wordnet.add_argument("--output", type=Path)
    sub.add_parser("setup-turkish-ocr", help="Explicitly download local PaddleOCR models")
    for command in ("turkish-clipboard", "lookup-turkish"):
        cmd = sub.add_parser(command)
        cmd.add_argument("--dictionary", type=Path)
        cmd.add_argument("--model-dir", type=Path)
        cmd.add_argument("--analyzer", choices=("stanza", "exact"), default="stanza")
        if command == "turkish-clipboard":
            cmd.add_argument("--hotkey", help="Clipboard shortcut in pynput syntax")
            cmd.add_argument("--search-hotkey", help="Typed-search shortcut in pynput syntax")
        else:
            cmd.add_argument("text")
            cmd.add_argument("--debug", action="store_true", help="Include raw analysis and attempted lookup routes")
            cmd.add_argument("--target", type=int, help="Zero-based token index (otherwise whole phrase, then first token)")
    args = parser.parse_args(argv)
    if args.command == "setup-turkish-wordnet":
        from meikipop.dictionary.turkish_wordnet import setup_wordnet
        print_json(setup_wordnet(args.source, args.output))
        return
    if args.command == "setup-turkish-ocr":
        from meikipop.ocr.turkish_paddle import setup_ocr
        print(setup_ocr())
        return
    if args.command == "build-turkish-dict":
        from meikipop.scripts.build_turkish_dictionary import main as build_main
        forwarded = []
        for name in ("source", "output"):
            if getattr(args, name):
                forwarded.extend((f"--{name}", str(getattr(args, name))))
        return build_main(forwarded)
    if args.command == "setup-turkish-model":
        from meikipop.language.stanza_analyzer import setup_models
        return setup_models(args.model_dir)
    from meikipop.dictionary.turkish_store import default_dictionary_path, TurkishStore
    dictionary = args.dictionary or default_dictionary_path()
    if args.command == "turkish-clipboard":
        from meikipop.gui.turkish.window import run_clipboard
        return run_clipboard(dictionary, args.analyzer, args.model_dir, args.hotkey, args.search_hotkey)
    if not args.text.strip() or len(args.text) > 2000:
        parser.error("Text must contain 1–2,000 characters")
    from meikipop.dictionary.turkish_lookup import TurkishLookup
    store = TurkishStore(dictionary)
    try:
        lookup = TurkishLookup(store, args.analyzer, args.model_dir)
        result = lookup.lookup(args.text, args.target, debug=args.debug)
        if args.target is not None and not 0 <= args.target < len(result.tokens):
            parser.error("Target is outside the token list")
        output = asdict(result)
        if args.debug:
            output["analyzer"] = lookup.analyzer.identity
            diagnostics = getattr(lookup.analyzer, "diagnostics", None)
            output["analysis"] = diagnostics(args.text) if diagnostics else None
        else:
            output.pop("attempts")
        print_json(output)
    finally:
        store.close()


def desktop():
    return main(["turkish-clipboard", *sys.argv[1:]])


if __name__ == "__main__":
    main()
