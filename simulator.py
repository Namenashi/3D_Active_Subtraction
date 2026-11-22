"""
Runs SAS and PAS module simulations and schedule workers
"""

import json
import os
import sys
import subprocess
import tempfile
import time
from collections import deque
from dataclasses import dataclass

from grid_3d import ADJACENT_DIRS, DIRECTIONS, OPPOSITE, SLIDE_DIRS, Grid, Module
from leader_3d_PAS import PASLeaderAlgorithm


def _markers_with_active_id(records, active_id):
    """
    Attaches an active ID to marker records.
    """
    return [dict(record, active_id=active_id) for record in records]


class SimulatorActiveEnvironment:
    """
    Adapts grid operations for a single SAS active module.
    """

    def __init__(self, grid, get_active_pos, active_id):
        """
        Stores SAS grid access and active identity.
        """
        self._simulator_grid = grid
        self._simulator_get_active_pos = get_active_pos
        self.active_id = active_id

    def _simulator_pos(self):
        """
        Reads the current active position.
        """
        position = self._simulator_get_active_pos()
        
        if position is None:
            raise RuntimeError('active position is not available in the environment')
        
        return position

    def contact_hosts(self):
        """
        Finds static contact hosts for the active module.
        """
        return self._simulator_grid.contact_hosts(self._simulator_pos())

    def dfs_entry_candidates_at(self, direction):
        """
        Reads candidate Trémaux marks in a direction.
        """
        return self._simulator_grid.dfs_entry_candidates_at(
            self._simulator_pos(),
            self.active_id,
            direction,
        )

    def is_legal_move_dir(self, direction, require_contact=True):
        """
        Checks a SAS movement direction.
        """
        return self._simulator_grid.is_legal_move_dir(
            self._simulator_pos(),
            direction,
            require_contact=require_contact,
        )

    def dfs_entry_mark_inc(self, direction):
        """
        Increments the selected Trémaux marks.
        """
        return self._simulator_grid.dfs_entry_mark_inc(
            self._simulator_pos(),
            self.active_id,
            direction,
        )


class SimulatorLog:
    """
    Provides shared simulation logging and timing methods.
    """
    def _progress(self, message):
        """
        Forwards a progress message to a callback
        """
        callback = getattr(self, 'simulator_progress_callback', None)
        
        if callback is not None:
            callback(message)

    def simulator_log_summary(self):
        """
        Appends a (successful) run summary to the trace.
        """
        if getattr(self, '_log_summary_written', False):
            return
        
        result = self.simulator_result()

        if not result['success']:
            return
        
        path = getattr(self, '_log_output_path', None)

        if path:
            with open(path, 'a', encoding='utf-8') as output:
                summary = {k: v for k, v in result.items() if k != 'schedule'}
                output.write(json.dumps({'event': 'summary', **summary}, ensure_ascii=False) + '\n')

        self._log_summary_written = True

    def _timing_reset_visual_execution(self):
        """
        Clears visual execution timestamps.
        """
        self.simulator_visual_started_at = None
        self.simulator_all_removed_at = None

    def _timing_note_visual_start(self):
        """
        Records the first visual execution timestamp.
        """
        if self.simulator_visual_started_at is None:
            self.simulator_visual_started_at = time.monotonic()

    def _timing_note_all_removed(self):
        """
        Records when the last excluded module is removed.
        """
        if self.simulator_all_removed_at is None:
            self.simulator_all_removed_at = time.monotonic()

    def simulator_visual_elapsed_seconds(self):
        """
        Calculates elapsed visual execution time.
        """
        if (
            self.simulator_visual_started_at is None
            or self.simulator_all_removed_at is None
        ):
            return None
        
        return abs(
            self.simulator_all_removed_at - self.simulator_visual_started_at
        )

    def simulator_result(self):
        """
        Collects the current simulation result.
        """
        if (not self.simulator_finished or self.simulator_error_msg
                or self.simulator_grid.get_excluded_positions()):
            return {'success': False}
        
        simulated_step_seconds = getattr(self, 'simulator_simulated_step_seconds', None)
        elapsed = (self.simulator_visual_elapsed_seconds()
                   if simulated_step_seconds is None
                   else self.simulator_step_count * simulated_step_seconds)
        
        if elapsed is None:
            return {'success': False}
        
        result = {
            'success': True,
            'excluded_total': self.simulator_initial_excluded,
            'excluded_removed': self.simulator_removed_module,
            'steps': self.simulator_step_count,
            'elapsed_seconds': getattr(self, 'simulator_preparation_seconds', 0.0) + elapsed,
        }
        
        if hasattr(self, 'simulator_wall_seconds'):
            result['wall_seconds'] = self.simulator_wall_seconds
        
        if hasattr(self, 'PASschedule'):
            result['schedule'] = [PASentry_payload(entry) for entry in self.PASschedule]
        
        return result

    def simulator_run(self, step_delay=0.2, before_step=None, after_step=None):
        """
        Runs steps until the simulator finishes.
        """
        import math

        if not math.isfinite(step_delay) or step_delay < 0:
            raise ValueError('step_delay must be finite and nonnegative')
        
        mode = 'PAS' if hasattr(self, 'PASschedule') else 'SAS'
        
        self._progress(f'[{mode}] execution started')
        
        try:
            while not self.simulator_finished:
                if before_step is not None:
                    before_step()
                self.simulator_step()
                if after_step is not None:
                    after_step()
                if (step_delay > 0 and not self.simulator_finished
                        and self.simulator_all_removed_at is None):
                    time.sleep(step_delay)
            return self.simulator_result()
        finally:
            self._log_close_stream()

    def _log_open_stream(self, log_path):
        """
        Opens a JSONL trace output stream.
        """
        self._log_output_path = log_path
        self._log_stream = None
        
        if log_path:
            log_parent = os.path.dirname(os.path.abspath(log_path))
            if log_parent:
                os.makedirs(log_parent, exist_ok=True)
            self._log_stream = open(log_path, 'w', encoding='utf-8')

    def _log_write_stream(self, log_record, log_encoder=repr):
        """
        Writes one JSONL record to the trace.
        """
        if self._log_stream is None or self._log_stream.closed:
            return
        
        self._log_stream.write(
            json.dumps(log_record, ensure_ascii=False, default=log_encoder) + '\n'
        )
        self._log_stream.flush()

    def _log_close_stream(self):
        """
        Closes the trace output stream.
        """
        if self._log_stream is not None and not self._log_stream.closed:
            self._log_stream.flush()
            self._log_stream.close()


