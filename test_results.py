"""
Reads, validates, and saves automatic-test results.
"""
import csv
import json
import math
import os
from pathlib import Path
import re

MODES = ('SAS', 'PAS_small', 'PAS_medium', 'PAS_max')
RESULT_FIELDS = [
    'pattern_size', 'pattern', 'mode', 'a_max', 'success',
    'excluded_removed', 'excluded_total', 'steps', 'elapsed_seconds',
    'step_delay', 'error',
]
PLOT_FIELDS = {'pattern_size', 'pattern', 'mode', 'a_max', 'success',
               'steps', 'elapsed_seconds', 'step_delay'}


def read_results(directory, recover_tail=False):
    """
    Reads JSONL results with optional truncated-tail recovery.
    """
    path = Path(directory) / 'results.jsonl'
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    records = []
    incomplete_tail = False
    
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            if recover_tail and number == len(lines) and not line.endswith('\n'):
                incomplete_tail = True
                break
            raise ValueError(f'{path.name} line {number}: invalid JSON') from exc
        records.append(record)
    
    return records, incomplete_tail


def _nonnegative_number(value):
    """
    Checks for a finite nonnegative numeric value.
    """
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validate_records(records, for_resume=False):
    """
    Validates test result records and consistency.
    """
    required = set(RESULT_FIELDS) if for_resume else PLOT_FIELDS
    seen = set()
    pattern_sizes = {}
    mode_limits = {}

    for number, row in enumerate(records, 1):
        prefix = f'Result {number}: '
        if not isinstance(row, dict):
            raise ValueError(prefix + 'expected an object')
        missing = required - row.keys()
        if missing:
            raise ValueError(prefix + 'missing fields: ' + ', '.join(sorted(missing)))
        size = row['pattern_size']
        if not isinstance(size, str) or not re.fullmatch(r'[1-9]\d*x[1-9]\d*x[1-9]\d*', size):
            raise ValueError(prefix + 'pattern_size must look like 5x5x5')
        name = row['pattern']
        if not isinstance(name, str) or not name or '/' in name or '\\' in name:
            raise ValueError(prefix + 'pattern must be a file name')
        mode = row['mode']
        if mode not in MODES:
            raise ValueError(prefix + 'unknown mode')
        if type(row['success']) is not bool:
            raise ValueError(prefix + 'success must be true or false')
        limit = row['a_max']
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError(prefix + 'a_max must be a positive integer or null')
        if mode == 'SAS' and limit is not None:
            raise ValueError(prefix + 'SAS a_max must be null')
        if mode in mode_limits and mode_limits[mode] != limit:
            raise ValueError(prefix + f'inconsistent a_max for {mode}')
        mode_limits[mode] = limit
        steps = row['steps']
        if not (steps is None and not row['success']):
            if type(steps) is not int or steps < 0:
                raise ValueError(prefix + 'steps must be a nonnegative integer')
        for field in ('elapsed_seconds', 'step_delay'):
            if not _nonnegative_number(row[field]):
                raise ValueError(prefix + field + ' must be a finite nonnegative number')
        key = (name, mode)
        if key in seen:
            raise ValueError(prefix + f'duplicate task: {name} / {mode}')
        seen.add(key)
        if name in pattern_sizes and pattern_sizes[name] != size:
            raise ValueError(prefix + 'inconsistent size for the same pattern')
        pattern_sizes[name] = size
        if for_resume:
            total, removed = row['excluded_total'], row['excluded_removed']
            if type(total) is not int or total < 0:
                raise ValueError(prefix + 'invalid excluded_total')
            if not (removed is None and not row['success']):
                if type(removed) is not int or not 0 <= removed <= total:
                    raise ValueError(prefix + 'invalid excluded_removed')
            if not isinstance(row['error'], str):
                raise ValueError(prefix + 'error must be text')
            if row['success'] and (removed != total or row['error']):
                raise ValueError(prefix + 'success conflicts with removal count or error')


def save_results(directory, records):
    """
    Writes JSONL and CSV test results.
    """
    directory = Path(directory)
    
    for filename in ('results.jsonl', 'results.csv'):
        path = directory / filename
        temporary = directory / (filename + '.tmp')
        encoding = 'utf-8' if filename.endswith('jsonl') else 'utf-8-sig'
        try:
            with temporary.open('w', encoding=encoding, newline='') as output:
                if filename.endswith('jsonl'):
                    for record in records:
                        output.write(json.dumps(record, ensure_ascii=False) + '\n')
                else:
                    writer = csv.DictWriter(output, fieldnames=RESULT_FIELDS)
                    writer.writeheader()
                    for record in records:
                        writer.writerow({field: record[field] for field in RESULT_FIELDS})
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
