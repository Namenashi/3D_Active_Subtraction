"""
Generate patterns. Runs and resumes SAS/PAS comparison tests.
- Output: test results!
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import random
import re
import shutil
import sys
import time

from auto_test_config import get_settings, validate_settings
from converter_3d import generator_load_pattern
from generator import generate_unique_pattern
from grid_3d import Grid
from test_results import MODES, read_results, validate_records, save_results

BASE_DIR = Path(__file__).resolve().parent


def pattern_info(path):
    """
    Reads pattern dimensions and excluded-module count.
    """
    pattern = generator_load_pattern(path)
    size = (pattern['width'], pattern['height'], pattern['depth'])
    total = sum(kind == Grid.EXCLUDED for kind in pattern['modules'].values())
    
    return 'x'.join(str(value) for value in size), total


def create_test_directory(root):
    """
    Creates the next numbered test directory.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    numbers = []
    
    for path in root.iterdir():
        match = re.fullmatch(r'test_(\d+)', path.name)
        if match:
            numbers.append(int(match.group(1)))
    number = max(numbers, default=0) + 1
    
    while True:
        directory = root / f'test_{number:04d}'
        try:
            directory.mkdir()
            return directory
        except FileExistsError:
            number += 1


def prepare_patterns(directory, settings, source_files=None):
    """
    Copies or generates test patterns in directory.
    """
    paths = []
    
    if source_files is not None:
        for source in source_files:
            target = directory / source.name
            shutil.copy2(source, target)
            paths.append(target)
        return paths

    rng = random.Random(settings['seed'])
    seen = set()
    
    for entry in settings['patterns']:
        size = entry['size']
        label = 'x'.join(str(value) for value in size)
        for index in range(1, entry['count'] + 1):
            path = directory / f'pattern_{label}_{index:04d}.txt'
            path.write_text(generate_unique_pattern(size, seen, rng), encoding='utf-8')
            paths.append(path)
            print(f'Generated: {path.name}', flush=True)
    
    return paths


def _worker(args):
    """
    Runs one simulation and saves its measurements. Save result JSON file and trace.
    """
    from simulator import SimulationRun

    run = SimulationRun(args.pattern, args.mode, args.trace_path, args.pas_max_active)
    started = time.monotonic()
    result = {'success': False, 'excluded_removed': None, 'steps': None, 'error': ''}
    
    try:
        instance = run.prepare()
        instance.simulator_simulated_step_seconds = args.step_delay
        instance.simulator_run(0.0)
        result['error'] = instance.simulator_error_msg or ''
        result['success'] = (
            instance.simulator_finished and not result['error']
            and not instance.simulator_grid.get_excluded_positions()
        )
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        result['wall_seconds'] = time.monotonic() - started
        result['elapsed_seconds'] = result['wall_seconds']
        result['preparation_seconds'] = 0.0
        if run.instance is not None:
            instance = run.instance
            result['excluded_removed'] = instance.simulator_removed_module
            result['steps'] = instance.simulator_step_count
            result['preparation_seconds'] = getattr(instance, 'simulator_preparation_seconds', 0.0)
            measured = instance.simulator_result()
            if measured['success']:
                result['elapsed_seconds'] = measured['elapsed_seconds']
                instance.simulator_log_summary()
            instance._log_close_stream()
        Path(args.result_path).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')


def run_case(pattern, mode, limit, delay, prefix):
    """
    Delegates a test case to an isolated runner.
    """
    from parallel_test_runner import run_case as run_parallel_case
    
    return run_parallel_case(pattern, mode, limit, delay, prefix, worker_script=__file__)


def resolve_test_folder(name, root=None):
    """
    Finds a test folder under the allowed root.
    """
    root = Path(root or BASE_DIR / 'test').resolve()
    
    if (not isinstance(name, str) or not name.strip() or name in ('.', '..')
            or '/' in name or '\\' in name):
        raise ValueError('Enter only a folder name inside test, for example test_0001')
    directory = (root / name).resolve()
    
    if directory.parent != root or not directory.is_dir():
        raise ValueError(f'Folder not found inside test: {name}')
    
    return directory


def collect_patterns(directory):
    """
    Validates and lists pattern files.
    """
    paths = sorted(path for path in Path(directory).iterdir()
                   if path.is_file() and path.suffix.lower() == '.txt')
    
    if not paths:
        raise ValueError('No .txt patterns in the selected folder')
    
    for path in paths:
        pattern_info(path)
    
    return paths


def execution_cases(settings):
    """
    Validates and lists pattern files for SAS or/and PAS test.
    """
    cases = [('SAS', 'SAS', None)]
    cases.extend((f'PAS_{name}', 'PAS', settings['pas_limits'][name])
                 for name in ('small', 'medium', 'max'))
    
    return cases


def execute_pending(directory, patterns, settings, records):
    """
    Schedules unfinished test cases.
    """
    from parallel_test_runner import execute_pending as run_pending
    
    return run_pending(directory, patterns, settings, records,
                       worker_script=__file__, pattern_info=pattern_info,
                       execution_cases=execution_cases)


