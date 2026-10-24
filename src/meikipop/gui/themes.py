"""Meikipop appearance presets shared by both desktop applications."""

THEMES = {
    "Dark": {
        "color_background": "#000000", "color_foreground": "#FFFFFF",
        "color_highlight_word": "#FFFFFF", "color_highlight_reading": "#B8B8B8",
        "background_opacity": 250,
    },
    "Tokyo Night": {
        "color_background": "#0B0E18", "color_foreground": "#E4E9FF",
        "color_highlight_word": "#82AAFF", "color_highlight_reading": "#86E1FC",
        "background_opacity": 250,
    },
    "Dracula": {
        "color_background": "#100D17", "color_foreground": "#F8F8F2",
        "color_highlight_word": "#FF92D0", "color_highlight_reading": "#C8ACFF",
        "background_opacity": 250,
    },
    "EVA": {
        "color_background": "#1C102D", "color_foreground": "#F4F1FF",
        "color_highlight_word": "#B8FF3D", "color_highlight_reading": "#C09AFF",
        "background_opacity": 250,
    },
    "Light": {
        "color_background": "#FFFFFF", "color_foreground": "#202020",
        "color_highlight_word": "#202020", "color_highlight_reading": "#606060",
        "background_opacity": 250,
    },
    "Custom": {}
}


def theme_name(name):
    if name == "Green":
        return "Tokyo Night"
    if name == "Monochrome Dark":
        return "Dark"
    return name if name in THEMES else "Dark"
