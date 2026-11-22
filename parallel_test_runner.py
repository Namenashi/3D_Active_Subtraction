"""
Runs isolated SAS/PAS tests under resource awared admission control.
"""
from collections import deque
import codecs
import uuid
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from auto_test_config import validate_settings
from test_results import MODES, save_results

# Windows: separate read-only log console per running pattern/mode.
SHOW_WORKER_WINDOWS = True


def _viewer_status(job, state, message):
    """
    Updates the external log viewer status
    """
    path = job.get('viewer_status')
    
    if path is None:
        return
    
    try:
        if job['viewer'].poll() is not None:
            path.unlink(missing_ok=True)
            return
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(state=state, message=message)), encoding='utf-8')
        os.replace(temporary, path)
    except OSError as exc:
        print(f'Log window status unavailable: {exc}', flush=True)


def _open_log_window(job, title):
    """
    Opens an optional Windows log viewer.
    """
    if not SHOW_WORKER_WINDOWS or sys.platform != 'win32':
        return

    path = job['log_path'].with_name(f'.viewer_{uuid.uuid4().hex}.json')

    try:
        path.write_text('{"state": "running", "message": ""}', encoding='utf-8')
        viewer = subprocess.Popen(
            [sys.executable, '-u', str(Path(__file__).resolve()), '--watch-log',
             str(job['log_path']), str(path), title, str(os.getpid())],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            close_fds=True,
        )
    except OSError as exc:
        path.unlink(missing_ok=True)
        print(f'Could not open log window ({exc}); use {job["log_path"]}', flush=True)
        return

    job.update(viewer=viewer, viewer_status=path)


def _watch_log(log_path, status_path, title, coordinator_pid):
    """
    Displays a worker log in an independent console
    """
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    
    if os.name == 'nt':
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(title)
    
    print(title, flush=True)
    print(f'Log: {log_path}', flush=True)
    print('This window only displays logs. Closing it does NOT stop the simulation.', flush=True)
    print('Stop all simulations using Ctrl+C in the MAIN auto_test window.\n', flush=True)
    
    monitor = require_monitor()
    
    try:
        coordinator = monitor.Process(coordinator_pid)
    except monitor.Error:
        coordinator = None
    
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    state = dict(state='running', message='')
    
    try:
        with Path(log_path).open('rb') as stream:
            while True:
                try:
                    state = json.loads(Path(status_path).read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    pass
                data = stream.read(65536)
                if data:
                    sys.stdout.write(decoder.decode(data))
                    sys.stdout.flush()
                    continue
                if state['state'] != 'running':
                    break
                if coordinator is None or not coordinator.is_running():
                    state = dict(state='stopped', message='Main test process exited; consult the log.')
                    break
                time.sleep(0.2)
        sys.stdout.write(decoder.decode(b'', final=True))
        seconds = 3 if state['state'] == 'success' else 15
        print(f'\n[{state["state"].upper()}] {state["message"]}', flush=True)
        print(f'Window closes in {seconds}s. Full output remains in {log_path}', flush=True)
        time.sleep(seconds)
    except KeyboardInterrupt:
        pass
    finally:
        Path(status_path).unlink(missing_ok=True)


def require_monitor():
    """
    Loads the system resource monitor
    """
    try:
        import psutil
    except ImportError as exc:
        raise ValueError('Adaptive parallel tests require psutil: python -m pip install psutil') from exc
    
    return psutil


class ResourceGate:
    """
    Admission control only. Restricts launches based on CPU and memory targets
    """
    def __init__(self, settings, monitor):
        """
        Initializes resource tracking and admission settings
        """
        self.monitor = monitor
        self.cpu_target = settings.get('cpu_target_percent', 50.0)
        self.memory_target = settings.get('memory_target_percent', 50.0)
        self.interval = settings.get('resource_sample_seconds', 1.0)
        self.ramp = settings.get('ramp_up_seconds', 10.0)
        self.samples = deque()
        self.last_start = float('-inf')
        self.peak_bytes = 256 * 1024 * 1024
        self.cpu = self.average = self.memory = 0.0
        self.headroom = 0
        
        monitor.cpu_percent(interval=None)

    def sample(self, now):
        """
        Samples current CPU and memory usage
        """
        self.cpu = self.monitor.cpu_percent(interval=None)
        self.samples.append((now, self.cpu))
        
        while len(self.samples) > 1 and self.samples[0][0] < now - 10.0:
            self.samples.popleft()
        
        self.average = sum(value for _, value in self.samples) / len(self.samples)
        memory = self.monitor.virtual_memory()
        self.memory = memory.percent
        self.headroom = memory.available - memory.total * (1 - self.memory_target / 100)

    def can_start(self, now, running, cap):
        """
        Checks whether another worker may start.
        """
        
        if running >= cap:
            return False
        
        if running == 0:
            return True
        
        return (now - self.last_start >= self.ramp
                and max(self.cpu, self.average) < self.cpu_target
                and self.memory < self.memory_target
                and self.headroom >= self.peak_bytes * 1.5)

    def observe_process(self, pid):
        """
        Tracks peak memory usage of a worker tree.
        """
        try:
            root = self.monitor.Process(pid)
            members = [root] + root.children(recursive=True)
        except self.monitor.Error:
            return
        
        rss = 0

        for member in members:
            try:
                rss += member.memory_info().rss
            except self.monitor.Error:
                pass

        self.peak_bytes = max(self.peak_bytes, rss)


def _stop_process_tree(process, monitor):
    """
    Terminates a worker and its descendants
    """
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        return
    
    try:
        parent = monitor.Process(process.pid)
        parent.suspend()
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.suspend()
            except monitor.Error:
                pass
        members = children + [parent]
        for member in members:
            try:
                member.kill()
            except monitor.Error:
                pass
        monitor.wait_procs(members, timeout=3)
    except monitor.NoSuchProcess:
        pass
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


def _start_case(pattern, mode, limit, delay, prefix, worker_script):
    """
    Starts an isolated test worker
    """
    result_path = Path(f'{prefix}_result.tmp')
    result_path.unlink(missing_ok=True)
    command = [sys.executable, '-u', str(Path(worker_script).resolve()), '--worker',
               '--pattern', str(pattern), '--mode', mode,
               '--step-delay', str(delay), '--trace-path', f'{prefix}_trace.jsonl',
               '--result-path', str(result_path)]
    
    if limit is not None:
        command += ['--pas-max-active', str(limit)]
    
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    started = time.monotonic()
    log_path = Path(f'{prefix}_output.log').resolve()
    output = log_path.open('w', encoding='utf-8')
    
    try:
        # Direct file output avoids pipe deadlocks and interleaved console logs.
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                   env=env, start_new_session=(os.name == 'posix'))
    except BaseException:
        output.close()
        raise
    
    return dict(process=process, output=output, result_path=result_path, started=started, log_path=log_path)


