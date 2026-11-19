"""Data plots from immutable stage snapshots; never manufacture missing curves."""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

COLORS = {'correct': '#23856D', 'criterion_error': '#BF4342', 'critical': '#D8A12A',
          'numerically_uncertain': '#885DB8', 'failed': '#555C64', 'missing': '#CDD3DA'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _curve(ax, curve, key, label, **kwargs):
    points = curve['points']
    ax.plot([row['time_ns'] for row in points], [row[key] for row in points], label=label, **kwargs)


def _sample(curve, key, times):
    points = curve['points']
    grid = np.array([row['time_ns'] for row in points])
    if min(times) < grid[0] or max(times) > grid[-1]:
        raise ValueError('Plot sampling outside actual curve support')
    return np.interp(times, grid, [row[key] for row in points])


def plot_snapshot(snapshot):
    snapshot = Path(snapshot).resolve()
    source = snapshot / 'summary.json'
    summary = json.loads(source.read_text(encoding='utf8'))
    provenance = json.loads((snapshot / 'sources.json').read_text(encoding='utf8'))
    if provenance['summary_sha256'] != sha(source):
        raise ValueError('Snapshot summary changed')
    out = snapshot / 'figures'
    if out.exists():
        raise ValueError('Figure directory is immutable; create a new snapshot to regenerate')
    out.mkdir()
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9, 'axes.titlesize': 11,
                         'axes.labelsize': 9, 'axes.spines.top': False, 'axes.spines.right': False,
                         'savefig.dpi': 180, 'svg.fonttype': 'none'})
    created, skipped = [], []
    label = 'SYNTHETIC FIXTURE - NOT PHYSICAL RESULTS' if summary.get('synthetic_fixture') else 'DATA PLOT - audited completed runs only'
    def save(fig, name, description, run_ids=()):
        fig.suptitle(label, fontsize=10, color='#8D2E2E' if summary.get('synthetic_fixture') else '#334B62', y=.998)
        fig.text(.01, .007, 'Snapshot SHA256 ' + sha(source)[:16] + ' | Run IDs + archive hashes: ' + name + '.sources.json', fontsize=6.5)
        plot_top = .85 if name.startswith('threshold-window-') else .89 if name in ('stratum-counts','initial-state') else .97
        fig.tight_layout(rect=(0, .025, 1, plot_top))
        files = []
        for suffix in ('png', 'svg'):
            path = out / (name + '.' + suffix)
            fig.savefig(path)
            files.append({'file': path.name, 'sha256': sha(path)})
        plt.close(fig)
        sources = {run: summary['audited_runs'][run]['archive_sha256'] for run in sorted(set(run_ids)) if run in summary['audited_runs']}
        sidecar = {'description': description, 'kind': 'synthetic_fixture' if summary.get('synthetic_fixture') else 'data_plot',
                   'not_native_visual_evidence': True, 'summary_sha256': sha(source), 'run_archive_sha256': sources,
                   'other_source_files_sha256': summary.get('source_files_sha256', {}), 'files': files}
        (out / (name + '.sources.json')).write_text(json.dumps(sidecar, indent=2) + '\n', encoding='utf8')
        created.append({'name': name, 'description': description, 'files': files, 'sources': name + '.sources.json'})
    audited = summary['audited_runs']
    if audited:
        fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2))
        for bit, neutral, color, marker, text in [(0, False, '#267CAB', 'o', 'stored 0'), (1, False, '#C5573C', 's', 'stored 1'), (None, True, '#6D638F', '^', 'neutral')]:
            values = [row for row in audited.values() if row['parameters'].get('neutral') == neutral and row['parameters'].get('stored_bit') == bit]
            if not values:
                continue
            x = [row['parameters']['gate_length_um'] for row in values]
            axes[0].scatter(x, [row['initial_SN_V'] for row in values], color=color, marker=marker, s=25, alpha=.7, label=text)
            axes[1].scatter(x, [row['initial_error_V'] * 1000 for row in values], color=color, marker=marker, s=25, alpha=.7, label=text)
        for target in (.1, .5, .9):
            axes[0].axhline(target, color='#AAAAAA', lw=.7, ls='--')
        axes[1].axhspan(-1, 1, color='#23856D', alpha=.08)
        axes[1].axhline(-1, color='#AAAAAA', ls='--'); axes[1].axhline(1, color='#AAAAAA', ls='--')
        for ax in axes:
            ax.set_xlabel('Gate length L (um)'); ax.grid(alpha=.18)
        fig.legend(*axes[0].get_legend_handles_labels(), loc='upper center', bbox_to_anchor=(.5,.95), ncol=3, fontsize=8)
        axes[0].set_ylabel('SN at 0.95 ns (V)'); axes[0].set_title('Controlled initial state')
        axes[1].set_ylabel('SN minus target (mV)'); axes[1].set_title('Initial-state error; tolerance +/-1 mV')
        save(fig, 'initial-state', 'Actual audited prestrike samples; targets are guides, not simulated samples.', audited)
    else:
        skipped.append({'plot': 'initial-state', 'reason': 'No completed audited samples'})
    curves = summary['curves']
    for length in (.18, .25, .35, .45):
        baseline = {bit: [curve for curve in curves.values() if curve['parameters']['gate_length_um'] == length
                          and curve['parameters'].get('stored_bit') == bit and not curve['parameters'].get('source_event')
                          and curve['parameters'].get('oxide_nm') == 5 and curve['parameters'].get('step_scale') == 1 and curve['parameters'].get('mesh_scale') == 1]
                    for bit in (0, 1)}
        neutral = [curve for curve in curves.values() if curve['parameters']['gate_length_um'] == length and curve['parameters'].get('neutral')
                   and curve['parameters'].get('oxide_nm') == 5 and curve['parameters'].get('step_scale') == 1 and curve['parameters'].get('mesh_scale') == 1]
        responses = [row for row in summary['responses'] if row['gate_length_um'] == length and row['status'] == 'measured']
        if not any(baseline.values()) and not responses:
            skipped.append({'plot': f'readout-l{length}', 'reason': 'No completed curves'})
            continue
        fig, axes = plt.subplots(2, 2, figsize=(11.5, 7), sharex=True)
        used = []
        for bit in (0, 1):
            for curve in baseline[bit]:
                used.append(curve['run_id'])
                for ax, key in zip(axes[bit], ('SN_V', 'BL_V')):
                    _curve(ax, curve, key, 'matched no-particle control', color='#172D45', lw=1.6)
            for curve in neutral:
                used.append(curve['run_id'])
                for ax, key in zip(axes[bit], ('SN_V', 'BL_V')):
                    _curve(ax, curve, key, 'neutral reference', color='#777777', lw=1.1, ls='--')
            shown = set()
            for row in (row for row in responses if row['stored_bit'] == bit):
                curve = curves.get(row['run_id'])
                if curve is None:
                    continue
                used.append(row['run_id'])
                group = row['particle'] + f" / {row['angle_deg']} deg"
                for ax, key in zip(axes[bit], ('SN_V', 'BL_V')):
                    _curve(ax, curve, key, group if group not in shown else None,
                           color='#C5573C' if row['particle'] == 'alpha' else '#267CAB',
                           alpha=.45, lw=.9, ls='-' if row['angle_deg'] == 0 else ':')
                shown.add(group)
            for ax, node in zip(axes[bit], ('SN', 'BL')):
                ax.set_title(f'L={length:g} um, stored {bit}: {node}'); ax.set_ylabel(node + ' (V)')
                ax.grid(alpha=.18); ax.legend(fontsize=7, loc='best')
        for ax in axes[-1]: ax.set_xlabel('Time (ns)')
        save(fig, f'readout-l{round(length*100):03d}', 'All available planned event curves, controls and neutral curves; missing curves omitted, no sample selection.', used)
        if not responses or not neutral:
            skipped.append({'plot': f'threshold-window-l{length}', 'reason': 'No matched event and neutral curves'})
            continue
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
        used = []
        for bit, ax in enumerate(axes):
            for epsilon in (2.5, 5., 10.):
                for sign in (-1, 1): ax.axhline(sign * epsilon, color='#AAAAAA', ls='--' if epsilon == 5 else ':', lw=.8)
            ax.axhspan(-5, 5, alpha=.07, color='#D8A12A')
            for row in (row for row in responses if row['stored_bit'] == bit):
                signal = curves.get(row['run_id']); reference = curves.get(row['sources']['neutral']['run_id'])
                if signal is None or reference is None: continue
                times = sorted({3.8, 4.} | {point['time_ns'] for curve in (signal, reference) for point in curve['points'] if 3.8 <= point['time_ns'] <= 4.})
                margin = (2 * bit - 1) * (_sample(signal, 'BL_V', times) - _sample(reference, 'BL_V', times)) * 1000
                ax.plot(times, margin, color='#C5573C' if row['particle'] == 'alpha' else '#267CAB', alpha=.55,
                        ls='-' if row['angle_deg'] == 0 else ':', lw=1)
                used.extend((signal['run_id'], reference['run_id']))
            ax.set_title(f'L={length:g} um, stored {bit}'); ax.set_xlabel('Time (ns)'); ax.grid(alpha=.15)
        axes[0].set_ylabel('Signed matched readout margin M (mV)')
        legend = [Line2D([], [], color='#C5573C', label='alpha'),
                  Line2D([], [], color='#267CAB', label='proton'),
                  Line2D([], [], color='#444444', ls='-', label='0 deg'),
                  Line2D([], [], color='#444444', ls=':', label='30 deg'),
                  Line2D([], [], color='#AAAAAA', ls='--', label='Main thresholds +/-5 mV'),
                  Line2D([], [], color='#AAAAAA', ls=':', label='Sensitivity +/-2.5, +/-10 mV')]
        fig.legend(handles=legend, loc='upper center', bbox_to_anchor=(.5, .95), ncol=3, fontsize=8)
        save(fig, f'threshold-window-l{round(length*100):03d}', 'All available event margins in 3.8-4 ns. Guides +/-2.5, 5, 10 mV; crimson alpha, blue proton; dotted 30 deg.', used)
    strata = [row for row in summary['statistics']['strata'] if row['threshold_mV'] == summary['design']['main_threshold_mV']]
    fig, ax = plt.subplots(figsize=(11, 10))
    labels = [f"L{row['gate_length_um']:g} {row['particle']} {row['angle_deg']}deg b{row['stored_bit']}" for row in strata]
    starts = np.zeros(len(strata))
    for status, color in COLORS.items():
        values = np.array([row[status] for row in strata])
        ax.barh(range(len(strata)), values, left=starts, color=color, label=status, height=.76)
        starts += values
    ax.set_yticks(range(len(strata)), labels, fontsize=7.5); ax.invert_yaxis()
    ax.set_xlim(0, 4); ax.set_xticks(range(5)); ax.set_xlabel('Planned event slots per bit/condition (N=4)')
    ax.set_title('5 mV criterion: measured outcomes and unresolved slots')
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, ncol=3, loc='upper center', bbox_to_anchor=(.58, .963), fontsize=8)
    save(fig, 'stratum-counts', 'Fixed N=4 per bit/physical stratum; missing bars describe planned status, not measurements.', audited)
    available = [row for row in strata if row['valid'] > 0]
    if available:
        fig, ax = plt.subplots(figsize=(10, max(4, len(available) * .27)))
        for i, row in enumerate(available):
            lo, hi = row['wilson_95_envelope']; a, b = row['point_bounds']
            ax.plot([lo, hi], [i, i], color='#A8B5C1', lw=5)
            ax.plot([a, b], [i, i], color='#225C83', lw=2)
        ax.set_yticks(range(len(available)), [f"L{r['gate_length_um']:g} {r['particle']} {r['angle_deg']}deg b{r['stored_bit']}" for r in available], fontsize=7.5)
        ax.invert_yaxis(); ax.set_xlim(0, 1); ax.set_xlabel('Criterion-error fraction bounds (planned N=4)')
        ax.set_title('Dark: best/worst point bounds; light: Wilson 95% envelope')
        save(fig, 'stratum-intervals', 'Only strata containing actual classified observations; descriptive envelope includes unresolved assignments.', audited)
    else:
        skipped.append({'plot': 'stratum-intervals', 'reason': 'No observed stratum; no invented estimate shown'})
    scoring = summary.get('prediction_scores')
    if scoring and scoring.get('stratified_residuals'):
        fig, axes = plt.subplots(2, 2, figsize=(11, 7))
        for bit in (0, 1):
            for index, target in enumerate(('deltaQ_fC', 'deltaM_mV')):
                ax = axes[bit, index]
                for model, marker, color in [('training_mean', 'x', '#8F9398'), ('ridge', 'o', '#267CAB')]:
                    values = [r for r in scoring['stratified_residuals'] if r['stored_bit'] == bit and r['target'] == target and r['model'] == model]
                    if values: ax.scatter([r['observed'] for r in values], [r['residual_prediction_minus_observed'] for r in values], label=model, marker=marker, color=color, alpha=.65, s=22)
                unit = 'fC' if target == 'deltaQ_fC' else 'mV'
                ax.axhline(0, color='#AAAAAA', ls='--'); ax.set_title(f'stored {bit}: {target}')
                ax.set_xlabel('Observed (' + unit + ')'); ax.set_ylabel('Prediction - observed (' + unit + ')'); ax.legend(fontsize=8); ax.grid(alpha=.15)
        save(fig, 'prediction-residuals', 'Actual holdout/extrapolation residuals for fixed pre-test models; missing responses omitted from points and counted in CSV.', audited)
    else:
        skipped.append({'plot': 'prediction-residuals', 'reason': 'No completed scored test responses'})
    oxide = summary.get('oxide')
    if oxide and oxide.get('responses'):
        fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.5))
        rows = oxide.get('baseline_5nm', []) + oxide['responses']
        for particle in ('alpha', 'proton'):
            for bit in (0, 1):
                values = sorted((r for r in rows if r['event']['particle'] == particle and r['stored_bit'] == bit), key=lambda r: r['oxide_nm'])
                for ax, target, factor in [(axes[0], 'deltaQ_fC', 1), (axes[1], 'deltaM_V', 1000)]:
                    ax.plot([r['oxide_nm'] for r in values], [r['observation']['metrics'][target] * factor for r in values], marker='o',
                            label=f'{particle}, stored {bit}', color='#C5573C' if particle == 'alpha' else '#267CAB', ls='-' if bit else '--')
        for ax in axes:
            ax.set_xlabel('TCAD oxide thickness (nm)'); ax.set_xticks([4, 5, 6]); ax.legend(fontsize=8); ax.grid(alpha=.15)
        axes[0].set_ylabel('Matched deltaQ (fC)'); axes[1].set_ylabel('Matched margin loss deltaM (mV)')
        axes[0].set_title('L=0.25 um, 0 deg, same silicon-entry events'); axes[1].set_title('No additional independent particle events')
        save(fig, 'oxide-sensitivity', 'Fixed source events across 4/5/6 nm; 5 nm responses reused. Not a changed transport material stack.', audited)
    else:
        skipped.append({'plot': 'oxide-sensitivity', 'reason': 'No completed oxide comparison'})
    index = {'schema': 'dram-see-v3-data-plot-index', 'summary_sha256': sha(source),
             'created': created, 'skipped': skipped, 'synthetic_fixture': summary.get('synthetic_fixture', False)}
    (out / 'index.json').write_text(json.dumps(index, indent=2) + '\n', encoding='utf8')
    return index


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('snapshot', type=Path)
    print(json.dumps(plot_snapshot(parser.parse_args().snapshot), indent=2))
