"""Read native DF-ISE exports without launching tools or altering observations.

Coordinate values come only from Vertices and Contact element connectivity.
Concentrations come only from complete region-local native datasets. Expected
geometry is used for comparison and units, never to manufacture measurements.
The D2 edge convention is independently checked by closed, positive-area cells,
per-region vertex counts and native SVisual integrals. D3 remains subject to its
first real export and the same coordinate/contact/data checks.
"""
from array import array
import csv
import math
from pathlib import Path
import re


def require(ok, message):
    if not ok:
        raise ValueError(message)


def finite(token):
    value = float(token)
    require(math.isfinite(value), 'Nonfinite DF-ISE value')
    return value


def meaningful(stream):
    while True:
        line = stream.readline()
        if not line:
            raise ValueError('Truncated DF-ISE document')
        value = line.strip()
        if value and not value.startswith('#'):
            return value


def block(stream):
    lines = []
    while True:
        line = meaningful(stream)
        if line == '}':
            return '\n'.join(lines)
        require('{' not in line and '}' not in line, 'Unexpected nested DF-ISE block')
        lines.append(line)


def attribute(text, name):
    found = re.findall(r'(?m)^\s*' + re.escape(name) + r'\s*=\s*([^\n]+)', text)
    require(len(found) == 1, 'Missing/duplicate DF-ISE attribute: ' + name)
    return found[0].strip()


def bracket(text, name):
    found = re.findall(r'\b' + re.escape(name) + r'\s*=\s*\[([^\]]*)\]', text)
    require(len(found) == 1, 'Missing/duplicate DF-ISE array: ' + name)
    return found[0].split()


def header(stream, kind):
    require(meaningful(stream) == 'DF-ISE text', 'Not native textual DF-ISE')
    require(meaningful(stream) == 'Info {', 'Missing DF-ISE Info')
    info = block(stream)
    require(attribute(info, 'type') == kind, 'Wrong DF-ISE document type')
    dim = int(attribute(info, 'dimension'))
    require(dim in (2, 3), 'Unsupported mesh dimension')
    counts = {name: int(attribute(info, 'nb_' + name))
              for name in ('vertices', 'edges', 'faces', 'elements', 'regions')}
    require(all(v >= 0 for v in counts.values()) and counts['vertices'] > 0
            and counts['elements'] > 0 and counts['regions'] > 0, 'Empty/invalid native mesh')
    require(meaningful(stream) == 'Data {', 'Missing DF-ISE Data')
    return info, dim, counts


def records(stream, count):
    for unused in range(count):
        line = meaningful(stream)
        require(line != '}', 'Truncated counted DF-ISE array')
        yield line
    require(meaningful(stream) == '}', 'Extra/truncated DF-ISE array values')


def index(value, count, label):
    require(0 <= value < count, 'DF-ISE reference out of range: ' + label)
    return value