class Simulator(SimulatorLog):
    """
    Executes SAS active-module selection and movement.
    """

    def __init__(self, grid, leader_factory, active_factory, trace_path=None):
        """
        Initializes the SAS grid, leader, and run state.
        """
        self.simulator_grid = grid
        self.simulator_grid.simulator_assign_ids_by_position()
        self.simulator_grid.simulator_compute_fixed_sink()
        self.simulator_leader = leader_factory(grid)
        self.simulator_active_factory = active_factory
        self.simulator_active = None
        self.simulator_active_pos = None
        self.simulator_active_id = None
        self.simulator_working_z = None
        self.simulator_step_count = 0
        self.simulator_initial_excluded = len(self.simulator_grid.get_excluded_positions())
        self.simulator_removed_module = 0
        self.simulator_finished = False
        self.simulator_error_msg = None
        self._timing_reset_visual_execution()
        self._visual_last_step_info = None
        self._log_trace_path = trace_path or 'sas_trace.jsonl'
        self._log_last_error_signature = None
        self._log_open_stream(self._log_trace_path)

    def _log_to_jsonable(self, value):
        """
        Converts values to JSON-compatible structures.
        """
        if isinstance(value, dict):
            return {
                str(key): self._log_to_jsonable(item)
                for key, item in value.items()
            }
        
        if isinstance(value, (list, tuple)):
            return [self._log_to_jsonable(item) for item in value]
        
        if isinstance(value, set):
            return [self._log_to_jsonable(item) for item in sorted(value)]
        
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        
        return repr(value)

    def _log_write_record(self, record):
        """
        Writes a SAS trace record.
        """
        self._log_write_stream(record, self._log_to_jsonable)

    def _log_error(self, reason, position=None):
        """
        Records a SAS execution error.
        """
        if position is None:
            position = self.simulator_active_pos

        record = {
            'step': self.simulator_step_count,
            'result': 'error',
            'active_id': self.simulator_active_id,
            'working_z': self.simulator_working_z,
            'position': position,
            'reason': str(reason),
        }
        signature = (
            record['step'],
            record['active_id'],
            record['working_z'],
            tuple(position) if position is not None else None,
            record['reason'],
        )

        if signature == self._log_last_error_signature:
            return
        
        self._log_last_error_signature = signature
        self._log_write_record(record)

    def simulator_step(self):
        """
        Advances one SAS simulation step.
        """
        self._timing_note_visual_start()

        try:
            return self._simulator_step_impl()
        except Exception as exc:
            self.simulator_error_msg = str(exc)
            self._log_error(repr(exc))
            self._log_close_stream()
            raise

    def _simulator_step_impl(self):
        """
        Selects, moves, or removes an active SAS module.
        """
        if self.simulator_finished:
            return ('finished', None)

        selected_pos = None
        
        if self.simulator_active is None:
            if not self.simulator_grid.get_excluded_positions():
                self._timing_note_all_removed()
                self.simulator_working_z = None
                self.simulator_finished = True
                self._visual_last_step_info = None
                self._log_close_stream()
                return ('finished', None)
            selected_pos = self.simulator_leader.select_next_module()
            if selected_pos is None:
                self.simulator_working_z = None
                self.simulator_finished = True
                self.simulator_error_msg = 'Leader could not find a candidate module'
                self._visual_last_step_info = None
                self._log_error(self.simulator_error_msg, position=None)
                self._log_close_stream()
                return ('stuck', None)
            self.simulator_active_pos = selected_pos
            self.simulator_active_id = self.simulator_grid.module[selected_pos].id
            self.simulator_working_z = selected_pos[2]
            self.simulator_grid.module[selected_pos].dfs_marks.clear()
            active_env = SimulatorActiveEnvironment(
                self.simulator_grid,
                lambda: self.simulator_active_pos,
                self.simulator_active_id,
            )
            self.simulator_active = self.simulator_active_factory(active_env)
            self._progress(f'[SAS t={self.simulator_step_count + 1}] removing {self.simulator_active_id}')

        active_id = self.simulator_active_id
        old_pos = self.simulator_active_pos
        direction = self.simulator_active.next_direction()
        legal_dirs = list(self.simulator_active._log_legal_dirs)

        if direction is None:
            self.simulator_finished = True
            reason = self.simulator_active.dead_reason
            self.simulator_error_msg = f'Active module at {old_pos} cannot proceed (STOP)'
            if reason:
                self.simulator_error_msg += f': {reason}'
            self._visual_last_step_info = {
                'direction': None,
                'legal_dirs': legal_dirs,
                'markers_before_move': [],
                'markers_after_move': [],
            }
            self._log_error(self.simulator_error_msg, position=old_pos)
            self._log_close_stream()
            return ('stuck', None)

        markers_before_move = _markers_with_active_id(
            self.simulator_active._log_markers_before_move, active_id
        )
        new_pos = self.simulator_grid.simulator_move_module(old_pos, direction)
        self.simulator_step_count += 1
        self.simulator_active_pos = new_pos

        self.simulator_active.after_move()
        
        markers_after_move = _markers_with_active_id(
            self.simulator_active._log_markers_after_move, active_id
        )
        result = 'removed' if new_pos in self.simulator_grid.sinks else 'moving'
        
        self._log_write_record({
            'step': self.simulator_step_count,
            'active_id': active_id,
            'legal_dirs': legal_dirs,
            'markers_before_move': markers_before_move,
            'chosen_dir': direction,
            'markers_after_move': markers_after_move,
            'result': result,
        })

        self._visual_last_step_info = {
            'direction': direction,
            'movements': [{'from': old_pos, 'to': new_pos}],
            'legal_dirs': legal_dirs,
            'markers_before_move': markers_before_move,
            'markers_after_move': markers_after_move,
        }

        if result == 'removed':
            self.simulator_grid.simulator_remove_module(new_pos)
            for module in self.simulator_grid.module.values():
                module.dfs_marks.pop(active_id, None)
            self.simulator_active = None
            self.simulator_active_pos = None
            self.simulator_active_id = None
            self.simulator_working_z = None
            self.simulator_removed_module += 1
            self._progress(
                f'[SAS t={self.simulator_step_count}] removed {active_id} '
                f'({self.simulator_removed_module}/{self.simulator_initial_excluded})'
            )
            if not self.simulator_grid.get_excluded_positions():
                self._timing_note_all_removed()
                self.simulator_finished = True
                self._log_close_stream()
            return ('arrive', None)

        if selected_pos is not None:
            return ('select_move', None)
        
        return ('move', None)


class PASRejectedError(RuntimeError):
    """
    Signals a rejected PAS move or schedule.
    """


def PASclone_initial_grid(PASsource_grid):
    """
    Clones grid geometry and module identities for PAS.
    """
    PASclone = Grid(
        PASsource_grid.width,
        PASsource_grid.height,
        PASsource_grid.depth,
        sinks=PASsource_grid.sinks,
    )

    for PASposition, PASmodule in PASsource_grid.module.items():
        PASclone.module[PASposition] = Module(PASmodule.type, PASmodule.id)

    PASclone._next_id = PASsource_grid._next_id

    return PASclone


@dataclass(frozen=True)
class PASSASRecord:
    """
    Stores an SAS module ID and movement duration.
    """
    PASmodule_id: str
    PASduration: int


@dataclass(frozen=True)
class PASScheduleEntry:
    """
    Stores PAS activation and arrival times.
    """
    PASmodule_id: str
    PASduration: int
    PASactivation_time: int
    PASarrival_time: int


@dataclass
class PASActiveState:
    """
    Holds an active PAS module's current state.
    """
    PASmodule_id: str
    PASposition: tuple
    PASalgorithm: object = None
    PASenvironment: object = None


@dataclass(frozen=True)
class PASSimulationResult:
    """
    Stores PAS acceptance and arrival records.
    """
    PASaccepted: bool
    PASarrival_times: dict
    PASreason: str = None


