"""Plot audited A0/A1/A4 data without launching or changing any solver run."""
from pathlib import Path
import csv
import hashlib
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    root = Path(__file__).resolve().parents[3]
    source = root / 'local_runtime/dram-see-v4/source-probe/audits'
    output = Path(__file__).resolve().parent / 'results'
    output.mkdir(exist_ok=True)
    evidence = []
    data = {}
    for case in ('A0', 'A1', 'A4'):
        folder = source / (case.lower() + '-b1-r1')
        audit = json.loads((folder / 'audit.json').read_text(encoding='utf-8'))
        if not audit['passed']:
            raise ValueError('Run audit has not passed: ' + case)
        tables = {}
        for name in ('circuit', 'device'):
            path = folder / (name + '.csv')
            with path.open(newline='', encoding='utf-8') as handle:
                rows = list(csv.DictReader(handle))
            tables[name] = {key: np.array([float(row[key]) for row in rows]) for key in rows[0]}
            evidence.append({'path': path.relative_to(root).as_posix(),
                             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        data[case] = tables

    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False,
                         'axes.spines.right': False, 'axes.grid': True,
                         'grid.alpha': 0.2})
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
    colors = {'A0': '#79828b', 'A1': '#137ba3', 'A4': '#dd8035'}
    labels = {'A0': 'A0: no source', 'A1': 'A1: 1 fC', 'A4': 'A4: 0.5 + 0.5 fC'}
    for case, tables in data.items():
        device, circuit = tables['device'], tables['circuit']
        t = device['time']
        # Original spatial integral: pairs/(cm^3 s) * um^3.
        rate_fC_s = device['IntegrSemiconductor HeavyIonGeneration'] * 1e-12 * 1.602176634e-19 * 1e15
        cumulative = np.r_[0., np.cumsum((rate_fC_s[1:] + rate_fC_s[:-1]) * np.diff(t) / 2.)]
        style = dict(color=colors[case], label=labels[case], lw=1.8,
                     linestyle='--' if case == 'A4' else '-')
        axes[0, 0].plot(t * 1e9, rate_fC_s * 1e-9, **style)
        axes[0, 1].plot(t * 1e9, cumulative, **style)
        axes[1, 0].plot(circuit['time'] * 1e9, circuit['v(sn)'], **style)
        axes[1, 1].plot(circuit['time'] * 1e9, circuit['v(bl)'], **style)
    axes[0, 0].set(xlim=(0.985, 1.015), xlabel='Time (ns)', ylabel='Generation rate (fC/ns)', title='Actual integrated source near injection')
    axes[0, 1].set(xlim=(0.985, 1.03), xlabel='Time (ns)', ylabel='Generated charge (fC)', title='Time integral of the source')
    axes[0, 1].axhline(1., color='#777777', lw=0.8, linestyle=':', label='1 fC target')
    axes[1, 0].set(xlim=(0, 4), xlabel='Time (ns)', ylabel='Storage node (V)', title='Storage-node response')
    axes[1, 1].set(xlim=(2.75, 4), xlabel='Time (ns)', ylabel='Bitline (V)', title='Precharge and readout response')
    for ax in axes.flat:
        ax.legend(fontsize=8, loc='best')
    fig.suptitle('v4 source interface probe | 2D, L = 0.25 um, stored bit = 1\nOverlapping traces are expected; no bit-flip classification', fontsize=13)
    fig.savefig(output / 'source-probe-curves.png', dpi=170)
    fig.savefig(output / 'source-probe-curves.pdf')
    plt.close(fig)
    (output / 'figure-provenance.json').write_text(json.dumps({
        'source': 'Real audited solver curves; no synthetic curves or smoothing',
        'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'inputs': evidence,
        'note': 'Plotting does not establish numerical convergence or device calibration.'
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
