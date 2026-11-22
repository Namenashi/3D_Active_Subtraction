"""
This file was generated entirely by Claude and provides an optional graphical user interface for controlling the simulator.
It does not implement or modify the core SAS/PAS algorithms.
"""

PALETTE = {
    'background': '#e8e6de',
    'panel': '#f0efea',
    'field': '#faf9f4',
    'paper': '#f7f6f1',
    'hover': '#dedbd0',
    'border': '#c8c5ba',
    'ink': '#191919',
    'muted': '#65645e',
    'accent': '#f0cb00',
    'accent_hover': '#e0bd00',
    'disabled': '#777777',
    'error': '#a33126',
    'preview_x': '#ef5350',
    'preview_y': '#66bb6a',
    'preview_z': '#5c9ded',
    'included_side_a': '#6d9cc1',
    'included_side_b': '#47799e',
    'included_top': '#91bad8',
    'excluded_side_a': '#cbd3dd',
    'excluded_side_b': '#a5afbe',
    'excluded_top': '#e5eaf0',
    'preview_outline': '#505050',
    'marker_before': '#a633d9',
    'marker_after': '#21c74d',
    'movement': '#ff5200',
}

COLORS = {
    'background': PALETTE['background'],
    'panel': PALETTE['panel'],
    'field': PALETTE['field'],
    'canvas': PALETTE['paper'],
    'control': PALETTE['background'],
    'active': PALETTE['hover'],
    'border': PALETTE['border'],
    'text': PALETTE['ink'],
    'muted': PALETTE['muted'],
    'header': PALETTE['ink'],
    'accent': PALETTE['accent'],
}

VISUAL_RGB = {
    'VISUAL_COLOR_INCLUDED': (0.27, 0.51, 0.71),
    'VISUAL_COLOR_EXCLUDED': (0.83, 0.83, 0.83),
    'VISUAL_COLOR_ACTIVE': (0.92, 0.76, 0.3),
    'VISUAL_COLOR_MOVE': (1.0, 0.32, 0.0),
    'VISUAL_COLOR_MARKED': (0.13, 0.78, 0.3),
    'VISUAL_COLOR_MARKED_BEFORE': (0.65, 0.2, 0.85),
    'VISUAL_COLOR_GROUND': (0.55, 0.27, 0.07),
    'VISUAL_COLOR_SINK': (0.86, 0.08, 0.24),
}

VISUAL_OPACITY_ACTIVE = 0.80
VISUAL_OPACITY_SINK = 0.80
VISUAL_CUBE_EDGE = 0.88
VISUAL_OPACITY_FOCUS = 1.0
VISUAL_OPACITY_MARKED = 0.42
VISUAL_OPACITY_DIM = 0.15
VISUAL_OPACITY_IDLE = 0.88
VISUAL_CAMERA_XY = 1.25
VISUAL_CAMERA_Z = -0.85

RENDER_RGB = {
    'white': (1.0, 1.0, 1.0),
    'black': (0.0, 0.0, 0.0),
    'red': (1.0, 0.0, 0.0),
    'green': (0.0, 1.0, 0.0),
    'blue': (0.0, 0.0, 1.0),
}