class PASActiveEnvironment:
    """
    Exposes static-only movement checks for PAS active modules.
    """
    def __init__(self, PASgrid, PASactive_pos, PASactive_id, PASstatic_ids):
        """
        Initializes PAS static-contact access.
        """
        self.PASgrid = PASgrid
        self.PASactive_pos = PASactive_pos
        self.PASactive_id = PASactive_id
        self.PASstatic_ids = PASstatic_ids
        self.active_id = PASactive_id

    def PASposition(self):
        """
        Returns the current PAS active position.
        """
        PASposition = self.PASactive_pos

        if PASposition is None:
            raise RuntimeError('PAS active position is not available')
        
        return PASposition

    def PASstatic_module_at(self, PASposition):
        """
        Looks up a static module at a coordinate.
        """
        PASmodule = self.PASgrid.module.get(PASposition)
        
        if PASmodule is None or PASmodule.id not in self.PASstatic_ids:
            return None
        
        return PASmodule

    def PASis_static_module_dir(self, PASposition, PASdirection):
        """
        Checks whether an adjacent module is static.
        """
        return self.PASstatic_module_at(self.PASgrid._neighbor(PASposition, PASdirection)) is not None

    def contact_hosts(self):
        """
        Finds adjacent static contact hosts.
        """
        PAShosts = []
        PASposition = self.PASposition()
        
        for PASdirection in ('D', 'U', 'F', 'B', 'L', 'R'):
            PASmodule = self.PASstatic_module_at(
                self.PASgrid._neighbor(PASposition, PASdirection)
            )
            if PASmodule is not None:
                PAShosts.append(
                    (PASdirection, PASmodule.tell_id(), OPPOSITE[PASdirection])
                )
        
        return PAShosts

    def dfs_entry_candidates_at(self, PASdirection):
        """
        Reads PAS Trémaux mark candidates.
        """
        PASrecords = self.PAScontact_mark_records()
        
        if not PASrecords:
            return []

        PASvalues = []
        PAScontact_records = []
        
        for PASmodule, PASface, PAShost_dir, PAShost_id in PASrecords:
            PASactive_marks = PASmodule.dfs_marks.get(self.PASactive_id, {})
            PASface_marks = PASactive_marks.get(PASface, {})
            PASmark = PASface_marks.get(PASdirection, 0)
            PASvalues.append(PASmark)
            PAScontact_records.append({
                'host_dir': PAShost_dir,
                'host_id': PAShost_id,
                'host_face': PASface,
                'mark': PASmark,
            })

        PASconsistent = len(set(PASvalues)) <= 1
        
        return [{
            'dir': PASdirection,
            'mark': PASvalues[0] if PASconsistent else None,
            'mark_consistent': PASconsistent,
            'replica_values': list(PASvalues),
            'contact_records': PAScontact_records,
        }]

    def is_legal_move_dir(self, PASdirection, require_contact=True):
        """
        Validates a PAS move against static geometry.
        """
        PASposition = self.PASposition()
        
        if PASdirection not in SLIDE_DIRS:
            return False

        PAStarget = self.PASgrid._neighbor(PASposition, PASdirection)

        if PAStarget[2] < 0 or self.PASstatic_module_at(PAStarget) is not None:
            return False

        PASparts = self.PASgrid._axis_component_dirs(PASdirection)

        if len(PASparts) == 2:
            PASempty_sides = [
                PASside
                for PASside in PASparts
                if (
                    (PASneighbor := self.PASgrid._neighbor(PASposition, PASside))[2] >= 0
                    and self.PASstatic_module_at(PASneighbor) is None
                )
            ]
            PAScarriers = [
                PASside
                for PASside in PASparts
                if self.PASis_static_module_dir(PASposition, PASside)
            ]
            if len(PASempty_sides) != 1 or len(PAScarriers) != 1:
                return False
        elif len(PASparts) != 1:
            return False

        if require_contact and not self.PASsupport_witnesses(
            PASposition,
            PASdirection,
        ):
            return False
        
        return True

    def dfs_entry_mark_inc(self, PASdirection):
        """
        Increments replicated PAS Trémaux marks.
        """
        PAScandidates = self.dfs_entry_candidates_at(PASdirection)
        
        if not PAScandidates:
            return None

        PAScandidate = PAScandidates[0]
        
        if not PAScandidate.get('mark_consistent', True):
            raise RuntimeError(
                f'PAS_MARK_INCONSISTENT active={self.PASactive_id} '
                f'dir={PASdirection} '
                f'values={PAScandidate.get("replica_values")}'
            )

        PASold = PAScandidate.get('mark', 0)
        PASnew = min(2, PASold + 1)
        PASupdated = []

        for PASmodule, PASface, PAShost_dir, PAShost_id in self.PAScontact_mark_records():
            PASby_active = PASmodule.dfs_marks.setdefault(self.PASactive_id, {})
            PASby_face = PASby_active.setdefault(PASface, {})
            PASprevious = PASby_face.get(PASdirection, 0)
            PASby_face[PASdirection] = PASnew
            PASupdated.append({
                'host_dir': PAShost_dir,
                'host_id': PAShost_id,
                'host_face': PASface,
                'old': PASprevious,
                'new': PASnew,
            })

        return {
            'dir': PASdirection,
            'old': PASold,
            'new': PASnew,
            'updated': PASupdated,
        }

    def PAScontact_mark_records(self):
        """
        Collects static contact marker hosts.
        """
        PASrecords = []
        PASposition = self.PASposition()
        
        for PAShost_dir, PAShost_id, PAShost_face in self.contact_hosts():
            PASmodule = self.PASstatic_module_at(
                self.PASgrid._neighbor(PASposition, PAShost_dir)
            )
            if PASmodule is not None:
                PASrecords.append(
                    (PASmodule, PAShost_face, PAShost_dir, PAShost_id)
                )
        
        return PASrecords

    def PASsupport_witnesses(self, PASposition, PASdirection):
        """
        Finds static modules supporting a PAS slide.
        """
        PASparts = self.PASgrid._axis_component_dirs(PASdirection)
        
        if len(PASparts) == 2:
            return [
                PASside
                for PASside in PASparts
                if self.PASis_static_module_dir(PASposition, PASside)
            ]
        
        if len(PASparts) != 1:
            return []

        PASwitnesses = []
        PASmove_vector = DIRECTIONS[PASdirection]
        
        for PAShost_direction in ADJACENT_DIRS:
            if PAShost_direction in (
                PASdirection,
                OPPOSITE[PASdirection],
            ):
                continue
            if not self.PASis_static_module_dir(PASposition, PAShost_direction):
                continue
            PAShost_vector = DIRECTIONS[PAShost_direction]
            PASafter_vector = (
                PAShost_vector[0] + PASmove_vector[0],
                PAShost_vector[1] + PASmove_vector[1],
                PAShost_vector[2] + PASmove_vector[2],
            )
            PASafter_direction = None
            for PASname, PASvector in DIRECTIONS.items():
                if PASvector == PASafter_vector:
                    PASafter_direction = PASname
                    break
            if (
                PASafter_direction is not None
                and self.PASis_static_module_dir(PASposition, PASafter_direction)
            ):
                PASwitnesses.append(PAShost_direction)
        
        return PASwitnesses


