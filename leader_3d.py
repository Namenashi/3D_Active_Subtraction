"""
Selects SAS modules with an iterative layer traversal
"""

from dataclasses import dataclass

DOWN = -1
UP = 1

def _spiral_xy(x_min, x_max, y_min, y_max):
    """
    Yields coordinates in inward XY spiral order
    """
    while x_min <= x_max and y_min <= y_max:
        for x in range(x_min, x_max + 1):
            yield (x, y_min)
        for y in range(y_min + 1, y_max + 1):
            yield (x_max, y)
        if y_min < y_max:
            for x in range(x_max - 1, x_min - 1, -1):
                yield (x, y_max)
        if x_min < x_max:
            for y in range(y_max - 1, y_min, -1):
                yield (x_min, y)
        x_min += 1
        x_max -= 1
        y_min += 1
        y_max -= 1


@dataclass
class Frame:
    """
    Holds a layer traversal frame.
    """
    lo: int
    hi: int
    direction: int
    layers: list
    i: int = 0


class Leader:
    """
    Selects movable excluded modules for SAS.
    """

    def __init__(self, grid):
        """
        Initializes the iterative SAS selector
        """
        self.grid = grid
        self._gen = self._run()

    def select_next_module(self):
        """
        Returns the next module to activate.
        """
        try:
            return next(self._gen)
        except StopIteration:
            return None

    def _spiral_order(self, candidates):
        """
        Orders module positions by XY spiral
        """
        by_xy = {(p[0], p[1]): p for p in candidates}
        ordered = []
        
        for (x, y) in _spiral_xy(0, self.grid.width - 1, 0, self.grid.height - 1):
            if (x, y) in by_xy:
                ordered.append(by_xy[(x, y)])
        
        return ordered

    def _layers(self, lo, hi, direction):
        """
        Calculate layer and gets excluded module layers in traversal order.
        """
        return sorted(
            {p[2] for p in self.grid.get_excluded_positions() if lo <= p[2] <= hi},
            reverse=(direction == DOWN),
        )

    def _run(self):
        """
        Traverses layers using an explicit stack.
        """
        exc = self.grid.get_excluded_positions()
        
        if not exc:
            return

        zs = [p[2] for p in exc]
        lo = min(zs)
        hi = max(zs)
        stack = [
            Frame(
                lo=lo,
                hi=hi,
                direction=DOWN,
                layers=self._layers(lo, hi, DOWN),
                i=0,
            )
        ]

        while stack:
            frame = stack[-1]

            if frame.i == len(frame.layers):
                stack.pop()
                continue

            z = frame.layers[frame.i]

            yield from self._drain_layer(z)

            frame.i += 1

            if frame.direction == DOWN:
                child_lo, child_hi = z, frame.hi
            else:
                child_lo, child_hi = frame.lo, z

            if self._has_movable_excluded(child_lo, child_hi):
                child_direction = UP if frame.direction == DOWN else DOWN
                child_layers = self._layers(
                    child_lo,
                    child_hi,
                    child_direction,
                )
                stack.append(
                    Frame(
                        lo = child_lo,
                        hi = child_hi,
                        direction = child_direction,
                        layers = child_layers,
                        i = 0,
                    )
                )

    def _has_movable_excluded(self, lo, hi):
        """
        Checks for movable excluded modules in a height range.
        """
        return any(
            lo <= u[2] <= hi and self.grid.get_free_faces(u) > 0
            for u in self.grid.get_excluded_positions()
        )

    def _drain_layer(self, z):
        """
        Yields movable modules from one layer
        """
        while True:
            movable = [
                u for u in self.grid.get_excluded_positions()
                if u[2] == z and self.grid.get_free_faces(u) > 0
            ]
            if not movable:
                return
            for module_pos in self._spiral_order(movable):
                # yield 뒤 Simulator가 해당 active를 끝낸 다음 generator가 재개된다.
                yield module_pos