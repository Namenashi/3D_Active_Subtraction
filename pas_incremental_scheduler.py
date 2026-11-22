"""
Maintains PAS candidate and approved-trajectory caches.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
import os

from active_3d import ActiveModule
from simulator import (
    PASActiveEnvironment, PASActiveState, PASSimulator, PASRejectedError,
    PASSimulationResult, PASclone_initial_grid,
)


@dataclass(frozen=True)
class Move:
    """
    Stores a recorded PAS movement and reserved cells
    """
    position: tuple
    required: frozenset
    direction: str


@dataclass
class PASStaticEnvironment:
    """
    Holds the candidate static layout and activation events.
    """
    grid: object
    static_ids: set
    activation_events: dict
    candidate_id: str
    activation_time: int


@dataclass
class PASPartialTrial:
    """
    Stores an unapproved PAS trial.
    """
    candidate: object
    prefix: tuple
    final: object
    suffix: dict
    markers: dict
 

class RecordingPASSimulator(PASSimulator):
    """
    Captures committed PAS moves during trials.
    """

    def PAScommit_moves(self, planned):
        """
        Records reserved cells and commits simultaneous moves
        """
        self._recorded_moves = {
            move['active_id']: Move(
                move['to'],
                frozenset(self.PASmovement_space(move['from'], move['chosen_dir'])),
                move['chosen_dir'],
            )
            for move in planned
        }
        
        return super().PAScommit_moves(planned)


class IncrementalPAS:
    """
    Caches approved PAS paths for candidate evaluation.
    """

    def __init__(self, execution, records):
        """
        Initializes PAS layout and movement caches
        """
        self.execution = execution
        self.records = tuple(records)
        self.initial = execution.PASinitial_grid
        self.start_position = {
            module.id: position for position, module in self.initial.module.items()
        }
        self.original_ids = set(self.start_position)
        self._module_ids = tuple(sorted(self.original_ids))
        self._module_bits = {module_id: 1 << i for i, module_id in enumerate(self._module_ids)}
        self._initial_static_bits = (1 << len(self._module_ids)) - 1
        self._activation_events = {}
        self._activation_times = []
        self._static_layout_at_activation = {}
        self.approved = ()
        self.moves = {}
        self.mark_history = {}
        self.stats = defaultdict(int)

    def _refresh_static_layouts(self):
        """
        Rebuilds static bitsets at activation times.
        """
        events = defaultdict(list)

        for entry in self.approved:
            events[entry.PASactivation_time].append(entry.PASmodule_id)
        
        self._activation_times = sorted(events)
        self._activation_events = dict(events)
        self._static_layout_at_activation = {}
        static = self._initial_static_bits
        
        for t in self._activation_times:
            for module_id in events[t]:
                static &= ~self._module_bits[module_id]
            self._static_layout_at_activation[t] = static

    def PASprepare_candidate(self, prefix, candidate):
        """
        Restores the static layout and traversal for a candidate
        """
        if tuple(prefix) != self.approved:
            raise RuntimeError('PAS stage1 environment received unexpected prefix')
        
        s = candidate.PASactivation_time
        idx = bisect_right(self._activation_times, s) - 1
        static = (self._static_layout_at_activation[self._activation_times[idx]]
                  if idx >= 0 else self._initial_static_bits)
        static &= ~self._module_bits[candidate.PASmodule_id]
        static_ids = {
            module_id for module_id in self._module_ids
            if static & self._module_bits[module_id]
        }
        grid = PASclone_initial_grid(self.initial)
        missing = self._initial_static_bits & ~static
        candidate_bit = self._module_bits[candidate.PASmodule_id]
        missing &= ~candidate_bit
        
        while missing:
            bit = missing & -missing
            grid.module.pop(self.start_position[self._module_ids[bit.bit_length() - 1]], None)
            missing ^= bit
        
        future_events = {
            t: ids for t, ids in self._activation_events.items() if t > s
        }
        environment = PASStaticEnvironment(
            grid, static_ids, future_events, candidate.PASmodule_id, s
        )
        module_id = environment.candidate_id
        pos = self.start_position[module_id]
        body = environment.grid.module[pos]
        body.dfs_marks.clear()
        active_env = PASActiveEnvironment(environment.grid, pos, module_id, environment.static_ids)
        algorithm = ActiveModule(active_env)
        
        class SpaceView:
            """
            Provides a grid and static IDs for movement space checks.
            """
            pass
        
        view = SpaceView()
        view.simulator_grid = environment.grid
        view.PASstatic_ids = environment.static_ids
        
        return {'layout': environment, 'position': pos, 'body': body,
                'environment': active_env, 'algorithm': algorithm, 'space_view': view}


    def PASapply_confirmed_activations(self, environment, step):
        """
        Updates a candidate layout for approved activations.
        """
        if step <= environment.activation_time:
            return

        for old_id in environment.activation_events.get(step, ()):
            environment.static_ids.remove(old_id)
            body = environment.grid.module.pop(self.start_position[old_id], None)
            if body is not None:
                body.dfs_marks.clear()

    @staticmethod
    def PASnext_candidate_direction(traversal):
        """
        Selects a candidate traversal direction.
        """
        return traversal['algorithm'].next_direction()

    @staticmethod
    def PAScandidate_required_cells(traversal, direction):
        """
        Computes reserved cells for a candidate move.
        """
        return frozenset(PASSimulator.PASmovement_space(
            traversal['space_view'], traversal['position'], direction))

    def PASconfirmed_moves_at(self, step):
        """
        Looks up approved moves at a given step.
        """
        return self.moves.get(step, {})

    @staticmethod
    def PASadvance_candidate(traversal, direction):
        """
        Applies one candidate move
        """
        grid = traversal['layout'].grid
        pos = traversal['position']
        dest = grid._neighbor(pos, direction)
        
        if dest in grid.module:
            raise PASRejectedError(f'PAS candidate target occupied: {dest}')
        
        body = grid.module.pop(pos)
        grid.module[dest] = body
        traversal['position'] = dest
        traversal['environment'].PASactive_pos = dest
        traversal['algorithm'].after_move()
        
        return dest

    def PASrestore_configuration_before(self, schedule):
        """
        Restores PAS state immediately before candidate execution.
        """
        schedule = tuple(schedule)
        
        if schedule[:-1] != self.approved:
            raise RuntimeError('PAS restore received unexpected approved prefix')
        s = schedule[-1].PASactivation_time
        idx = bisect_left(self._activation_times, s) - 1
        static_bits = (self._static_layout_at_activation[self._activation_times[idx]]
                       if idx >= 0 else self._initial_static_bits)
        static_ids = {id_ for id_ in self._module_ids if static_bits & self._module_bits[id_]}
        sim = RecordingPASSimulator(PASclone_initial_grid(self.initial), ActiveModule, schedule, PAScandidate_mode=True)
        sim.PAScurrent_time = s
        sim.simulator_step_count = s - 1
        sim.simulator_finished = False
        sim.PASstatic_ids = static_ids
        bodies = {}

        for entry in self.approved:
            if entry.PASactivation_time < s:
                module_id = entry.PASmodule_id
                bodies[module_id] = sim.simulator_grid.module.pop(self.start_position[module_id])
                if entry.PASarrival_time < s:
                    sim.PASarrival_times[module_id] = entry.PASarrival_time
                    sim.simulator_removed_module += 1
        
        for entry in self.approved:
            if not (entry.PASactivation_time < s <= entry.PASarrival_time):
                continue
            module_id = entry.PASmodule_id
            previous = self.moves.get(s - 1, {}).get(module_id)
            if previous is None:
                raise RuntimeError(f'No approved trajectory at step {s-1} for active {module_id}')
            pos = previous.position
            if pos in sim.simulator_grid.module:
                raise RuntimeError(f'PAS restore occupied cell {pos} at t={s}')
            sim.simulator_grid.module[pos] = bodies[module_id]
            environment = PASActiveEnvironment(sim.simulator_grid, pos, module_id, static_ids)
            state = PASActiveState(module_id, pos, PASenvironment=environment)
            state.PASalgorithm = ActiveModule(environment)
            state.PASalgorithm.current_D = previous.direction
            sim.PASactive_states[module_id] = state
            for (host_id, face, direction), history in self.mark_history.get(module_id, {}).items():
                if host_id not in static_ids:
                    continue
                index = bisect_left(history, (s, -1)) - 1
                if index < 0:
                    continue
                value = history[index][1]
                if value:
                    host = sim.simulator_grid.module[self.start_position[host_id]]
                    host.dfs_marks.setdefault(module_id, {}).setdefault(face, {})[direction] = value

        sim.PASrefresh_active_view()
        
        if len(sim.PASactive_states) == 1:
            only = next(iter(sim.PASactive_states.values()))
            sim.simulator_active_id = only.PASmodule_id
            sim.simulator_active_pos = only.PASposition
        
        self.stats['direct_restores'] += 1
        
        return sim

    @staticmethod
    def PASexecute_simultaneous_step(sim):
        """
        Executes one simultaneous PAS step.
        """
        return sim.simulator_step()

    @staticmethod
    def PASobserved_moves(sim):
        """
        Reads moves recorded in the current step.
        """
        return dict(getattr(sim, '_recorded_moves', {}))

    def PASnew_trial(self, candidate):
        """
        Creates a new unapproved trial record.
        """
        return PASPartialTrial(candidate, self.approved, None, {}, {})

    @staticmethod
    def PASrecord_trial_step(trial, sim, step):
        """
        Stores step movements and marker updates
        """
        trial.suffix[step] = dict(getattr(sim, '_recorded_moves', {}))
        log = sim._visual_last_step_info or {}
        writes = []
        
        for category in ('markers_before_move', 'markers_after_move'):
            for item in log.get(category, ()):
                writes.append((item['active_id'], item['module_id'],
                               item['face'], item['dir'], item['new']))
        
        trial.markers[step] = writes

    @staticmethod
    def PASfinalize_trial(trial, sim):
        """
        Attaches the completed simulator to a trial
        """
        trial.final = sim

    def PAScommit_approved(self, confirmed, trial):
        """
        Adds a verified trial to approved caches.
        """
        if trial is None or trial.prefix != self.approved or trial.final is None:
            raise RuntimeError('PAS cannot commit without a completed verified trial')
        
        candidate = trial.candidate
        
        if (candidate.PASmodule_id != confirmed.PASmodule_id
                or candidate.PASduration != confirmed.PASduration
                or candidate.PASactivation_time != confirmed.PASactivation_time
                or trial.final.PASarrival_times[candidate.PASmodule_id] != confirmed.PASarrival_time):
            raise RuntimeError('PAS committed entry differs from verified trial')
        
        s = candidate.PASactivation_time
        self.moves = {t: moves for t, moves in self.moves.items() if t < s}
        
        self.moves.update(trial.suffix)
        
        for by_key in self.mark_history.values():
            for key, history in list(by_key.items()):
                cut = bisect_left(history, (s, -1))
                if cut < len(history):
                    del history[cut:]
                if not history:
                    del by_key[key]
        
        for step in sorted(trial.markers):
            for active_id, host, face, direction, value in trial.markers[step]:
                by_key = self.mark_history.setdefault(active_id, {})
                by_key.setdefault((host, face, direction), []).append((step, value))
        
        self.approved = trial.prefix + (confirmed,)
        self._refresh_static_layouts()
        self.stats['accepted'] += 1
        self._prune()
        
        if self.stats['accepted'] % 25 == 0:
            print(f'[PAS] approved {self.stats["accepted"]}/{len(self.records)}; '
                  f'attempts={self.stats["attempts"]}, '
                  f'RAM steps={len(self.moves)}, marker_ids={len(self.mark_history)}',
                  flush=True)

    def _prune(self):
        """
        Discards obsolete moves and marker cache entries.
        """
        remaining = self.records[len(self.approved):]
        
        if not remaining:
            self.moves.clear()
            self.mark_history.clear()
            return
        
        longest = max(record.PASduration for record in remaining)
        earliest = self.approved[-1].PASarrival_time + 2 - longest
        self.moves = {t: moves for t, moves in self.moves.items() if t >= earliest - 1}
        retain = {entry.PASmodule_id for entry in self.approved
                  if entry.PASarrival_time >= earliest}
        self.mark_history = {aid: h for aid, h in self.mark_history.items() if aid in retain}
        self.stats['cached_steps'] = len(self.moves)
        self.stats['cached_marker_ids'] = len(self.mark_history)

    def restore_approved(self, entries):
        """
        Reconstructs approved moves after a worker restart.
        """
        entries = tuple(entries)

        if not entries:
            return
        
        if self.approved:
            raise RuntimeError('Cannot restore over populated cache')
        
        sim = RecordingPASSimulator(PASclone_initial_grid(self.initial), ActiveModule, entries, PAScandidate_mode=False)
        moves = {}
        markers = {}
        max_steps = int(os.environ.get('PAS_MAX_STEPS', '1000000'))

        for _ in range(max_steps):
            t = sim.PAScurrent_time
            event = self.PASexecute_simultaneous_step(sim)
            if event[0] == 'stuck':
                raise RuntimeError(sim.simulator_error_msg or 'Failed to recover PAS schedule')
            trial = PASPartialTrial(None, (), None, moves, markers)
            self.PASrecord_trial_step(trial, sim, t)
            if sim.simulator_finished:
                break
        
        else:
            raise RuntimeError('PAS recovery exceeded maximum steps')
        
        if any(sim.PASarrival_times.get(e.PASmodule_id) != e.PASarrival_time for e in entries):
            raise RuntimeError('Recovered prefix does not match saved arrival times')
        
        self.moves = moves
        
        for step in sorted(markers):
            for active_id, host, face, direction, value in markers[step]:
                self.mark_history.setdefault(active_id, {}).setdefault(
                    (host, face, direction), []).append((step, value))
        
        self.approved = entries
        self._refresh_static_layouts()
        self._prune()