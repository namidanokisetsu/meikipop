"""Meikipop appearance presets shared by both desktop applications."""

THEMES = {
    "Cyan": {
        "color_background": "#000000", "color_foreground": "#FFFFFF",
        "color_highlight_word": "#00E5FF", "color_highlight_reading": "#B8B8B8",
        "background_opacity": 255,
    },
    "Lime": {
        "color_background": "#000000", "color_foreground": "#FFFFFF",
        "color_highlight_word": "#B6FF00", "color_highlight_reading": "#B8B8B8",
        "background_opacity": 255,
    },
    "Light": {
        "color_background": "#FFFFFF", "color_foreground": "#202124",
        "color_highlight_word": "#185ABC", "color_highlight_reading": "#196637",
        "background_opacity": 255,
    },
    "Custom": {}
}


def theme_name(name):
    return name if name in THEMES else {
        "Academic": "Light", "light": "Light", "Dusk": "Lime",
    }.get(name, "Cyan")
