"""
Stores 3D modules and evaluates local slide and Trémaux mark operations.
"""

# 26-neighbor definitions
DIRECTIONS = {
    'R':  (-1, 0, 0),
    'L':  (1, 0, 0),
    'F':  (0, -1, 0),
    'B':  (0, 1, 0),
    'U':  (0, 0, 1),
    'D':  (0, 0, -1),

    'LF': (1, -1, 0),
    'RF': (-1, -1, 0),
    'RB': (-1, 1, 0),
    'LB': (1, 1, 0),

    'LU': (1, 0, 1),
    'RU': (-1, 0, 1),
    'RD': (-1, 0, -1),
    'LD': (1, 0, -1),

    'FU': (0, -1, 1),
    'BU': (0, 1, 1),
    'BD': (0, 1, -1),
    'FD': (0, -1, -1),

    'LFU': (1, -1, 1),
    'RFU': (-1, -1, 1),
    'RBU': (-1, 1, 1),
    'LBU': (1, 1, 1),
    'LFD': (1, -1, -1),
    'RFD': (-1, -1, -1),
    'RBD': (-1, 1, -1),
    'LBD': (1, 1, -1),
}
OPPOSITE = {
    'R': 'L', 'L': 'R',
    'F': 'B', 'B': 'F',
    'U': 'D', 'D': 'U',
    'LF': 'RB', 'RB': 'LF',
    'RF': 'LB', 'LB': 'RF',
    'LU': 'RD', 'RD': 'LU',
    'RU': 'LD', 'LD': 'RU',
    'FU': 'BD', 'BD': 'FU',
    'BU': 'FD', 'FD': 'BU',
    'LFU': 'RBD', 'RBD': 'LFU',
    'RFU': 'LBD', 'LBD': 'RFU',
    'RBU': 'LFD', 'LFD': 'RBU',
    'LBU': 'RFD', 'RFD': 'LBU',
}
ADJACENT_DIRS = ('F', 'U', 'B', 'D', 'R', 'L')
CONTACT_DIR_ORDER = ('D', 'U', 'F', 'B', 'L', 'R')
SLIDE_DIRS = (
    'F', 'U', 'B', 'D', 'R', 'L',
    'LF', 'RF', 'RB', 'LB',
    'LU', 'RU', 'RD', 'LD',
    'FU', 'BU', 'BD', 'FD',
)


class IllegalSlideError(RuntimeError):
    """
    This class signals an illegal module slide.
    """


class Module:
    """
    Class for module (INCLUDED or EXCLUDED). Stores a module type, ID, and contact marks.
    """
    INCLUDED = 'I'
    EXCLUDED = 'E'

    def __init__(self, module_type, module_id):
        """
        Initializes module identity and mark storage.
        """
        if module_type not in (self.INCLUDED, self.EXCLUDED):
            raise ValueError(f'Invalid module type: {module_type!r}')
        
        self.type = module_type
        self.id = module_id
        self.remembered_id = None
        self.dfs_marks = {}

    def tell_id(self):
        """
        Returns the module identifier (Module ID).
        """
        return self.id