class PASSimulator(SimulatorLog):
    """
    Executes scheduled concurrent PAS movements.
    """
    def __init__(
        self,
        PASgrid,
        PASactive_factory,
        PASschedule,
        PAStrace_path=None,
        PAScandidate_mode=False,
        PASvalidate_offline=True,
    ):
        """
        Initializes the PAS schedule and active-module state.
        """
        self.PAScandidate_mode = PAScandidate_mode
        self.PASvalidate_offline = PASvalidate_offline
        self.simulator_grid = PASgrid
        self.simulator_grid.simulator_assign_ids_by_position()
        self.simulator_grid.simulator_compute_fixed_sink()
        self.PASactive_factory = PASactive_factory
        self.PASschedule = tuple(PASschedule)
        self.PASschedule_by_id = {
            PASentry.PASmodule_id: PASentry
            for PASentry in self.PASschedule
        }
        self.PASactive_states = {}
        self.PASarrival_times = {}
        self.PASstatic_ids = {
            PASmodule.id
            for PASmodule in self.simulator_grid.module.values()
        }
        self.PAScurrent_time = min(
            (PASentry.PASactivation_time for PASentry in self.PASschedule),
            default=0,
        )
        self.PASrejection_reason = None
        self.PASactive_positions = set()
        self.PASactive_ids = set()
        self.simulator_active = None
        self.simulator_active_pos = None
        self.simulator_active_id = None
        self.simulator_working_z = None
        self.simulator_step_count = self.PAScurrent_time - 1
        self.simulator_initial_excluded = len(self.simulator_grid.get_excluded_positions())
        self.simulator_removed_module = 0
        self.simulator_finished = not self.PASschedule
        self.simulator_error_msg = None
        self._timing_reset_visual_execution()
        self._visual_last_step_info = None
    
        self._log_open_stream(PAStrace_path)

        if PAStrace_path:
            self.PAS_log_write({'event': 'schedule', 'schedule': [PASentry_payload(e) for e in self.PASschedule]})

    def PAS_log_write(self, PASrecord):
        """
        Writes a PAS trace record.
        """
        self._log_write_stream(PASrecord)

    def PAS_log_error(self, PASreason):
        """
        Records a PAS rejection reason.
        """
        self.PAS_log_write({
            'step': self.PAScurrent_time,
            'result': 'rejected',
            'reason': str(PASreason),
        })

    def PASdispose_candidate(self):
        """
        Releases an offline candidate's temporary state.
        """
        self._log_close_stream()
        self.PASactive_states.clear()
        self.PASactive_positions.clear()
        self.PASactive_ids.clear()
        self.PASstatic_ids.clear()
        self.PASschedule_by_id.clear()
        self.simulator_grid.module.clear()

    def PASposition_for_id(self, PASmodule_id):
        """
        Finds the position of a given PAS module.
        """
        for PASposition, PASmodule in self.simulator_grid.module.items():
            if PASmodule.id == PASmodule_id:
                return PASposition
        
        return None

    def PASactivate_current_modules(self):
        """
        Activates modules scheduled for the current step.
        """
        PASactivating = [
            PASentry.PASmodule_id
            for PASentry in self.PASschedule
            if PASentry.PASactivation_time == self.PAScurrent_time
        ]

        if not PASactivating:
            return []
        
        for PASmodule_id in PASactivating:
            if PASmodule_id not in self.PASstatic_ids:
                raise PASRejectedError(
                    f'PAS module {PASmodule_id} cannot be activated twice'
                )
            self.PASstatic_ids.remove(PASmodule_id)
        
        for PASmodule_id in PASactivating:
            PASposition = self.PASposition_for_id(PASmodule_id)
            if PASposition is None:
                raise PASRejectedError(f'PAS module {PASmodule_id} is absent at activation')
            self.simulator_grid.module[PASposition].dfs_marks.clear()
        
        if self.PASvalidate_offline and not self.PASremaining_static_connected():
            raise PASRejectedError(
                'PAS remaining static configuration lost connectivity at '
                f't={self.PAScurrent_time}; activating={PASactivating}'
            )

        for PASmodule_id in PASactivating:
            PASposition = self.PASposition_for_id(PASmodule_id)
            if PASposition is None:
                raise PASRejectedError(
                    f'PAS module {PASmodule_id} is absent at activation'
                )
            PASenvironment = PASActiveEnvironment(
                self.simulator_grid,
                PASposition,
                PASmodule_id,
                self.PASstatic_ids,
            )
            PASstate = PASActiveState(
                PASmodule_id,
                PASposition,
                PASenvironment=PASenvironment,
            )
            PASstate.PASalgorithm = self.PASactive_factory(PASenvironment)
            self.PASactive_states[PASmodule_id] = PASstate

        self.PASrefresh_active_view()

        if PASactivating:
            self._progress(
                f'[PAS t={self.PAScurrent_time}] activated {", ".join(PASactivating)}; '
                f'removing {", ".join(self.PASactive_states)}'
            )

        return PASactivating

    def PASremaining_static_connected(self):
        """
        Checks static-module face connectivity.
        """
        PASstatic_positions = {
            PASposition
            for PASposition, PASmodule in self.simulator_grid.module.items()
            if PASmodule.id in self.PASstatic_ids
        }

        if not PASstatic_positions:
            return True

        PASincluded = {
            PASposition
            for PASposition in PASstatic_positions
            if self.simulator_grid.module[PASposition].type
            == self.simulator_grid.INCLUDED
        }

        if not PASincluded:
            return False
        
        PASstart = min(PASstatic_positions)
        PASvisited = {PASstart}
        PASqueue = deque([PASstart])

        while PASqueue:
            PASposition = PASqueue.popleft()
            for PASdirection in ADJACENT_DIRS:
                PASneighbor = self.simulator_grid._neighbor(
                    PASposition,
                    PASdirection,
                )
                if (
                    PASneighbor in PASstatic_positions
                    and PASneighbor not in PASvisited
                ):
                    PASvisited.add(PASneighbor)
                    PASqueue.append(PASneighbor)

        return PASvisited == PASstatic_positions

    def PASmovement_space(self, PASposition, PASdirection):
        """
        Computes the cells reserved by a PAS move.
        """
        PASgrid = self.simulator_grid
        PAStarget = PASgrid._neighbor(PASposition, PASdirection)
        PASspace = {PASposition, PAStarget}
        PASparts = PASgrid._axis_component_dirs(PASdirection)

        def PASstatic_at(PAScell):
            """
            Checks static occupancy of a coordinate.
            """
            PASmodule = PASgrid.module.get(PAScell)
            
            return PASmodule is not None and PASmodule.id in self.PASstatic_ids

        if len(PASparts) == 2:
            PAScarriers = [
                PASgrid._neighbor(PASposition, PASside)
                for PASside in PASparts
                if PASstatic_at(PASgrid._neighbor(PASposition, PASside))
            ]
            PAStransits = [
                PASgrid._neighbor(PASposition, PASside)
                for PASside in PASparts
                if not PASstatic_at(PASgrid._neighbor(PASposition, PASside))
            ]
            if len(PAScarriers) != 1 or len(PAStransits) != 1:
                raise PASRejectedError(
                    f'PAS diagonal move has invalid static carrier/transit: '
                    f'pos={PASposition}, dir={PASdirection}'
                )
            PASspace.update(PAScarriers)
            PASspace.update(PAStransits)
        elif len(PASparts) == 1:
            PASmove = DIRECTIONS[PASdirection]
            for PASside in ADJACENT_DIRS:
                PASdelta = DIRECTIONS[PASside]
                if sum(a * b for a, b in zip(PASmove, PASdelta)) != 0:
                    continue
                PASbefore = PASgrid._neighbor(PASposition, PASside)
                PASafter = PASgrid._neighbor(PAStarget, PASside)
                if PASstatic_at(PASbefore) and PASstatic_at(PASafter):
                    PASspace.update((PASbefore, PASafter))
                    break
            else:
                raise PASRejectedError(
                    f'PAS axis move has no static carrier pair: '
                    f'pos={PASposition}, dir={PASdirection}'
                )
        else:
            raise PASRejectedError(f'PAS direction is not a one-step slide: {PASdirection}')
        
        return PASspace

    def PASremove_sink_modules(self):
        """
        Removes all active modules at sinks.
        """
        PASremoving = [
            (PASmodule_id, PASstate.PASposition)
            for PASmodule_id, PASstate in self.PASactive_states.items()
            if PASstate.PASposition in self.simulator_grid.sinks
        ]

        if self.PASvalidate_offline:
            for PASmodule_id, PASposition in PASremoving:
                PASarrival_time = self.PAScurrent_time
                PASexpected = self.PASschedule_by_id[PASmodule_id].PASarrival_time
                if self.PAScandidate_mode and PASmodule_id == self.PASschedule[-1].PASmodule_id:
                    if PASarrival_time > PASexpected:
                        raise PASRejectedError(
                            f'PAS candidate {PASmodule_id} arrived at '
                            f'{PASarrival_time}, deadline {PASexpected}'
                        )
                    if (
                        len(self.PASschedule) > 1
                        and PASarrival_time <= self.PASschedule[-2].PASarrival_time
                    ):
                        raise PASRejectedError(
                            f'PAS candidate {PASmodule_id} violated SAS sink-arrival order: '
                            f'{PASarrival_time} <= {self.PASschedule[-2].PASarrival_time}'
                        )
                elif PASarrival_time != PASexpected:
                    raise PASRejectedError(
                        f'PAS active {PASmodule_id} arrived at '
                        f'{PASarrival_time}, expected {PASexpected}'
                    )

        for PASmodule_id, PASposition in PASremoving:
            self.simulator_grid.simulator_remove_module(PASposition)
            del self.PASactive_states[PASmodule_id]
            self.PASarrival_times[PASmodule_id] = self.PAScurrent_time
            self.simulator_removed_module += 1
            # F9/PAS-12: 해당 Active ID의 기록만 잔존 Static Module에서 삭제.
            for PASmodule in self.simulator_grid.module.values():
                if PASmodule.id in self.PASstatic_ids:
                    PASmodule.dfs_marks.pop(PASmodule_id, None)

        return [PASmodule_id for PASmodule_id, _ in PASremoving]

    def PAScommit_moves(self, PASplanned):
        """
        Applies all planned PAS moves simultaneously.
        """
        PASgrid = self.simulator_grid
        PASmoving = {
            PASmove['from']: PASgrid.module[PASmove['from']]
            for PASmove in PASplanned
        }

        for PASold_pos in PASmoving:
            del PASgrid.module[PASold_pos]

        for PASmove in PASplanned:
            PASnew_pos = PASmove['to']
            if self.PASvalidate_offline and PASnew_pos in PASgrid.module:
                raise PASRejectedError(f'PAS batch target is occupied: {PASnew_pos}')
            PASgrid.module[PASnew_pos] = PASmoving[PASmove['from']]
            PASstate = self.PASactive_states[PASmove['active_id']]
            PASstate.PASposition = PASnew_pos
            PASstate.PASenvironment.PASactive_pos = PASnew_pos

    def PASrefresh_active_view(self):
        """
        Refreshes active positions and IDs for display.
        """
        self.PASactive_positions = {
            PASstate.PASposition
            for PASstate in self.PASactive_states.values()
        }
        self.PASactive_ids = set(self.PASactive_states)

    def simulator_step(self):
        """
        Advances one PAS step with error handling.
        """
        self._timing_note_visual_start()

        if self.simulator_finished:
            return ('finished', None)
        
        try:
            return self.PASstep_impl()
        except Exception as PASexc:
            self.PASrejection_reason = str(PASexc)
            self.simulator_error_msg = str(PASexc)
            self.simulator_finished = True
            self.PAS_log_error(repr(PASexc))
            self._log_close_stream()
            return ('stuck', None)

    def PASstep_impl(self):
        """
        One PAS step. Executes activation, concurrent moves, and sink removal.
        """
        if self.PASvalidate_offline:
            for PASentry in self.PASschedule:
                if (
                    PASentry.PASarrival_time < self.PAScurrent_time
                    and PASentry.PASmodule_id not in self.PASarrival_times
                ):
                    raise PASRejectedError(
                        f'PAS active {PASentry.PASmodule_id} did not arrive by '
                        f'expected time {PASentry.PASarrival_time}'
                    )

        PASactivating = self.PASactivate_current_modules()
        PASplanned = []
        PASmarker_before = []
        PASmarker_after = []

        for PASmodule_id, PASstate in tuple(self.PASactive_states.items()):
            PASold_pos = PASstate.PASposition
            PASalgorithm = PASstate.PASalgorithm
            PASdirection = PASalgorithm.next_direction()
            PASlegal_dirs = list(PASalgorithm._log_legal_dirs)
            if PASdirection is None:
                raise PASRejectedError(
                    f'PAS active {PASmodule_id} cannot proceed at '
                    f'{PASold_pos}: {PASalgorithm.dead_reason}'
                )
            PASmarker_before.extend(_markers_with_active_id(
                PASalgorithm._log_markers_before_move, PASmodule_id
            ))
            PASplanned.append({
                'active_id': PASmodule_id,
                'from': PASold_pos,
                'to': self.simulator_grid._neighbor(PASold_pos, PASdirection),
                'chosen_dir': PASdirection,
                'legal_dirs': PASlegal_dirs,
            })

        if self.PASvalidate_offline:
            PASoccupied_spaces = set()
            for PASmove in PASplanned:
                PASspace = self.PASmovement_space(PASmove['from'], PASmove['chosen_dir'])
                PASoverlap = PASspace & PASoccupied_spaces
                if PASoverlap:
                    raise PASRejectedError(
                        f'PAS same-step movement-space collision at '
                        f't={self.PAScurrent_time}, active={PASmove["active_id"]}, '
                        f'cells={sorted(PASoverlap)}'
                    )
                PASoccupied_spaces.update(PASspace)

        self.PAScommit_moves(PASplanned)

        for PASmove in PASplanned:
            PASmodule_id = PASmove['active_id']
            PASalgorithm = self.PASactive_states[PASmodule_id].PASalgorithm
            PASalgorithm.after_move()
            PASmarker_after.extend(_markers_with_active_id(
                PASalgorithm._log_markers_after_move, PASmodule_id
            ))
        
        PASarrivals = self.PASremove_sink_modules()
        PAStime = self.PAScurrent_time
        self.PAScurrent_time += 1
        self.simulator_step_count = PAStime
        self.PASrefresh_active_view()
        self.simulator_active = None
        self.simulator_active_id = None
        self.simulator_active_pos = None

        if len(self.PASactive_states) == 1:
            PASactive_id = next(iter(self.PASactive_states))
            self.simulator_active_id = PASactive_id
            self.simulator_active_pos = self.PASactive_states[PASactive_id].PASposition

        self.simulator_working_z = None
        self._visual_last_step_info = {
            'direction': ', '.join(
                f'{PASmove["active_id"]}:{PASmove["chosen_dir"]}'
                for PASmove in PASplanned
            ) or None,
            'legal_dirs': [],
            'movements': PASplanned,
            'markers_before_move': PASmarker_before,
            'markers_after_move': PASmarker_after,
        }

        for PASmove in PASplanned:
            PASmodule_id = PASmove['active_id']
            self.PAS_log_write({
                'step': PAStime,
                'active_id': PASmodule_id,
                'legal_dirs': PASmove['legal_dirs'],
                'markers_before_move': [m for m in PASmarker_before if m['active_id'] == PASmodule_id],
                'chosen_dir': PASmove['chosen_dir'],
                'markers_after_move': [m for m in PASmarker_after if m['active_id'] == PASmodule_id],
                'result': 'removed' if PASmodule_id in PASarrivals else 'moving',
            })

        if PASarrivals:
            self._progress(
                f'[PAS t={PAStime}] removed {", ".join(PASarrivals)} '
                f'({self.simulator_removed_module}/{self.simulator_initial_excluded}); '
                f'removing {", ".join(self.PASactive_states) or "none"}'
            )

        if self.PASfinished_now():
            self._timing_note_all_removed()
            self.simulator_finished = True
            self._log_close_stream()
            return ('finished', None)
        
        if PASarrivals:
            return ('arrive', None)
        
        return ('move', None)

    def PASfinished_now(self):
        """
        Checks whether all scheduled modules have arrived.
        """
        return len(self.PASarrival_times) == len(self.PASschedule)

    def PASrun_to_completion(self, PASmax_steps=1_000_000):
        """
        Runs a candidate to completion or a step limit.
        """
        PASiterations = 0

        while not self.simulator_finished:
            if PASiterations >= PASmax_steps:
                self.simulator_error_msg = (
                    f'PAS exceeded candidate limit of {PASmax_steps} global steps'
                )
                self.PASrejection_reason = self.simulator_error_msg
                self.simulator_finished = True
                break
            self.simulator_step()
            PASiterations += 1

        self._log_close_stream()

        return PASSimulationResult(
            PASaccepted=(
                self.simulator_error_msg is None
                and self.PASfinished_now()
            ),
            PASarrival_times=dict(self.PASarrival_times),
            PASreason=self.PASrejection_reason,
        )


