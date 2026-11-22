"""
Defines and validates automatic-test settings.
Size -> (x, y, z)
Counts -> number of patterns for each size
"""
import math

PATTERNS = [
    {'size': (5, 5, 5), 'count': 20},
    {'size': (10, 10, 10), 'count': 20},
    {'size': (15, 15, 15), 'count': 20},
    {'size': (20, 20, 20), 'count': 20},
    {'size': (25, 25, 25), 'count': 20}
]

# PAS activation caps. None = disables the limit.
PAS_LIMITS = {'small': 2, 'medium': 7, 'max': None}
# Step interval in seconds; not used during PAS preparation.
STEP_DELAY = 0.2 
# None = Random seed
SEED = None

# Soft CPU target for starting new workers.
CPU_TARGET_PERCENT = 50.0
MEMORY_TARGET_PERCENT = 50.0
# None = uses the CPU-based cap
MAX_PARALLEL_PATTERNS = None
RESOURCE_SAMPLE_SECONDS = 1.0
# Minimum spacing between worker starts in seconds.
RAMP_UP_SECONDS = 10.0


def get_settings():
    """
    Collects and validates configured test parameters.
    - Output: settings dict
    """
    settings = {'patterns': PATTERNS, 'pas_limits': PAS_LIMITS,
                'step_delay': STEP_DELAY, 'seed': SEED,
                'cpu_target_percent': CPU_TARGET_PERCENT,
                'memory_target_percent': MEMORY_TARGET_PERCENT,
                'max_parallel_patterns': MAX_PARALLEL_PATTERNS,
                'resource_sample_seconds': RESOURCE_SAMPLE_SECONDS,
                'ramp_up_seconds': RAMP_UP_SECONDS}
    
    validate_settings(settings)
    return settings


def validate_settings(settings):
    """
    Checks test and resource-limit settings.
    """
    if not isinstance(settings, dict):
        raise ValueError('Settings must be an object')
    
    if not {'patterns', 'pas_limits', 'step_delay', 'seed'} <= settings.keys():
        raise ValueError('Settings require patterns, pas_limits, step_delay and seed')
    
    patterns = settings['patterns']
    limits = settings['pas_limits']
    delay = settings['step_delay']
    seed = settings['seed']
    
    if not isinstance(patterns, list) or not patterns:
        raise ValueError('PATTERNS must contain at least one size')
    sizes = set()

    for entry in patterns:
        if not isinstance(entry, dict) or not {'size', 'count'} <= entry.keys():
            raise ValueError('Each PATTERNS entry requires size and count')
        size, count = entry['size'], entry['count']
        if (not isinstance(size, (list, tuple)) or len(size) != 3
                or any(type(v) is not int or v < 1 for v in size)
    
                or size[2] < 2):
            raise ValueError('Pattern size must use integers: x >= 1, y >= 1, z >= 2')
        if tuple(size) in sizes:
            raise ValueError('Each pattern size must appear only once')
        sizes.add(tuple(size))
        if type(count) is not int or count < 1:
            raise ValueError('Pattern count must be a positive integer')
    
    if not isinstance(limits, dict) or set(limits) != {'small', 'medium', 'max'}:
        raise ValueError('PAS_LIMITS must contain small, medium and max')
    values = []
    
    for name in ('small', 'medium', 'max'):
        limit = limits[name]
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError('A_max must be a positive integer or None')
        values.append(float('inf') if limit is None else limit)
    
    if values != sorted(values):
        raise ValueError('A_max must satisfy small <= medium <= max')
    
    if type(delay) not in (int, float) or not math.isfinite(delay) or delay < 0:
        raise ValueError('STEP_DELAY must be finite and nonnegative')
    
    if seed is not None and type(seed) is not int:
        raise ValueError('SEED must be an integer or None')

    for key in ('cpu_target_percent', 'memory_target_percent'):
        value = settings.get(key, 50.0)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 100:
            raise ValueError(f'{key} must be in (0, 100]')
    
    for key, default in (('resource_sample_seconds', 1.0), ('ramp_up_seconds', 10.0)):
        value = settings.get(key, default)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{key} must be positive and finite')
    
    cap = settings.get('max_parallel_patterns')
    
    if cap is not None and (type(cap) is not int or cap < 1):
        raise ValueError('max_parallel_patterns must be a positive integer or None')