def read_grid(path):
    """Streaming parser keeps coordinate/connectivity arrays compact for D3."""
    vertices, edges = array('d'), array('q')
    regions, observed_sections = [], set()
    with Path(path).open(encoding='ascii', newline='') as stream:
        info, dim, counts = header(stream, 'grid')
        names = re.findall(r'"([^"\n]+)"', ' '.join(bracket(info, 'regions')))
        materials = bracket(info, 'materials')
        require(len(names) == len(materials) == counts['regions'] and len(set(names)) == len(names),
                'Native mesh region inventory differs from header')
        owners = array('i', [-1]) * counts['elements']
        element_offset = None
        while True:
            line = meaningful(stream)
            if line == '}':
                break
            if line == 'CoordSystem {':
                require('CoordSystem' not in observed_sections, 'Duplicate coordinate system')
                observed_sections.add('CoordSystem')
                cs = block(stream)
                transform = list(map(finite, bracket(cs, 'transform')))
                translate = list(map(finite, bracket(cs, 'translate')))
                require(transform == [1., 0., 0., 0., 1., 0., 0., 0., 1.] and translate == [0., 0., 0.],
                        'Unverified DF-ISE coordinate transform; no implicit rotation/scale allowed')
                continue
            section = re.fullmatch(r'(Vertices|Edges|Faces|Locations|Elements)\s*\((\d+)\)\s*\{', line)
            if section:
                kind, count = section[1], int(section[2])
                require(kind not in observed_sections, 'Duplicate mesh section: ' + kind)
                observed_sections.add(kind)
                expected = counts[{'Vertices':'vertices','Edges':'edges','Faces':'faces','Elements':'elements',
                                   'Locations':'edges' if dim == 2 else 'faces'}[kind]]
                require(count == expected, 'Mesh section count/header mismatch: ' + kind)
                if kind == 'Locations':
                    raw = ''.join(block(stream).split())
                    require(len(raw) == count and set(raw) <= set('ief'), 'Invalid native element locations')
                    continue
                if kind == 'Elements':
                    element_offset = stream.tell()
                for row in records(stream, count):
                    if kind == 'Vertices':
                        values = list(map(finite, row.split()))
                        require(len(values) == dim, 'Vertex dimension mismatch')
                        vertices.extend(values)
                    elif kind == 'Edges':
                        values = list(map(int, row.split()))
                        require(len(values) == 2 and values[0] != values[1], 'Invalid/zero native edge')
                        for v in values:
                            index(v, counts['vertices'], 'edge vertex')
                        edges.extend(values)
                    else:
                        # Full cell interpretation occurs only after region membership is known.
                        require(re.fullmatch(r'[+-]?\d+(?:\s+[+-]?\d+)*', row) is not None,
                                'Invalid integer connectivity record')
                continue
            match = re.fullmatch(r'Region\s*\("([^"\n]+)"\)\s*\{', line)
            require(match is not None, 'Unexpected native grid section: ' + line[:100])
            name = match[1]
            require(name in names and name not in {r['name'] for r in regions}, 'Unknown/duplicate grid region')
            material_line = meaningful(stream)
            require(material_line.startswith('material = '), 'Missing native region material')
            material = material_line.split('=', 1)[1].strip()
            require(material == materials[names.index(name)], 'Native region/header material mismatch')
            region_elements = re.fullmatch(r'Elements\s*\((\d+)\)\s*\{', meaningful(stream))
            require(region_elements is not None, 'Missing native region elements')
            expected = int(region_elements[1]); seen = 0; rid = len(regions)
            while True:
                line = meaningful(stream)
                if line == '}':
                    break
                for value in map(int, line.split()):
                    index(value, counts['elements'], 'region element')
                    require(owners[value] == -1, 'Duplicate native element ownership')
                    owners[value] = rid
                    seen += 1
            require(seen == expected and seen > 0, 'Empty/truncated region element membership')
            require(meaningful(stream) == '}', 'Unclosed native region')
            regions.append(dict(name=name, material=material, element_count=seen))
        require(not stream.read().strip(), 'Unexpected trailing grid contents')
        require({'Vertices','Edges','Elements','Locations','CoordSystem'} <= observed_sections
                and len(regions) == counts['regions'] and -1 not in owners and element_offset is not None,
                'Incomplete native grid topology')
        require(dim != 3 or 'Faces' in observed_sections, 'Missing 3D native faces')
        contact_ids = {r['name']: set() for r in regions if r['material'] == 'Contact'}
        contact_measures = {name: [] for name in contact_ids}
        region_ids = {r['name']: set() for r in regions if r['material'] not in ('Contact', 'Interface')} if dim == 2 else {}
        region_areas = {name: [] for name in region_ids}

        def point(vid):
            index(vid, counts['vertices'], 'element vertex')
            return tuple(vertices[dim * vid:dim * (vid + 1)])

        def polygon(edge_refs):
            oriented = []
            for ref in edge_refs:
                eid = ref if ref >= 0 else -ref - 1
                index(eid, counts['edges'], 'oriented element edge')
                a, b = edges[2 * eid:2 * eid + 2]
                oriented.append((a, b) if ref >= 0 else (b, a))
            require(all(oriented[k][1] == oriented[(k + 1) % len(oriented)][0]
                        for k in range(len(oriented))), 'Native polygon edges do not form a closed loop')
            vids = [item[0] for item in oriented]
            require(len(set(vids)) == len(vids), 'Repeated native polygon vertex')
            return vids

        stream.seek(element_offset)
        for eid, row in enumerate(records(stream, counts['elements'])):
            region = regions[owners[eid]]
            name, material = region['name'], region['material']
            if material != 'Contact' and name not in region_ids:
                continue
            item = list(map(int, row.split()))
            if material == 'Contact' and dim == 2:
                require(len(item) == 3 and item[0] == 1, 'Unsupported 2D contact element')
                vids = item[1:]
                points = [point(v) for v in vids]
                measure = math.sqrt(sum((a - b) ** 2 for a, b in zip(*points)))
            else:
                require(item[0] in (2, 3) and len(item) == (4 if item[0] == 2 else 5),
                        'Unsupported native polygon element')
                vids = polygon(item[1:]); points = [point(v) for v in vids]
                if dim == 2:
                    measure = .5 * math.fsum(points[k][0] * points[(k + 1) % len(points)][1]
                                             - points[(k + 1) % len(points)][0] * points[k][1]
                                             for k in range(len(points)))
                else:
                    require(len(points) == 3, '3D contact quadrilateral requires separate native verification')
                    u = [b-a for a,b in zip(points[0], points[1])]
                    v = [b-a for a,b in zip(points[0], points[2])]
                    cross = [u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
                    measure = .5 * math.sqrt(sum(x*x for x in cross))
            require(math.isfinite(measure) and measure > 0, 'Nonpositive/nonfinite native element measure')
            if material == 'Contact':
                contact_ids[name].update(vids); contact_measures[name].append(measure)
            else:
                region_ids[name].update(vids); region_areas[name].append(measure)
        contacts = {}
        for name, vids in contact_ids.items():
            points = [point(v) for v in vids]
            require(points, 'Contact has no observed vertices')
            contacts[name] = dict(vertices=len(vids), bounds=[[min(p[k] for p in points), max(p[k] for p in points)]
                                                           for k in range(dim)],
                                  mesh_measure=math.fsum(contact_measures[name]))
        for region in regions:
            if region['name'] in region_ids:
                region.update(vertices=len(region_ids[region['name']]), mesh_measure=math.fsum(region_areas[region['name']]))
        return dict(dimension=dim, counts=counts, transform=transform, translate=translate,
                    bounds=[[min(vertices[k::dim]), max(vertices[k::dim])] for k in range(dim)],
                    regions=regions, contacts=contacts)


def read_datasets(path):
    datasets = {}
    with Path(path).open(encoding='ascii', newline='') as stream:
        unused, dim, counts = header(stream, 'dataset')
        while True:
            line = meaningful(stream)
            if line == '}':
                break
            match = re.fullmatch(r'Dataset\s*\("([^"\n]+)"\)\s*\{', line)
            require(match is not None, 'Unexpected native dataset declaration')
            name = match[1]; attrs = []
            while True:
                line = meaningful(stream)
                values = re.fullmatch(r'Values\s*\((\d+)\)\s*\{', line)
                if values:
                    break
                attrs.append(line)
            attrs = '\n'.join(attrs)
            require(attribute(attrs, 'function') == name and attribute(attrs, 'type') == 'scalar'
                    and attribute(attrs, 'dimension') == '1' and attribute(attrs, 'location') == 'vertex',
                    'Unsupported native dataset type/location')
            validity = re.findall(r'"([^"\n]+)"', ' '.join(bracket(attrs, 'validity')))
            require(len(validity) == 1, 'Expected one native region per dataset')
            key = (validity[0], name)
            require(key not in datasets, 'Duplicate native region field')
            n = 0; lo, hi = math.inf, -math.inf; nonzero = 0
            while True:
                line = meaningful(stream)
                if line == '}':
                    break
                for value in map(finite, line.split()):
                    n += 1; lo = min(lo, value); hi = max(hi, value); nonzero += int(value != 0)
            require(n == int(values[1]) and n > 0, 'Empty/truncated native field values')
            require(meaningful(stream) == '}', 'Unclosed native dataset')
            datasets[key] = dict(count=n, min=lo, max=hi, nonzero=nonzero)
        require(not stream.read().strip(), 'Unexpected trailing dataset contents')
    return dict(dimension=dim, counts=counts, datasets=datasets)


def rows(path):
    with Path(path).open(encoding='utf-8', newline='') as stream:
        result = list(csv.DictReader(stream))
    require(result and all(None not in row and None not in row.values() for row in result), 'Malformed metadata CSV')
    return result


def observe(plan, raw):
    raw = Path(raw)
    grid = read_grid(raw / 'mesh-observed.grd')
    data = read_datasets(raw / 'mesh-observed.dat')
    require(grid['dimension'] == data['dimension'] == plan['dimension'] and grid['counts'] == data['counts'],
            'Native grid/dataset identity counts differ')
    geometries = rows(raw / 'tdr-geometry.csv')
    require(len(geometries) == 1, 'Expected one original TDR geometry')
    geometry = geometries[0]
    require(geometry['geometry_index'] == '0' and geometry['geometry_type'] == 'mixed_element'
            and int(geometry['dimension']) == plan['dimension'] and geometry['states'] == '1'
            and int(geometry['regions']) == grid['counts']['regions']
            and list(map(finite, geometry['transform'].split())) == grid['transform']
            and list(map(finite, geometry['shift'].split())) == grid['translate'],
            'Original TDR/DF-ISE geometry or coordinate mapping differs')
    inventory = rows(raw / 'tdr-region-datasets.csv')
    native_fields = {}
    region_map = {r['name']: r for r in grid['regions']}
    seen_regions = set()
    for row in inventory:
        name = row['region_name']; seen_regions.add(name)
        require(name in region_map and row['geometry_index'] == '0' and row['state_index'] == '0',
                'TDX region identity differs')
        material = region_map[name]['material']
        require(row['material'] == {'Contact':'<contact>', 'Interface':'<interface>'}.get(material, material),
                'TDX/grid material mapping differs')
        expected_type = {'Contact':'contact', 'Interface':'interface'}.get(material, 'bulk')
        require(row['region_type'] == expected_type and int(row['region_dimension']) ==
                (plan['dimension'] if expected_type == 'bulk' else plan['dimension'] - 1),
                'TDX/grid region type/dimension differs')
        if row['command_status'] == 'NO_DATASETS':
            require(expected_type != 'bulk' and row['num_values'] == '0' and row['dataset_name'] == '',
                    'Missing native bulk dataset')
            continue
        key = (name, row['dataset_name'])
        require(row['command_status'] == 'OK' and key not in native_fields and key in data['datasets']
                and row['location'] == 'vertex' and row['unit'] == 'cm^-3'
                and row['quantity'] == row['dataset_name'], 'Missing/duplicate/wrong-unit native field metadata')
        require(int(row['num_values']) == data['datasets'][key]['count'], 'TDX/export dataset count differs')
        if 'vertices' in region_map[name]:
            require(region_map[name]['vertices'] == data['datasets'][key]['count'],
                    'Native region topology/dataset vertex count differs')
        native_fields[key] = row
    require(seen_regions == set(region_map) and set(native_fields) == set(data['datasets']),
            'TDX/export region or dataset coverage differs')
    output = {}
    physical = {r['name']:r['material'] for r in plan['expected_geometry']['regions']}
    require({r['name']:r['material'] for r in grid['regions'] if r['material'] not in ('Contact','Interface')} == physical,
            'Actual DF-ISE physical region/material inventory differs')
    require(set(grid['contacts']) == {c['name'] for c in plan['expected_geometry']['contacts']},
            'Actual native contact coverage differs')
    for item in plan['measurements']:
        if item['category'] == 'contacts':
            require(item['entity_kind'] == 'region' and item['unit'] == 'um'
                    and item['field'] in 'XYZ'[:plan['dimension']] and item['operation'] in ('min','max'),
                    'Unsupported contact observation request')
            value = grid['contacts'][item['entity']]['bounds']['XYZ'.index(item['field'])][('min','max').index(item['operation'])]
            source = 'native_dfise_contact_vertices'
        elif item['id'].startswith('outside_si.'):
            require(item['entity'] in physical and physical[item['entity']] != 'Silicon'
                    and item['entity_kind'] == 'region' and item['unit'] == 'cm^-3'
                    and item['operation'] in ('min','max'), 'Unsupported non-silicon field observation request')
            key = (item['entity'], item['field'])
            require(key in data['datasets'], 'Actual non-silicon field is absent; never substitute zero')
            value = data['datasets'][key][item['operation']]
            source = 'native_dfise_region_dataset'
        else:
            continue
        output[item['id']] = dict(value=value, source=source)
    # Independent native SVisual domain coordinates and integrals tie the export
    # to the actual AsIs geometry and chosen SDE micrometer modeling unit.
    visual_rows = rows(raw / 'material-measurements.csv')
    visual = {row['id']:row for row in visual_rows}
    require(len(visual) == len(visual_rows), 'Duplicate native SVisual cross-check value')
    crosschecks = []
    def corroborate(name, actual, absolute, relative):
        require(name in visual and visual[name]['command_status'] == 'OK', 'Native SVisual corroboration is missing')
        match = re.fullmatch(r'\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(?:\s+\{([^{}]+)\})?\s*',
                             visual[name]['raw_value'])
        require(match is not None, 'Native SVisual corroboration is nonfinite/malformed')
        observed = finite(match[1])
        if match[2] is not None:
            coordinates = list(map(finite, match[2].split()))
            require(len(coordinates) in (plan['dimension'],3), 'Native SVisual corroboration coordinate dimension differs')
        require(abs(actual-observed) <= max(absolute,relative*abs(observed)),
                'DF-ISE/native SVisual coordinate or unit corroboration differs: '+name)
        crosschecks.append(dict(id=name,dfise=actual,svisual=observed,absolute_delta=abs(actual-observed)))
    for axis, limits in zip('XYZ', grid['bounds']):
        for operation, value in zip(('min','max'), limits):
            corroborate('domain.'+axis+'.'+operation,value,plan['comparison_policy']['coordinate_absolute_um'],0.)
    if plan['dimension'] == 2:
        for region in grid['regions']:
            if region['name'] in physical:
                corroborate('region.'+region['name'],region['mesh_measure'],
                            plan['comparison_policy']['region_absolute'],plan['comparison_policy']['region_relative'])
    audit = dict(grid=grid, datasets=[dict(region=k[0], field=k[1], **v) for k,v in sorted(data['datasets'].items())],
                 independent_native_crosschecks=crosschecks,
                 coordinate_interpretation='TDR identity transform/zero shift equals DF-ISE identity transform/zero translate; no rotation or scale applied',
                 length_unit='um', length_unit_basis='Frozen SDE modeling unit; independently checked against native SVisual domain and region integrals')
    return output, audit
