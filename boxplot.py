"""
Produces plots and a summary from saved test results as .md file.
"""

import argparse
import math
import json
import time
from pathlib import Path
from statistics import fmean, median

from test_results import MODES, read_results, validate_records

COLORS = ('#557ca6', '#e7ad52', '#69a787', '#a67cb2')


def _log_progress(message):
    """
    Prints plot-generation progress.
    """
    print(f'[plot] {message}', flush=True)


def mode_label(mode, records):
    """
    Labels a simulation mode and its active limit.
    """
    if mode == 'SAS':
        return 'SAS'
    
    limits = {row['a_max'] for row in records if row['mode'] == mode}
    
    if len(limits) != 1:
        raise ValueError(f'{mode}: multiple A_max values found; cannot merge configurations')
    
    limit = next(iter(limits))
    value = 'unlimited' if limit is None else str(limit)
    
    return f'PAS {mode.split("_", 1)[-1]} (A_max={value})'


def sorted_a_max_values(rows):
    """
    Sorts distinct PAS active-module limits.
    """
    return sorted({row['a_max'] for row in rows},
                  key=lambda limit: (limit is None, 0 if limit is None else limit))


def plot_configurations(modes, records):
    """
    Plot configuration. Separates plot series by mode and PAS limit.
    """
    configurations = []
    
    for mode in modes:
        if mode == 'SAS':
            configurations.append((mode, None))
        else:
            rows = [row for row in records if row['mode'] == mode]
            configurations.extend((mode, limit) for limit in sorted_a_max_values(rows))
    
    return configurations


def configuration_label(mode, a_max):
    """
    Formats a plot configuration label.
    """
    if mode == 'SAS':
        return 'SAS'
    
    value = 'unlimited' if a_max is None else str(a_max)
    
    return f'PAS {mode.split("_", 1)[-1]} (A_max={value})'


def group_color(index, group_count, plt):
    """
    Assigns a color to a plot series.
    """
    if group_count <= len(COLORS):
        return COLORS[index]
    
    return plt.get_cmap('tab20', group_count)(index)


def numeric_value(row, field):
    """
    Validates a nonnegative numeric result field.
    """
    value = row.get(field)
    
    if value is None:
        return None
    
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        raise ValueError(f'Invalid {field} for {row["pattern"]} / {row["mode"]}: {value!r}')
    
    return value


def metric_values(rows, field):
    """
    Extracts valid values for one metric.
    """
    values = [numeric_value(row, field) for row in rows]

    return [value for value in values if value is not None]


def preparation_ratios(rows):
    """
    Calculates PAS preparation-time percentages (preparation_seconds / elapsed_seconds).
    """
    values = []

    for row in rows:
        preparation = numeric_value(row, 'preparation_seconds')
        elapsed = numeric_value(row, 'elapsed_seconds')
        if preparation is None or elapsed is None or elapsed == 0:
            continue  # 분모가 0이거나 필요한 값이 없으면 비율은 정의되지 않는다.
        if preparation > elapsed and not math.isclose(preparation, elapsed):
            raise ValueError(
                f'preparation_seconds exceeds elapsed_seconds for '
                f'{row["pattern"]} / {row["mode"]}'
            )
        values.append(min(preparation / elapsed, 1.0) * 100)
    
    return values


def format_stat(values, statistic, percent=False):
    """
    Formats a statistic with sample count.
    """
    if not values:
        return '— (n=0)'
    
    result = statistic(values)
    
    return f'{result:.2f}{"%" if percent else ""} (n={len(values)})'


