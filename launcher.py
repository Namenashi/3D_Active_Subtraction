"""
This file was generated entirely by Claude and provides an optional graphical user interface for controlling the simulator.
It does not implement or modify the core SAS/PAS algorithms.
"""
from pathlib import Path
import datetime
import math
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

from converter_3d import generator_parse_pattern
from grid_3d import Grid
from launcher_design import LauncherDesign, PatternPreview, project_point, PREVIEW_ELEVATION
from ui_config import COLORS

BASE_DIR = Path(__file__).resolve().parent
EXAMPLE = ''

def validate_delay(value):
    delay = float(value)
    if not math.isfinite(delay) or delay < 0:
        raise ValueError('Step delay must be a finite number greater than or equal to zero.')
    return delay

def validate_pas_max_active(value):
    try:
        limit = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError('PAS max active modules must be a whole number (0 = unlimited).')
    if limit < 0:
        raise ValueError('PAS max active modules must be 0 or greater.')
    return None if limit == 0 else limit

def pattern_filename(name):
    name = name.strip()
    if not name or name in ('.', '..') or any(c in name for c in '/\\:*?"<>|'):
        raise ValueError('Enter a valid file name without a folder path.')
    if not name.lower().endswith('.txt'):
        name += '.txt'
    else:
        name = name[:-4] + '.txt'
    if name.startswith('.'):
        raise ValueError('File names cannot start with a dot.')
    return name

def simulation_command(
    pattern, mode, delay, capture, downloads, run_dir, pas_max_active=None
):
    command = [sys.executable, '-u', str(BASE_DIR / 'main.py'), str(pattern),
               mode, '--step-delay', str(validate_delay(delay)),
               '--run-dir', str(run_dir)]
    if mode.upper() == 'PAS' and pas_max_active is not None:
        command += ['--pas-max-active', str(int(pas_max_active))]
    if capture:
        command += ['--downloads-dir', str(downloads)]
    else:
        command.append('--no-capture')
    return command

