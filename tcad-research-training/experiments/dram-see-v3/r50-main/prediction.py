"""R50-main pure prediction algorithms, explicitly derived without old IO.

Production fitting/freezing is exclusively finish.py after R50 raw gate checks.
"""
import math
import platform
import numpy as np
TARGETS = ('deltaQ_fC', 'deltaM_mV')
FEATURES = ('Qdep_fC', 'Qdep_fC/L_um', 'Qdep_fC*sin(theta)')
ALPHAS = (0., .01, .1, 1., 10.)
CONTINUOUS_ACCEPTED = ('RAW_AUDIT_PASSED', 'MATCHED_REFINEMENT_PASSED', 'PASSED')

def _configuration(design):
    p = design.get('prediction', {})
    expected = {'models': ['training_mean', 'ridge'], 'targets': list(TARGETS),
                'features': list(FEATURES), 'ridge_candidates': list(ALPHAS),
                'train_lengths_um': [.18, .35], 'holdout_lengths_um': [.25],
                'extrapolation_lengths_um': [.45], 'separate_model_per_bit_and_target': True,
                'cv': 'leave-one-physical-condition-out over 8 training (L,particle,angle) groups; all four repeats and both bits stay grouped',
                'selection_score': 'arithmetic mean of per-fold RMSE for each bit/target independently',
                'tie_break': 'lowest alpha among scores within 1e-12 target units of minimum',
                'standardization': 'training fold population mean/std only; zero std replaced with1; final fit uses all training data',
                'ridge_objective': 'sum_squared_error + alpha*sum(coef**2); intercept unpenalized; alpha0 via least-squares'}
    for key, value in expected.items():
        if p.get(key) != value:
            raise ValueError('Prediction configuration differs from frozen implementation: ' + key)
    events = design.get('events', [])
    if len(events) != 64 or len({event['label'] for event in events}) != 64:
        raise ValueError('Expected exactly 64 unique frozen events')
    for split, count, lengths in [('train', 32, (.18, .35)), ('holdout', 16, (.25,)), ('extrapolation', 16, (.45,))]:
        selected = [event for event in events if event['split'] == split]
        if len(selected) != count or any(event['gate_length_um'] not in lengths for event in selected):
            raise ValueError('Frozen split mismatch: ' + split)
    return p


def features(row):
    q, length, angle = row['Qdep_fC'], row['gate_length_um'], row['angle_deg']
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (q, length, angle)):
        raise ValueError('Nonfinite or invalid predictor')
    if q < 0 or length not in (.18, .25, .35, .45) or angle not in (0, 30):
        raise ValueError('Outside frozen feature conditions')
    return [q, q / length, q * math.sin(math.radians(angle))]


def _validated_rows(rows, design, training):
    _configuration(design)
    events = {e['label']: e for e in design['events'] if (e['split'] == 'train') == training}
    expected = {(label, bit) for label in events for bit in (0, 1)}
    indexed = {}
    for row in rows:
        key = (row['event_label'], row['stored_bit'])
        if key not in expected or key in indexed or type(row['stored_bit']) is not int:
            raise ValueError('Unknown, leaked or duplicate response in ' + ('training' if training else 'test inputs'))
        event = events[key[0]]
        for name in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'condition_id', 'replicate', 'split'):
            if row.get(name) != event[name]:
                raise ValueError('Response/event identity mismatch: ' + name)
        features(row)
        if row.get('oxide_nm', 5) != 5 or row.get('step_scale', 1) != 1 or row.get('mesh_scale', 1) != 1:
            raise ValueError('Process/refinement responses do not enter length prediction')
        if training:
            if row.get('continuous_valid') is not True or row.get('continuous_numerical_status') not in CONTINUOUS_ACCEPTED:
                raise ValueError('Incomplete/failed continuous training target')
            if set(row.get('targets', {})) != set(TARGETS):
                raise ValueError('Both audited continuous targets required')
            if any(not math.isfinite(row['targets'][target]) for target in TARGETS):
                raise ValueError('Nonfinite training target')
        elif any(name in row for name in ('targets', 'deltaQ_fC', 'deltaM_mV', 'deltaM_V', 'response_run_id', 'signal_response')):
            raise ValueError('Held-out response leaked into predictor input')
        indexed[key] = row
    if set(indexed) != expected:
        raise ValueError('Need every frozen ' + ('64 training responses' if training else '64 test input/bit pairs'))
    ordered = [indexed[(event['label'], bit)] for event in design['events'] if event['label'] in events for bit in (0, 1)]
    # The deposited event is shared by its two bits, not measured independently.
    for label in events:
        if indexed[(label, 0)]['Qdep_fC'] != indexed[(label, 1)]['Qdep_fC']:
            raise ValueError('Paired bits must use exactly the same event deposition')
    return ordered


