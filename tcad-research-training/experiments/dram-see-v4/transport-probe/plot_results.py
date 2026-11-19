"""Plot only completed audited proton probes, never probability estimates."""
import csv
import hashlib
import itertools
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUNTIME = ROOT / 'local_runtime/dram-see-v4/transport-probe'


def main():
    index = json.loads((HERE / 'run-index.json').read_text(encoding='utf-8'))
    if any(q['status'] != 'PASSED' for q in index['requests']):
        raise ValueError('The frozen probes have not all passed')
    evidence = []

    def rows(label, name):
        audit = json.loads((RUNTIME / 'audits' / label / 'audit.json').read_text(encoding='utf-8'))
        if not audit['passed']:
            raise ValueError('Plot input audit has not passed')
        path = RUNTIME / 'runs' / label / name
        evidence.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        with path.open(encoding='utf-8', newline='') as stream:
            return list(csv.DictReader(stream))

    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    fig = plt.figure(figsize=(11.2, 5.1), constrained_layout=True)
    ax = fig.add_subplot(121, projection='3d')
    sample = rows('format-h5-a0-r1', 'steps.csv')
    tracks = {}
    for row in sample:
        if row['event_id'] == '0' and row['pre_volume'] == 'Si':
            tracks.setdefault(row['track_id'], []).append(row)
    seen = set()
    for track in tracks.values():
        particle = track[0]['particle']
        color = '#147f9d' if particle == 'proton' else '#dc8027' if particle == 'e-' else '#925cac'
        pts = [[float(track[0]['pre_' + c + '_um'])] + [float(s['post_' + c + '_um']) for s in track] for c in ('x', 'y', 'z')]
        ax.plot(*pts, color=color, lw=1.8 if particle == 'proton' else 1.1,
                label=particle if particle not in seen else None)
        seen.add(particle)
    corners = list(itertools.product((0., .85), (0., 1.2), (-.5, .5)))
    for a, b in itertools.combinations(corners, 2):
        if sum(x != y for x, y in zip(a, b)) == 1:
            ax.plot(*zip(a, b), color='#969da3', alpha=.6, lw=.6)
    ax.set(xlabel='x (um)', ylabel='y (um)', zlabel='z (um)',
           xlim=(0, .85), ylim=(0, 1.2), zlim=(-.5, .5),
           title='Recorded tracks inside silicon\n5 MeV, 0 deg, format probe event 0')
    ax.view_init(elev=22, azim=-55)
    ax.legend(loc='upper left', fontsize=9)
    ax2 = fig.add_subplot(122)
    for angle, color, marker in ((0, '#147f9d', 'o'), (30, '#dc8027', '^')):
        first = True
        for q in index['requests']:
            if q['stage'] != 'small-events' or q['arm'] != 'H' or q['angle_deg'] != angle:
                continue
            events = rows(q['label'], 'events.csv')
            energies = [float(e['ionizing_si_MeV']) * 1000 for e in events]
            ax2.scatter([q['energy_MeV']] * len(events), energies, color=color, marker=marker,
                        s=48, alpha=.85, label=str(angle) + ' deg' if first else None)
            first = False
    ax2.set_xscale('log')
    ax2.set_xticks([1, 5, 20, 100], labels=['1', '5', '20', '100'])
    ax2.set(xlabel='Primary proton energy (MeV)', ylabel='Si ionizing deposition per primary (keV)',
            title='H-arm small checks\n2 primaries per energy / angle; no fitted curve')
    ax2.grid(alpha=.2)
    ax2.legend()
    fig.suptitle('v4 Geant4 10.7.3 transport-record checks | uncalibrated silicon slab', fontsize=13)
    output = HERE / 'results'
    fig.savefig(output / 'proton-checks.png', dpi=170)
    fig.savefig(output / 'proton-checks.pdf')
    plt.close(fig)
    (output / 'figure-provenance.json').write_text(json.dumps({
        'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'inputs': evidence, 'scope': 'Actual complete audited records. Tracks shown only for Si steps; raw records retain world steps and full z. Descriptive tiny samples, no probability or device response claim.'
    }, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
