"""
Renders VPython scene elements and simulation status.
"""
from html import escape
from string import Template
from vpython import canvas, box, vector, wtext, label, distant_light, arrow
from grid_3d import Grid, DIRECTIONS, ADJACENT_DIRS
import ui_config as config
from ui_config import PALETTE

RENDER_COLORS = {name: vector(*rgb) for name, rgb in config.RENDER_RGB.items()}

class VisualizerDesign:
    """
    Provides scene construction and synchronization methods.
    """
    VISUAL_COLOR_INCLUDED = vector(*config.VISUAL_RGB['VISUAL_COLOR_INCLUDED'])
    VISUAL_COLOR_EXCLUDED = vector(*config.VISUAL_RGB['VISUAL_COLOR_EXCLUDED'])
    VISUAL_COLOR_ACTIVE = vector(*config.VISUAL_RGB['VISUAL_COLOR_ACTIVE'])
    VISUAL_COLOR_MOVE = vector(*config.VISUAL_RGB['VISUAL_COLOR_MOVE'])
    VISUAL_OPACITY_ACTIVE = config.VISUAL_OPACITY_ACTIVE
    VISUAL_OPACITY_SINK = config.VISUAL_OPACITY_SINK
    VISUAL_COLOR_MARKED = vector(*config.VISUAL_RGB['VISUAL_COLOR_MARKED'])
    VISUAL_COLOR_MARKED_BEFORE = vector(*config.VISUAL_RGB['VISUAL_COLOR_MARKED_BEFORE'])
    VISUAL_COLOR_GROUND = vector(*config.VISUAL_RGB['VISUAL_COLOR_GROUND'])
    VISUAL_COLOR_SINK = vector(*config.VISUAL_RGB['VISUAL_COLOR_SINK'])
    VISUAL_CUBE_EDGE = config.VISUAL_CUBE_EDGE
    VISUAL_OPACITY_FOCUS = config.VISUAL_OPACITY_FOCUS
    VISUAL_OPACITY_MARKED = config.VISUAL_OPACITY_MARKED
    VISUAL_OPACITY_DIM = config.VISUAL_OPACITY_DIM
    VISUAL_OPACITY_IDLE = config.VISUAL_OPACITY_IDLE
    VISUAL_CAMERA_XY = config.VISUAL_CAMERA_XY
    VISUAL_CAMERA_Z = config.VISUAL_CAMERA_Z
    VISUAL_UI_CSS = Template("""<style>
    body { --visual-area-height:78vh; margin:0; padding:1.5%; box-sizing:border-box; background:${background}; color:${ink};
           font:14px 'Segoe UI',Arial,sans-serif; }
    div:has(> .glowscript-canvas-wrapper):has(#modular-heading) {
        display:grid !important; grid-template-columns:minmax(0, 1fr) minmax(0, 26%);
        align-items:start;
        gap:0 1.5%; width:100%; margin:0 auto; float:none !important;
    }
    div:has(> #modular-heading) {
        grid-column:1 / -1; background:${ink}; color:${paper};
        padding:20px 24px; border-bottom:3px solid ${accent};
        white-space:normal !important; margin-bottom:20px;
    }
    #modular-heading { display:flex; align-items:center; justify-content:space-between;
                       margin-bottom:18px; }
    #modular-heading small { font:12px Consolas,monospace; letter-spacing:2px; color:${border}; }
    #modular-heading h1 { font-size:28px; margin:6px 0 0; letter-spacing:-1px; }
    .mode-tag { border:1px solid ${muted}; padding:8px 16px; font:14px Consolas,monospace; }
    div:has(> #modular-heading) + div { grid-column:1 / -1; grid-row:2; }
    /* The wrapper owns layout; VPython's canvas layers fill the same box. */
    .glowscript-canvas-wrapper { grid-column:1; grid-row:3; margin:0 !important;
        position:relative !important; box-sizing:border-box; padding:0 !important;
        width:100% !important; height:var(--visual-area-height) !important;
        min-width:0; min-height:0; align-self:start; overflow:hidden; }
    .glowscript-canvas-wrapper > canvas {
        position:absolute !important; inset:0 !important; margin:0 !important;
        display:block; box-sizing:border-box;
        width:100% !important; height:100% !important; }
    .glowscript-canvas-wrapper + div, .ui-section, .ui-stats > div { min-width:0; }

    .glowscript-canvas-wrapper + div { grid-column:2; grid-row:3; box-sizing:border-box; margin:0 !important;
        width:100%; height:var(--visual-area-height); min-height:0;
        max-height:var(--visual-area-height); align-self:start; overflow:auto; background:${panel}; padding:22px;
        white-space:normal !important; border:1px solid ${border}; line-height:1.5; }
    .glowscript-canvas-wrapper + div > span:first-child {
        display:block; padding-bottom:18px; border-bottom:1px solid ${border}; color:${muted}; }
    .ui-section { padding:20px 0; border-bottom:1px solid ${border}; }
    .ui-eyebrow { font:11px Consolas,monospace; color:${muted}; letter-spacing:1px; }
    .ui-section h2 { margin:5px 0 14px; font-size:22px; letter-spacing:-.5px; }
    .ui-stats { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
    .ui-value { font:24px Consolas,monospace; margin-top:4px; overflow-wrap:anywhere; }
    .ui-row { display:flex; justify-content:space-between; gap:12px; margin:9px 0; }
    .ui-row code { text-align:right; overflow-wrap:anywhere; }
    .ui-muted { color:${muted}; font-size:12px; }
    .marker-group { margin-top:18px; }
    .marker-heading { display:flex; gap:8px; align-items:center; font-weight:600; }
    .marker-chip { display:inline-block; width:10px; height:10px; flex-shrink:0; }
    .marker-before { background:${marker_before}; } .marker-after { background:${marker_after}; }
    .marker-row { margin-top:10px; padding:10px; background:${field};
                  border:1px solid ${border}; font:13px/1.7 Consolas,monospace; overflow-wrap:anywhere; }
    .marker-row strong { font-weight:600; }
    .ui-shortcuts { font:12px/1.9 Consolas,monospace; color:${muted}; padding-top:18px; }
    @media(max-width:800px) {
        div:has(> .glowscript-canvas-wrapper):has(#modular-heading) {
            grid-template-columns:minmax(0, 1fr); width:100%; }
        .glowscript-canvas-wrapper + div { grid-row:4; grid-column:1; width:100%;
            height:auto; max-height:none; margin-top:2% !important; }
    }
    </style>""").substitute(PALETTE)

    def _visual_setup_scene(self):
        """
        Creates scene objects and visual controls.
        """
        x0, x1, y0, y1, z0, z1 = self._visual_world_bounds()
        visual_center = vector(
            (x0 + x1) / 2.0,
            (y0 + y1) / 2.0,
            max(0.0, (z0 + z1) / 2.0),
        )
        visual_span = max(x1 - x0 + 1, y1 - y0 + 1, z1 - z0 + 1, 3)
        mode = 'PAS' if self.PAS_mode else 'SAS'
        visual_header = self.VISUAL_UI_CSS + (
            '<header id="modular-heading"><div>'
            '<h1>SIMULATOR</h1></div><span class="mode-tag">' + mode + '</span></header>'
        )
        self._visual_scene = canvas(
            title=visual_header,
            width=1200,
            height=760,
            center=visual_center,
            background=RENDER_COLORS['white'],
        )
        self._visual_scene.up = vector(0, 0, 1)
        self._visual_scene.forward = vector(
            -self.VISUAL_CAMERA_XY,
            -self.VISUAL_CAMERA_XY,
            self.VISUAL_CAMERA_Z,
        )
        self._visual_scene.range = visual_span * 0.78 + 1.5
        self._visual_scene.autoscale = False

        distant_light(direction=vector(1, 1, -1), color=RENDER_COLORS['white'])
        distant_light(direction=vector(-1, -0.5, -0.25), color=RENDER_COLORS['white'])

        self._visual_status_text = wtext(text='Initializing scene...\n')
        self._visual_panel_text = wtext(text='')

    def _visual_draw_ground(self):
        """
        Draws the simulation ground plane.
        """
        if self._visual_ground_box is not None:
            return

        x0, x1, y0, y1, _, _ = self._visual_world_bounds()
        visual_margin = 1.5
        visual_size_x = max(1.0, (x1 - x0 + 1) + 2 * visual_margin)
        visual_size_y = max(1.0, (y1 - y0 + 1) + 2 * visual_margin)
        visual_center_x = (x0 + x1) / 2.0
        visual_center_y = (y0 + y1) / 2.0
        self._visual_ground_box = box(
            pos=vector(visual_center_x, visual_center_y, -0.56),
            size=vector(visual_size_x, visual_size_y, 0.12),
            color=self.VISUAL_COLOR_GROUND,
            opacity=0.28,
        )

    def _visual_sync_sinks(self):
        """
        Synchronizes sink markers with the grid.
        """
        simulator_grid = self._visual_simulator.simulator_grid
        visual_current = set(simulator_grid.sinks)
        visual_drawn = set(self._visual_sink_boxes)

        for position in visual_drawn - visual_current:
            self._visual_sink_boxes[position].visible = False
            del self._visual_sink_boxes[position]

        for position in visual_current:
            if position not in self._visual_sink_boxes:
                x, y, z = position
                self._visual_sink_boxes[position] = box(
                    pos=vector(x, y, z),
                    size=vector(
                        self.VISUAL_CUBE_EDGE,
                        self.VISUAL_CUBE_EDGE,
                        self.VISUAL_CUBE_EDGE,
                    ),
                    color=self.VISUAL_COLOR_SINK,
                    opacity=self.VISUAL_OPACITY_SINK,
                    emissive=True,
                )
            else:
                self._visual_sink_boxes[position].visible = True

    def _visual_draw_axes(self):
        """
        Draws coordinate axes.
        """
        if self._visual_axis_objects:
            return

        simulator_grid = self._visual_simulator.simulator_grid
        visual_axis_margin = 1.0
        visual_x_len = simulator_grid.width + visual_axis_margin
        visual_y_len = simulator_grid.height + visual_axis_margin
        visual_z_len = simulator_grid.depth + visual_axis_margin
        visual_origin = vector(0, 0, 0)
        visual_shaft = max(
            0.035,
            max(visual_x_len, visual_y_len, visual_z_len) * 0.012,
        )
        visual_x_arrow = arrow(
            pos=visual_origin,
            axis=vector(visual_x_len, 0, 0),
            color=RENDER_COLORS['red'],
            shaftwidth=visual_shaft,
        )
        visual_y_arrow = arrow(
            pos=visual_origin,
            axis=vector(0, visual_y_len, 0),
            color=RENDER_COLORS['green'],
            shaftwidth=visual_shaft,
        )
        visual_z_arrow = arrow(
            pos=visual_origin,
            axis=vector(0, 0, visual_z_len),
            color=RENDER_COLORS['blue'],
            shaftwidth=visual_shaft,
        )
        visual_x_label = label(
            pos=visual_origin + vector(visual_x_len, 0, 0),
            text='x', box=False, opacity=0, color=RENDER_COLORS['red'], height=12,
        )
        visual_y_label = label(
            pos=visual_origin + vector(0, visual_y_len, 0),
            text='y', box=False, opacity=0, color=RENDER_COLORS['green'], height=12,
        )
        visual_z_label = label(
            pos=visual_origin + vector(0, 0, visual_z_len),
            text='z', box=False, opacity=0, color=RENDER_COLORS['blue'], height=12,
        )
        self._visual_axis_objects = [
            visual_x_arrow, visual_y_arrow, visual_z_arrow,
            visual_x_label, visual_y_label, visual_z_label,
        ]

    def _visual_sync_marker_faces(self, selections):
        """
        Shows marker changes on contacting module faces.
        """
        used = 0
        edge = self.VISUAL_CUBE_EDGE
        
        for position, module in self._visual_simulator.simulator_grid.module.items():
            if self._visual_preview_included_only and module.type != Grid.INCLUDED:
                continue
            for face, phase in sorted(selections.get(module.id, {}).items()):
                normal = DIRECTIONS[face]
                axis = next(i for i, value in enumerate(normal) if value)
                split_axis = next(i for i in range(3) if i != axis)
                colors = ([self.VISUAL_COLOR_MARKED_BEFORE, self.VISUAL_COLOR_MARKED]
                          if phase == 3 else [self.VISUAL_COLOR_MARKED_BEFORE
                                             if phase == 1 else self.VISUAL_COLOR_MARKED])
                for index, tint in enumerate(colors):
                    center = list(position)
                    center[axis] += normal[axis] * (edge / 2 + 0.002)
                    size = [edge, edge, edge]
                    size[axis] = 0.002
                    if phase == 3:
                        size[split_axis] = edge / 2
                        center[split_axis] += (-1 if index == 0 else 1) * edge / 4
                    if used == len(self._visual_marker_faces):
                        obj = box(pos=vector(*center), size=vector(*size),
                                  color=tint, opacity=1.0, emissive=True)
                        self._visual_marker_faces.append(obj)
                    else:
                        obj = self._visual_marker_faces[used]
                        obj.pos, obj.size, obj.color = vector(*center), vector(*size), tint
                        obj.visible = True
                    used += 1
        
        for obj in self._visual_marker_faces[used:]:
            obj.visible = False

    def _visual_sync_move_arrows(self):
        """
        Updates arrows for the latest module movements.
        """

        info = self._visual_simulator._visual_last_step_info or {}
        used = 0
        
        for move in info.get('movements', []):
            if self._visual_preview_included_only:
                break
            start, end = move['from'], move['to']
            delta = tuple(b - a for a, b in zip(start, end))
            if not any(delta):
                continue
            if used == len(self._visual_move_arrows):
                obj = arrow(pos=vector(*start), axis=vector(*delta),
                            color=self.VISUAL_COLOR_MOVE, shaftwidth=0.08,
                            headwidth=0.20, headlength=0.24, emissive=True)
                self._visual_move_arrows.append(obj)
            else:
                obj = self._visual_move_arrows[used]
                obj.pos, obj.axis = vector(*start), vector(*delta)
                obj.visible = True
            used += 1
        
        for obj in self._visual_move_arrows[used:]:
            obj.visible = False

    def _visual_sync_modules(self):
        """
        Synchronizes module shapes and colors.
        """
        simulator = self._visual_simulator
        simulator_grid = simulator.simulator_grid
        visual_current = set(simulator_grid.module.keys())
        visual_drawn = set(self._visual_module_boxes.keys())

        for position in visual_drawn - visual_current:
            self._visual_module_boxes[position].visible = False
            del self._visual_module_boxes[position]

        PAS_visual_active_positions = set(
            getattr(simulator, 'PASactive_positions', set())
        )
        visual_active_pos = simulator.simulator_active_pos

        if visual_active_pos is not None:
            PAS_visual_active_positions.add(visual_active_pos)

        visual_working_z = simulator.simulator_working_z
        visual_markers = self._visual_marker_selections()
        visual_has_focus = bool(PAS_visual_active_positions) or visual_working_z is not None

        for position in visual_current:
            module = simulator_grid.module[position]
            if (
                self._visual_preview_included_only
                and module.type != Grid.INCLUDED
            ):
                if position in self._visual_module_boxes:
                    self._visual_module_boxes[position].visible = False
                continue

            visual_base_color = (
                self.VISUAL_COLOR_INCLUDED
                if module.type == Grid.INCLUDED
                else self.VISUAL_COLOR_EXCLUDED
            )

            visual_is_marked = module.id in visual_markers
            visual_is_working_layer = (
                visual_working_z is not None
                and position[2] == visual_working_z
            )
            if position in PAS_visual_active_positions:
                visual_module_color = self.VISUAL_COLOR_ACTIVE
                visual_opacity = self.VISUAL_OPACITY_ACTIVE
            else:
                visual_module_color = visual_base_color
                if visual_is_working_layer:
                    visual_opacity = self.VISUAL_OPACITY_FOCUS
                elif visual_is_marked:
                    visual_opacity = self.VISUAL_OPACITY_MARKED
                else:
                    visual_opacity = (
                        self.VISUAL_OPACITY_DIM
                        if visual_has_focus
                        else self.VISUAL_OPACITY_IDLE
                    )
            if position not in self._visual_module_boxes:
                x, y, z = position
                self._visual_module_boxes[position] = box(
                    pos=vector(x, y, z),
                    size=vector(
                        self.VISUAL_CUBE_EDGE,
                        self.VISUAL_CUBE_EDGE,
                        self.VISUAL_CUBE_EDGE,
                    ),
                    color=visual_module_color,
                    opacity=visual_opacity,
                )
            else:
                visual_object = self._visual_module_boxes[position]
                visual_object.visible = True
                visual_object.color = visual_module_color
                visual_object.opacity = visual_opacity

        self._visual_sync_marker_faces(visual_markers)
        self._visual_sync_move_arrows()

    def _visual_sync_id_labels(self):
        """
        Updates visible module ID labels.
        """
        simulator_grid = self._visual_simulator.simulator_grid
        visual_current = set()
        visual_active_positions = set(
            getattr(self._visual_simulator, 'PASactive_positions', set())
        )
        visual_active_pos = self._visual_simulator.simulator_active_pos

        if visual_active_pos is not None:
            visual_active_positions.add(visual_active_pos)

        visual_marked_ids = set(self._visual_marker_selections()) if self._visual_started else set()
        
        for visual_position, visual_module in simulator_grid.module.items():
            if self._visual_preview_included_only and visual_module.type != Grid.INCLUDED:
                continue
            if (
                self._visual_started
                and visual_position not in visual_active_positions
                and visual_module.id not in visual_marked_ids
            ):
                continue
            visual_current.add(visual_position)

        if not self._visual_show_ids:
            for position in list(self._visual_id_labels.keys()):
                self._visual_id_labels[position].visible = False
            self._visual_id_labels.clear()
            return

        visual_drawn = set(self._visual_id_labels.keys())
        
        for position in visual_drawn - visual_current:
            self._visual_id_labels[position].visible = False
            del self._visual_id_labels[position]

        for position in visual_current:
            x, y, z = position
            module = simulator_grid.module[position]
            if position in self._visual_id_labels:
                self._visual_id_labels[position].text = str(module.id)
            else:
                self._visual_id_labels[position] = label(
                    pos=vector(x, y, z + 0.7),
                    text=str(module.id),
                    height=11,
                    box=False,
                    opacity=0,
                    color=RENDER_COLORS['black'],
                )

    def _visual_update_panel(self):
        """
        Updates the simulation information panel.
        """
        if self._visual_panel_text is None:
            return

        simulator = self._visual_simulator
        visual_info = simulator._visual_last_step_info or {}
        PAS_visual_active_ids = sorted(
            getattr(simulator, 'PASactive_ids', set())
        )
        visual_active_id = simulator.simulator_active_id
        visual_working_z = simulator.simulator_working_z
        visual_move = visual_info.get('direction')
        visual_legal_dirs = visual_info.get('legal_dirs') or []

        if PAS_visual_active_ids:
            visual_active_text = ', '.join(PAS_visual_active_ids)
        else:
            visual_active_text = (
                '-' if visual_active_id is None else str(visual_active_id)
            )

        visual_z_text = (
            '-' if visual_working_z is None else str(visual_working_z)
        )
        visual_move_text = '-' if visual_move is None else str(visual_move)
        visual_legal_text = (
            ', '.join(str(direction) for direction in visual_legal_dirs)
            if visual_legal_dirs
            else '-'
        )

        def value(text):
            """
            Escapes text for HTML display.
            """
            return escape(str(text))

        remaining = len(simulator.simulator_grid.get_excluded_positions())
        self._visual_panel_text.text = (
            '<section class="ui-section"><div class="ui-eyebrow">01 / LIVE STATE</div>'
            '<h2>Overview</h2><div class="ui-stats">'
            f'<div><span class="ui-muted">Step</span><div class="ui-value">{simulator.simulator_step_count}</div></div>'
            f'<div><span class="ui-muted">Active ID</span><div class="ui-value">{value(visual_active_text)}</div></div></div>'
            f'<div class="ui-row"><span>Move</span><code>{value(visual_move_text)}</code></div></section>'
            '<section class="ui-section"><div class="ui-eyebrow">02 / THIS STEP</div>'
            '<h2>Marker</h2><div class="ui-muted">Host module ID · [active ID, face, stored direction]</div>'
            f'<div class="marker-heading ui-muted"><span class="marker-chip" style="background:{PALETTE["movement"]}"></span>Arrow · actual movement</div>'
            + self._visual_marker_group_html('Before move', 'before', visual_info.get('markers_before_move', []))
            + self._visual_marker_group_html('After move', 'after', visual_info.get('markers_after_move', []))
            + '</section><section class="ui-section"><div class="ui-eyebrow">03 / PROGRESS</div>'
            f'<div class="ui-row"><span>Removed</span><code>{simulator.simulator_removed_module}</code></div>'
            f'<div class="ui-row"><span>Remaining</span><code>{remaining}</code></div>'
            f'<div class="ui-row"><span>Working layer</span><code>{value(visual_z_text)}</code></div>'
            f'<details><summary>Legal moves</summary><code>{value(visual_legal_text)}</code></details></section>'
            '<div class="ui-shortcuts">'
            '<div style="display:block">S = Start / Stop</div>'
            '<div style="display:block">N = Single Step</div>'
            '<div style="display:block">I = Toggle IDs</div>'
            '<div style="display:block">C = Rotate Camera 90°</div>'
            '<div style="display:block">P = Included-Only Preview</div>'
            '</div>'
        )

    @staticmethod
    def _visual_marker_group_html(title, phase, updates):
        """
        Formats marker records as an HTML group.
        """
        grouped = {}

        for update in updates:
            module_id = update.get('module_id')
            face, direction = update.get('face'), update.get('dir')
            if module_id is None or face is None or direction is None:
                continue
            # Keep distinct owners even when they write the same face/direction.
            active_id = update.get('active_id')
            owner = '?' if active_id is None else str(active_id)
            grouped.setdefault(str(module_id), set()).add((owner, str(face), str(direction)))
        
        rows = []
        
        for module_id, pairs in sorted(grouped.items()):
            pairs_text = ', '.join(f'[ID{owner}, {face}, {direction}]' for owner, face, direction in sorted(pairs))
            rows.append('<div class="marker-row"><strong>ID' + escape(module_id)
                        + ':</strong> ' + escape(pairs_text) + '</div>')
        
        return ('<div class="marker-group"><div class="marker-heading">'
                f'<span class="marker-chip marker-{phase}"></span>{escape(title)}</div>'
                + (''.join(rows) if rows else '<p class="ui-muted">No markers recorded.</p>') + '</div>')