def _fit_ridge(x, y, alpha):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mean = np.mean(x, axis=0)
    raw_std = np.std(x, axis=0, ddof=0)
    scale = np.where(raw_std == 0, 1., raw_std)
    z = (x - mean) / scale
    intercept = float(np.mean(y))
    if alpha == 0:
        coefficient = np.linalg.lstsq(z, y - intercept, rcond=None)[0]
    else:
        coefficient = np.linalg.solve(z.T @ z + alpha * np.eye(x.shape[1]), z.T @ (y - intercept))
    if not np.all(np.isfinite(coefficient)):
        raise ValueError('Nonfinite fitted coefficient')
    return {'alpha': alpha, 'feature_mean': mean.tolist(), 'feature_population_std': raw_std.tolist(),
            'feature_scale': scale.tolist(), 'coefficient_standardized': coefficient.tolist(),
            'intercept': intercept, 'coefficient_original_units': (coefficient / scale).tolist(),
            'intercept_original_units': intercept - float(mean @ (coefficient / scale)),
            'training_n': len(y)}


def _predict_ridge(model, x):
    x = np.asarray(x, dtype=float)
    z = (x - np.asarray(model['feature_mean'])) / np.asarray(model['feature_scale'])
    return z @ np.asarray(model['coefficient_standardized']) + model['intercept']


def _rmse(prediction, actual):
    return float(np.sqrt(np.mean((np.asarray(prediction) - np.asarray(actual)) ** 2)))


def fit_models(training_rows, design):
    """Pure fit: all 64 declared, audited targets; never silently discard a row."""
    rows = _validated_rows(training_rows, design, True)
    groups = sorted({row['condition_id'] for row in rows})
    if len(groups) != 8 or any(sum(row['condition_id'] == group for row in rows) != 8 for group in groups):
        raise ValueError('Need eight complete training physical-condition groups')
    models = {}
    for bit in (0, 1):
        bit_rows = [row for row in rows if row['stored_bit'] == bit]
        x = np.asarray([features(row) for row in bit_rows])
        for target in TARGETS:
            y = np.asarray([row['targets'][target] for row in bit_rows])
            cv = []
            for group in groups:
                validation = np.asarray([row['condition_id'] == group for row in bit_rows])
                train = ~validation
                mean = float(np.mean(y[train]))
                ridge = []
                for alpha in ALPHAS:
                    fitted = _fit_ridge(x[train], y[train], alpha)
                    predictions = _predict_ridge(fitted, x[validation])
                    ridge.append({'alpha': alpha, 'rmse': _rmse(predictions, y[validation]),
                                  'fit': fitted, 'predictions': predictions.tolist()})
                cv.append({'held_condition_id': group,
                           'training_event_labels': [row['event_label'] for row, keep in zip(bit_rows, train) if keep],
                           'validation_event_labels': [row['event_label'] for row, keep in zip(bit_rows, validation) if keep],
                           'training_mean': {'value': mean, 'rmse': _rmse(np.full(sum(validation), mean), y[validation])},
                           'ridge_candidates': ridge})
            scores = [float(np.mean([fold['ridge_candidates'][i]['rmse'] for fold in cv])) for i in range(len(ALPHAS))]
            minimum = min(scores)
            selected = min(alpha for alpha, score in zip(ALPHAS, scores) if score <= minimum + 1e-12)
            final = _fit_ridge(x, y, selected)
            models[f'bit{bit}:{target}'] = {
                'stored_bit': bit, 'target': target, 'training_response_n': 32,
                'training_mean': {'value': float(np.mean(y)),
                                  'cv_mean_fold_rmse': float(np.mean([fold['training_mean']['rmse'] for fold in cv]))},
                'ridge': final, 'selected_alpha': selected,
                'cv_alpha_scores': [{'alpha': a, 'mean_fold_rmse': s} for a, s in zip(ALPHAS, scores)],
                'cv_folds': cv,
            }
    return {'schema': 'dram-see-v3-r50-main-prediction-models', 'configuration': design['prediction'],
            'feature_names': list(FEATURES), 'train_independent_events': 32,
            'train_paired_responses': 64, 'models': models,
            'implementation': {'python': platform.python_version(), 'numpy': np.__version__,
                               'linear_algebra': 'numpy lstsq(rcond=None) for alpha0; solve otherwise'},
            'scope': design['prediction']['scope']}