def concurrent_counts(directory, row, progress=None):
    """
    Validates a PAS trace and measures active modules.
    """
    path = Path(directory) / f"{Path(row['pattern']).stem}_{row['mode'].lower()}_trace.jsonl"
    
    def fail(message):
        """
        Rejects an invalid PAS trace.
        """
        raise ValueError(f'{path.name}: {message}; output generation aborted')

    schedule = None
    summary = None
    last_steps = {}
    removed = set()
    counts = {}
    last_report = time.monotonic() if progress is not None else None
    
    try:
        with path.open(encoding='utf-8') as stream:
            for number, line in enumerate(stream, 1):
                if progress is not None and number % 10000 == 0:
                    now = time.monotonic()
                    if now - last_report >= 5:
                        progress(number)
                        last_report = now
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    fail(f'invalid JSON at line {number}')
                if not isinstance(event, dict) or summary is not None:
                    fail(f'invalid record at line {number}')
                if event.get('event') == 'schedule':
                    if schedule is not None or not isinstance(event.get('schedule'), list):
                        fail('invalid or duplicate schedule')
                    schedule = {}
                    for entry in event['schedule']:
                        if not isinstance(entry, dict):
                            fail('invalid schedule entry')
                        module = entry.get('PASmodule_id')
                        start = entry.get('PASactivation_time')
                        if (not isinstance(module, str) or not module or module in schedule
                                or type(start) is not int or start < 0):
                            fail('invalid module ID or activation time')
                        schedule[module] = start
                elif event.get('event') == 'summary':
                    summary = event
                else:
                    if schedule is None or event.get('result') not in ('moving', 'removed'):
                        fail(f'unexpected execution record at line {number}')
                    module, step = event.get('active_id'), event.get('step')
                    if (not isinstance(module, str) or module not in schedule
                            or type(step) is not int or module in removed):
                        fail(f'invalid module or step at line {number}')
                    expected = last_steps[module] + 1 if module in last_steps else schedule[module]
                    if step != expected:
                        fail(f'missing or duplicate step for {module}: expected {expected}, got {step}')
                    last_steps[module] = step
                    counts[step] = counts.get(step, 0) + 1
                    if event['result'] == 'removed':
                        removed.add(module)
    except OSError as exc:
        fail(f'required trace unavailable: {exc}')

    if schedule is None or summary is None:
        fail('missing schedule or completion summary')
    
    if summary.get('success') is not True or summary.get('steps') != row['steps']:
        fail('completion summary disagrees with results.jsonl')
    
    if removed != set(schedule):
        fail('incomplete module execution records')
    
    for field in ('excluded_total', 'excluded_removed'):
        if summary.get(field) != len(schedule):
            fail(f'invalid {field} in completion summary')
        if field in row and row[field] != summary[field]:
            fail(f'{field} disagrees with results.jsonl')
    
    if not schedule:
        return 0, 0, 0
    
    if max(counts) != row['steps']:
        fail('last execution step disagrees with results.jsonl')
    
    samples = row['steps'] - min(schedule.values()) + 1
    
    return samples, sum(counts.values()), max(counts.values())


def summary_text(directory, records, sizes, modes, progress=None):
    """
    Builds Markdown statistics (without writing a file).
    """
    grouped = {}
    configurations = plot_configurations(modes, records)
    pas_total = sum(row['mode'] != 'SAS' for row in records)
    pas_index = 0
    
    for row in records:
        for field in ('steps', 'elapsed_seconds'):
            if numeric_value(row, field) is None:
                raise ValueError(f'Missing {field}: {row["pattern"]} / {row["mode"]}')
        if row['mode'] == 'SAS':
            continue
        if numeric_value(row, 'preparation_seconds') is None:
            raise ValueError(f'Missing preparation_seconds: {row["pattern"]} / {row["mode"]}')
        preparation_ratios([row])
        pas_index += 1
        trace_name = f"{Path(row['pattern']).stem}_{row['mode'].lower()}_trace.jsonl"
        if progress is not None:
            progress(f'Checking PAS trace {pas_index}/{pas_total}: {trace_name}')
        trace_progress = (lambda lines: progress(
            f'Reading PAS trace {pas_index}/{pas_total}: {lines:,} lines ({trace_name})'
        )) if progress is not None else None
        samples, total, peak = concurrent_counts(directory, row, progress=trace_progress)
        if progress is not None:
            progress(f'Validated PAS trace {pas_index}/{pas_total}: {trace_name}')
        group = grouped.setdefault((row['pattern_size'], row['a_max']), [0, 0, 0, 0])
        group[0] += 1
        group[1] += samples
        group[2] += total
        group[3] = max(group[3], peak)

    if progress is not None:
        progress('Computing Average/Median statistics and Markdown tables...')
    
    delays = sorted({row['step_delay'] for row in records})
    lines = ['# Simulation Results', '',
             f'Step interval (s): {", ".join(str(v) for v in delays)}', '']
    
    for label, statistic in (('Average', fmean), ('Median', median)):
        lines += [f'## {label}', '',
                  '| Pattern size | Mode | Steps | Elapsed (s) | PAS preparation (s) | Preparation / PAS elapsed |',
                  '|:--|:--|--:|--:|--:|--:|']
        for size in sizes:
            for mode, a_max in configurations:
                rows = [row for row in records
                        if row['pattern_size'] == size and row['mode'] == mode
                        and (mode == 'SAS' or row['a_max'] == a_max)]
                if not rows:
                    continue
                steps = format_stat(metric_values(rows, 'steps'), statistic)
                elapsed = format_stat(metric_values(rows, 'elapsed_seconds'), statistic)
                preparation = ratio = 'N/A'
                if mode != 'SAS':
                    preparation = format_stat(metric_values(rows, 'preparation_seconds'), statistic)
                    ratios = preparation_ratios(rows)
                    ratio = format_stat(ratios, statistic, percent=True) if ratios else 'N/A (elapsed=0)'
                lines.append(f'| {size} | {configuration_label(mode, a_max)} | {steps} | {elapsed} | {preparation} | {ratio} |')
        lines += ['']
    
    lines += ['## PAS Concurrent Active Modules', '',
              '| Pattern size | A_max | Runs | Total sampled steps | Mean concurrent active modules | Max concurrent active modules |',
              '|:--|:--|--:|--:|--:|--:|']
    size_order = {size: index for index, size in enumerate(sizes)}
    
    for size, limit in sorted(
            grouped,
            key=lambda key: (size_order[key[0]], key[1] is None,
                             key[1] if key[1] is not None else 0)):
        runs, samples, total, peak = grouped[(size, limit)]
        # Mean and Max!
        mean = f'{total / samples:.2f}' if samples else 'N/A (no execution steps)'
        maximum = str(peak) if samples else 'N/A (no execution steps)'
        lines.append(
            f'| {size} | {"unlimited" if limit is None else limit} | '
            f'{runs} | {samples} | {mean} | {maximum} |'
        )
    if not grouped:
        lines += ['', 'No PAS runs in this result set.']
    
    lines += ['']
    
    return '\n'.join(lines)


