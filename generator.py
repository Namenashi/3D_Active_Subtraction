"""
Generates connected, non-hollow 3D test patterns.
"""
import random
from collections import deque
from pathlib import Path


def _neighbors(p, size):
    """
    Enumerates in-bounds face-adjacent coordinates.
    """
    for axis in range(3):
        for delta in (-1, 1):
            q = list(p)
            q[axis] += delta
            if 0 <= q[axis] < size[axis]:
                yield tuple(q)


def _reach(seeds, cells, size):
    """
    Finds cells reachable through a selected cell set.
    """
    reached = set(seeds) & cells
    queue = deque(reached)

    while queue:
        for q in _neighbors(queue.popleft(), size):
            if q in cells and q not in reached:
                reached.add(q)
                queue.append(q)
    
    return reached


def generate_pattern(rng=None, density=0.6, max_attempts=500, size=None):
    """
    Creates a connected, non-hollow random pattern.
    """
    rng = rng if rng is not None else random.Random()

    if not 0 < density < 1:
        raise ValueError('density must be between 0 and 1')
    if size is None:
        size = tuple(rng.randint(3, 10) for _ in range(3))
    if (len(size) != 3 or any(type(value) is not int or value < 1 for value in size)
            or size[2] < 2):
        raise ValueError('size must be (x >= 1, y >= 1, z >= 2), using integers')
    
    nx, ny, nz = size
    cells = {(x, y, z) for x in range(nx) for y in range(ny) for z in range(nz)}
    floor = {p for p in cells if p[2] == 0}
    exterior = {p for p in cells if p[0] in (0, nx-1)
                or p[1] in (0, ny-1) or p[2] == nz-1}
    
    for _ in range(max_attempts):
        included = floor | {p for p in sorted(cells) if rng.random() < density}
        included = _reach(floor, included, size)
        excluded = cells - included
        excluded = _reach(exterior & excluded, excluded, size)
        included = cells - excluded
        if excluded and _reach(floor, included, size) == included:
            # converter의 파일 형식: block=x, 행=큰 z부터, 열=y.
            blocks = ['\n'.join(' '.join('1' if (x,y,z) in included else '0'
                        for y in range(ny)) for z in reversed(range(nz)))
                      for x in range(nx)]
            return '# 1=INCLUDED, 0=EXCLUDED; bottom row z=0\n' + '\n\n'.join(blocks) + '\n'
    
    raise RuntimeError('Could not generate a valid non-hollow pattern')


def save_pattern(path, rng=None, size=None):
    """
    Writes a generated pattern to a file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_pattern(rng, size=size), encoding='utf-8')

    return path


def generate_unique_pattern(size, seen, rng=None):
    """
    Generates and registers an unseen pattern.
    """
    from converter_3d import generator_parse_pattern

    while True:
        text = generate_pattern(rng=rng, size=size)
        pattern = generator_parse_pattern(text)
        key = (tuple(size), tuple(sorted(pattern['modules'].items())))
        if key not in seen:
            seen.add(key)
            return text
