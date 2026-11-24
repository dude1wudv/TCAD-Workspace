import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
from collections import Counter


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pinned(work, reference):
    path = work / reference['path']
    require(sha(path) == reference['sha256'], f'Input SHA mismatch: {path}')
    return json.loads(path.read_bytes())


def probe_points(geometry, frame, faces):
    names = {region['id']: region['material'] for region in geometry['regions']}
    names['World'] = geometry['world']['material']
    boxes = [*geometry['regions'], geometry['world']]
    direction = frame['source_plane']['normal_toward_device']

    def row(kind, key, point, region, material, back=-1, forward=-1, layer=math.inf):
        offsets = [[min(pos - lower, upper - pos) for pos, lower, upper in
                    zip(point, box['lo_nm'], box['hi_nm'], strict=True)] for box in boxes]
        clearance = min(min(axis) if min(axis) >= 0 else math.hypot(*(min(value, 0) for value in axis))
                        for axis in offsets)
        require(all(math.isfinite(value) for value in point) and names[region] == material, key)
        return (kind, key, *point, region, material, back, forward, min(clearance, layer))

    rays = frame['probes']
    require(len(rays) == 40 and {ray['target_region'] for ray in rays} == names.keys() - {'World'},
            'Incomplete ray inventory')
    for index, ray in enumerate(rays):
        origin = ray['origin_nm']
        plane = frame['source_plane']
        relative = [value - center for value, center in zip(origin, plane['center_nm'], strict=True)]
        def dot(axis):
            return sum(first * second for first, second in zip(relative, axis, strict=True))

        require(abs(dot(direction)) < 1e-8, f'Ray origin is outside source plane: {index}')
        for axis, span in (('u_axis', 'u_offsets_nm'), ('v_axis', 'v_offsets_nm')):
            require(plane[span][0] <= dot(plane[axis]) <= plane[span][1], f'Ray origin outside source area: {index}')
        chords = ray['candidate_chords']
        require(ray['same_region_order'] and any(hit['region'] == ray['target_region'] for hit in chords),
                f'Ray missed its target region: {index}')
        previous_exit = chords[0]['entry_path_nm']
        yield row('S', f'ray{index}-source', origin, 'World', names['World'], forward=previous_exit)
        for segment, hit in enumerate(chords):
            start, stop = hit['entry_path_nm'], hit['exit_path_nm']
            require(0 < start < stop and start >= previous_exit - 1e-10, f'Bad chord order: {index}/{segment}')
            for label, lower, upper, region, material in (
                ('gap', previous_exit, start, 'World', names['World']),
                ('chord', start, stop, hit['region'], hit['material']),
            ):
                if label == 'gap' and upper - lower <= 1e-10:
                    continue
                half = (upper - lower) / 2
                point = [value + (lower + half) * component for value, component in zip(origin, direction, strict=True)]
                yield row('C', f'ray{index}-{label}{segment}', point, region, material, half, half)
            previous_exit = stop
    for index, face in enumerate(faces):
        target = face['candidate']
        require(target and not face['ambiguous'] and face['width_nm'] > 0, f'Ambiguous face: {index}')
        yield row('F', f'face{index}', list(map(float, face['point_nm_decimal'])), target['id'], target['material'],
                  layer=face['width_nm'] / 2)


def stage(work, policy, output):
    contract = pinned(work, policy['scientific_gate']['contract'])
    recipe = pinned(work, policy['scheduler_supply']['continuous'])
    handoff = pinned(work, recipe['geometry_audit_index'])
    audits = {}
    for reference in handoff['geometry_audits']:
        audit = pinned(work, reference)
        require(audit['status'] == 'passed' and audit['manifest'] == contract['manifest'], 'Geometry audit differs')
        audits[audit['profile_id']] = (audit, reference)
    require(len(audits) == 6, 'Expected six geometry audits')
    inventory = {}
    for reference in recipe['transport']['preparations']:
        for pool in pinned(work, reference)['pools']:
            candidate, *others = pool['pool_request_candidates']
            profile = candidate['profile_id']
            if profile not in audits:
                continue
            key = pool['task_id']
            require(not others and key not in inventory and re.fullmatch('[a-z0-9-]+', key), f'Invalid frozen pool: {key}')
            project = work / pool['project']
            pins = pool['input_sha256']
            require({name: sha(project / name) for name in pins} == pins, f'Pool inputs changed: {key}')
            request = pinned(work, candidate['native_request'])
            audit, audit_ref = audits[profile]
            frame, = [frame for frame in audit['ray_frames'] if frame['radiation']['id'] == request['radiation_id']]
            require(request['id'] == key and request['profile_ids'] == [profile] and
                    request['manifest_sha256'] == contract['manifest']['sha256'] and
                    request['geometry_sha256'] == pins['geometry.json'] and
                    request['source_plane'] == frame['source_plane'] and request['event_count'] == 100000 and
                    request['incident_energy_MeV'] == frame['radiation']['energy_MeV'] and
                    request['theta_deg'] == frame['radiation']['theta_deg'] and
                    request['phi_deg'] == frame['radiation']['phi_deg'], f'Pool frame mismatch: {key}')
            geometry = json.loads((project / 'geometry.json').read_bytes())
            require(geometry['mesh_sha256'] == audit['native_mesh_sha256'] and
                    geometry['regions'] == audit['candidate_regions'] and
                    (audit['archived_candidate'] is None or pins['geometry.json'] == audit['archived_candidate']['sha256']),
                    f'Geometry differs from audit: {key}')
            points = list(probe_points(geometry, frame, audit['near_interface_probes']))
            counts = {kind: sum(point[0] == kind for point in points) for kind in ('S', 'C', 'F')}
            header = (key, pins['geometry.json'], pins['request.json'], *request['source_plane']['normal_toward_device'],
                      *counts.values())
            directory = output / key
            directory.mkdir(parents=True)
            for name in ('transport_l08.cc', 'geometry.hh'):
                shutil.copyfile(project / name, directory / name)
            point_file = directory / 'points.tsv'
            point_file.write_text(''.join('\t'.join(map(str, row)) + '\n' for row in (header, *points)), encoding='ascii')
            inventory[key] = {'profile_id': profile, 'radiation_id': request['radiation_id'], 'input_sha256': pins,
                              'counts': counts, 'geometry_audit': audit_ref, 'preparation': reference,
                              'points_sha256': sha(point_file)}
    require(Counter(row['profile_id'] for row in inventory.values()) == {profile: 8 for profile in audits} and
            len({(row['profile_id'], row['radiation_id']) for row in inventory.values()}) == 48,
            'Expected 48 unique LHS transport pools')
    (output / 'inventory.json').write_text(json.dumps(inventory, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    workspace, policy_file, target = map(Path, sys.argv[1:])
    stage(workspace, json.loads(policy_file.read_bytes()), target)
