"""
Parses 3D pattern text and constructs simulation grids.
"""

from grid_3d import Grid

_GENERATOR_INCLUDED_CHARS = {'1', 'I', 'i'}
_GENERATOR_EXCLUDED_CHARS = {'0', 'E', 'e'}
_GENERATOR_EMPTY_CHARS = {'.', '_'}

def _generator_parse_layer(layer_lines):
    """
    Splits a pattern layer into cell tokens.
    """
    parsed_rows = []

    for line in layer_lines:
        stripped = line.strip()
        if ' ' in stripped or '\t' in stripped:
            tokens = stripped.split()
        else:
            tokens = list(stripped)
        parsed_rows.append(tokens)

    return parsed_rows


def generator_load_pattern(filepath):
    """
    Loads and validates a pattern file.
    """
    with open(filepath, encoding='utf-8-sig') as generator_file:
        return generator_parse_pattern(generator_file.read())


def generator_parse_pattern(text):
    """
    Parses and validates a 3D text pattern.  All cells with z=0 must be INCLUDED!
    """
    layers_raw = []
    current = []

    for generator_line in text.lstrip('\ufeff').splitlines():
        if generator_line.lstrip().startswith('#'):
            continue
        if generator_line.strip():
            current.append(generator_line)
        elif current:
            layers_raw.append(current)
            current = []
    
    if current:
        layers_raw.append(current)

    if not layers_raw:
        raise ValueError("Empty pattern file")

    parsed_layers = [_generator_parse_layer(layer) for layer in layers_raw]
    num_rows = len(parsed_layers[0])
    num_cols = len(parsed_layers[0][0])
    num_layers = len(parsed_layers)

    modules = {}

    for generator_x, parsed_rows in enumerate(parsed_layers):
        if len(parsed_rows) != num_rows:
            raise ValueError(
                f"Layer {generator_x} has {len(parsed_rows)} rows; expected {num_rows}"
            )
        for row_idx, row in enumerate(parsed_rows):
            if len(row) != num_cols:
                raise ValueError(
                    f"Layer {generator_x}, row {row_idx + 1} has {len(row)} columns; "
                    f"expected {num_cols}"
                )
            x = generator_x
            z = num_rows - 1 - row_idx
            for generator_y, cell in enumerate(row):
                y = generator_y
                if z == 0 and cell not in _GENERATOR_INCLUDED_CHARS:
                    raise ValueError(
                        f"The bottom row must be entirely INCLUDED: "
                        f"x={x}, y={y}, z=0, value={cell!r}"
                    )
                if cell in _GENERATOR_INCLUDED_CHARS:
                    modules[(x, y, z)] = Grid.INCLUDED
                elif cell in _GENERATOR_EXCLUDED_CHARS:
                    modules[(x, y, z)] = Grid.EXCLUDED
                elif cell in _GENERATOR_EMPTY_CHARS:
                    pass
                else:
                    raise ValueError(
                        f"Unknown cell {cell!r} "
                        f"(layer {generator_x}, row {row_idx + 1}, column {generator_y + 1})"
                    )

    return {'width': num_layers, 'height': num_cols, 'depth': num_rows, 'modules': modules,}


def generator_build_grid(pattern):
    """
    Populates a Grid from a parsed pattern.
    """
    grid = Grid(pattern['width'], pattern['height'], pattern['depth'])

    for (x, y, z), generator_type in pattern['modules'].items():
        grid.simulator_set_module(x, y, z, generator_type)

    return grid


def generator_build_grid_from_file(filepath):
    """
    Builds a Grid from a pattern file.
    """
    pattern = generator_load_pattern(filepath)

    return generator_build_grid(pattern)