"""
Selects active-module movement. Using (local) Trémaux marks.
- Input: environment informations.
- Output: movement decisions and mark updates.
"""

from grid_3d import OPPOSITE, SLIDE_DIRS

GLOBAL_PRIORITY = (
    'D', 'FD', 'RD',
    'LD', 'F', 'RF',
    'LF', 'R', 'L', 'FU', 'RU', 'LU',
    'U', 'BU', 'RB',
    'LB', 'B', 'BD',
)

_PRIORITY_INDEX = {d: i for i, d in enumerate(GLOBAL_PRIORITY)}


class SurfaceContactInvariantError(RuntimeError):
    """
    Signals a missing required surface contact.
    - Output: runtime exception.
    """


def direction_rank(direction):
    """
    Orders directions by fixed priority.
    - Input: direction(s).
    - Output: priority (integer).
    """
    return _PRIORITY_INDEX.get(direction, 10_000)


class ActiveModule:
    """
    Controls active-module traversal with local marks.
    """

    def __init__(self, env):
        """
        Initializes movement and logging state.
        """
        self.env = env
        self._pending_reverse_mark = None
        self.current_D = None
        self.dead_reason = None

        # [log] 알고리즘 결과를 바꾸지 않고 한 step의 관찰값만 보존한다.
        self._log_legal_dirs = []
        self._log_markers_before_move = []
        self._log_markers_after_move = []

    def next_direction(self):
        """
        Chooses the next contact-preserving Trémaux move unsing local environment and stored marks.
        - Output: direction (New edge -> cycle closure -> backtracking) or None.
        """
        self._finalize_pending_reverse_mark()
        self.dead_reason = None
        self._log_legal_dirs = []
        self._log_markers_before_move = []
        self._log_markers_after_move = []

        if not self.env.contact_hosts():
            raise SurfaceContactInvariantError(
                'Active module has no face-contact host during Trémaux traversal'
            )

        legal_dirs = [
            direction
            for direction in SLIDE_DIRS
            if self.env.is_legal_move_dir(direction, require_contact=True)
        ]
        self._log_legal_dirs = list(legal_dirs)

        if not legal_dirs:
            self.dead_reason = 'No contact-preserving legal move available'
            return None

        incoming_reverse = OPPOSITE.get(self.current_D) if self.current_D else None

        direction_candidates = []
        inconsistent = []
        for direction in legal_dirs:
            candidate_list = self.env.dfs_entry_candidates_at(direction)
            if not candidate_list:
                continue
            candidate = dict(candidate_list[0])
            candidate['is_incoming_reverse'] = (
                incoming_reverse is not None and direction == incoming_reverse
            )
            direction_candidates.append(candidate)
            if not candidate.get('mark_consistent', True):
                inconsistent.append(candidate)

        if inconsistent:
            self.dead_reason = 'Inconsistent replicated marks for the same direction'
            return None

        # mark 2 = used edge!
        selectable = [
            candidate
            for candidate in direction_candidates
            if candidate.get('mark') in (0, 1)
        ]
        incoming = [
            candidate
            for candidate in selectable
            if candidate.get('is_incoming_reverse')
        ]
        incoming_candidate = incoming[0] if incoming else None
        incoming_mark = (
            incoming_candidate.get('mark') if incoming_candidate else None
        )

        non_incoming_all = [
            candidate
            for candidate in direction_candidates
            if not candidate.get('is_incoming_reverse')
        ]
        non_incoming_marked = [
            candidate
            for candidate in non_incoming_all
            if candidate.get('mark') in (1, 2)
        ]
        non_incoming_0 = [
            candidate
            for candidate in selectable
            if not candidate.get('is_incoming_reverse')
            and candidate.get('mark') == 0
        ]
        non_incoming_1 = [
            candidate
            for candidate in selectable
            if not candidate.get('is_incoming_reverse')
            and candidate.get('mark') == 1
        ]

        non_incoming_0.sort(key=lambda candidate: direction_rank(candidate['dir']))
        non_incoming_1.sort(key=lambda candidate: direction_rank(candidate['dir']))

        if (
            incoming_candidate is not None
            and incoming_mark == 1
            and non_incoming_marked
        ):
            return self._take_direction_move(incoming_candidate)

        if non_incoming_0:
            return self._take_direction_move(non_incoming_0[0])

        if incoming_candidate is not None and incoming_mark == 0:
            return self._take_direction_move(incoming_candidate)

        if non_incoming_1:
            return self._take_direction_move(non_incoming_1[0])

        if incoming_candidate is not None and incoming_mark == 1:
            return self._take_direction_move(incoming_candidate)

        self.dead_reason = 'Legal physical moves exist, but no direction with mark < 2 is available'
        return None

    def after_move(self):
        """
        Updates arrival marks after a committed move.
        """
        result = self._finalize_pending_reverse_mark()
        self._log_markers_after_move = self._log_marker_updates(result)

    @staticmethod
    def _log_marker_updates(result):
        """
        Formats mark changes for tracing. Update log.
        """
        if not result:
            return []
        direction = result.get('dir')
        return [
            {
                'module_id': update.get('host_id'),
                'face': update.get('host_face'),
                'dir': direction,
                'old': update.get('old'),
                'new': update.get('new'),
            }
            for update in result.get('updated', [])
        ]

    def _take_direction_move(self, candidate):
        """
        Marks a selected departure direction.
        """
        direction = candidate['dir']
        result = self.env.dfs_entry_mark_inc(direction)
        self._log_markers_before_move = self._log_marker_updates(result)
        self._pending_reverse_mark = direction
        self.current_D = direction
        return direction

    def _finalize_pending_reverse_mark(self):
        """
        Marks the reverse direction after arrival.
        """
        if self._pending_reverse_mark is None:
            return None

        entered_dir = self._pending_reverse_mark
        self._pending_reverse_mark = None
        reverse_dir = OPPOSITE[entered_dir]

        if not self.env.contact_hosts():
            raise SurfaceContactInvariantError(
                'Active module lost all face-contact after a committed Trémaux move'
            )

        return self.env.dfs_entry_mark_inc(reverse_dir)
