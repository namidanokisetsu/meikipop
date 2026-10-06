"""Explicit model setup for optional shared-popup lemmatization."""
import argparse


def main():
    from meikipop.dictionary.library import language_code
    from meikipop.language.stanza_analyzer import setup_models
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", type=language_code)
    args = parser.parse_args()
    if args.language == "ja":
        parser.error("Japanese already uses the bundled deconjugation rules.")
    setup_models(language=args.language)


if __name__ == "__main__":
    main()
