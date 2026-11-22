"""
Connects simulation steps with VPython rendering and capture.
"""

import time
from vpython import vector, rate
from visualizer_design import VisualizerDesign

from grid_3d import Grid, DIRECTIONS, ADJACENT_DIRS


class Visualizer(VisualizerDesign):
    """
    Controls VPython input, drawing, and frame capture.
    """
    VISUAL_START_DELAY = 3.0
    VISUAL_FINISH_DELAY = 3.0

    def __init__(
        self,
        simulator,
        step_delay=0.2,
        capture_prefix='sas_step',
        PAS_mode=False,
        capture_enabled=True,
        auto_start=False,
    ):
        """
        Initializes visualization state and controls.
        """
        self._visual_simulator = simulator
        self._visual_step_delay = step_delay
        self._visual_capture_prefix = capture_prefix
        self.PAS_mode = bool(PAS_mode)
        self._visual_capture_enabled = capture_enabled
        self._visual_auto_start = auto_start
        self._visual_paused = False
        self._visual_started = False
        self._visual_step_advance = False
        self._visual_show_ids = False
        self._visual_preview_included_only = False
        self._visual_capture_idx = 0
        self._visual_camera_view_idx = 0
        self._visual_module_boxes = {}
        self._visual_marker_faces = []
        self._visual_move_arrows = []
        self._visual_sink_boxes = {}
        self._visual_id_labels = {}
        self._visual_scene = None
        self._visual_ground_box = None
        self._visual_axis_objects = []
        self._visual_status_text = None
        self._visual_panel_text = None

    def _visual_world_bounds(self):
        """
        Calculates the visible simulation bounds.
        """
        simulator_grid = self._visual_simulator.simulator_grid
        positions = list(simulator_grid.module.keys()) + list(simulator_grid.sinks)
        
        if not positions:
            return (-1, 1, -1, 1, 0, 1)

        xs = [position[0] for position in positions]
        ys = [position[1] for position in positions]
        zs = [position[2] for position in positions]
        
        return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

    def _visual_marker_selections(self):
        """
        Collects marker updates for face highlighting.
        """
        selections = {}
        info = self._visual_simulator._visual_last_step_info or {}
        
        for key, phase in (('markers_before_move', 1), ('markers_after_move', 2)):
            for update in info.get(key, []):
                module_id, face = update.get('module_id'), update.get('face')
                if module_id is None or face not in ADJACENT_DIRS:
                    continue
                faces = selections.setdefault(module_id, {})
                faces[face] = faces.get(face, 0) | phase
        
        return selections

    def _visual_set_included_preview(self, enabled):
        """
        Toggles included-module preview visibility.
        """
        self._visual_preview_included_only = bool(enabled)
        self._visual_sync_modules()
        self._visual_sync_id_labels()

    def _visual_rotate_camera(self):
        """
        Updates the camera rotation.
        """
        self._visual_camera_view_idx = (
            self._visual_camera_view_idx + 1
        ) % 4
        visual_a = self.VISUAL_CAMERA_XY
        visual_z = self.VISUAL_CAMERA_Z
        visual_views = (
            vector(-visual_a, -visual_a, visual_z),
            vector(+visual_a, -visual_a, visual_z),
            vector(+visual_a, +visual_a, visual_z),
            vector(-visual_a, +visual_a, visual_z),
        )
        self._visual_scene.forward = visual_views[
            self._visual_camera_view_idx
        ]

    def _visual_on_key(self, event):
        """
        Handles visualization keyboard controls.
        """
        visual_key = event.key

        if visual_key in ('s', 'S'):
            if self._visual_preview_included_only:
                self._visual_set_included_preview(False)
            if not self._visual_started:
                self._visual_started = True
                self._visual_paused = False
                self._visual_sync_id_labels()
            else:
                self._visual_paused = not self._visual_paused
        elif visual_key in ('n', 'N') and self._visual_paused:
            if self._visual_preview_included_only:
                self._visual_set_included_preview(False)
            self._visual_step_advance = True
        elif visual_key in ('i', 'I'):
            self._visual_show_ids = not self._visual_show_ids
            self._visual_sync_id_labels()
        elif visual_key in ('c', 'C'):
            self._visual_rotate_camera()
        elif visual_key in ('p', 'P'):
            self._visual_set_included_preview(
                not self._visual_preview_included_only
            )

    def _visual_capture_frame(self):
        """
        Captures the current scene frame.
        """
        if not self._visual_capture_enabled:
            return
        
        self._visual_capture_idx += 1
        visual_filename = (
            f"{self._visual_capture_prefix}_{self._visual_capture_idx:04d}"
        )

        self._visual_scene.capture(visual_filename)

    def _visual_refresh(self):
        """
        Synchronizes the displayed scene with simulation state.
        """
        self._visual_sync_sinks()
        self._visual_sync_modules()
        self._visual_sync_id_labels()
        self._visual_update_panel()
        self._visual_capture_frame()

    def visual_run(self):
        """
        Runs the interactive visualization and simulation loop.
        """
        self._visual_setup_scene()
        self._visual_scene.bind('keydown', self._visual_on_key)
        self._visual_draw_ground()
        self._visual_sync_sinks()
        self._visual_draw_axes()
        self._visual_sync_modules()
        self._visual_sync_id_labels()
        self._visual_update_panel()

        self._visual_paused = not self._visual_auto_start
        self._visual_started = self._visual_auto_start
        self._visual_status_text.text = (
            '<b>Ready</b>'
        )

        while not self._visual_started:
            rate(30)

        self._visual_status_text.text = (
            f'<b>Starting...</b> '
            f'(Movement begins in about {self.VISUAL_START_DELAY:.0f} seconds)\n'
        )

        self._visual_refresh()

        visual_start_end = time.time() + self.VISUAL_START_DELAY
        while time.time() < visual_start_end:
            rate(30)
        self._visual_status_text.text = (
            '<b>Simulation Running</b>'
        )
        paused_seconds = 0.0

        def wait_for_step_permission():
            """
            Waits until the simulation may advance.
            """
            nonlocal paused_seconds

            if self._visual_paused and not self._visual_step_advance:
                paused_at = time.monotonic()
                try:
                    while self._visual_paused and not self._visual_step_advance:
                        rate(30)
                finally:
                    paused_seconds += time.monotonic() - paused_at
            
            self._visual_step_advance = False

        self._visual_simulator.simulator_run(
            self._visual_step_delay,
            before_step=wait_for_step_permission,
            after_step=self._visual_refresh,
        )

        execution_seconds = self._visual_simulator.simulator_visual_elapsed_seconds()
        
        if execution_seconds is not None:
            self._visual_simulator.simulator_wall_seconds = (
                getattr(self._visual_simulator, 'simulator_wall_preparation_seconds', 0.0)
                + max(0.0, execution_seconds - paused_seconds)
            )

        if self._visual_simulator.simulator_error_msg:
            visual_result_html = '<b>STOP — Simulation Terminated Due to an Error.</b>'
        else:
            visual_result_html = '<b>Perfect! Simulation Complete.</b>'
        
        self._visual_status_text.text = (
            f'{visual_result_html} '
            f'Post-processing begins in {self.VISUAL_FINISH_DELAY:.0f} seconds '
            + ('(Moving PNGs + Generating GIF)...\n' if self._visual_capture_enabled else '...\n')
        )
        visual_finish_end = time.time() + self.VISUAL_FINISH_DELAY
        
        while time.time() < visual_finish_end:
            rate(30)

        self._visual_status_text.text = (
            ('<b>Post-processing...</b> ' if self._visual_capture_enabled else '<b>Complete.</b> ')
            + 'You may close the browser window manually.\n'
        )