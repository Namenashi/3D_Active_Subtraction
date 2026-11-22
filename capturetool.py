"""
Processes captured VPython screenshots.
"""

import argparse
import glob
import os
import shutil
import sys


def _visual_frame_order(visual_path):
    """
    Builds a sort key from a screenshot filename.
    """
    visual_name = os.path.basename(visual_path)
    visual_stem = os.path.splitext(visual_name)[0]
    visual_step = visual_stem.rsplit('_', 1)[-1]
    
    if visual_step.isdigit():
        return (0, int(visual_step), visual_name)
    
    return (1, 0, visual_name)


def _visual_find_frames(visual_dir, visual_pattern):
    """
    Finds screenshots in frame order.
    """
    visual_dir = os.path.expanduser(visual_dir)
    visual_search = os.path.join(visual_dir, visual_pattern)
    
    return sorted(glob.glob(visual_search), key=_visual_frame_order)


def visual_move_pngs(src_dir, dst_dir, pattern='sas_step_*.png'):
    """
    Moves captured PNGs to a results directory.
    """
    src_dir = os.path.expanduser(src_dir)
    dst_dir = os.path.expanduser(dst_dir)

    os.makedirs(dst_dir, exist_ok=True)

    files = _visual_find_frames(src_dir, pattern)
    moved = 0

    for src in files:
        dst = os.path.join(dst_dir, os.path.basename(src))
        shutil.move(src, dst)
        moved += 1

    return moved

def visual_cleanup_pngs(target_dir, pattern='sas_step_*.png'):
    """
    Removes PNGs matching a capture pattern.
    """
    target_dir = os.path.expanduser(target_dir)
    search = os.path.join(target_dir, pattern)
    files = glob.glob(search)
    visual_removed = 0
    
    for visual_path in files:
        try:
            os.remove(visual_path)
        except OSError:
            continue
        visual_removed += 1

    return visual_removed


def visual_make_gif(image_dir, output_path, pattern='sas_step_*.png', fps=8):
    """
    Combines ordered PNGs into a single GIF.
    """
    try:
        import imageio.v2 as imageio
    except ImportError:
        print("imageio is required: pip install imageio", file=sys.stderr)
        return 0, None

    files = _visual_find_frames(image_dir, pattern)

    if not files:
        return 0, None

    frames = []
    
    for visual_path in files:
        frames.append(imageio.imread(visual_path))

    imageio.mimsave(output_path, frames, fps=fps)

    return len(files), output_path

def _visual_cli():
    """
    Runs the screenshot-to-GIF command.
    """
    parser = argparse.ArgumentParser(
        description='Generate a GIF from a screenshot directory (manual run)'
    )
    parser.add_argument(
        'image_dir',
        help='Directory containing PNG files'
    )
    parser.add_argument(
        '--pattern', default='sas_step_*.png',
        help='Image glob pattern (default: sas_step_*.png)'
    )
    parser.add_argument(
        '--output', default=None,
        help='Output filename (default: {image_dir}/simulation.gif)'
    )
    parser.add_argument(
        '--fps', type=int, default=8,
        help='Frames per second (default: 8)'
    )

    args = parser.parse_args()
    output = args.output or os.path.join(args.image_dir, 'simulation.gif')
    n, path = visual_make_gif(args.image_dir, output, args.pattern, args.fps)

    if n == 0:
        print(f"Error: no matching files in {args.image_dir}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Done: {n} frames → {path}")


if __name__ == '__main__':
    _visual_cli()