class PASExecution:
    """
    Provides SAS baseline and PAS schedule execution services.
    """
    def __init__(
        self,
        PASgrid,
        PASsas_leader_factory,
        PASactive_factory,
        PASprogress_callback=None,
        PASmax_active_modules=None,
    ):
        """
        Initializes the PAS scheduling environment.
        """
        PASgrid.simulator_assign_ids_by_position()
        PASgrid.simulator_compute_fixed_sink()
        
        self.PASgrid = PASgrid
        self.PASinitial_grid = PASclone_initial_grid(PASgrid)
        self.PASsas_leader_factory = PASsas_leader_factory
        self.PASactive_factory = PASactive_factory
        self.PASprogress_callback = PASprogress_callback
        
        if PASmax_active_modules is None:
            self.PASmax_active_modules = None
        else:
            self.PASmax_active_modules = int(PASmax_active_modules)
            if self.PASmax_active_modules < 1:
                raise ValueError('PAS max active modules must be at least 1')
        
        self.PASsas_records = ()
        self.PASbaseline_completed_at = None
        self.PASpreparation_elapsed = None
        self.PASschedule = None
        self.PAScandidate_attempts = {}
        self.PASleader = PASLeaderAlgorithm(self)

    def PASreport_progress(self, PASmessage):
        """
        For PAS progress messages.
        """
        if self.PASprogress_callback is not None:
            self.PASprogress_callback(PASmessage)

    def PASactive_limit(self):
        """
        Returns the maximum concurrent active count.
        """
        return self.PASmax_active_modules

    def PASrun_sas_baseline(self):
        """
        Runs SAS to record removal order and durations
        """
        self.PASreport_progress('PAS: running SAS baseline...')
        
        PASbaseline_grid = PASclone_initial_grid(self.PASinitial_grid)
        PASsimulator = Simulator(
            PASbaseline_grid,
            self.PASsas_leader_factory,
            self.PASactive_factory,
            trace_path=os.devnull,
        )
        PASsimulator.simulator_progress_callback = lambda message: self.PASreport_progress(
            '[PAS baseline] ' + message
        )
        PASdurations = {}
        PASrecords = []
        PASmax_steps = int(os.environ.get('PAS_MAX_STEPS', '1000000'))
        
        try:
            while not PASsimulator.simulator_finished:
                if PASsimulator.simulator_step_count >= PASmax_steps:
                    raise RuntimeError(
                        f'PAS SAS baseline exceeded {PASmax_steps} steps'
                    )
                PASids_before = {
                    PASmodule.id
                    for PASmodule in PASsimulator.simulator_grid.module.values()
                }
                PASmodule_id = PASsimulator.simulator_active_id
                PASbefore = PASsimulator.simulator_step_count
                PASresult = PASsimulator.simulator_step()[0]
                PASafter = PASsimulator.simulator_step_count
                if PASmodule_id is None:
                    PASmodule_id = PASsimulator.simulator_active_id
                if PASmodule_id is None and PASresult == 'arrive':
                    PASids_after = {
                        PASmodule.id
                        for PASmodule in PASsimulator.simulator_grid.module.values()
                    }
                    PASremoved_ids = PASids_before - PASids_after
                    if len(PASremoved_ids) == 1:
                        PASmodule_id = list(PASremoved_ids)[0]
                if (PASmodule_id is not None and PASafter > PASbefore
                        and PASresult in ('select_move', 'move', 'arrive')):
                    PASdurations[PASmodule_id] = (
                        PASdurations.get(PASmodule_id, 0)
                        + PASafter - PASbefore
                    )
                if PASresult == 'arrive':
                    PASrecords.append(
                        PASSASRecord(
                            PASmodule_id,
                            PASdurations[PASmodule_id],
                        )
                    )
                    if len(PASrecords) % 10 == 0:
                        self.PASreport_progress(
                            f'PAS: SAS baseline removed {len(PASrecords)} modules'
                        )
                elif PASresult == 'stuck':
                    raise RuntimeError(
                        'PAS cannot schedule because SAS baseline failed: '
                        f'{PASsimulator.simulator_error_msg}'
                    )
        finally:
            PASsimulator._log_close_stream()

        self.PASsas_records = tuple(PASrecords)

        self.PASreport_progress(
            f'PAS: SAS baseline complete ({len(PASrecords)} modules)'
        )

        return self.PASsas_records

    def PASsimulate_candidate(self, PASschedule):
        """
        Simulates a PAS schedule candidate.
        """
        PAScandidate = PASSimulator(
            PASclone_initial_grid(self.PASinitial_grid),
            self.PASactive_factory,
            PASschedule,
            PAScandidate_mode=True,
        )

        try:
            return PAScandidate.PASrun_to_completion(
                int(os.environ.get('PAS_MAX_STEPS', '1000000'))
            )
        finally:
            PAScandidate.PASdispose_candidate()

    def PASbuild_schedule(self):
        """
        Constructs the PAS schedule through its leader.
        """
        self.PASschedule, PASattempt_counts = self.PASleader.PASleader_build()
        self.PAScandidate_attempts.update(PASattempt_counts)
        
        return self.PASschedule

    def PASnormalize_schedule(self, PASentries):
        """
        Normalizes PAS schedule time values.
        """
        return self.PASleader.PASleader_normalize(PASentries)

    def PASbuild_schedule_isolated(self, PASpattern_path):
        """
        Builds a PAS schedule with worker subprocesses.
        """
        PASstarted = time.monotonic()
        PASrecords, PASentries, PASbaseline_completed_at = _PASrun_schedule_workers(
            PASpattern_path,
            self.PASmax_active_modules,
        )
        self.PASsas_records = PASrecords
        self.PASbaseline_completed_at = PASbaseline_completed_at
        self.PASschedule = self.PASnormalize_schedule(PASentries)
        self.PASpreparation_elapsed = time.monotonic() - PASstarted
        
        return self.PASschedule

    def PASextend_schedule(self, PASrecords, PASexisting_entries=(), PASmodule_limit=None):
        """
        Extends an existing PAS schedule.
        """
        PASentries, PASattempt_counts = self.PASleader.PASleader_extend(
            PASrecords, PASexisting_entries, PASmodule_limit
        )
        self.PAScandidate_attempts.update(PASattempt_counts)
        
        return PASentries

    def PAScreate_simulator(self, PAStrace_path=None):
        """
        Creates a simulator for the computed PAS schedule.
        """
        if self.PASschedule is None:
            self.PASbuild_schedule()
        
        return self.PASleader.PASleader_execute(self.PASschedule, PAStrace_path)

    @staticmethod
    def PASmake_entry(PASmodule_id, PASduration, PASactivation, PASarrival):
        """
        Creates a PAS schedule entry.
        """
        return PASScheduleEntry(PASmodule_id, PASduration, PASactivation, PASarrival)

    @staticmethod
    def PAScandidate_limit():
        """
        Reads the PAS candidate attempt limit.
        """
        return int(os.environ.get('PAS_MAX_CANDIDATES', '1000000'))

    def PAScreate_execution(self, PASentries, PAStrace_path=None):
        """
        Creates final execution for an accepted schedule.
        """
        return PASSimulator(
            self.PASgrid, self.PASactive_factory, PASentries,
            PAStrace_path=PAStrace_path,
            PASvalidate_offline=False,
        )


