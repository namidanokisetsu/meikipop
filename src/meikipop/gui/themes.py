"""Meikipop appearance presets shared by both desktop applications."""

THEMES = {
    "Charcoal": {
        "color_background": "#181A1F", "color_foreground": "#E8EAED",
        "color_highlight_word": "#8AB4F8", "color_highlight_reading": "#93C5AA",
        "background_opacity": 255,
    },
    "Slate": {
        "color_background": "#1E293B", "color_foreground": "#F1F5F9",
        "color_highlight_word": "#93C5FD", "color_highlight_reading": "#A7F3D0",
        "background_opacity": 255,
    },
    "Dusk": {
        "color_background": "#28231F", "color_foreground": "#F3EADF",
        "color_highlight_word": "#E4BD8B", "color_highlight_reading": "#B8CFAD",
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
    return name if name in THEMES else {"Academic": "Light", "Celestial Indigo": "Slate"}.get(name, "Charcoal")
