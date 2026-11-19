"""Correlated finite-step/point Gaussian source and independent box-time oracle.

Coordinates are um, time is s, charge is fC. generation() returns cm^-3 s^-1.
The path parameter couples position and time; neither coordinate is compressed.
"""
import json
import math
from pathlib import Path
import re

import common

SCHEMA = 'nuclear-closure-source-r1'
MAGIC = 'NUCLEAR_CLOSURE_SOURCE_V1'
E_C = 1.602176634e-19
W_UM = .03
SIGMA_S = 2e-12
SQRT_PI = math.sqrt(math.pi)
SQRT2 = math.sqrt(2.)
STEP_KEYS = {'uid', 'r0_um', 'r1_um', 't0_s', 't1_s', 'charge_fC', 'w_um', 'sigma_s', 'kind', 'provenance'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def _finite(value, name):
    require(type(value) in (int, float) and math.isfinite(value), 'Nonfinite/non-numeric ' + name)
    return float(value)


def _json_tree(value):
    if isinstance(value, dict):
        require(all(isinstance(k, str) for k in value), 'Metadata keys must be strings')
        for v in value.values():
            _json_tree(v)
    elif isinstance(value, list):
        for v in value:
            _json_tree(v)
    elif type(value) is float:
        require(math.isfinite(value), 'Nonfinite metadata')
    else:
        require(value is None or type(value) in (str, int, bool), 'Non-JSON metadata')


def validate_source(source):
    require(isinstance(source, dict) and set(source) == {'schema', 'geometry_sha256', 'steps', 'provenance'}, 'Source top-level fields differ')
    require(source['schema'] == SCHEMA, 'Unknown source schema')
    require(source['geometry_sha256'] == common.contract()['geometry']['sha256'] == common.sha(common.GEOMETRY), 'Source geometry differs')
    require(isinstance(source['steps'], list) and isinstance(source['provenance'], dict), 'Missing source steps/provenance')
    _json_tree(source['provenance'])
    seen = set()
    for step in source['steps']:
        require(isinstance(step, dict) and set(step) == STEP_KEYS, 'Source step fields differ')
        uid = step['uid']
        require(isinstance(uid, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', uid) and uid not in seen, 'Unsafe/duplicate source UID')
        seen.add(uid)
        for key in ('r0_um', 'r1_um'):
            require(isinstance(step[key], (list, tuple)) and len(step[key]) == 3, 'Source endpoint must have xyz')
            for value in step[key]:
                _finite(value, key)
        for key in ('t0_s', 't1_s', 'charge_fC', 'w_um', 'sigma_s'):
            _finite(step[key], key)
        require(0 <= step['t0_s'] <= step['t1_s'], 'Source times must be ordered and nonnegative')
        require(step['charge_fC'] > 0, 'Zero/negative energy belongs in the ledger, not an active source')
        require(step['w_um'] == W_UM and step['sigma_s'] == SIGMA_S, 'Source width/time model differs from the frozen assumption')
        point = list(step['r0_um']) == list(step['r1_um'])
        require(step['kind'] == ('point' if point else 'segment'), 'Point/segment kind does not match actual endpoints')
        require(isinstance(step['provenance'], dict), 'Step provenance must be explicit')
        _json_tree(step['provenance'])
    return {'schema': SCHEMA, 'step_count': len(seen), 'total_charge_fC': math.fsum(s['charge_fC'] for s in source['steps']),
            'geometry_sha256': source['geometry_sha256'], 'kernel': 'correlated-endpoint-gaussian-r1'}


def _normal_number(value):
    value = float(value)
    return 0. if value == 0 else value


def _sort_key(step):
    return tuple(step['r0_um'] + step['r1_um']) + tuple(step[k] for k in ('t0_s', 't1_s', 'charge_fC', 'w_um', 'sigma_s')) + (step['uid'],)


def canonical_source(source):
    validate_source(source)
    value = json.loads(json.dumps(source, sort_keys=True, allow_nan=False))
    for step in value['steps']:
        for key in ('r0_um', 'r1_um'):
            step[key] = [_normal_number(x) for x in step[key]]
        for key in ('t0_s', 't1_s', 'charge_fC', 'w_um', 'sigma_s'):
            step[key] = _normal_number(step[key])
    value['steps'].sort(key=_sort_key)
    return value


def native_bytes(source):
    value = canonical_source(source)
    lines = [MAGIC + ' ' + str(len(value['steps']))]
    for step in value['steps']:
        row = step['r0_um'] + step['r1_um'] + [step[k] for k in ('t0_s', 't1_s', 'charge_fC', 'w_um', 'sigma_s')]
        lines.append(' '.join(format(x, '.17g') for x in row))
    return ('\n'.join(lines) + '\n').encode('ascii')


def write_native(source, path):
    data = native_bytes(source)
    path = Path(path)
    with path.open('xb') as stream:
        stream.write(data)
    return {'path': str(path), 'sha256': common.sha(path), 'steps': len(source['steps']), 'bytes': len(data), 'format': MAGIC}


def _erf_difference(lo, hi):
    if lo >= 0:
        return math.erfc(lo) - math.erfc(hi)
    if hi <= 0:
        return math.erfc(-hi) - math.erfc(-lo)
    return math.erf(hi) - math.erf(lo)


def _density(step, xyz, time_s):
    w, sigma = step['w_um'], step['sigma_s']
    offset = [(xyz[i] - step['r0_um'][i]) / w for i in range(3)] + [(time_s - step['t0_s']) / (SQRT2 * sigma)]
    delta = [(step['r1_um'][i] - step['r0_um'][i]) / w for i in range(3)] + [(step['t1_s'] - step['t0_s']) / (SQRT2 * sigma)]
    length = math.hypot(*delta)
    if length < 1e-7:
        # Quadrature avoids cancellation in the analytic point limit.
        integral = math.fsum(weight * math.exp(-math.fsum((offset[j] - u * delta[j]) ** 2 for j in range(4)))
                             for u, weight in _gauss_unit(16))
    else:
        direction = [d / length for d in delta]
        parallel = math.fsum(a * b for a, b in zip(offset, direction))
        perpendicular2 = math.fsum((a - parallel * b) ** 2 for a, b in zip(offset, direction))
        integral = math.exp(-perpendicular2) * SQRT_PI / (2 * length) * _erf_difference(-parallel, length - parallel)
    normalization = 1 / (math.pi ** 1.5 * w ** 3 * math.sqrt(2 * math.pi) * sigma)
    return step['charge_fC'] * 1e-15 / E_C * 1e12 * normalization * integral


def generation(source, xyz_um, time_s):
    value = canonical_source(source)
    require(len(xyz_um) == 3, 'Observation must have xyz')
    xyz = [_finite(x, 'observation xyz') for x in xyz_um]
    time_s = _finite(time_s, 'observation time')
    result = math.fsum(_density(step, xyz, time_s) for step in value['steps'])
    require(math.isfinite(result) and result >= 0, 'Invalid generation rate')
    return result


def _average_breakpoints(step, xyz, window):
    points = set(_breakpoints(step, [[-math.inf] * 3, [math.inf] * 3], window))
    direction = [step['r1_um'][i] - step['r0_um'][i] for i in range(3)]
    length = math.hypot(*direction)
    if length:
        center = math.fsum((xyz[i] - step['r0_um'][i]) * (direction[i] / length) for i in range(3)) / length
        for multiple in (-8., -4., -2., 0., 2., 4., 8.):
            u = center + multiple * step['w_um'] / length
            if 0 < u < 1:
                points.add(u)
    return sorted(points)


def average_generation(source, xyz_um, window_s):
    """BE interval-average G; zero/nonpositive dt is never silently substituted."""
    value = canonical_source(source)
    require(len(xyz_um) == 3, 'Observation must have xyz')
    xyz = [_finite(x, 'observation xyz') for x in xyz_um]
    require(len(window_s) == 2, 'BE window must contain two bounds')
    lo, hi = [_finite(t, 'BE time') for t in window_s]
    require(hi > lo, 'BE average requires a positive actual interval')
    rates = []
    for step in value['steps']:
        def integrand(u):
            r = [step['r0_um'][i] + u * (step['r1_um'][i] - step['r0_um'][i]) for i in range(3)]
            t = step['t0_s'] + u * (step['t1_s'] - step['t0_s'])
            spatial = math.exp(-math.fsum(((xyz[i] - r[i]) / step['w_um']) ** 2 for i in range(3)))
            mass = _normal_interval(t, SQRT2 * step['sigma_s'], lo, hi)[0]
            return [spatial * mass]
        breaks = _average_breakpoints(step, xyz, [lo, hi])
        probability = math.fsum(_adaptive(integrand, a, b)[0][0] for a, b in zip(breaks, breaks[1:]))
        rates.append(step['charge_fC'] * 1e-15 / E_C * 1e12 * probability /
                     (math.pi ** 1.5 * step['w_um'] ** 3 * (hi - lo)))
    result = math.fsum(rates)
    require(math.isfinite(result) and result >= 0, 'Invalid BE average generation')
    return result


_GAUSS_CACHE = {}


def _gauss_unit(order):
    if order not in _GAUSS_CACHE:
        nodes = []
        for i in range(1, order + 1):
            z = math.cos(math.pi * (i - .25) / (order + .5))
            for _ in range(40):
                p0, p1 = 1., z
                for k in range(2, order + 1):
                    p0, p1 = p1, ((2 * k - 1) * z * p1 - (k - 1) * p0) / k
                derivative = order * (z * p1 - p0) / (z * z - 1)
                new = z - p1 / derivative
                if abs(new - z) <= 2e-16:
                    z = new
                    break
                z = new
            nodes.append(((z + 1) / 2, 1 / ((1 - z * z) * derivative * derivative)))
        _GAUSS_CACHE[order] = tuple(sorted(nodes))
    return _GAUSS_CACHE[order]


def _normal_interval(center, scale, lo, hi):
    """Probability and first raw moment for exp(-((x-center)/scale)^2)."""
    a, b = (lo - center) / scale, (hi - center) / scale
    probability = .5 * _erf_difference(a, b)
    first = center * probability + scale / (2 * SQRT_PI) * (math.exp(-a * a) - math.exp(-b * b))
    return probability, first


def _breakpoints(step, box, window):
    points = {0., 1.}
    axes = [(step['r0_um'][i], step['r1_um'][i] - step['r0_um'][i], step['w_um'], box[0][i], box[1][i]) for i in range(3)]
    axes.append((step['t0_s'], step['t1_s'] - step['t0_s'], SQRT2 * step['sigma_s'], window[0], window[1]))
    for start, delta, scale, lo, hi in axes:
        if delta == 0:
            continue
        for boundary in (lo, hi):
            if not math.isfinite(boundary):
                continue
            for multiple in (-8., -4., -2., 0., 2., 4., 8.):
                u = (boundary + multiple * scale - start) / delta
                if 0 < u < 1:
                    points.add(u)
    return sorted(points)


def _quadrature(function, lo, hi, order):
    values = [(function(lo + (hi - lo) * u), weight * (hi - lo)) for u, weight in _gauss_unit(order)]
    return [math.fsum(row[j] * weight for row, weight in values) for j in range(len(values[0][0]))]


def _adaptive(function, lo, hi, depth=0):
    a, b = _quadrature(function, lo, hi, 8), _quadrature(function, lo, hi, 16)
    errors = [abs(x - y) for x, y in zip(a, b)]
    if all(error <= 1e-12 * (hi - lo) + 1e-10 * abs(value) for error, value in zip(errors, b)):
        return b, errors
    require(depth < 18, 'Independent source oracle did not converge; do not renormalize')
    mid = (lo + hi) / 2
    left, le = _adaptive(function, lo, mid, depth + 1)
    right, re_ = _adaptive(function, mid, hi, depth + 1)
    return [x + y for x, y in zip(left, right)], [x + y for x, y in zip(le, re_)]


def _bounds(box_um, window_s):
    require(isinstance(box_um, (list, tuple)) and len(box_um) == 2 and all(len(x) == 3 for x in box_um), 'box_um must be [[xmin,ymin,zmin],[xmax,ymax,zmax]]')
    require(len(window_s) == 2, 'window_s must contain two bounds')
    for lo, hi in zip(box_um[0], box_um[1]):
        require(type(lo) in (int, float) and type(hi) in (int, float) and lo < hi and not math.isnan(lo) and not math.isnan(hi), 'Invalid spatial bounds')
    require(window_s[0] < window_s[1] and all(type(x) in (int, float) and not math.isnan(x) for x in window_s), 'Invalid time window')
    return box_um, window_s


def integrated(source, box_um, window_s):
    """Return charge/moments in a rectangular space-time domain, without renormalization.

    Infinite bounds are accepted for independent total-charge/partition checks.
    The oracle integrates products of Gaussian CDFs in u; it never samples
    generation(), which uses a different closed-form pointwise implementation.
    """
    value = canonical_source(source)
    box, window = _bounds(box_um, window_s)
    totals, error = [0.] * 5, 0.
    step_results = []
    for step in value['steps']:
        def integrand(u):
            spatial = [_normal_interval(step['r0_um'][i] + u * (step['r1_um'][i] - step['r0_um'][i]),
                                        step['w_um'], box[0][i], box[1][i]) for i in range(3)]
            temporal = _normal_interval(step['t0_s'] + u * (step['t1_s'] - step['t0_s']), SQRT2 * step['sigma_s'], *window)
            probabilities = [pair[0] for pair in spatial] + [temporal[0]]
            moments = [pair[1] for pair in spatial] + [temporal[1]]
            return [math.prod(probabilities)] + [moments[i] * math.prod(probabilities[j] for j in range(4) if j != i)
                                                   / (step['w_um'] if i < 3 else step['sigma_s']) for i in range(4)]
        breaks = _breakpoints(step, box, window)
        pieces = [_adaptive(integrand, lo, hi) for lo, hi in zip(breaks, breaks[1:])]
        normalized = [math.fsum(row[0][i] for row in pieces) for i in range(5)]
        q = step['charge_fC']
        scaled = [q * normalized[0]] + [q * normalized[i + 1] * (step['w_um'] if i < 3 else step['sigma_s']) for i in range(4)]
        absolute_error = q * math.fsum(row[1][0] for row in pieces)
        require(-absolute_error <= scaled[0] <= q + absolute_error + 1e-12 * q, 'Oracle charge allocation outside physical bounds')
        totals = [x + y for x, y in zip(totals, scaled)]
        error += absolute_error
        step_results.append({'uid': step['uid'], 'charge_fC': scaled[0], 'estimated_abs_error_fC': absolute_error})
    charge = totals[0]
    return {'charge_fC': charge, 'spatial_first_moment_fC_um': totals[1:4], 'time_first_moment_fC_s': totals[4],
            'centroid_um': [x / charge for x in totals[1:4]] if charge > 0 else None,
            'time_centroid_s': totals[4] / charge if charge > 0 else None,
            'total_charge_fC': math.fsum(s['charge_fC'] for s in value['steps']),
            'estimated_abs_error_fC': error, 'step_allocations': step_results,
            'method': 'independent Gaussian box/window CDF moments with adaptive 8/16-point Gauss-Legendre over correlated u',
            'renormalized': False}