class SimulationRun:
    """
    Enter point for coordinates preparation, execution, and reporting of one run.
    """
    def __init__(self, pattern, mode='SAS', trace_path=None, pas_max_active=None):
        """
        Stores simulation options.
        """
        self.pattern = pattern
        self.mode = mode.upper()
        self.trace_path = trace_path
        self.pas_max_active = pas_max_active
        self.instance = None

    def prepare(self):
        """
        Loads a pattern and prepares the SAS or PAS simulator.
        """
        from converter_3d import generator_build_grid_from_file
        from leader_3d import Leader
        from active_3d import ActiveModule

        if self.mode not in ('SAS', 'PAS'):
            raise ValueError('mode must be SAS or PAS')
        
        grid = generator_build_grid_from_file(self.pattern)

        print(f'Pattern loaded: {self.pattern}  [3D {self.mode} Mode]')
        print(f'Grid size: {grid.width} x {grid.height} x {grid.depth}')
        print(f'Included modules: {len(grid.get_included_positions())}')
        print(f'Excluded modules: {len(grid.get_excluded_positions())}')

        if self.mode == 'PAS':
            execution = PASExecution(
                grid, Leader, ActiveModule, PASprogress_callback=print,
                PASmax_active_modules=self.pas_max_active,
            )
            limit = 'unlimited' if self.pas_max_active is None else self.pas_max_active
            print(f'PAS max active modules: {limit}')
            execution.PASbuild_schedule_isolated(self.pattern)
            self.instance = execution.PAScreate_simulator(PAStrace_path=self.trace_path)
            self.instance.simulator_preparation_seconds = execution.PASpreparation_elapsed
            print('\nPAS schedule (SAS arrival order):')
            for entry in execution.PASschedule:
                print(f'  {entry.PASmodule_id}: Δ={entry.PASduration}, '
                      f's={entry.PASactivation_time}, a={entry.PASarrival_time}')
        else:
            self.instance = Simulator(grid, Leader, ActiveModule, trace_path=self.trace_path)
        
        self.instance.simulator_progress_callback = PASprint_progress
        
        return self.instance

    def report(self):
        """
        Displays and returns the simulation result.
        """
        result = self.instance.simulator_result() if self.instance is not None else {'success': False}
        
        if result['success']:
            self.instance.simulator_log_summary()
            print(f"\nSimulation finished: {result['steps']} steps, "
                  f"{result['excluded_removed']} modules removed, "
                  f"elapsed_seconds={result['elapsed_seconds']:.3f} s")
            if 'wall_seconds' in result:
                print(f"wall_seconds={result['wall_seconds']:.3f} s")
        else:
            print('\nSimulation failed')
        
        return result

    def run(self, step_delay=0.2):
        """
        Executes a simulation without visualization.
        """
        try:
            self.prepare().simulator_run(step_delay)
        except Exception:
            return {'success': False}
        
        return self.report()


