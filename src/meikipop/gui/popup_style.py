"""Shared Meikipop popup frame, independent of dictionary and OCR imports."""

from PyQt6.QtGui import QColor


def frame_stylesheet(background, foreground, opacity, font_family):
    color = QColor(background)
    return f'''
        QFrame {{
            background-color: rgba({color.red()}, {color.green()}, {color.blue()}, {opacity});
            color: {foreground};
            border-radius: 8px;
            border: 1px solid #555;
        }}
        QLabel {{
            background-color: transparent;
            border: none;
            font-family: "{font_family}";
        }}
        hr {{ border: none; height: 1px; }}
    '''


def popup_position(x, y, popup_size, screen_geo, mode):
    """Original Meikipop placement rules, shared by both language windows."""
    offset = 15
    # --- Positioning logic based on mode ---

    if mode == 'visual_novel_mode':
        # --- Vertical Position (VN Mode) ---
        screen_height = screen_geo.height()
        cursor_y_in_screen = y - screen_geo.top()
        is_below = True
        if cursor_y_in_screen > (2 * screen_height / 3):  # Lower third
            is_below = False  # Place above
        elif cursor_y_in_screen < (screen_height / 3):  # Upper third
            is_below = True  # Place below
        else:  # Middle third
            is_below = cursor_y_in_screen < (screen_height / 2)
        final_y = (y + offset) if is_below else (y - popup_size.height() - offset)

        # Vertical Push
        if final_y < screen_geo.top(): final_y = screen_geo.top()
        if final_y + popup_size.height() > screen_geo.bottom():
            final_y = screen_geo.bottom() - popup_size.height()

        # --- Horizontal Position (VN Mode) ---
        screen_width = screen_geo.width()
        cursor_x_in_screen = x - screen_geo.left()
        # Define anchor points for interpolation
        pos_right = x + offset
        pos_center = x - popup_size.width() / 2.0
        pos_left = x - popup_size.width() - offset

        # Interpolate smoothly between right, center, and left alignment
        if cursor_x_in_screen < screen_width / 2.0:
            ratio = cursor_x_in_screen / (screen_width / 2.0)
            final_x = pos_right * (1 - ratio) + pos_center * ratio
        else:
            ratio = (cursor_x_in_screen - (screen_width / 2.0)) / (screen_width / 2.0)
            final_x = pos_center * (1 - ratio) + pos_left * ratio

    elif mode == 'flip_horizontally':
        # X: Flip, Y: Push
        preferred_x = x + offset
        final_x = preferred_x if preferred_x + popup_size.width() <= screen_geo.right() else x - popup_size.width() - offset

        final_y = y + offset
        if final_y + popup_size.height() > screen_geo.bottom(): final_y = screen_geo.bottom() - popup_size.height()
        if final_y < screen_geo.top(): final_y = screen_geo.top()

    elif mode == 'flip_vertically':
        # X: Push, Y: Flip
        final_x = x + offset
        if final_x + popup_size.width() > screen_geo.right(): final_x = screen_geo.right() - popup_size.width()
        if final_x < screen_geo.left(): final_x = screen_geo.left()

        preferred_y = y + offset
        final_y = preferred_y if preferred_y + popup_size.height() <= screen_geo.bottom() else y - popup_size.height() - offset

    else:  # 'flip_both'
        # X: Flip
        preferred_x = x + offset
        final_x = preferred_x if preferred_x + popup_size.width() <= screen_geo.right() else x - popup_size.width() - offset

        # Y: Flip
        preferred_y = y + offset
        final_y = preferred_y if preferred_y + popup_size.height() <= screen_geo.bottom() else y - popup_size.height() - offset

    # Final clamp to ensure the popup is always fully visible.
    # This acts as a safeguard against any edge cases.
    final_x = max(screen_geo.left(), min(final_x, screen_geo.right() - popup_size.width()))
    final_y = max(screen_geo.top(), min(final_y, screen_geo.bottom() - popup_size.height()))

    return int(final_x), int(final_y)
