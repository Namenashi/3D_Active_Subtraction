"""
This file was generated entirely by Claude and provides an optional graphical user interface for controlling the simulator.
It does not implement or modify the core SAS/PAS algorithms.
"""
import math
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from grid_3d import Grid
from ui_config import COLORS, PALETTE

PREVIEW_ELEVATION = math.atan2(0.85, math.hypot(1.25, 1.25))

def project_point(x, y, z, angle):
    a, b = math.cos(angle), math.sin(angle)
    se, ce = math.sin(PREVIEW_ELEVATION), math.cos(PREVIEW_ELEVATION)
    near = a*x + b*y
    return (-b*x + a*y, se*near - ce*z, ce*near + se*z)

class PatternPreview(tk.Canvas):
    def __init__(self, parent, included_only=False, **kwargs):
        super().__init__(parent, background=COLORS['canvas'], highlightthickness=0, **kwargs)
        self.included_only = included_only
        self.pattern = None
        self.angle = math.pi / 4
        self.bind('<Configure>', lambda event: self.draw())

    def set_pattern(self, pattern):
        self.pattern = pattern
        self.draw()

    def draw(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if not self.pattern:
            self.create_text(w / 2, h / 2, text='Enter a valid pattern', fill=COLORS['muted'])
            return
        p = self.pattern
        cx, cy, cz = (p['width']-1)/2, (p['height']-1)/2, (p['depth']-1)/2
        a, b = math.cos(self.angle), math.sin(self.angle)
        def project(x, y, z):
            return project_point(x-cx, y-cy, z-cz, self.angle)

        # Axes start at the real world origin, as in the browser simulator.
        axes = [('x', (p['width']+1.0, 0, 0), PALETTE['preview_x']),
                ('y', (0, p['height']+1.0, 0), PALETTE['preview_y']),
                ('z', (0, 0, p['depth']+1.0), PALETTE['preview_z'])]
        # Both previews share the complete pattern's bounds and scale.
        bounds = [project(x, y, z) for x in (-.5, p['width']-.5)
                  for y in (-.5, p['height']-.5) for z in (-.5, p['depth']-.5)]
        bounds.extend(project(*end) for _, end, _ in axes)
        xmin, xmax = min(v[0] for v in bounds), max(v[0] for v in bounds)
        ymin, ymax = min(v[1] for v in bounds), max(v[1] for v in bounds)
        scale = max(1, min((w-40)/max(xmax-xmin, 1), (h-55)/max(ymax-ymin, 1)))

        def screen(v):
            return (w/2 + (v[0]-(xmin+xmax)/2)*scale,
                    h/2 + (v[1]-(ymin+ymax)/2)*scale)

        # Cull faces facing away from the camera; painter-sort visible faces.
        faces = []
        d = .44
        for (x, y, z), kind in p['modules'].items():
            if self.included_only and kind != Grid.INCLUDED:
                continue
            colors = (PALETTE['included_side_a'], PALETTE['included_side_b'], PALETTE['included_top']) if kind == Grid.INCLUDED else (PALETTE['excluded_side_a'], PALETTE['excluded_side_b'], PALETTE['excluded_top'])
            sx, sy = (1 if a >= 0 else -1), (1 if b >= 0 else -1)
            polygons = [
                [(x+sx*d,y-d,z-d),(x+sx*d,y+d,z-d),(x+sx*d,y+d,z+d),(x+sx*d,y-d,z+d)],
                [(x-d,y+sy*d,z-d),(x+d,y+sy*d,z-d),(x+d,y+sy*d,z+d),(x-d,y+sy*d,z+d)],
                [(x-d,y-d,z+d),(x+d,y-d,z+d),(x+d,y+d,z+d),(x-d,y+d,z+d)],
            ]
            for vertices, color in zip(polygons, colors):
                projected = [project(*v) for v in vertices]
                faces.append((sum(v[2] for v in projected)/4, projected, color))
        for _, vertices, color in sorted(faces, key=lambda face: face[0]):
            points = [coord for v in vertices for coord in screen(v)]
            self.create_polygon(*points, fill=color, outline=PALETTE['preview_outline'], width=.7)
        if not faces:
            self.create_text(w/2, h/2, text='No INCLUDED modules', fill=COLORS['muted'])
        origin = screen(project(0, 0, 0))
        for name, end, color in axes:
            ex, ey = screen(project(*end))
            self.create_line(*origin, ex, ey, fill=color, arrow=tk.LAST, width=2)
            self.create_text(ex, ey-9, text=name, fill=color)

class LauncherDesign:
    def build_ui(self):
        style = ttk.Style()
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        self.root.configure(background=COLORS['background'])
        # Shared warm neutral palette with a restrained yellow action accent.
        style.configure('.', font=('Segoe UI', 10), background=COLORS['panel'], foreground=COLORS['text'],
                        bordercolor=COLORS['border'], lightcolor=COLORS['border'],
                        darkcolor=COLORS['background'], troughcolor=COLORS['background'])
        style.configure('TFrame', background=COLORS['panel'])
        style.configure('TLabel', background=COLORS['panel'], foreground=COLORS['text'])
        style.configure('TLabelframe', background=COLORS['panel'], bordercolor=COLORS['border'])
        style.configure('TLabelframe.Label', background=COLORS['panel'], foreground=COLORS['text'])
        style.configure('TPanedwindow', background=COLORS['background'])
        style.configure('TButton', padding=(12, 8), relief='flat', background=COLORS['control'])
        style.configure('Primary.TButton', background=COLORS['accent'], font=('Segoe UI', 10, 'bold'))
        style.map('Primary.TButton', background=[('disabled', COLORS['control']), ('active', PALETTE['accent_hover']), ('!disabled', COLORS['accent'])])
        style.map('TButton', background=[('pressed', COLORS['background']), ('active', COLORS['active'])],
                  foreground=[('disabled', PALETTE['disabled'])])
        for name in ('TEntry', 'TSpinbox', 'TCombobox'):
            style.configure(name, fieldbackground=COLORS['field'], foreground=COLORS['text'],
                            background=COLORS['control'], insertcolor=COLORS['text'],
                            arrowcolor=COLORS['text'])
            style.map(name, fieldbackground=[('readonly', COLORS['field']), ('disabled', COLORS['panel'])],
                      foreground=[('readonly', COLORS['text']), ('disabled', PALETTE['disabled'])],
                      selectbackground=[('!disabled', COLORS['active'])],
                      selectforeground=[('!disabled', COLORS['text'])])
        style.configure('TCheckbutton', background=COLORS['panel'], indicatorbackground=COLORS['field'])
        style.map('TCheckbutton', background=[('active', COLORS['panel'])],
                  indicatorbackground=[('selected', COLORS['accent']), ('active', COLORS['control'])])
        for name in ('Horizontal.TScrollbar', 'Vertical.TScrollbar'):
            style.configure(name, background=COLORS['control'], arrowcolor=COLORS['text'])
            style.map(name, background=[('active', COLORS['active'])])
        # Also theme the Tk widgets used by standard text-entry dialogs.
        for option, value in [('Background', COLORS['panel']), ('Foreground', COLORS['text']),
                              ('Entry.Background', COLORS['field']), ('Entry.insertBackground', COLORS['text']),
                              ('Button.Background', COLORS['control']), ('Button.activeBackground', COLORS['active']),
                              ('Button.activeForeground', COLORS['text']),
                              ('TCombobox*Listbox.background', COLORS['field']),
                              ('TCombobox*Listbox.foreground', COLORS['text']),
                              ('TCombobox*Listbox.selectBackground', COLORS['active'])]:
            self.root.option_add('*'+option, value)
        style.configure('Title.TLabel', font=('Segoe UI', 15, 'bold'))
        style.configure('Muted.TLabel', foreground=COLORS['muted'])
        bar = tk.Frame(self.root, background=COLORS['header'], padx=22, pady=18)
        bar.pack(fill='x')
        tk.Label(bar, text='LAUNCHER', background=COLORS['header'],
                 foreground=PALETTE['paper'], font=('Segoe UI', 20, 'bold')).pack(side='left')
        tk.Label(bar, textvariable=self.status, background=COLORS['header'],
                 foreground=COLORS['accent'], font=('Consolas', 11)).pack(side='right')
        tk.Frame(self.root, background=COLORS['accent'], height=3).pack(fill='x')
        panes = ttk.Panedwindow(self.root, orient='horizontal')
        panes.pack(fill='both', expand=True, padx=16, pady=16)
        left, middle, right = [ttk.Frame(panes, padding=10) for _ in range(3)]
        for frame, weight in ((left, 38), (right, 37), (middle, 25)):
            panes.add(frame, weight=weight)
        # Percent-based allocation on resize; no fixed requested pane widths.
        def fit_panes(event=None):
            width = panes.winfo_width()
            if width > 1:
                panes.sashpos(0, int(width * .38))
                panes.sashpos(1, int(width * .75))
        panes.bind('<Configure>', fit_panes)
        self.root.after_idle(fit_panes)
        # Keep every editor/settings control reachable even in a short window.
        left_shell = left
        left_scrollbar = ttk.Scrollbar(left_shell, orient='vertical')
        left_scrollbar.pack(side='right', fill='y')
        left_viewport = tk.Canvas(left_shell, background=COLORS['panel'],
                                  highlightthickness=0, width=1, height=1,
                                  yscrollcommand=left_scrollbar.set)
        left_viewport.pack(side='left', fill='both', expand=True)
        left_scrollbar.configure(command=left_viewport.yview)
        left = ttk.Frame(left_viewport)
        left_window = left_viewport.create_window(0, 0, window=left, anchor='nw')
        def fit_editor(event=None):
            width = max(1, left_viewport.winfo_width())
            for child in left.winfo_children():
                if isinstance(child, ttk.Label):
                    child.configure(wraplength=max(60, width - 8))
            left_viewport.itemconfigure(left_window, width=width,
                height=max(left_viewport.winfo_height(), left.winfo_reqheight()))
            left_viewport.configure(scrollregion=left_viewport.bbox('all'))
        left_viewport.bind('<Configure>', fit_editor)
        left.bind('<Configure>', fit_editor)
        ttk.Label(left, text='01 / Pattern editor', style='Title.TLabel').pack(anchor='w')
        buttons = ttk.Frame(left)
        buttons.pack(fill='x', pady=8)
        for column, (label, action) in enumerate([('New',self.new_pattern),('Open',self.open_pattern),('Save',self.save_pattern)]):
            buttons.columnconfigure(column, weight=1, uniform='file-actions')
            ttk.Button(buttons,text=label,command=action,width=1).grid(row=0,column=column,sticky='ew',padx=(0,4))
        ttk.Label(left,text='1 / I = INCLUDED · 0 / E = EXCLUDED \nBlank line = x layer · Bottom row (z=0) must be all 1', wraplength=400).pack(anchor='w')
        self.editor = ScrolledText(left, wrap='none', undo=True, font=('Consolas',12), width=1, height=1, background=COLORS['field'], foreground=COLORS['text'],
                                   insertbackground=COLORS['text'], selectbackground=COLORS['active'],
                                   selectforeground=COLORS['text'], relief='flat', padx=10, pady=10)
        self.editor.pack(fill='both',expand=True,pady=8)
        hscroll = ttk.Scrollbar(left, orient='horizontal', command=self.editor.xview)
        hscroll.pack(fill='x', pady=(0, 6))
        self.editor.configure(xscrollcommand=hscroll.set)
        self.editor.bind('<<Modified>>', self.on_edit)
        self.pattern_label = ttk.Label(left, textvariable=self.pattern_status, wraplength=390)
        self.pattern_label.pack(anchor='w',pady=(0,8))
        settings = ttk.LabelFrame(left,text='Run Settings',padding=8)
        settings.pack(fill='x')
        ttk.Label(settings,text='Mode').grid(row=0,column=0,sticky='w')
        ttk.Combobox(settings,textvariable=self.mode,values=('SAS','PAS'),state='readonly',width=1).grid(row=0,column=1,sticky='ew',padx=4)
        ttk.Label(settings,text='Step delay (seconds)').grid(row=1,column=0,sticky='w',pady=6)
        ttk.Spinbox(settings,textvariable=self.delay,from_=0,to=60,increment=.05,width=1).grid(row=1,column=1,sticky='ew',padx=4)
        ttk.Label(settings,text='PAS limit (0 = unlimited)').grid(row=2,column=0,sticky='w',pady=(0,6))
        self.pas_max_active_spinbox = ttk.Spinbox(
            settings,
            textvariable=self.pas_max_active,
            from_=0,
            to=1000000,
            increment=1,
            width=1,
        )
        self.pas_max_active_spinbox.grid(row=2,column=1,sticky='ew',padx=4,pady=(0,6))
        ttk.Checkbutton(settings,text='Save screenshots + generate GIF',variable=self.capture).grid(row=3,column=0,columnspan=3,sticky='w')
        ttk.Label(settings,text='Browser downloads folder').grid(row=4,column=0,columnspan=3,sticky='w',pady=(8,2))
        ttk.Entry(settings,textvariable=self.downloads,width=1).grid(row=5,column=0,columnspan=2,sticky='ew')
        ttk.Button(settings,text='Browse',command=self.choose_downloads).grid(row=6,column=0,columnspan=2,sticky='ew',pady=(4,0))
        settings.columnconfigure(0,weight=55,uniform='settings')
        settings.columnconfigure(1,weight=45,uniform='settings')
        def wrap_settings(event):
            for child in settings.winfo_children():
                if isinstance(child, ttk.Label):
                    child.configure(wraplength=max(60, int(event.width * .50)))
        settings.bind('<Configure>', wrap_settings)
        runbar = ttk.Frame(left)
        runbar.pack(fill='x',pady=(8,0))
        self.run_button = ttk.Button(runbar,text='RUN SIMULATION',style='Primary.TButton',command=self.run_simulation)
        self.run_button.pack(side='left',fill='x',expand=True)
        self.stop_button = ttk.Button(runbar,text='Stop',command=self.stop_simulation,state='disabled')
        self.stop_button.pack(side='left',padx=(6,0))
        ttk.Label(middle,text='03 / Run log',style='Title.TLabel').pack(anchor='w')
        ttk.Button(middle,text='Clear Log',command=self.clear_log).pack(anchor='e',pady=6)
        self.log = ScrolledText(middle,state='disabled',background=COLORS['canvas'],foreground=COLORS['text'],insertbackground=COLORS['text'],font=('Consolas',10),wrap='word',width=1,height=1,relief='flat',padx=10,pady=10)
        self.log.pack(fill='both',expand=True)
        for widget in (self.editor, self.log):
            widget.frame.configure(background=COLORS['panel'])
            widget.vbar.configure(background=COLORS['control'], troughcolor=COLORS['background'],
                                  activebackground=COLORS['active'], highlightthickness=0)
        ttk.Label(middle,text='Current run: stdout + stderr · Auto-scroll').pack(anchor='w',pady=6)
        heading = ttk.Frame(right)
        heading.pack(fill='x')
        ttk.Label(heading,text='02 / Preview',style='Title.TLabel').pack(side='left')
        ttk.Button(heading,text='Rotate 90°',command=self.rotate_previews).pack(side='right')
        ttk.Label(right,text='Blue = INCLUDED · Gray = EXCLUDED').pack(anchor='w',pady=6)
        self.previews = []
        for title, included in [('INCLUDED and EXCLUDED',False),('INCLUDED only',True)]:
            frame = ttk.LabelFrame(right,text=title,padding=4)
            frame.pack(fill='both',expand=True,pady=(0,8))
            preview = PatternPreview(frame,included_only=included,width=1,height=1)
            preview.pack(fill='both',expand=True)
            self.previews.append(preview)

    @staticmethod
    def _design_window_size(root):
        root.geometry(f'{int(root.winfo_screenwidth() * .90)}x{int(root.winfo_screenheight() * .85)}')
        root.minsize(800, 560)

    def _design_pattern_status(self, valid):
        self.pattern_label.configure(foreground=COLORS['muted'] if valid else PALETTE['error'])