def PASprint_progress(PASmessage):
    """
    Prints a PAS progress message.
    """
    print(PASmessage, flush=True)


def PASrecord_payload(PASrecord):
    """
    Serializes an SAS baseline record.
    """
    return {
        'PASmodule_id': PASrecord.PASmodule_id,
        'PASduration': PASrecord.PASduration,
    }


def PASentry_payload(PASentry):
    """
    Serializes a PAS schedule entry.
    """
    return {
        'PASmodule_id': PASentry.PASmodule_id,
        'PASduration': PASentry.PASduration,
        'PASactivation_time': PASentry.PASactivation_time,
        'PASarrival_time': PASentry.PASarrival_time,
    }


def PASwrite_json_atomic(PASoutput_path, PASpayload):
    """
    Saves a PAS JSON checkpoint.
    """
    PAStemporary_path = f'{PASoutput_path}.tmp-{os.getpid()}'

    try:
        with open(PAStemporary_path, 'w', encoding='utf-8') as PASoutput:
            json.dump(PASpayload, PASoutput, ensure_ascii=False)
        os.replace(PAStemporary_path, PASoutput_path)
    finally:
        if os.path.exists(PAStemporary_path):
            os.remove(PAStemporary_path)


def PASread_json(PASpath):
    """
    Reads a PAS JSON file.
    """
    with open(PASpath, encoding='utf-8') as PASfile:
        return json.load(PASfile)


def PASload_state(PASstate_path):
    """
    Restores PAS records and entries from a checkpoint.
    """
    PASstate = PASread_json(PASstate_path)
    PASrecords = []
    
    for PASitem in PASstate['PASrecords']:
        PASrecords.append(PASSASRecord(
            PASitem['PASmodule_id'], PASitem['PASduration'],
        ))

    PASentries = []

    for PASitem in PASstate['PASentries']:
        PASentries.append(PASScheduleEntry(
            PASitem['PASmodule_id'], PASitem['PASduration'],
            PASitem['PASactivation_time'], PASitem['PASarrival_time'],
        ))

    return tuple(PASrecords), tuple(PASentries), PASstate.get('PASpending')


def PASsave_state(PASstate_path, PASrecords, PASentries, PASpending=None):
    """
    Saves PAS records and pending scheduling state.
    """
    PASrecord_data = []
    
    for PASrecord in PASrecords:
        PASrecord_data.append(PASrecord_payload(PASrecord))
    
    PASentry_data = []
    
    for PASentry in PASentries:
        PASentry_data.append(PASentry_payload(PASentry))
    
    PASwrite_json_atomic(PASstate_path, {
        'PASrecords': PASrecord_data,
        'PASentries': PASentry_data,
        'PASpending': PASpending,
    })


def _PASworker_environment(PASpattern_path):
    """
    Builds a PAS execution environment from a pattern.
    """
    from active_3d import ActiveModule
    from converter_3d import generator_build_grid_from_file
    from leader_3d import Leader

    PASgrid = generator_build_grid_from_file(PASpattern_path)
    PASmax_active_raw = os.environ.get('PAS_MAX_ACTIVE_MODULES')
    PASmax_active_modules = (
        None if PASmax_active_raw in (None, '') else int(PASmax_active_raw)
    )

    return PASExecution(
        PASgrid,
        Leader,
        ActiveModule,
        PASprogress_callback=PASprint_progress,
        PASmax_active_modules=PASmax_active_modules,
    )


def PASwrite_baseline_state_file(PASpattern_path, PASoutput_path):
    """
    Computes and saves the SAS baseline checkpoint.
    """
    PASenvironment = _PASworker_environment(PASpattern_path)
    PASrecords = PASenvironment.PASleader.PASleader_baseline()
    
    PASsave_state(PASoutput_path, PASrecords, ())


def PASextend_schedule_state_file(PASpattern_path, PASstate_path, PASmodule_limit):
    """
    Extends the checkpoint by a module count.
    """
    PASrecords, PASentries, PASpending = PASload_state(PASstate_path)
    PASenvironment = _PASworker_environment(PASpattern_path)
    PAStarget_count = min(
        len(PASrecords),
        len(PASentries) + max(0, int(PASmodule_limit)),
    )

    while len(PASentries) < PAStarget_count:
        PAScompleted_before = len(PASentries)
        PASentries, PASpending, _PASattempts = (
            PASenvironment.PASleader.PASleader_attempt(
                PASrecords,
                PASentries,
                PASpending,
            )
        )
        PASsave_state(
            PASstate_path,
            PASrecords,
            PASentries,
            PASpending,
        )
        if len(PASentries) > PAScompleted_before:
            print(
                f'PAS: checkpoint saved ({len(PASentries)}/{len(PASrecords)})',
                flush=True,
            )


def PASattempt_schedule_state_file(PASpattern_path, PASstate_path):
    """
    Tests one PAS candidate and saves its state.
    """
    PASrecords, PASentries, PASpending = PASload_state(PASstate_path)
    
    if len(PASentries) >= len(PASrecords):
        return
    
    PASenvironment = _PASworker_environment(PASpattern_path)
    PASextended, PASnext_pending, _PASattempts = PASenvironment.PASleader.PASleader_attempt(
        PASrecords, PASentries, PASpending,
    )
    
    PASsave_state(PASstate_path, PASrecords, PASextended, PASnext_pending)
    
    if len(PASextended) > len(PASentries):
        print(
            f'PAS: checkpoint saved ({len(PASextended)}/{len(PASrecords)})',
            flush=True,
        )