def predict_inputs(models, test_rows, design):
    rows = _validated_rows(test_rows, design, False)
    if models.get('configuration') != design['prediction']:
        raise ValueError('Model configuration differs from frozen design')
    predictions = []
    for row in rows:
        values = features(row)
        targets = {}
        for target in TARGETS:
            fitted = models['models'][f"bit{row['stored_bit']}:{target}"]
            targets[target] = {'training_mean': fitted['training_mean']['value'],
                               'ridge': float(_predict_ridge(fitted['ridge'], [values])[0])}
        predictions.append({'event_label': row['event_label'], 'stored_bit': row['stored_bit'],
                            'condition_id': row['condition_id'], 'split': row['split'],
                            'feature_values': dict(zip(FEATURES, values)), 'predictions': targets})
    return {'schema': 'dram-see-v3-r50-main-frozen-predictions', 'test_independent_events': 32,
            'test_paired_responses': 64, 'predictions': predictions}


def score_predictions(frozen_predictions, observed_rows, design):
    """Pure post-test evaluation; never refit or select using observed responses.

    Missing/failed observations remain in the planned denominator while error
    scores explicitly use only supplied audited continuous values.
    """
    _configuration(design)
    events = {event['label']: event for event in design['events'] if event['split'] != 'train'}
    expected = {(label, bit) for label in events for bit in (0, 1)}
    predicted = {}
    for row in frozen_predictions['predictions']:
        key = (row['event_label'], row['stored_bit'])
        if key not in expected or key in predicted:
            raise ValueError('Unknown/duplicate frozen test prediction')
        predicted[key] = row
    if set(predicted) != expected:
        raise ValueError('Frozen test predictions are incomplete')
    observed = {}
    for row in observed_rows:
        key = (row['event_label'], row['stored_bit'])
        if key not in expected or key in observed:
            raise ValueError('Unknown/duplicate held-out observation')
        if row.get('oxide_nm', 5) != 5 or row.get('step_scale', 1) != 1 or row.get('mesh_scale', 1) != 1:
            raise ValueError('Oxide/refinement results are outside length-prediction scores')
        if row.get('continuous_valid') is True:
            if set(row.get('targets', {})) != set(TARGETS) or any(not math.isfinite(row['targets'][target]) for target in TARGETS):
                raise ValueError('Valid held-out observation requires finite targets')
        observed[key] = row
    residuals, scores = [], []
    for split in ('holdout', 'extrapolation'):
        for bit in (0, 1):
            keys = [key for key in expected if events[key[0]]['split'] == split and key[1] == bit]
            for target in TARGETS:
                for model in ('training_mean', 'ridge'):
                    errors = []
                    for key in sorted(keys):
                        actual = observed.get(key)
                        if actual is None or actual.get('continuous_valid') is not True:
                            continue
                        predicted_value = predicted[key]['predictions'][target][model]
                        if not math.isfinite(predicted_value):
                            raise ValueError('Nonfinite frozen prediction')
                        error = predicted_value - actual['targets'][target]
                        errors.append(error)
                        event = events[key[0]]
                        residuals.append({'event_label': key[0], 'stored_bit': bit, 'split': split,
                                          'gate_length_um': event['gate_length_um'], 'particle': event['particle'],
                                          'angle_deg': event['angle_deg'], 'replicate': event['replicate'],
                                          'target': target, 'model': model, 'prediction': predicted_value,
                                          'observed': actual['targets'][target], 'residual_prediction_minus_observed': error})
                    scores.append({'split': split, 'stored_bit': bit, 'target': target, 'model': model,
                                   'planned_n': len(keys), 'valid_n': len(errors),
                                   'missing_n': sum(key not in observed for key in keys),
                                   'invalid_or_failed_n': sum(key in observed and observed[key].get('continuous_valid') is not True for key in keys),
                                   'MAE': float(np.mean(np.abs(errors))) if errors else None,
                                   'RMSE': _rmse(errors, np.zeros(len(errors))) if errors else None,
                                   'max_absolute_error': max(map(abs, errors)) if errors else None})
    return {'schema': 'dram-see-v3-r50-main-prediction-scores', 'scores': scores, 'stratified_residuals': residuals,
            'scope': 'Fixed pre-test predictions only; scores conditional on valid observed responses; missing/failed counts retained'}