class Launcher(LauncherDesign):
    def __init__(self, root):
        self.root = root
        self.patterns_dir = BASE_DIR / 'patterns'
        self.patterns_dir.mkdir(exist_ok=True)
        self.process = None
        self.events = queue.Queue()
        self.preview_job = None
        self.dirty = False
        self.filename = 'untitled.txt'
        self.mode = tk.StringVar(value='SAS')
        self.delay = tk.StringVar(value='0.2')
        self.pas_max_active = tk.StringVar(value='0')
        self.capture = tk.BooleanVar(value=False)
        self.downloads = tk.StringVar(value=str(Path.home() / 'Downloads'))
        self.status = tk.StringVar(value='Idle')
        self.pattern_status = tk.StringVar()
        root.title('Launcher')
        self._design_window_size(root)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.build_ui()
        self.mode.trace_add('write', self._update_pas_limit_state)
        self._update_pas_limit_state()
        root.bind('<Control-o>', lambda event: self.open_pattern())
        root.bind('<Control-s>', lambda event: self.save_pattern())
        default = self.patterns_dir / '0000.txt'
        if default.is_file():
            try:
                self.set_text(default.read_text(encoding='utf-8-sig'), default.name)
            except (OSError, UnicodeError):
                self.set_text(EXAMPLE, 'untitled.txt')
        else:
            self.set_text(EXAMPLE, 'untitled.txt')
        self.refresh_preview()
        self.root.after(100, self.poll_events)

    def text(self):
        return self.editor.get('1.0','end-1c')

    def set_text(self,text,name):
        self.editor.delete('1.0','end')
        self.editor.insert('1.0',text)
        self.editor.edit_reset()
        self.editor.edit_modified(False)
        self.filename = name
        self.dirty = False
        self.update_title()
        self.refresh_preview()

    def update_title(self):
        self.root.title(f'{"* " if self.dirty else ""}{self.filename} — Launcher')

    def on_edit(self,event=None):
        if not self.editor.edit_modified():
            return
        self.editor.edit_modified(False)
        self.dirty = True
        self.update_title()
        if self.preview_job is not None:
            self.root.after_cancel(self.preview_job)
        self.preview_job = self.root.after(350,self.refresh_preview)

    def refresh_preview(self):
        if self.preview_job is not None:
            self.root.after_cancel(self.preview_job)
            self.preview_job = None
        try:
            pattern = generator_parse_pattern(self.text())
        except ValueError as exc:
            self.pattern_status.set(f'Invalid pattern: {exc}')
            self._design_pattern_status(False)
            for preview in self.previews:
                preview.set_pattern(None)
            return
        included = sum(kind == Grid.INCLUDED for kind in pattern['modules'].values())
        excluded = len(pattern['modules'])-included
        self.pattern_status.set(f"x={pattern['width']} · y={pattern['height']} · z={pattern['depth']} | INCLUDED {included} · EXCLUDED {excluded}")
        self._design_pattern_status(True)
        for preview in self.previews:
            preview.set_pattern(pattern)

    def rotate_previews(self):
        for preview in self.previews:
            preview.angle += math.pi/2
            preview.draw()

    def confirm_discard(self):
        return not self.dirty or messagebox.askyesno('Unsaved Changes','Discard the current edits?',parent=self.root)

    def new_pattern(self):
        if self.confirm_discard():
            self.set_text('', 'untitled.txt')

    def open_pattern(self):
        if not self.confirm_discard():
            return
        path = filedialog.askopenfilename(parent=self.root,initialdir=self.patterns_dir,filetypes=[('Pattern files','*.txt'),('All files','*.*')])
        if not path:
            return
        try:
            self.set_text(Path(path).read_text(encoding='utf-8-sig'),Path(path).name)
        except (OSError,UnicodeError) as exc:
            messagebox.showerror('Could Not Open File',str(exc),parent=self.root)

    def save_pattern(self):
        # Invalid drafts may be saved; only previews and runs require valid patterns.
        name = simpledialog.askstring('Save Pattern','File name to save in the patterns folder:',initialvalue=self.filename,parent=self.root)
        if name is None:
            return
        try:
            path = self.patterns_dir / pattern_filename(name)
            if path.exists() and not messagebox.askyesno('Overwrite File',f'Overwrite {path.name}?',parent=self.root):
                return
            path.write_text(self.text(),encoding='utf-8')
            self.filename = path.name
            self.dirty = False
            self.update_title()
            self.append_log(f'[Save] {path}\n')
        except (ValueError,OSError) as exc:
            messagebox.showerror('Could Not Save File',str(exc),parent=self.root)

    def _update_pas_limit_state(self, *_args):
        """PAS 전용 설정은 PAS mode에서만 편집 가능하게 유지한다."""
        if not hasattr(self, 'pas_max_active_spinbox'):
            return
        state = 'normal' if self.mode.get() == 'PAS' else 'disabled'
        self.pas_max_active_spinbox.configure(state=state)

    def choose_downloads(self):
        path = filedialog.askdirectory(parent=self.root,initialdir=self.downloads.get())
        if path:
            self.downloads.set(path)

    def append_log(self,text):
        self.log.configure(state='normal')
        self.log.insert('end',text)
        # Bound widget memory during long runs.
        lines = int(self.log.index('end-1c').split('.')[0])
        if lines > 12000:
            self.log.delete('1.0',f'{lines-10000}.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def clear_log(self):
        self.log.configure(state='normal')
        self.log.delete('1.0','end')
        self.log.configure(state='disabled')

    def run_simulation(self):
        if self.process is not None:
            return
        # 런 버튼을 누른 시점을 PAS baseline 구간의 시작점으로 보존한다.
        run_started_at = time.time()
        try:
            generator_parse_pattern(self.text())
            delay = validate_delay(self.delay.get())
            pas_max_active = (
                validate_pas_max_active(self.pas_max_active.get())
                if self.mode.get() == 'PAS'
                else None
            )
            downloads = Path(self.downloads.get()).expanduser()
            if self.capture.get() and not downloads.is_dir():
                raise ValueError('Choose your actual browser downloads folder to save screenshots.')
            stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            run_dir = BASE_DIR / 'runs' / f'run_{stamp}_{self.mode.get().lower()}_3d'
            run_dir.mkdir(parents=True)
            # Immutable per-run input; editor changes cannot affect PAS workers.
            snapshot = run_dir / 'pattern.txt'
            snapshot.write_text(self.text(),encoding='utf-8')
            command = simulation_command(
                snapshot, self.mode.get(), delay, self.capture.get(), downloads, run_dir,
                pas_max_active=pas_max_active,
            )
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['SIMULATION_LAUNCHER_START_TIME'] = repr(run_started_at)
            kwargs = {'start_new_session':True} if os.name != 'nt' else {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP}
            process = subprocess.Popen(command,cwd=BASE_DIR,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                       text=True,encoding='utf-8',errors='replace',bufsize=1,env=env,**kwargs)
        except (ValueError,OSError) as exc:
            messagebox.showerror('Could Not Start Simulation',str(exc),parent=self.root)
            return
        self.process = process
        self.status.set(f'{self.mode.get()} Running')
        self.run_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        PASlimit_log = (
            ' · Max active unlimited'
            if self.mode.get() == 'PAS' and pas_max_active is None
            else (f' · Max active {pas_max_active}' if self.mode.get() == 'PAS' else '')
        )
        self.append_log(
            f'\n[Run] {self.mode.get()} · Delay {delay}s · Capture {self.capture.get()}'
            f'{PASlimit_log}\nOutput folder: {run_dir}\n'
        )
        threading.Thread(target=self.read_output,args=(process,),daemon=True).start()

    def read_output(self,process):
        try:
            with process.stdout:
                for line in process.stdout:
                    self.events.put(('log',line))
        except OSError as exc:
            self.events.put(('log',f'[Log read error] {exc}\n'))
        finally:
            self.events.put(('exit',process.wait()))

    def poll_events(self):
        for _ in range(300):
            try:
                kind,value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                self.append_log(value)
            elif kind == 'exit':
                self.append_log(f'[Process exited] Code {value}\n')
                self.process = None
                self.status.set('Idle' if value == 0 else f'Exited (code {value})')
                self.run_button.configure(state='normal')
                self.stop_button.configure(state='disabled')
        self.root.after(100,self.poll_events)

    def stop_simulation(self):
        process = self.process
        if process is None or process.poll() is not None:
            return
        self.status.set('Stopping')
        self.stop_button.configure(state='disabled')
        self.append_log('[Stop requested] Terminating the current run.\n')
        threading.Thread(target=self.terminate_process,args=(process,),daemon=True).start()

    @staticmethod
    def terminate_process(process):
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            else:
                import signal
                os.killpg(process.pid,signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL)
        except (OSError,ProcessLookupError):
            pass

    def close(self):
        if self.process is not None and self.process.poll() is None:
            if not messagebox.askyesno('Running','Stop the simulation and close the launcher?',parent=self.root):
                return
        if not self.confirm_discard():
            return
        if self.process is not None:
            # Non-daemon thread finishes child cleanup even after Tk exits.
            threading.Thread(target=self.terminate_process,args=(self.process,),daemon=False).start()
        self.root.destroy()

def launch():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise SystemExit(f'The launcher requires a desktop GUI and Tkinter: {exc}') from exc
    Launcher(root)
    root.mainloop()

if __name__ == '__main__':
    launch()