def _finish_case(job):
    """
    Reads results and closes a completed job
    """
    process = job['process']
    result_path = job['result_path']
    elapsed = time.monotonic() - job['started']
    result = dict(success=False, excluded_removed=None, steps=None,
                  elapsed_seconds=elapsed, wall_seconds=elapsed,
                  preparation_seconds=0.0, error='')
    
    try:
        if result_path.exists():
            payload = json.loads(result_path.read_text(encoding='utf-8'))
            if not isinstance(payload, dict):
                raise ValueError('Worker result must be an object')
            result.update(payload)
        if process.returncode != 0 or not result_path.exists():
            result['success'] = False
            result['error'] = result.get('error') or f'Worker exited without a result (code {process.returncode})'
    except (OSError, ValueError) as exc:
        result['success'] = False
        result['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        job['output'].close()
        result_path.unlink(missing_ok=True)
    _viewer_status(job, 'success' if result['success'] else 'failed',
                   'Simulation completed.' if result['success'] else result['error'])

    return result


def run_case(pattern, mode, limit, delay, prefix, *, worker_script):
    """
    Runs one isolated test to completion
    """
    monitor = require_monitor()
    job = _start_case(pattern, mode, limit, delay, prefix, worker_script)
    
    try:
        job['process'].wait()
    except BaseException:
        _stop_process_tree(job['process'], monitor)
        job['output'].close()
        job['result_path'].unlink(missing_ok=True)
        raise
    
    return _finish_case(job)


def execute_pending(directory, patterns, settings, records, *, worker_script,
                    pattern_info, execution_cases):
    """
    Coordinates queued tests and saves results
    """
    validate_settings(settings)

    done = {(row['pattern'], row['mode']) for row in records if row['success']}
    record_indices = {(row['pattern'], row['mode']): i for i, row in enumerate(records)}
    total = len(patterns) * len(MODES)

    if len(done) == total:
        print(f'All {total} tasks are already complete: {directory}')
        return directory

    monitor = require_monitor()
    gate = ResourceGate(settings, monitor)

    try:
        cpu_count = len(monitor.Process().cpu_affinity())
    except (AttributeError, monitor.Error):
        cpu_count = monitor.cpu_count() or 1
    cap = min(len(patterns), settings.get('max_parallel_patterns') or max(1, cpu_count))
    waiting = deque()

    for pattern in patterns:
        cases = deque(case for case in execution_cases(settings)
                      if (pattern.name, case[0]) not in done)
        if cases:
            size, excluded = pattern_info(pattern)
            waiting.append(dict(pattern=pattern, size=size, excluded=excluded, cases=cases))

    active = []

    print(f'Output: {directory} ({len(done)}/{total} complete)', flush=True)
    print(f'Adaptive targets: CPU {gate.cpu_target:g}%, RAM {gate.memory_target:g}% '
          f'(system-wide soft targets); parallel cap={cap}. At least one case runs. Ctrl+C stops workers.', flush=True)
    print('Existing elapsed_seconds includes measured PAS preparation; '
          'wall_seconds and preparation_seconds are also stored in results.jsonl.', flush=True)

    def record_result(state, case, result):
        """
        Updates and saves an individual test result
        """
        label, mode, limit = case
        record = dict(pattern_size=state['size'], pattern=state['pattern'].name,
                      mode=label, a_max=limit, excluded_total=state['excluded'],
                      step_delay=settings['step_delay'], **result)
        key = (state['pattern'].name, label)
        
        if key in record_indices:
            records[record_indices[key]] = record
        else:
            record_indices[key] = len(records)
            records.append(record)
        
        save_results(directory, records)
        
        if result['success']:
            done.add(key)
        
        print(f"[{len(done)}/{total}] {key[0]} / {label}: "
              f"{'OK' if result['success'] else result['error']}", flush=True)
        
        if state['cases']:
            waiting.append(state)

    last_report = float('-inf')
    
    try:
        while waiting or active:
            time.sleep(gate.interval)
            now = time.monotonic()
            gate.sample(now)
            for job in list(active):
                gate.observe_process(job['process'].pid)
                if job['process'].poll() is not None:
                    result = _finish_case(job)
                    active.remove(job)
                    record_result(job['state'], job['case'], result)
            if waiting and gate.can_start(now, len(active), cap):
                state = waiting.popleft()
                case = state['cases'].popleft()
                label, mode, limit = case
                pattern = state['pattern']
                gate.last_start = now
                try:
                    job = _start_case(pattern, mode, limit, settings['step_delay'],
                                      directory / f'{pattern.stem}_{label.lower()}', worker_script)
                except OSError as exc:
                    record_result(state, case, dict(success=False, excluded_removed=None,
                                  steps=None, elapsed_seconds=0.0, wall_seconds=0.0,
                                  preparation_seconds=0.0, error=str(exc)))
                else:
                    job.update(state=state, case=case)
                    active.append(job)
                    _open_log_window(job, f'{pattern.name} / {label}')
                    print(f'Start: {pattern.name} / {label}; running={len(active)}', flush=True)
            if now - last_report >= 10:
                print(f'CPU={gate.cpu:.1f}% (average {gate.average:.1f}%), '
                      f'RAM={gate.memory:.1f}%; running={len(active)}, '
                      f'waiting patterns={len(waiting)}. '
                      'Only additional work waits for resources; running simulations are never paused.', flush=True)
                last_report = now
    finally:
        for job in active:
            try:
                _stop_process_tree(job['process'], monitor)
            finally:
                job['output'].close()
                _viewer_status(job, 'stopped', 'Cancelled by main test process.')
                job['result_path'].unlink(missing_ok=True)
    
    if len(done) < total:
        print(f'{total - len(done)} task(s) failed; choose resume to retry them.')
    
    try:
        from boxplot import create_boxplots
        create_boxplots(directory)
    except (ImportError, ValueError) as exc:
        print(f'Plots were not generated: {exc}')
        print(f'python boxplot.py "{directory}"')
    
    return directory


if __name__ == '__main__':
    if len(sys.argv) == 6 and sys.argv[1] == '--watch-log':
        _watch_log(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))
    else:
        raise SystemExit('This module is used by auto_test.py; run auto_test.py to start tests.')
