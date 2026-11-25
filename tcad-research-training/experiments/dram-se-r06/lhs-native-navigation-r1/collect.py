import csv
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

from stage import require, sha


def collect(output):
    require((output / 'geant4-version.txt').read_text().strip() == '10.7.3', 'Wrong Geant4 version')
    inventory = json.loads((output / 'inventory.json').read_bytes())
    result = {}
    for task, spec in inventory.items():
        directory = output / task
        artifacts = {}
        for name, expected in {**{name: spec['input_sha256'][name] for name in ('transport_l08.cc', 'geometry.hh')},
                               'points.tsv': spec['points_sha256']}.items():
            require(sha(directory / name) == expected, f'Compiled probe input differs: {task}/{name}')
        for name in ('geometry-built.csv', 'navigation.csv', 'navigation.err', 'compile.err', 'exit-code'):
            path = directory / name
            if path.is_file():
                artifacts[name] = sha(path)
        report = {**spec, 'artifacts_sha256': artifacts}
        exit_file = directory / 'exit-code'
        if not exit_file.is_file():
            report.update(status='pending')
        elif exit_file.read_text().strip() != '0':
            report.update(status='failed', exit_code=int(exit_file.read_text()))
        else:
            with (directory / 'navigation.csv').open(newline='') as stream:
                expected_pins = spec['input_sha256']
                lines = iter(stream)
                overlap_log = [next(lines, '').strip() for _ in range(40)]
                require(all(re.fullmatch(r'Checking overlaps for volume R[0-9]{3} \(G4Box\) \.\.\. OK!', line)
                            for line in overlap_log), f'Unexpected Geant4 overlap log: {task}')
                require(next(lines, '').strip().split() ==
                        ['#', task, expected_pins['geometry.json'], expected_pins['request.json']],
                        f'Transport identity differs in native output: {task}')
                rows = list(csv.DictReader(line for line in lines if not re.fullmatch(
                    r'WARNING - Attempt to delete the (physical volume|logical volume|solid) store while geometry closed !\s*',
                    line)))
            with (directory / 'geometry-built.csv').open(newline='') as stream:
                volumes = list(csv.DictReader(stream))
            require(Counter(row['kind'] for row in rows) == spec['counts'] and
                    len({row['point'] for row in rows}) == len(rows) and
                    len(volumes) == len({row['volume'] for row in volumes}) == 41, f'Missing native rows: {task}')
            require(all(row['overlap_check_passed'] == '1' for row in volumes), f'Overlap observed: {task}')
            require(all(row['status'] == 'pass' or
                        (row['kind'] == 'F' and row['status'] == 'resolution_limited') for row in rows),
                    f'Navigation mismatch: {task}')
            report.update(status='passed', source_origins=spec['counts']['S'], chord_or_gap_points=spec['counts']['C'],
                          resolved_faces=sum(row['kind'] == 'F' and row['status'] == 'pass' for row in rows),
                          resolution_limited_faces=sum(row['status'] == 'resolution_limited' for row in rows))
        result[task] = report
    return {'schema': 'tcad-r06-lhs-native-navigation-v1', 'utc': datetime.now(timezone.utc).isoformat(),
            'geant4': '10.7.3', 'primaries': 0, 'maximum_world_extent_nm': 3000, 'surface_tolerance_nm': 3e-8,
            'inventory_sha256': sha(output / 'inventory.json'), 'probe_sha256': sha(output / 'navigation.cc'),
            'counts': dict(Counter(row['status'] for row in result.values())), 'pools': result}


if __name__ == '__main__':
    report = collect(Path(sys.argv[1]))
    with Path(sys.argv[2]).open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(report['counts'])