def create_summaries(directory, records, sizes, modes):
    """
    Writes the Markdown summary.
    """
    text = summary_text(directory, records, sizes, modes)
    path = Path(directory) / 'result.md'
    
    path.write_text(text, encoding='utf-8')
    
    return [path]


def create_boxplots(directory):
    """
    Generates metric plots and the results.
    """
    directory = Path(directory)
    
    _log_progress(f'Reading results: {directory / "results.jsonl"}')
    
    records, _ = read_results(directory)
    
    _log_progress(f'Loaded {len(records)} runs; checking result records...')
    
    if not records:
        raise ValueError('No experiment results to plot')
    
    validate_records(records)
    
    failed = [row for row in records if not row['success']]
    
    if failed:
        first = failed[0]
        raise ValueError(
            f"Cannot generate plots: {len(failed)} failed result(s). "
            f"First: {first['pattern']} / {first['mode']}. "
            'Resume the test and resolve all failed results first.'
        )

    modes = [mode for mode in MODES if any(row['mode'] == mode for row in records)]
    configurations = plot_configurations(modes, records)

    _log_progress('Loading matplotlib...')
    
    import matplotlib

    matplotlib.use('Agg')
    
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    sizes = sorted({row['pattern_size'] for row in records},
                   key=lambda size: tuple(int(v) for v in size.split('x')))
    labels = [configuration_label(mode, limit) for mode, limit in configurations]
    colors = [group_color(index, len(configurations), plt)
              for index in range(len(configurations))]

    # Validate every required input before creating any Markdown or PNG.
    _log_progress('Validating inputs and preparing result.md...')
    report = summary_text(directory, records, sizes, modes, progress=_log_progress)
    _log_progress('Input validation complete; generating boxplots...')

    outputs = []
    
    for metric, ylabel, filename in (
        ('steps', 'Required steps', 'boxplot_steps.png'),
        ('elapsed_seconds', 'Elapsed time (s)', 'boxplot_time.png'),
    ):
        _log_progress(f'Rendering {filename}...')
        fig, ax = plt.subplots(figsize=(max(10, len(sizes) * 2.6), 6.5))
        for size_index, size in enumerate(sizes):
            spacing = min(0.2, 0.8 / len(configurations))
            for mode_index, (mode, a_max) in enumerate(configurations):
                rows = [row for row in records
                        if row['pattern_size'] == size and row['mode'] == mode
                        and (mode == 'SAS' or row['a_max'] == a_max)]
                values = metric_values(rows, metric)
                position = size_index + (mode_index - (len(configurations) - 1) / 2) * spacing
                if values:
                    plot = ax.boxplot([values], positions=[position], widths=spacing * 0.8,
                                      patch_artist=True, manage_ticks=False,
                                      medianprops={'color': '#222222'})
                    plot['boxes'][0].set_facecolor(colors[mode_index])
                ax.text(position, 0.98, f'{len(values)}/{len(rows)}',
                        transform=ax.get_xaxis_transform(), ha='center', va='top',
                        fontsize=8, color=colors[mode_index])
        ax.set_xticks(range(len(sizes)))
        ax.set_xticklabels(sizes)
        ax.set_xlim(-0.6, len(sizes) - 0.4)
        ax.set_yscale('log', base=10)
        ax.margins(y=0.18)
        ax.set_xlabel('Pattern size (x × y × z)')
        ax.set_ylabel(ylabel)
        ax.set_title('SAS / PAS — ' + ylabel)
        ax.grid(axis='y', alpha=0.25)
        ax.set_axisbelow(True)
        ax.legend(handles=[Patch(facecolor=color, label=label)
                           for color, label in zip(colors, labels)],
                  loc='upper center', bbox_to_anchor=(0.5, -0.12), ncol=2)
        delays = sorted({row['step_delay'] for row in records})
        note = f'Step interval (s): {", ".join(str(v) for v in delays)}.'
        fig.text(0.5, 0.02, note, ha='center', fontsize=9)
        fig.tight_layout(rect=(0, 0.1, 1, 1))
        path = directory / filename
        _log_progress(f'Saving {filename}...')
        fig.savefig(path, dpi=180)
        plt.close(fig)
        outputs.append(path)
        _log_progress(f'Saved: {path}')

    # For PAS only
    pas_rows = [row for row in records if row['mode'] != 'SAS']
    if pas_rows:
        filename = 'boxplot_preparation_ratio.png'
        _log_progress(f'Rendering {filename}...')
        limits = sorted_a_max_values(pas_rows)
        ratio_colors = [group_color(index, len(limits), plt)
                        for index in range(len(limits))]
        spacing = min(0.2, 0.8 / len(limits))
        fig, ax = plt.subplots(figsize=(max(10, len(sizes) * 2.6), 6.5))
        for size_index, size in enumerate(sizes):
            for limit_index, limit in enumerate(limits):
                rows = [row for row in pas_rows
                        if row['pattern_size'] == size and row['a_max'] == limit]
                values = preparation_ratios(rows)
                position = (size_index
                            + (limit_index - (len(limits) - 1) / 2) * spacing)
                if values:
                    plot = ax.boxplot([values], positions=[position],
                                      widths=spacing * 0.8,
                                      patch_artist=True, manage_ticks=False,
                                      medianprops={'color': '#222222'})
                    plot['boxes'][0].set_facecolor(ratio_colors[limit_index])
                ax.text(position, 0.98, f'{len(values)}/{len(rows)}',
                        transform=ax.get_xaxis_transform(), ha='center', va='top',
                        fontsize=8, color=ratio_colors[limit_index])

        ax.set_xticks(range(len(sizes)))
        ax.set_xticklabels(sizes)
        ax.set_xlim(-0.6, len(sizes) - 0.4)
        ax.set_ylim(0, 40)  # Space for n/total
        ax.set_yticks(range(0, 41, 5))
        ax.set_yticklabels([f'{value}%' for value in range(0, 41, 5)])
        ax.set_xlabel('Pattern size (x × y × z)')
        ax.set_ylabel('Preparation / elapsed time (%)')
        ax.set_title('PAS — Preparation / elapsed time by A_max')
        ax.grid(axis='y', alpha=0.25)
        ax.set_axisbelow(True)
        ax.legend(handles=[
            Patch(facecolor=color,
                  label=f'A_max={"unlimited" if limit is None else limit}')
            for color, limit in zip(ratio_colors, limits)
        ], loc='upper center', bbox_to_anchor=(0.5, -0.12),
            ncol=min(4, len(limits)))

        delays = sorted({row['step_delay'] for row in records})
        note = f'Step interval (s): {", ".join(str(v) for v in delays)}.'
        fig.text(0.5, 0.02, note, ha='center', fontsize=9)
        fig.tight_layout(rect=(0, 0.1, 1, 1))
        path = directory / filename
        _log_progress(f'Saving {filename}...')
        fig.savefig(path, dpi=180)
        plt.close(fig)
        outputs.append(path)
        _log_progress(f'Saved: {path}')

    report_path = directory / 'result.md'

    _log_progress('Saving result.md...')
    report_path.write_text(report, encoding='utf-8')
    outputs.append(report_path)
    _log_progress(f'Saved: {report_path}')
    _log_progress('Finished generating plots and result.md.')
    
    return outputs


def main():
    """
    Starts plot generation from the command line.
    - Output: plot/report files and status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('test_directory', help='Folder containing results.jsonl')
    args = parser.parse_args()
    
    try:
        for path in create_boxplots(args.test_directory):
            print(path)
    except ImportError:
        parser.error('matplotlib is required: python -m pip install matplotlib')
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()