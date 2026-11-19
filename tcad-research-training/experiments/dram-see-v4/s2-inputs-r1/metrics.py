"""Offline numerical reduction of S2 accepted-time circuit arrays.

The caller must extract original PLT columns without resampling and supply
time_s, v_sn_V, v_bl_V, i_sn_A. Currents are total terminal currents into the
device at SN. No receipt or native qualification is created by this module.
"""
from bisect import bisect_right
import math

REQUIRED = ('time_s', 'v_sn_V', 'v_bl_V', 'i_sn_A')


def validate(data):
    if not all(k in data for k in REQUIRED):
        raise ValueError('Missing original time/voltage/terminal-current column')
    n = len(data['time_s'])
    if n < 2 or any(len(data[k]) != n for k in REQUIRED):
        raise ValueError('Inconsistent or empty circuit columns')
    if any(type(v) not in (int, float) or not math.isfinite(v) for k in REQUIRED for v in data[k]):
        raise ValueError('Nonfinite circuit value')
    t = data['time_s']
    if any(b <= a for a, b in zip(t, t[1:])):
        raise ValueError('Accepted times must strictly increase; no duplicate/rejected steps')
    if abs(t[0]) > 1e-18 or abs(t[-1]-25e-9) > 1e-18:
        raise ValueError('Require the full original 0 to 25 ns trace')
    return True


def interpolate(t, values, x):
    if x < t[0] or x > t[-1]:
        raise ValueError('No extrapolation of missing time coverage')
    if x == t[-1]:
        return values[-1]
    j = bisect_right(t, x)-1
    f = (x-t[j])/(t[j+1]-t[j])
    return values[j]*(1-f)+values[j+1]*f


def voltage_window(t, values, a, b):
    if b <= a:
        raise ValueError('Empty window')
    tt = [a]+[x for x in t if a < x < b]+[b]
    vv = [interpolate(t, values, x) for x in tt]
    mean = math.fsum((y+x)*.5*(tb-ta) for ta, tb, x, y in zip(tt, tt[1:], vv, vv[1:]))/(b-a)
    return tt, vv, mean


def be_integral(t, values, a, b):
    if a < t[0] or b > t[-1] or b <= a:
        raise ValueError('BE integration requires covered increasing bounds')
    # A native accepted endpoint value applies over its entire preceding BE step.
    return math.fsum(values[k]*max(0., min(b, t[k])-max(a, t[k-1])) for k in range(1, len(t)))


def kcl(data):
    validate(data)
    t, v, current = (data[k] for k in ('time_s', 'v_sn_V', 'i_sn_A'))
    rows = []
    for i in range(1, len(t)):
        qc = 20*(v[i]-v[i-1])  # fF*V == fC; plate is fixed 0.6 V.
        qt = current[i]*(t[i]-t[i-1])*1e15
        limit = max(1e-4, .01*max(abs(qc), abs(qt)))
        rows.append({'end_s': t[i], 'capacitor_delta_fC': qc, 'terminal_integral_fC': qt,
                     'residual_fC': qc+qt, 'limit_fC': limit, 'passed': abs(qc+qt) <= limit})
    return {'per_step': rows, 'passed': all(r['passed'] for r in rows),
            'max_residual_fC': max(abs(r['residual_fC']) for r in rows)}


def baseline(data, bit):
    if type(bit) is not int or bit not in (0, 1):
        raise ValueError('bit must be integer 0 or 1')
    validate(data)
    t, vsn, vbl = (data[k] for k in ('time_s', 'v_sn_V', 'v_bl_V'))
    written = interpolate(t, vsn, 6e-9)
    _, hold, _ = voltage_window(t, vsn, 8.1e-9, 19.9e-9)
    drift = max(abs(v-hold[0]) for v in hold)
    pre = interpolate(t, vbl, 8.1e-9)
    _, _, read = voltage_window(t, vbl, 21.9e-9, 22e-9)
    margin = (2*bit-1)*(read-.6)
    balance = kcl(data)
    checks = {'actual_write': written <= .12 if bit == 0 else written >= 1.08,
              'hold_5mV': drift <= .005, 'precharge_1mV': abs(pre-.6) <= .001,
              'read_margin_20mV': margin >= .020, 'per_BE_KCL': balance['passed']}
    return {'schema': 's2-baseline-candidate-metrics-r1', 'stored_bit': bit,
            'written_vsn_V': written, 'hold_drift_V': drift, 'precharge_vbl_V': pre,
            'mean_read_vbl_V': read, 'signed_read_margin_V': margin, 'checks': checks,
            'candidate_functional_pass': all(checks.values()), 'kcl': balance,
            'G1_qualified': False, 'native_engineering_chain_verified': False,
            'remaining': ['original native receipts and provenance', 'main/h2/dt2 comparison',
                          'CAD/material/doping/mesh and DC engineering acceptance']}


def paired_response(signal, control, bit):
    validate(signal)
    validate(control)
    if type(bit) is not int or bit not in (0, 1):
        raise ValueError('bit must be integer 0 or 1')
    a, b = 14.9984e-9, 19.9e-9
    qs = [be_integral(d['time_s'], d['i_sn_A'], a, b)*1e15 for d in (signal, control)]
    dv = [(interpolate(d['time_s'], d['v_sn_V'], b)-interpolate(d['time_s'], d['v_sn_V'], a))
          for d in (signal, control)]
    qc, qt = 20*(dv[0]-dv[1]), qs[0]-qs[1]
    mean = [voltage_window(d['time_s'], d['v_bl_V'], 21.9e-9, 22e-9)[2] for d in (signal, control)]
    limit = max(1e-4, .01*max(abs(qc), abs(qt)))
    return {'Qcol_signed_fC': -qt, 'capacitor_delta_fC': qc, 'paired_KCL_residual_fC': qc+qt,
            'paired_KCL_limit_fC': limit, 'paired_KCL_pass': abs(qc+qt) <= limit,
            'read_margin_signal_V': (2*bit-1)*(mean[0]-.6),
            'read_margin_control_V': (2*bit-1)*(mean[1]-.6),
            'native_qualified': False, 'persistent_flip_label': None}
