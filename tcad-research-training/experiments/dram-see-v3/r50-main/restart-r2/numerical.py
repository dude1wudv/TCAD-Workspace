"""Exact pure preregistered numerical comparison; no ledger or source loader."""
import math

def _number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('Nonfinite numerical comparison value')
    return value


def _classify(margin, threshold):
    return 'correct' if margin > threshold else 'criterion_logic_flip' if margin < -threshold else 'critical'


def compare_observations(baseline, refined, thresholds_V=(.0025, .005, .01), readout_tolerance_V=.0005, charge_tolerance_fC=.01):
    """Pure comparison; classification crossing is distinct from continuous error."""
    differences = {role + '_BL4_V': _number(refined['readout_BL_V'][role]) - _number(baseline['readout_BL_V'][role])
                   for role in ('signal', 'control', 'neutral')}
    for key in ('D4_V', 'M4_V', 'control_D4_V', 'control_M4_V', 'deltaM_V'):
        differences[key] = _number(refined['metrics'][key]) - _number(baseline['metrics'][key])
    charge_difference = _number(refined['metrics']['deltaQ_fC']) - _number(baseline['metrics']['deltaQ_fC'])
    continuous = (all(abs(value) <= readout_tolerance_V for value in differences.values())
                  and abs(charge_difference) <= charge_tolerance_fC)
    classes = {}
    affected = []
    for threshold in thresholds_V:
        rows = {role: {'baseline': _classify(baseline['metrics'][key], threshold),
                       'refined': _classify(refined['metrics'][key], threshold)}
                for role, key in (('signal', 'M4_V'), ('control', 'control_M4_V'))}
        stable = all(row['baseline'] == row['refined'] for row in rows.values())
        classes[str(threshold)] = {'stable': stable, 'roles': rows}
        if not stable or not continuous:
            affected.append(threshold)
    return {'continuous_passed': continuous, 'classification_stable': all(row['stable'] for row in classes.values()),
            'differences_V': differences, 'deltaQ_difference_fC': charge_difference,
            'tolerances': {'readout_V': readout_tolerance_V, 'deltaQ_fC': charge_tolerance_fC},
            'classification_comparison': classes, 'numerically_uncertain_thresholds_V': affected,
            'baseline_sources': baseline['metrics']['sources'], 'refined_sources': refined['metrics']['sources'],
            'baseline_metrics': baseline['metrics'], 'refined_metrics': refined['metrics'],
            'rule': 'Continuous tolerance failure blocks expansion; classification crossing remains numerical uncertainty'}