def run_tests(settings, source_dir=None, output_root=None):
    """
    Creates and executes a new test batch.
    """
    validate_settings(settings)
    
    from parallel_test_runner import require_monitor
    
    require_monitor()
    
    root = Path(output_root or BASE_DIR / 'test').resolve()
    source = resolve_test_folder(source_dir, root) if source_dir is not None else None
    source_files = collect_patterns(source) if source is not None else None
    directory = create_test_directory(root)
    snapshot = dict(settings, source_dir=str(source) if source else None,
                    started_at=datetime.datetime.now().astimezone().isoformat())
    
    (directory / 'settings.json').write_text( json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
    
    patterns = prepare_patterns(directory, settings, source_files)
    
    save_results(directory, [])
    
    return execute_pending(directory, patterns, settings, [])


def resume_tests(folder_name, output_root=None):
    """
    Validates and resumes an existing test batch.
    """
    directory = resolve_test_folder(folder_name, output_root)
    settings = json.loads((directory / 'settings.json').read_text(encoding='utf-8'))
    validate_settings(settings)
    patterns = collect_patterns(directory)
    
    if settings.get('source_dir') is None:
        expected = []
        for entry in settings['patterns']:
            label = 'x'.join(str(value) for value in entry['size'])
            expected.extend(f'pattern_{label}_{index:04d}.txt'
                            for index in range(1, entry['count'] + 1))
        if set(expected) != {path.name for path in patterns}:
            raise ValueError('Generated pattern files do not match settings.json; pattern preparation is incomplete or files changed')
        patterns = [directory / name for name in expected]
    
    result_path = directory / 'results.jsonl'
    records, incomplete_tail = [], False
    
    if result_path.exists():
        records, incomplete_tail = read_results(directory, recover_tail=True)
    elif (directory / 'results.csv').exists():
        raise ValueError('results.jsonl is missing; cannot safely determine completed tasks from CSV alone')
    
    validate_records(records, for_resume=True)
    
    info = {path.name: pattern_info(path) for path in patterns}
    limits = {label: limit for label, mode, limit in execution_cases(settings)}
    
    for row in records:
        if row['pattern'] not in info:
            raise ValueError(f"Pattern file missing for result: {row['pattern']}")
        size, total = info[row['pattern']]
        if row['pattern_size'] != size or row['excluded_total'] != total:
            raise ValueError(f"Pattern contents disagree with saved result: {row['pattern']}")
        if row['a_max'] != limits[row['mode']] or row['step_delay'] != settings['step_delay']:
            raise ValueError('Saved results disagree with settings.json (A_max or step interval)')
    
    if incomplete_tail:
        print('Ignoring an unfinished final JSON line; that task will run again.')
    
    save_results(directory, records)
    
    return execute_pending(directory, patterns, settings, records)


def main():
    """
    Dispatches test generation, resume, and plotting commands.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    start = parser.add_mutually_exclusive_group()
    start.add_argument('--generate', action='store_true', help='Generate patterns using auto_test_config.py')
    start.add_argument('--patterns-dir', help='New test using a folder NAME inside test')
    start.add_argument('--resume', help='Resume a folder NAME inside test')
    start.add_argument('--plot-only', help='Plot a folder NAME inside test without simulation')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--pattern', help=argparse.SUPPRESS)
    parser.add_argument('--mode', choices=('SAS', 'PAS'), help=argparse.SUPPRESS)
    parser.add_argument('--trace-path', help=argparse.SUPPRESS)
    parser.add_argument('--result-path', help=argparse.SUPPRESS)
    parser.add_argument('--step-delay', type=float, help=argparse.SUPPRESS)
    parser.add_argument('--pas-max-active', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    
    if args.worker:
        _worker(args)
        return
    
    try:
        if not any((args.generate, args.patterns_dir, args.resume, args.plot_only)):
            choice = input('Mode (1: New, 2: Resume, 3: Plot only): ').strip()
            if choice == '1':
                source_choice = input('Patterns (1: Generate new, 2: Use existing patterns): ').strip()
                if source_choice == '1':
                    args.generate = True
                elif source_choice == '2':
                    args.patterns_dir = input('Pattern folder name: ').strip()
                    if not args.patterns_dir:
                        raise ValueError('Enter a folder name')
                else:
                    raise ValueError('Choose 1 or 2')
            elif choice in ('2', '3'):
                name = input('Folder name: ').strip()
                if not name:
                    raise ValueError('Enter a folder name')
                if choice == '2':
                    args.resume = name
                else:
                    args.plot_only = name
            else:
                raise ValueError('Choose 1, 2 or 3')
        if args.plot_only is not None:
            from boxplot import create_boxplots
            for path in create_boxplots(resolve_test_folder(args.plot_only)):
                print(path)
            return
        if args.resume is not None:
            directory = resume_tests(args.resume)
        else:
            directory = run_tests(get_settings(), args.patterns_dir)
        print(f'Completed: {directory}')
    except KeyboardInterrupt:
        print('Stopped. Completed results are saved; use --resume to continue.')
    except ImportError:
        parser.error('Plots require matplotlib: python -m pip install matplotlib')
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
