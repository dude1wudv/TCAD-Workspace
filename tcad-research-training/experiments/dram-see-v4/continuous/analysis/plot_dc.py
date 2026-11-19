"""Plot original native DC reduction without filtering or changing current signs.

The input is continuous/data/current_dc.py output. Figures are descriptive;
successful rendering is never native or scientific qualification.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create(report_path, output):
    report_path, output = Path(report_path), Path(output)
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if report.get('origin') != 'native_pipeline' or report.get('synthetic') is not False:
        raise ValueError('Only original native reductions can be plotted here')
    if report.get('status') != 'NATIVE_DC_CURVE_REDUCTION_ONLY':
        raise ValueError('No parsed native DC curves in this report')
    if output.exists():
        raise ValueError('Use a new figure directory; preserve earlier results')
    curves = report['curves']
    rows = []
    for name in ('low', 'high'):
        for point in curves[name]['points']:
            vals = [point['Vgs_V'], point['Vds_V']] + list(point['terminal_current_A'].values())
            if not all(math.isfinite(v) for v in vals):
                raise ValueError('Nonfinite original point; no silent plotting filter')
            rows.append(dict(curve=name, Vgs_V=point['Vgs_V'], Vds_V=point['Vds_V'],
                **{terminal+'_A': point['terminal_current_A'][terminal]
                   for terminal in ('drain', 'source', 'body', 'gate')},
                KCL_A=math.fsum(point['terminal_current_A'].values())))
    positive_currents = all(row['drain_A'] > 0 for row in rows)
    output.mkdir(parents=True)
    with (output/'native-dc-points.csv').open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with plt.rc_context({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'figure.dpi': 150, 'savefig.dpi': 220}):
        fig, axes = plt.subplots(1, 3, figsize=(12.2, 4.1), layout='constrained')
        for name, color in (('low', '#21618c'), ('high', '#b45a2a')):
            points = [r for r in rows if r['curve'] == name]
            x = [r['Vgs_V'] for r in points]
            label = 'Vds = {:g} V'.format(points[0]['Vds_V'])
            axes[0].plot(x, [r['drain_A']*1e6 for r in points], color=color, label=label, lw=1.7)
            axes[1].plot(x, [r['drain_A'] for r in points], color=color, label=label, lw=1.7)
            axes[2].plot(x, [r['KCL_A']*1e18 for r in points], color=color, label=label, lw=1.2)
        axes[0].set(title='Transfer current', ylabel='Signed drain current (uA)')
        axes[1].set(title='Signed current across decades', ylabel='Signed drain current (A)')
        if positive_currents:
            axes[1].set_yscale('log')
        else:
            axes[1].set_yscale('symlog', linthresh=1e-16)
        axes[2].set(title='Terminal current balance', ylabel='Sum of terminal currents (aA)')
        for ax in axes:
            ax.set_xlabel('Gate-source voltage (V)')
            if ax is not axes[1] or not positive_currents:
                ax.axhline(0, color='#6d7379', lw=.6)
            ax.grid(True, color='#dce1e6', lw=.5)
        axes[0].legend(frameon=False, loc='best')
        note = ('{:d}D representative BCAT | AreaFactor {:g} | '
                'native signed currents; uncalibrated physics assumptions').format(
                    report['dimension'], report['normalization']['area_factor'])
        if not report.get('passed'):
            note += ' | DIAGNOSTIC: reduction checks failed'
        fig.suptitle(note, fontsize=10.5)
        fig.savefig(output/'dc-curves.png')
        fig.savefig(output/'dc-curves.pdf')
        plt.close(fig)
    inventory = {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()}
    provenance = dict(schema='dram-see-v4-dc-figure-r1', origin='native_pipeline', synthetic=False,
        source_report=str(report_path.resolve()), source_report_sha256=digest(report_path),
        source_data_sha256=report['data_hashes'], role_id=report['role_id'],
        reduction_passed=report['passed'], scientific_acceptance=False,
        row_count=len(rows), removed_points=0, absolute_value_or_sign_flip=False,
        logarithmic_display=('log; every original drain current is strictly positive' if positive_currents else
                             'symlog; linear interval +/- 1e-16 A is display only, not a criterion'),
        output_sha256=inventory, code_sha256=digest(__file__))
    (output/'provenance.json').write_text(json.dumps(provenance, indent=2)+'\n', encoding='utf-8')
    return dict(output=str(output.resolve()), role_id=report['role_id'], points=len(rows))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(create(args.report, args.output)))
