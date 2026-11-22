"""
Main enter point. Launches SAS/PAS simulation and optional visual capture.
"""

import argparse
import datetime
import os
import sys
import time
import capturetool

def _visual_parse_args():
    """
    Parses and validates simulation command-line options
    """
    parser = argparse.ArgumentParser(
        description='SAS/PAS Modular Robot Simulator (3D)'
    )
    parser.add_argument(
        'pattern', nargs='?', default=None,
        help='Pattern file (default: patterns/0000.txt)'
    )
    parser.add_argument(
        'mode',
        nargs='?',
        default='SAS',
        type=str.upper,
        choices=('SAS', 'PAS'),
        help='Execution mode: SAS or PAS (default: SAS)',
    )
    parser.add_argument(
        '--run-dir', default=None,
        help='Output directory (default: runs/run_<timestamp>_<mode>_3d)'
    )
    parser.add_argument(
        '--downloads-dir', default='~/Downloads',
        help='[3D] Browser downloads directory'
    )
    parser.add_argument('--fps', type=int, default=8, help='GIF FPS')
    parser.add_argument(
        '--step-delay', type=float, default=0.2,
        help='[3D] Delay between steps in seconds'
    )
    parser.add_argument('--no-capture', action='store_true', help='Disable screenshots and GIF')
    parser.add_argument('--auto-start', action='store_true', help='Start without pressing Space')
    parser.add_argument(
        '--pas-max-active',
        type=int,
        default=None,
        help='[PAS] Maximum number of simultaneously active modules (default: unlimited)',
    )
    args = parser.parse_args()

    import math

    if not math.isfinite(args.step_delay) or args.step_delay < 0:
        parser.error('--step-delay must be finite and nonnegative')

    if args.fps <= 0:
        parser.error('--fps must be positive')

    if args.pas_max_active is not None and args.pas_max_active < 1:
        parser.error('--pas-max-active must be at least 1')

    return args

def _visual_make_run_dir(visual_arg_run_dir, visual_mode='SAS'):
    """
    Creates the simulation output directory
    """
    if visual_arg_run_dir:
        visual_path = visual_arg_run_dir
    else:
        visual_timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        visual_path = f'runs/run_{visual_timestamp}_{visual_mode.lower()}_3d'

    os.makedirs(visual_path, exist_ok=True)
    
    return visual_path

def _launcher_start_time(default):
    """
    Reads an optional launcher start timestamp
    """
    raw = os.environ.get('SIMULATION_LAUNCHER_START_TIME')
    
    if raw is None:
        return default
    
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    
    import math
    
    return value if math.isfinite(value) else default

def _visual_run_3d(visual_args, visual_run_dir):
    """
    Executes and visualizes a 3D simulation
    """
    from simulator import SimulationRun

    visual_downloads = os.path.expanduser(visual_args.downloads_dir)

    if visual_args.no_capture:
        pass
    elif os.path.isdir(visual_downloads):
        visual_capture_prefix = f'{visual_args.mode.lower()}_step'
        visual_cleaned = capturetool.visual_cleanup_pngs(
            visual_downloads,
            f'{visual_capture_prefix}_*.png',
        )
        if visual_cleaned:
            print(
                'Downloads cleanup: removed '
                f'{visual_cleaned} previous '
                f'{visual_capture_prefix}_*.png files'
            )
    else:
        print(
            f"Error: downloads directory not found: {visual_downloads}",
            file=sys.stderr,
        )
        print(
            'Specify a valid path with --downloads-dir.',
            file=sys.stderr,
        )
        sys.exit(1)

    _log_trace_path = os.path.join(
        visual_run_dir,
        f'{visual_args.mode.lower()}_trace.jsonl',
    )
    run = SimulationRun(
        visual_args.pattern, visual_args.mode, _log_trace_path,
        visual_args.pas_max_active,
    )
    preparation_started = time.monotonic()
    simulator_instance = run.prepare()
    simulator_instance.simulator_wall_preparation_seconds = time.monotonic() - preparation_started
    simulator_instance.simulator_simulated_step_seconds = visual_args.step_delay

    print(f"\nRun directory: {visual_run_dir}")
    
    if visual_args.auto_start:
        print('Simulation starts automatically in the browser.')
    else:
        print('Press Space in the browser window to start the simulation.')
    
    if not visual_args.no_capture:
        print(f"Downloads directory: {visual_downloads}")
        print('Each step is captured; PNGs and GIF are saved after completion.')
    else:
        print('Screenshots and GIF disabled. JSONL trace is still saved.')

    from visualizer_vpython import Visualizer

    visualizer = Visualizer(
        simulator_instance,
        step_delay=visual_args.step_delay,
        capture_prefix=f'{visual_args.mode.lower()}_step',
        PAS_mode=(visual_args.mode == 'PAS'),
        capture_enabled=not visual_args.no_capture,
        auto_start=visual_args.auto_start,
    )
    
    try:
        visualizer.visual_run()
    except Exception as exc:
        if visual_args.mode == 'PAS':
            simulator_instance.PAS_log_error(repr(exc))
        else:
            simulator_instance._log_error(repr(exc))
        raise
    finally:
        simulator_instance._log_close_stream()

    run.report()

    if visual_args.no_capture:
        return

    print(f"\nMoving PNG files: {visual_downloads} → {visual_run_dir}")
    
    visual_moved = capturetool.visual_move_pngs(
        visual_downloads,
        visual_run_dir,
        f'{visual_args.mode.lower()}_step_*.png',
    )
    
    print(f"{visual_moved} PNG files moved")

    if visual_moved:
        visual_gif_path = os.path.join(visual_run_dir, 'simulation.gif')
        print(f"Generating GIF: {visual_gif_path}")
        visual_frame_count, _ = capturetool.visual_make_gif(
            visual_run_dir,
            visual_gif_path,
            pattern=f'{visual_args.mode.lower()}_step_*.png',
            fps=visual_args.fps,
        )
        if visual_frame_count:
            print(f"Done: {visual_frame_count} frames → {visual_gif_path}")
        else:
            print('Error: failed to generate GIF')
    else:
        print('Error: no PNG files were moved. Check the downloads directory path.')


def _simulator_main():
    """
    Dispatches the launcher or CLI simulation
    """
    if len(sys.argv) == 1:
        from launcher import launch
        launch()
        return
    
    visual_args = _visual_parse_args()

    if visual_args.pattern is None:
        visual_args.pattern = 'patterns/0000.txt'
    elif not visual_args.pattern.endswith('.txt'):
        visual_args.pattern = os.path.join(
            'patterns',
            f'{visual_args.pattern}.txt',
        )

    if not os.path.exists(visual_args.pattern):
        print(
            f"Error: pattern file not found: {visual_args.pattern}",
            file=sys.stderr,
        )
        sys.exit(1)

    visual_run_dir = _visual_make_run_dir(
        visual_args.run_dir,
        visual_args.mode,
    )
    
    _visual_run_3d(visual_args, visual_run_dir)

if __name__ == '__main__':
    _simulator_main()