class Grid:
    """
    Manages 3D module positions, sinks, and local movement rules.
    """
    INCLUDED = Module.INCLUDED
    EXCLUDED = Module.EXCLUDED

    def __init__(self, width, height, depth=1, sinks=None):
        """
        Initializes a 3D grid and its module storage.
        """
        if width < 1 or height < 1 or depth < 1:
            raise ValueError('Grid dimensions must all be positive')
        
        self.width = width
        self.height = height
        self.depth = depth
        self.sinks = set(sinks) if sinks else set()
        self.module = {}
        self._next_id = 0

    @staticmethod
    def _simulator_format_id(number, width=4):
        """
        Formats a numeric module identifier into 0-padding
        """
        return f'{number:0{width}d}'

    def simulator_set_module(self, x, y, z, module_type):
        """
        Adds a module at an unoccupied coordinate.
        """
        position = (x, y, z)
        
        if position in self.module:
            raise ValueError(f'Module already exists at {position}')
        
        self.module[position] = Module(
            module_type,
            self._simulator_format_id(self._next_id),
        )
        self._next_id += 1

    def simulator_assign_ids_by_position(self):
        """
        Assigns module IDs in positional order.
        """
        if not self.module:
            self._next_id = 0
            return
        
        ordered = sorted(self.module, key=lambda pos: (pos[2], pos[0], pos[1]))
        width = max(4, len(str(len(ordered) - 1)))
        
        for rank, position in enumerate(ordered):
            self.module[position].id = self._simulator_format_id(rank, width)
        
        self._next_id = len(ordered)

    def simulator_remove_module(self, position):
        """
        Removes a module at a coordinate.
        """
        self.module.pop(position, None)

    def simulator_move_module(self, from_pos, direction):
        """
        Commits a legal contact-preserving slide.
        - Output: destination position.
        """
        if from_pos not in self.module:
            raise IllegalSlideError(f'No active module at {from_pos}')
        
        if direction not in SLIDE_DIRS:
            raise IllegalSlideError(
                f'Illegal one-step direction {direction!r}; '
                'three-axis corner moves require multiple slides'
            )
        
        if not self.is_legal_move_dir(from_pos, direction, require_contact=True):
            raise IllegalSlideError(
                f'Illegal contact-preserving slide: pos={from_pos}, dir={direction}'
            )

        to_pos = self._neighbor(from_pos, direction)
        
        if to_pos in self.module:
            raise IllegalSlideError(f'Target cell is occupied: {to_pos}')

        self.module[to_pos] = self.module.pop(from_pos)

        return to_pos

    def simulator_compute_fixed_sink(self):
        """
        Sets the fixed sink row along the x-axis.
        """
        self.sinks = {(x, -1, 0) for x in range(self.width)}
        
        return self.sinks

    def is_empty(self, position):
        """
        Checks whether a coordinate is empty.
        """
        if position[2] < 0:
            return False
        
        return position not in self.module

    def get_free_faces(self, position):
        """
        Counts empty face-adjacent cells.
        """
        simulator_free_count = 0
        
        for simulator_direction in ADJACENT_DIRS:
            simulator_neighbor = self._neighbor(position, simulator_direction)
            if self.is_empty(simulator_neighbor):
                simulator_free_count += 1
        
        return simulator_free_count

    def is_empty_dir(self, my_pos, direction):
        """
        Checks an adjacent cell in a given direction.
        """
        return self.is_empty(self._neighbor(my_pos, direction))

    def is_module_dir(self, my_pos, direction):
        """
        Checks for a module in a given direction.
        """
        return self._neighbor(my_pos, direction) in self.module

    def _neighbor(self, position, direction):
        """
        Calculates a neighboring coordinate.
        """
        if direction not in DIRECTIONS:
            raise ValueError(f'Unknown direction: {direction!r}')
        
        dx, dy, dz = DIRECTIONS[direction]
        
        return (
            position[0] + dx,
            position[1] + dy,
            position[2] + dz,
        )

    def _axis_component_dirs(self, direction):
        """
        Decomposes a direction into axis steps.
        """
        dx, dy, dz = DIRECTIONS[direction]
        parts = []
        
        if dx < 0:
            parts.append('R')
        elif dx > 0:
            parts.append('L')
        
        if dy < 0:
            parts.append('F')
        elif dy > 0:
            parts.append('B')
        
        if dz < 0:
            parts.append('D')
        elif dz > 0:
            parts.append('U')
        
        return parts

    def contact_hosts(self, my_pos, order=CONTACT_DIR_ORDER):
        """
        Lists face-contacting modules and their IDs.
        """
        hosts = []
        
        for direction in order:
            module = self.module.get(self._neighbor(my_pos, direction))
            if module is not None:
                hosts.append((direction, module.tell_id(), OPPOSITE[direction]))
        
        return hosts


    def _diagonal_surface_carriers(self, my_pos, direction):
        """
        Finds contacts supporting modules(carrier) for a diagonal slide.
        """
        parts = self._axis_component_dirs(direction)

        if len(parts) != 2:
            return []
        
        return [side for side in parts if self.is_module_dir(my_pos, side)]

    def local_support_witnesses(self, my_pos, direction):
        """
        Finds contacts supporting modules(carrier) for a slide.
        """
        if direction not in SLIDE_DIRS:
            return []

        parts = self._axis_component_dirs(direction)
        
        if len(parts) == 2:
            return self._diagonal_surface_carriers(my_pos, direction)
        if len(parts) != 1:
            return []

        witnesses = []
        move_vector = DIRECTIONS[direction]
        
        for host_direction in ADJACENT_DIRS:
            if host_direction in (direction, OPPOSITE[direction]):
                continue
            if not self.is_module_dir(my_pos, host_direction):
                continue

            host_vector = DIRECTIONS[host_direction]
            after_vector = (
                host_vector[0] + move_vector[0],
                host_vector[1] + move_vector[1],
                host_vector[2] + move_vector[2],
            )
            after_direction = None
            for simulator_name, simulator_vector in DIRECTIONS.items():
                if simulator_vector == after_vector:
                    after_direction = simulator_name
                    break
            if after_direction is not None and self.is_module_dir(
                my_pos,
                after_direction,
            ):
                witnesses.append(host_direction)

        return witnesses

    def is_legal_move_dir(self, my_pos, direction, require_contact=True):
        """
        Checks whether a one-step slide is legal.
        """
        if direction not in SLIDE_DIRS:
            return False

        target = self._neighbor(my_pos, direction)
  
        if not self.is_empty(target):
            return False

        parts = self._axis_component_dirs(direction)
  
        if len(parts) == 2:
            empty_sides = [
                side for side in parts if self.is_empty_dir(my_pos, side)
            ]
            carriers = self._diagonal_surface_carriers(my_pos, direction)
            if len(empty_sides) != 1 or len(carriers) != 1:
                return False
        elif len(parts) != 1:
            return False

        if require_contact and not self.local_support_witnesses(my_pos, direction):
            return False

        return True

    def _prepare_marks_for_active(self, module, active_id):
        """
        Resets marks when the active ID changes.
        """
        if active_id is None or module is None:
            return
        
        if module.remembered_id != active_id:
            module.remembered_id = active_id
            module.dfs_marks = {}

    def _current_contact_mark_records(self, my_pos, active_id):
        """
        Collects contact hosts for mark operations.
        """
        if active_id is None:
            return []

        records = []

        for host_dir, host_id, host_face in self.contact_hosts(my_pos):
            module = self.module.get(self._neighbor(my_pos, host_dir))
            if module is None:
                continue
            self._prepare_marks_for_active(module, active_id)
            records.append((module, host_face, host_dir, host_id))
        
        return records

    def dfs_entry_candidates_at(self, my_pos, active_id, move_dir):
        """
        Reads replicated Trémaux marks for a move.
        """
        records = self._current_contact_mark_records(my_pos, active_id)

        if not records:
            return []

        contact_records = []
        values = []
        
        for module, face, host_dir, host_id in records:
            mark = module.dfs_marks.get(active_id, {}).get(face, {}).get(
                move_dir,
                0,
            )
            values.append(mark)
            contact_records.append({
                'host_dir': host_dir,
                'host_id': host_id,
                'host_face': face,
                'mark': mark,
            })

        consistent = len(set(values)) <= 1
        
        return [{
            'dir': move_dir,
            'mark': values[0] if consistent else None,
            'mark_consistent': consistent,
            'replica_values': list(values),
            'contact_records': contact_records,
        }]

    def dfs_entry_mark_inc(self, my_pos, active_id, move_dir):
        """
        Increments replicated marks for one move direction.
        """
        candidates = self.dfs_entry_candidates_at(my_pos, active_id, move_dir)
        
        if not candidates:
            return None

        candidate = candidates[0]
        
        if not candidate.get('mark_consistent', True):
            raise RuntimeError(
                f'MARK_INCONSISTENT pos={my_pos} active={active_id} '
                f'dir={move_dir} values={candidate.get("replica_values")} '
                f'records={candidate.get("contact_records")}'
            )

        old = candidate.get('mark', 0)
        new = min(2, old + 1)
        updated = []
        
        for module, face, host_dir, host_id in self._current_contact_mark_records( my_pos, active_id,):
            by_active = module.dfs_marks.setdefault(active_id, {})
            by_face = by_active.setdefault(face, {})
            previous = by_face.get(move_dir, 0)
            by_face[move_dir] = new
            updated.append({
                'host_dir': host_dir,
                'host_id': host_id,
                'host_face': face,
                'old': previous,
                'new': new,
            })

        return {
            'dir': move_dir,
            'old': old,
            'new': new,
            'updated': updated,
        }

    def get_excluded_positions(self):
        """
        Lists coordinates of EXCLUDED modules.
        """
        return [
            position
            for position, module in self.module.items()
            if module.type == self.EXCLUDED
        ]

    def get_included_positions(self):
        """
        Lists coordinates of INCLUDED modules.
        """
        return [
            position
            for position, module in self.module.items()
            if module.type == self.INCLUDED
        ]