def PASattempt_schedule_batch_state_file(
    PASpattern_path,
    PASstate_path,
    PASattempt_limit,
):
    """
    Tests a batch of candidates with checkpoints.
    """
    PASattempt_limit = max(1, int(PASattempt_limit))
    PASrecords, PASentries, PASpending = PASload_state(PASstate_path)
    
    if len(PASentries) >= len(PASrecords):
        return

    PASenvironment = _PASworker_environment(PASpattern_path)

    for _ in range(PASattempt_limit):
        if len(PASentries) >= len(PASrecords):
            break
        PAScompleted_before = len(PASentries)
        PASentries, PASpending, _PASattempts = (
            PASenvironment.PASleader.PASleader_attempt(
                PASrecords,
                PASentries,
                PASpending,
            )
        )
        PASsave_state(
            PASstate_path,
            PASrecords,
            PASentries,
            PASpending,
        )
        if len(PASentries) > PAScompleted_before:
            print(
                f'PAS: checkpoint saved ({len(PASentries)}/{len(PASrecords)})',
                flush=True,
            )


def PASwrite_schedule_file(PASpattern_path, PASoutput_path):
    """
    Calculate schedule and writes a normalized PAS schedule (JSON).
    """
    PASwrite_baseline_state_file(PASpattern_path, PASoutput_path)
    PASincremental_schedule_state_file(PASpattern_path, PASoutput_path)

    PASrecords, PASentries, _PASpending = PASload_state(PASoutput_path)
    PASenvironment = _PASworker_environment(PASpattern_path)
    PASschedule = PASenvironment.PASnormalize_schedule(PASentries)
    PASentry_data = []

    for PASentry in PASschedule:
        PASentry_data.append(PASentry_payload(PASentry))

    PASwrite_json_atomic(PASoutput_path, PASentry_data)


def _PASformat_worker_returncode(PASreturncode):
    """
    Formats a worker process exit code.
    """
    if os.name == 'nt':
        return f'{PASreturncode} (0x{PASreturncode & 0xFFFFFFFF:08X})'
    
    return str(PASreturncode)


def PASincremental_schedule_state_file(PASpattern_path, PASstate_path):
    """
    Extends PAS schedules with cached worker state.
    """
    PASrecords, PASentries, _ = PASload_state(PASstate_path)

    if len(PASentries) >= len(PASrecords):
        return
    
    PASenvironment = _PASworker_environment(PASpattern_path)
    PAScache = PASenvironment.PASleader.PASleader_prepare_engine(PASrecords, PASentries)
    PAScheckpoint_every = max(1, int(os.environ.get(
        'PAS_SCHEDULE_CHECKPOINT_MODULES', '50'
    )))
    PASaccepted_since_checkpoint = 0

    def PASon_accept(PASaccepted_entries, PASattempts):
        """
        Saves a checkpoint after an acceptance interval.
        """
        nonlocal PASaccepted_since_checkpoint
        
        PASaccepted_since_checkpoint += 1
        
        if PASaccepted_since_checkpoint >= PAScheckpoint_every:
            PASsave_state(PASstate_path, PASrecords, PASaccepted_entries)
            PASaccepted_since_checkpoint = 0

    PASentries, _PASattempt_counts = PASenvironment.PASleader.PASleader_extend(
        PASrecords, PASentries,
        PASengine=PAScache, PASon_accept=PASon_accept,
    )

    if tuple(PASentries) != PAScache.approved:
        raise RuntimeError('PAS leader and committed trajectory cache disagree')
    
    PASsave_state(PASstate_path, PASrecords, PASentries)
    PASprint_progress(
        '[PAS] incremental scheduling done: '
        + ', '.join(f'{k}={v}' for k, v in sorted(PAScache.stats.items()))
    )


def _PASrun_schedule_workers(PASpattern_path, PASmax_active_modules=None):
    """
    Runs isolated SAS baseline and PAS scheduling workers.
    """
    PASworker_path = os.path.abspath(__file__)
    PASworker_env = os.environ.copy()

    if PASmax_active_modules is None:
        PASworker_env.pop('PAS_MAX_ACTIVE_MODULES', None)
    else:
        PASworker_env['PAS_MAX_ACTIVE_MODULES'] = str(int(PASmax_active_modules))
    
    PASfd, PASstate_path = tempfile.mkstemp(
        prefix='pas_schedule_state_', suffix='.json',
    )

    os.close(PASfd)

    try:
        PASbase_command = [
            sys.executable, '-X', 'faulthandler', '-S', '-u', PASworker_path,
        ]
        PASabsolute_pattern = os.path.abspath(PASpattern_path)
        PASbaseline = subprocess.run(
            PASbase_command + ['--baseline-worker', PASabsolute_pattern, PASstate_path],
            check=False, env=PASworker_env,
        )
        if PASbaseline.returncode != 0:
            raise RuntimeError(
                'PAS baseline worker failed with exit code '
                + _PASformat_worker_returncode(PASbaseline.returncode)
            )
        PASbaseline_completed_at = time.time()
        PASprint_progress('[PAS] incremental scheduling started')

        PASretries = max(0, int(os.environ.get('PAS_SCHEDULE_WORKER_RETRIES', '5')))
        PASconsecutive_failures = 0
        while True:
            PASstate_before = PASread_json(PASstate_path)
            if len(PASstate_before['PASentries']) >= len(PASstate_before['PASrecords']):
                break
            PASworker = subprocess.run(
                PASbase_command + [
                    '--incremental-schedule-worker', PASabsolute_pattern, PASstate_path,
                ], check=False, env=PASworker_env,
            )
            PASstate_after = PASread_json(PASstate_path)
            if len(PASstate_after['PASentries']) >= len(PASstate_after['PASrecords']):
                if PASworker.returncode != 0:
                    raise RuntimeError('PAS worker failed after writing final schedule')
                break
            PASprogressed = len(PASstate_after['PASentries']) > len(PASstate_before['PASentries'])
            PASconsecutive_failures = 0 if PASprogressed else PASconsecutive_failures + 1
            PASprint_progress(
                'PAS: incremental worker stopped; recovery from last confirmed '
                f'checkpoint={len(PASstate_after["PASentries"])}/'
                f'{len(PASstate_after["PASrecords"])}; '
                f'exit_code={_PASformat_worker_returncode(PASworker.returncode)}'
            )
            if PASconsecutive_failures > PASretries:
                raise RuntimeError('PAS incremental worker repeatedly failed without progress')
        PASrecords, PASentries, _ = PASload_state(PASstate_path)
        PASprint_progress('[PAS] scheduling complete')
        return PASrecords, PASentries, PASbaseline_completed_at
    finally:
        try:
            os.remove(PASstate_path)
        except OSError:
            pass


def _PASworker_main():
    """
    Dispatches PAS worker commands.
    """
    if len(sys.argv) == 4 and sys.argv[1] == '--incremental-schedule-worker':
        PASincremental_schedule_state_file(sys.argv[2], sys.argv[3])
        return
    
    if len(sys.argv) == 4 and sys.argv[1] == '--baseline-worker':
        PASwrite_baseline_state_file(sys.argv[2], sys.argv[3])
        return
    
    if len(sys.argv) == 5 and sys.argv[1] == '--schedule-batch-worker':
        PASattempt_schedule_batch_state_file(
            sys.argv[2],
            sys.argv[3],
            int(sys.argv[4]),
        )
        return
    
    if len(sys.argv) == 4 and sys.argv[1] == '--schedule-attempt-worker':
        PASattempt_schedule_state_file(sys.argv[2], sys.argv[3])
        return
    
    if len(sys.argv) == 4 and sys.argv[1] == '--schedule-worker':
        PASwrite_schedule_file(sys.argv[2], sys.argv[3])
        return
    
    raise SystemExit(
        'usage: python -S simulator.py '
        '--baseline-worker <pattern.txt> <state.json> | '
        '--schedule-batch-worker <pattern.txt> <state.json> <attempts> | '
        '--schedule-attempt-worker <pattern.txt> <state.json>'
    )


if __name__ == '__main__':
    _PASworker_main()
