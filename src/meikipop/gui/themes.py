"""Meikipop appearance presets shared by both desktop applications."""

THEMES = {
    "Green": {
        "color_background": "#000000", "color_foreground": "#E8E8E8",
        "color_highlight_word": "#80D69B", "color_highlight_reading": "#A8CFB5",
        "background_opacity": 204,
    },
    "Monochrome Dark": {
        "color_background": "#000000", "color_foreground": "#FFFFFF",
        "color_highlight_word": "#FFFFFF", "color_highlight_reading": "#B8B8B8",
        "background_opacity": 255,
    },
    "Light": {
        "color_background": "#FFFFFF", "color_foreground": "#202020",
        "color_highlight_word": "#202020", "color_highlight_reading": "#606060",
        "background_opacity": 255,
    },
    "Custom": {}
}


def theme_name(name):
    return name if name in THEMES else {
        "Academic": "Light", "light": "Light", "Meikipop": "Custom",
    }.get(name, "Monochrome Dark")
