"""Read completed, explicitly diagnostic-only evidence; create no solver jobs."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tarfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNTIME = ROOT / 'local_runtime/dram-see-v3/diagnostics/precharge-additional-r1'
OUTPUT = HERE / 'data/diagnostics/precharge-additional-r1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def write_json(path, value):
    with Path(path).open('x', encoding='utf8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def write_csv(path, rows):
    with Path(path).open('x', encoding='utf8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def generate():
    diagnostic = read(RUNTIME / 'diagnostic.json')
    plan = read(RUNTIME / 'plan.json')
    if (diagnostic['state'] != 'DIAGNOSTIC_COMPLETE' or diagnostic['original_state'] != 'FAILED'
            or not diagnostic['diagnostic_only'] or diagnostic['training_or_prediction_eligible']
            or diagnostic['main_matrix_resume_authorized'] or len(diagnostic['comparisons']) != 2
            or sha(RUNTIME / 'plan.json') != diagnostic['plan_sha256']):
        raise ValueError('Requires the complete original-failure-preserving diagnostic')
    if OUTPUT.exists():
        raise ValueError('Published diagnostic directory already exists; do not overwrite')
    audit_source = HERE / 'audit.py'
    if sha(audit_source) != plan['source_sha256'][audit_source.relative_to(ROOT).as_posix()]:
        raise ValueError('Frozen curve parser differs')
    spec = importlib.util.spec_from_file_location('_diagnostic_plot_audit', audit_source)
    audit = importlib.util.module_from_spec(spec)
    exec(compile(audit_source.read_bytes(), str(audit_source), 'exec'), audit.__dict__)
    observations = [diagnostic['original_observation']] + [c['observation'] for c in diagnostic['comparisons']]
    names = ['Original', 'Half time step', 'Mesh scale 0.7']
    source_archives, curves, rows = {}, {}, []
    for name, obs in zip(names, observations):
        if not obs['diagnostic_only'] or obs['training_or_prediction_eligible']:
            raise ValueError('Diagnostic data must not be eligible for scoring')
        for role, source in obs['metrics']['sources'].items():
            archive_path = ROOT / 'local_runtime/runs' / source['run_id'] / 'results.tar'
            if sha(archive_path) != source['archive_sha256']:
                raise ValueError('Original archive changed: ' + source['run_id'])
            source_archives[source['run_id']] = source
            with tarfile.open(archive_path) as archive:
                _, raw = audit.parse_plt(audit.read(archive, 'circuit.plt').decode())
            segment = audit.segment(raw, 2.8e-9, 3e-9, first=True)
            curves[(name, role)] = segment
            for row in segment:
                rows.append({'variation': name, 'role': role, 'run_id': source['run_id'],
                             'diagnostic_only': True, 'raw_audit_state': obs['raw_audit_states'][role],
                             'time_ns': row['time'] * 1e9, 'BL_V': row['v(bl)'], 'REF_V': row['v(ref)'],
                             'BL_error_uV': (row['v(bl)'] - .5) * 1e6})
    OUTPUT.mkdir(parents=True)
    figures = OUTPUT / 'figures'; figures.mkdir()
    shutil.copyfile(RUNTIME / 'diagnostic.json', OUTPUT / 'diagnostic.json')
    shutil.copyfile(RUNTIME / 'plan.json', OUTPUT / 'plan.json')
    records = OUTPUT / 'audits'; records.mkdir()
    for case in plan['planned_cases']:
        path = RUNTIME / 'audits' / (case['tag'] + '.json')
        if sha(path) != diagnostic['cases'][case['tag']]['audit_sha256']:
            raise ValueError('Diagnostic audit binding differs')
        shutil.copyfile(path, records / path.name)
    write_csv(OUTPUT / 'precharge-curves.csv', rows)
    metrics = []
    for name, obs in zip(names, observations):
        m = obs['metrics']
        metrics.append({'variation': name, 'diagnostic_only': True, 'main_state': 'FAILED',
                        'signal_run_id': m['sources']['signal']['run_id'],
                        'signal_precharge_error_uV': obs['precharge']['signal']['BL_error_uV'],
                        'control_precharge_error_uV': obs['precharge']['control']['BL_error_uV'],
                        'neutral_precharge_error_uV': obs['precharge']['neutral']['BL_error_uV'],
                        **{role + '_BL4_V': value for role, value in obs['readout_BL_V'].items()},
                        **{role + '_REF4_V': value for role, value in obs['readout_REF_V'].items()},
                        **{key: m[key] for key in ('deltaQ_fC', 'D4_V', 'M4_V', 'control_D4_V', 'control_M4_V', 'deltaM_V')},
                        'raw_class_2p5mV': m['classification']['0.0025'],
                        'raw_class_5mV': m['classification']['0.005'],
                        'raw_class_10mV': m['classification']['0.01']})
    write_csv(OUTPUT / 'metrics.csv', metrics)
    compare_rows = []
    for name, row in zip(names[1:], diagnostic['comparisons']):
        c = row['comparison']
        compare_rows.append({'variation': name, 'diagnostic_only': True,
                             'max_abs_readout_change_mV': max(abs(v) for v in c['differences_V'].values()) * 1e3,
                             'deltaQ_difference_fC': c['deltaQ_difference_fC'],
                             'readout_tolerance_mV': .5, 'charge_tolerance_fC': .01,
                             'continuous_comparison_passed': c['continuous_passed'],
                             'raw_classification_stable': c['classification_stable'],
                             'raw_event_audit_state': row['observation']['raw_audit_states']['signal']})
    write_csv(OUTPUT / 'comparison.csv', compare_rows)
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                         'svg.fonttype': 'none', 'figure.facecolor': 'white'})
    colors = ['#bb4438', '#26768a', '#666666']
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.9), gridspec_kw={'width_ratios': [1.4, 1, 1]})
    x = np.arange(3)
    for j, (role, color) in enumerate(zip(('signal', 'control', 'neutral'), colors)):
        values = [abs(o['precharge'][role]['BL_error_uV']) for o in observations]
        bars = axes[0].bar(x + (j - 1) * .23, values, .22, color=color, label=role.title())
        if role == 'signal':
            axes[0].bar_label(bars, fmt='%.3f', padding=3, fontsize=9)
    axes[0].axhline(10, color='black', ls='--', lw=1, label='Frozen gate: 10 uV')
    axes[0].set(xticks=x, xticklabels=['Original', 'Half step', 'Fine mesh'], ylabel='|BL(3 ns) - 0.5 V| (uV)',
                ylim=(0, 17.8), title='(a) Precharge gate remains failed')
    axes[0].legend(fontsize=8, ncol=2, loc='upper center')
    for axis, key, bound, title, ylabel, fmt in [
            (axes[1], 'max_abs_readout_change_mV', .5, '(b) Readout sensitivity', 'Maximum absolute change (mV)', '%.5f'),
            (axes[2], 'deltaQ_difference_fC', .01, '(c) Signed-charge sensitivity', '|Change in deltaQ| (fC)', '%.6f')]:
        values = [abs(r[key]) for r in compare_rows]
        bars = axis.bar([0, 1], values, .48, color=['#26768a', '#7d5094'])
        axis.bar_label(bars, labels=[fmt % v for v in values], padding=4)
        axis.axhline(bound, color='black', ls='--', lw=1, label='Frozen comparison tolerance')
        axis.set(xticks=[0, 1], xticklabels=['Half step', 'Fine mesh'], ylabel=ylabel,
                 ylim=(0, bound * 1.18), title=title)
        axis.legend(fontsize=7.6, loc='upper center')
    fig.suptitle('DATA PLOT | Same alpha event, L=0.18 um, stored bit 0 | DIAGNOSTIC ONLY', fontsize=13)
    fig.text(.5, .025, 'Readout comparisons pass; all three event audits remain FAILED. No replacement of the original response.', ha='center', fontsize=9)
    fig.subplots_adjust(left=.055, right=.985, bottom=.17, top=.82, wspace=.38)
    for suffix in ('png', 'svg'): fig.savefig(figures / ('precharge-comparison.' + suffix), dpi=170)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharex=True)
    for axis, role in zip(axes, ('signal', 'control')):
        for name, color, style in zip(names, ['#bb4438', '#26768a', '#7d5094'], ['-', '--', ':']):
            segment = curves[(name, role)]
            axis.plot([r['time'] * 1e9 for r in segment], [(r['v(bl)'] - .5) * 1e6 for r in segment],
                      label=name, color=color, ls=style, lw=1.8)
        axis.axhspan(-10, 10, color='#b6d7c3', alpha=.25)
        axis.axhline(-10, color='black', ls='--', lw=.8)
        axis.set_yscale('symlog', linthresh=10)
        axis.set(xlim=(2.90, 3.0), xlabel='Time (ns)', ylabel='BL - 0.5 V (uV; symlog)',
                 title='Particle signal: FAILED' if role == 'signal' else 'Matched unirradiated control: PASSED')
        axis.legend(fontsize=9, loc='lower right')
        axis.grid(alpha=.2)
    fig.suptitle('DATA PLOT | Original precharge curves | DIAGNOSTIC ONLY', fontsize=13)
    fig.text(.5, .025, 'Incoming 3 ns boundary; green band denotes +/-10 uV. Curves are original archived solver output.', ha='center', fontsize=9)
    fig.subplots_adjust(left=.075, right=.985, bottom=.17, top=.82, wspace=.23)
    for suffix in ('png', 'svg'): fig.savefig(figures / ('precharge-curves.' + suffix), dpi=170)
    plt.close(fig)
    sources = {'schema': 'dram-see-v3-diagnostic-report-sources', 'diagnostic_only': True,
               'diagnostic_sha256': sha(RUNTIME / 'diagnostic.json'), 'plan_sha256': sha(RUNTIME / 'plan.json'),
               'generator_sha256': sha(__file__), 'audit_parser_sha256': sha(audit_source),
               'new_independent_events': 0, 'original_main_state': 'FAILED', 'archives': source_archives,
               'files_sha256': {p.relative_to(OUTPUT).as_posix(): sha(p) for p in OUTPUT.rglob('*') if p.is_file()},
               'scope': 'Data plots and diagnostic tables only; not native GUI captures; no main training or prediction eligibility.'}
    write_json(OUTPUT / 'sources.json', sources)
    print(json.dumps({'output': str(OUTPUT), 'sources_sha256': sha(OUTPUT / 'sources.json'),
                      'diagnostic_sha256': sources['diagnostic_sha256'], 'comparison': compare_rows}, indent=2))


if __name__ == '__main__':
    generate()
