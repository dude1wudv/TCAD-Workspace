"""Read the complete, original h5dump FILE export; never execute native tools.

This version supports only the observed W-2024.09, TDR-HDF5-v16 3D schema.
It does not infer Ogawa storage types or a field-local to global vertex order.
The caller must independently bind the native operation/collection provenance.
"""
from array import array
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys

SCHEMA = 'dram-see-v4-native-hdf5-observation-r1'
ACTIVE_SCHEMA = 'dram-see-v4-native-hdf5-observation-r2'
ACTIVE_BINDING_SCHEMA = 'dram-see-v4-metadata-hdf5-source-binding-r2'
ACTIVE_CONTEXT_SCHEMA = 'dram-see-v4-hdf5-geometry-observation-context-r2'
ACTIVE_REPRESENTATION = 'tdr-hdf5-v16'
GEO = '/collection/geometry_0'
FIELDS = ('DelVorWeight', 'DopingConcentration', 'ArsenicActiveConcentration', 'BoronActiveConcentration')
EXPECTED_PATHS = ([GEO + '/vertex', GEO + '/offset', GEO + '/transformation/A', GEO + '/transformation/b']
                  + [GEO + '/region_%d/elements_0' % i for i in range(13)]
                  + [GEO + '/state_0/dataset_%d/values' % i for i in range(16)]
                  + ['/collection/pi/data'])
IDENTITY = [1., 0., 0., 0., 1., 0., 0., 0., 1.]
UNIT_UM = [-6, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1]
UNIT_CM3 = [6, -3, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1]
H5DUMP = '/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64/bin/h5dump'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1048576), b''):
            h.update(part)
    return h.hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _json(path):
    with Path(path).open(encoding='utf-8') as stream:
        return json.load(stream, object_pairs_hook=_pairs,
                         parse_constant=lambda value: require(False, 'Nonfinite JSON: ' + value))


class DDL:
    """Strict lexer/parser for the actual h5dump DDL, never evaluates text."""
    token = re.compile(r'\s*("(?:[^"\\]|\\.)*"|[{}();,:/]|[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|[A-Za-z_][A-Za-z_0-9]*)')

    def __init__(self, text):
        self.tokens = []
        pos = 0
        while text[pos:].strip():
            match = self.token.match(text, pos)
            require(match is not None, 'Unsupported/truncated HDF5 DDL token at %d' % pos)
            self.tokens.append(match[1]); pos = match.end()
        self.i = 0
        self.groups = {}
        self.datasets = {}

    def pop(self, expected=None):
        require(self.i < len(self.tokens), 'Truncated HDF5 DDL')
        value = self.tokens[self.i]; self.i += 1
        require(expected is None or value == expected, 'Unexpected HDF5 DDL: expected %r, got %r' % (expected, value))
        return value

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def string(self):
        value = self.pop()
        require(value.startswith('"'), 'Expected HDF5 DDL quoted string')
        return json.loads(value)

    def datatype(self):
        self.pop('DATATYPE'); kind = self.pop()
        if kind == 'H5T_COMPOUND':
            self.pop('{'); members = []
            while self.peek() != '}':
                typ = self.pop(); name = self.string(); self.pop(';')
                require(typ == 'H5T_IEEE_F64LE' and name in ('x', 'y', 'z')
                        and name not in [item[0] for item in members], 'Unsupported coordinate compound member')
                members.append([name, typ])
            self.pop('}')
            return dict(kind=kind, members=members)
        if kind == 'H5T_STRING':
            self.pop('{'); props = {}
            while self.peek() != '}':
                key = self.pop(); require(key not in props, 'Duplicate HDF5 string property')
                props[key] = self.pop(); self.pop(';')
            self.pop('}')
            require(set(props) == {'STRSIZE', 'STRPAD', 'CSET', 'CTYPE'}
                    and props['STRSIZE'].isdigit() and int(props['STRSIZE']) > 0
                    and props['STRPAD'] == 'H5T_STR_NULLTERM' and props['CSET'] == 'H5T_CSET_ASCII'
                    and props['CTYPE'] == 'H5T_C_S1', 'Unsupported HDF5 string type')
            return dict(kind=kind, properties=props)
        require(kind in ('H5T_IEEE_F64LE', 'H5T_STD_I8LE', 'H5T_STD_I32LE', 'H5T_STD_I64LE'),
                'Unsupported HDF5 primitive type: ' + kind)
        return dict(kind=kind)

    def shape(self):
        self.pop('DATASPACE'); kind = self.pop()
        if kind == 'SCALAR':
            return []
        require(kind == 'SIMPLE', 'Unsupported HDF5 dataspace')
        self.pop('{')
        shapes = []
        for n in range(2):
            if n:
                self.pop('/')
            self.pop('('); dims = []
            while self.peek() != ')':
                value = self.pop()
                require(value.isdigit() and int(value) > 0, 'Invalid HDF5 extent')
                dims.append(int(value))
                if self.peek() == ',':
                    self.pop(',')
                else:
                    break
            self.pop(')'); shapes.append(dims)
        self.pop('}')
        require(shapes[0] == shapes[1] and shapes[0], 'Resizable/empty HDF5 dataspace is unsupported')
        return shapes[0]

    def data(self, dtype, shape, allow_empty=False):
        self.pop('DATA'); self.pop('{'); values = []
        count = math.prod(shape) if hasattr(math, 'prod') else _product(shape)
        while self.peek() != '}':
            self.pop('('); offset = self.pop(); self.pop(')'); self.pop(':')
            require(offset.isdigit() and int(offset) == len(values), 'Noncontiguous HDF5 attribute data')
            while True:
                raw = self.pop()
                kind = dtype['kind']
                if kind == 'H5T_STRING':
                    require(raw.startswith('"'), 'Wrong HDF5 string value')
                    value = json.loads(raw)
                    require(value.isascii() if hasattr(value, 'isascii') else all(ord(c) < 128 for c in value),
                            'Non-ASCII HDF5 string')
                    require(len(value) <= int(dtype['properties']['STRSIZE']), 'HDF5 string exceeds declared size')
                elif kind == 'H5T_IEEE_F64LE':
                    value = float(raw); require(math.isfinite(value), 'Nonfinite HDF5 attribute')
                else:
                    require(re.fullmatch(r'[+-]?\d+', raw) is not None, 'Noninteger HDF5 attribute')
                    value = int(raw)
                    bits = {'H5T_STD_I8LE': 8, 'H5T_STD_I32LE': 32, 'H5T_STD_I64LE': 64}[kind]
                    require(-(1 << (bits-1)) <= value < (1 << (bits-1)), 'HDF5 integer overflow')
                values.append(value)
                if self.peek() != ',':
                    break
                self.pop(',')
                if self.peek() in ('(', '}'):
                    break
        self.pop('}')
        require(len(values) == count or (allow_empty and not values), 'HDF5 attribute value count differs')
        return values[0] if not shape and values else values

    def attribute(self):
        self.pop('ATTRIBUTE'); name = self.string(); self.pop('{')
        dtype = self.datatype(); shape = self.shape(); value = self.data(dtype, shape)
        self.pop('}')
        return name, dict(dtype=dtype, shape=shape, value=value)

    def node(self, parent=''):
        kind = self.pop(); require(kind in ('GROUP', 'DATASET'), 'Unexpected HDF5 node')
        name = self.string(); self.pop('{')
        path = name if name.startswith('/') else parent.rstrip('/') + '/' + name
        target = self.groups if kind == 'GROUP' else self.datasets
        require(path not in target, 'Duplicate HDF5 node: ' + path)
        node = dict(attributes={}); target[path] = node
        if kind == 'DATASET':
            node.update(dtype=self.datatype(), shape=self.shape())
        while self.peek() != '}':
            if self.peek() == 'ATTRIBUTE':
                key, value = self.attribute()
                require(key not in node['attributes'], 'Duplicate HDF5 attribute: ' + key)
                node['attributes'][key] = value
            elif kind == 'GROUP' and self.peek() in ('GROUP', 'DATASET'):
                self.node(path)
            elif kind == 'DATASET' and self.peek() == 'DATA':
                require('data' not in node, 'Duplicate HDF5 DATA')
                node['data'] = self.data(node['dtype'], node['shape'], True)
                require(node['data'] == [], 'Binary export DDL unexpectedly contains textual values')
            else:
                raise ValueError('Unsupported HDF5 block: ' + str(self.peek()))
        self.pop('}')

    def parse(self):
        self.pop('HDF5'); source = self.string(); self.pop('{')
        self.node(); self.pop('}')
        require(self.i == len(self.tokens), 'Trailing HDF5 DDL content')
        return dict(source=source, groups=self.groups, datasets=self.datasets)


def _product(values):
    result = 1
    for value in values:
        result *= value
    return result


def _file(root, name):
    require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_.-]+', name) is not None,
            'Unsafe/unsupported raw export filename')
    path = root / name
    require(path.is_file() and not path.is_symlink(), 'Missing/nonregular raw export: ' + name)
    return path


def _attrs(node):
    return {key: value['value'] for key, value in node['attributes'].items()}


def _binary(path, code, count):
    result = array(code)
    require(result.itemsize == {'d': 8, 'i': 4, 'b': 1}[code], 'Unsupported host array itemsize')
    with path.open('rb') as stream:
        result.fromfile(stream, count)
        require(not stream.read(1), 'Trailing binary export bytes')
    if sys.byteorder != 'little' and result.itemsize > 1:
        result.byteswap()
    return result


def load_export(raw):
    """Validate all original export members and typed DDL before semantic decoding."""
    root = Path(raw) / 'hdf5-export'
    index = _json(_file(root, '_collection-members.json'))
    checked = {}
    def original(name):
        path = _file(root, name)
        require(name in index and index[name]['size'] == path.stat().st_size
                and index[name]['sha256'] == sha(path), 'Original export collection hash/size differs: ' + name)
        checked[name] = dict(sha256=index[name]['sha256'], bytes=index[name]['size'])
        return path
    manifest = _json(original('raw-export-manifest.json'))
    request = _json(original('export-request.json'))
    require(manifest['schema'] == 'dram-see-v4-hdf5-raw-export-r1' and manifest['completed'] is True
            and manifest['binary_format'] == 'FILE' and manifest['native_command_count'] == 35
            and manifest['all_native_exit_codes'] == [0] * 35
            and all(type(value) is int for value in manifest['all_native_exit_codes'])
            and manifest['scientific_qualification'] is False
            and manifest['topology_interpretation_performed'] is False, 'Incomplete/unknown raw HDF5 export manifest')
    require(request['schema'] == 'dram-see-v4-hdf5-raw-export-request-r1'
            and request['binary_format'] == 'FILE' and request['datasets'] == EXPECTED_PATHS,
            'Unknown/incomplete raw HDF5 export request')
    require(request['source_sha256'] == manifest['source_sha256']
            and request['original_mesh_sha256'] == manifest['original_mesh_sha256'], 'HDF5 request/manifest source mismatch')
    for name in ('source-before.json', 'source-after.json'):
        item = _json(original(name))
        require(item['source'] == request['source'] and item['sha256'] == manifest['source_sha256']
                and item['original_source'] == request['original_mesh_source']
                and item['original_sha256'] == manifest['original_mesh_sha256'], 'HDF5 source before/after identity differs')
    for name in ('exit-code.txt', 'operation-task-exit-code.txt'):
        require(original(name).read_text().strip() == '0', 'Original HDF5 export operation failed')
    def command(name, args):
        rec = _json(original(name + '-command.json'))
        require(type(rec['exit_code']) is int and rec['exit_code'] == 0
                and rec['command'] == [H5DUMP] + args + [request['source']], 'Native h5dump command/exit differs: ' + name)
        require(original(name + '-stderr.txt').read_bytes() == b'', 'Native h5dump stderr is not empty: ' + name)
        return original(name + '-stdout.txt')
    attrs_path = command('hdf5-attributes', ['-A', '-m', '%.17g'])
    parsed = DDL(attrs_path.read_text(encoding='ascii')).parse()
    require(parsed['source'] == request['source'] and set(parsed['datasets']) == set(EXPECTED_PATHS),
            'Full HDF5 attribute inventory does not cover exactly all 34 native datasets')
    entries = manifest['exports']
    require(len(entries) == 34 and [e['path'] for e in entries] == EXPECTED_PATHS, 'Missing/duplicate/reordered raw HDF5 export')
    files = {}
    for n, entry in enumerate(entries):
        stem = 'dataset-%02d' % n
        require(entry['file'] == stem + '.bin' and entry['command_record'] == stem + '-command.json'
                and entry['native_ddl'] == stem + '-stdout.txt', 'Ambiguous raw HDF5 file binding')
        ddl = DDL(command(stem, ['-d', entry['path'], '-b', 'FILE', '-o', entry['file']]).read_text(encoding='ascii')).parse()
        require(ddl['source'] == request['source'] and not ddl['groups'] and list(ddl['datasets']) == [entry['path']],
                'Binary dataset DDL path differs')
        actual = ddl['datasets'][entry['path']]; full = parsed['datasets'][entry['path']]
        require(actual['dtype'] == full['dtype'] and actual['shape'] == full['shape']
                and not actual['attributes'] and actual.get('data') == [], 'Binary/full HDF5 DDL type/shape differs')
        path = original(entry['file'])
        kind = actual['dtype']['kind']
        size = {'H5T_IEEE_F64LE': 8, 'H5T_STD_I32LE': 4, 'H5T_STD_I8LE': 1}.get(kind)
        if kind == 'H5T_COMPOUND':
            require(actual['dtype']['members'] == [['x', 'H5T_IEEE_F64LE'], ['y', 'H5T_IEEE_F64LE'], ['z', 'H5T_IEEE_F64LE']],
                    'Unsupported coordinate compound layout')
            size = 24
        require(size is not None and len(actual['shape']) == 1 and entry['bytes'] == path.stat().st_size
                == _product(actual['shape']) * size and entry['sha256'] == checked[entry['file']]['sha256'],
                'Raw HDF5 dtype/shape/byte count/hash mismatch')
        files[entry['path']] = path
    return dict(manifest=manifest, request=request, ddl=parsed, files=files, checked=checked,
                export_manifest_sha256=sha(root / 'raw-export-manifest.json'),
                attributes_sha256=sha(attrs_path))


def _check_attrs(node, expected, int64=()):
    require(set(node['attributes']) == set(expected), 'Unknown/missing native HDF5 attributes')
    for name, wanted in expected.items():
        attr = node['attributes'][name]
        require(attr['value'] == wanted, 'Native HDF5 attribute differs: ' + name)
        if isinstance(wanted, str):
            kind, shape = 'H5T_STRING', []
        elif isinstance(wanted, list):
            kind, shape = 'H5T_STD_I32LE', [len(wanted)]
        elif isinstance(wanted, float):
            kind, shape = 'H5T_IEEE_F64LE', []
        else:
            kind, shape = ('H5T_STD_I64LE' if name in int64 else 'H5T_STD_I32LE'), []
        require(attr['dtype']['kind'] == kind and attr['shape'] == shape,
                'Native HDF5 attribute type/shape differs: ' + name)


def _unit(name):
    require(name in ('um', 'cm^-3'), 'Unsupported HDF5 unit')
    return {'unit:exponent': UNIT_UM if name == 'um' else UNIT_CM3,
            'unit:long name': 'micrometer' if name == 'um' else 'cm^-3',
            'unit:name': name, 'unit:significand': 1.}


def _schema(export, plan):
    groups, datasets = export['ddl']['groups'], export['ddl']['datasets']
    expected_groups = {'/', '/collection', GEO, GEO + '/reference coordinate system',
                       GEO + '/state_0', GEO + '/transformation', '/collection/pi',
                       '/collection/tag_group_0', '/collection/tag_group_0/tag_group_0',
                       '/collection/tag_group_0/tag_group_0/tag_0'}
    expected_groups.update(GEO + '/region_%d' % n for n in range(13))
    expected_groups.update(GEO + '/state_0/dataset_%d' % n for n in range(16))
    require(set(groups) == expected_groups and plan['dimension'] == 3, 'Unsupported HDF5 group inventory/dimension')
    _check_attrs(groups['/'], {})
    _check_attrs(groups['/collection'], {'TDR HDF5 version': 16, 'encryption mode': 0, 'number of blobs': 0,
                                       'number of geometric column geometries': 0, 'number of geometries': 1, 'number of plots': 0})
    nvertices = _attrs(groups[GEO])['number of vertices']
    require(type(nvertices) is int and nvertices > 0, 'Invalid native global vertex count')
    geo_expected = {'coordname_0': 'X', 'coordname_1': 'Y', 'coordname_2': 'Z', 'dimension': 3, 'eta': 0.,
                    'name': 'geometry_0', 'number of atoms': 0, 'number of bonds': 0, 'number of bonds multi': 0,
                    'number of molecules': 0, 'number of molecules multi': 0, 'number of regions': 13,
                    'number of states': 1, 'number of vertices': nvertices, 'phi': 0., 'type': 1}
    geo_expected.update(_unit('um'))
    _check_attrs(groups[GEO], geo_expected, ('number of atoms', 'number of bonds', 'number of bonds multi',
                                           'number of molecules', 'number of molecules multi', 'number of vertices'))
    _check_attrs(groups[GEO + '/reference coordinate system'], {'ncsx_in_rcs': 0, 'ncsy_in_rcs': 1, 'ncsz_in_rcs': 2})
    _check_attrs(groups[GEO + '/transformation'], {'type': 0})
    _check_attrs(groups[GEO + '/state_0'], {'name': 'state_0', 'number of datasets': 16,
                 'number of datasets atomistic': 0, 'number of geom datasets': 0, 'number of geom datasets multi_lattice': 0,
                 'number of overlays': 0, 'number of plots': 0, 'number of string streams': 0, 'number of xy plots': 0})
    _check_attrs(groups['/collection/tag_group_0'], {'name': 'collection', 'number of tag groups': 1, 'number of tags': 0})
    _check_attrs(groups['/collection/tag_group_0/tag_group_0'], {'name': 'UserPreferences', 'number of tag groups': 0, 'number of tags': 1})
    _check_attrs(groups['/collection/tag_group_0/tag_group_0/tag_0'],
                 {'key': 'CoordinateConventionSprocess', 'structure type': 0, 'value': 1, 'value type': 0})
    pi_size = datasets['/collection/pi/data']['shape'][0]
    _check_attrs(groups['/collection/pi'], {'size': pi_size})
    require(pi_size > 0, 'Empty original native PI data')
    physical = {r['name']: r['material'] for r in plan['expected_geometry']['regions']}
    contacts = {c['name'] for c in plan['expected_geometry']['contacts']}
    regions = []
    for n in range(13):
        attrs = _attrs(groups[GEO + '/region_%d' % n])
        expected = {'name': attrs['name'], 'number of parts': 1, 'type': 0 if n < 4 else 1 if n < 8 else 2}
        if n < 4:
            expected.update({'is atomistic': 0, 'is multi_lattice': 0, 'material': attrs['material'], 'material type': 0})
            require(attrs['name'] in physical and attrs['material'] == physical[attrs['name']], 'Native HDF5 physical region differs')
        else:
            # Contact bulk0 is retained as opaque native metadata: the actual gate
            # disproves interpreting it as a global bulk index. Faces decide ownership.
            expected['bulk 0'] = attrs['bulk 0']
            if n < 8:
                require(attrs['name'] in contacts and attrs['bulk 0'] == 0, 'Unknown native contact attributes')
            else:
                expected['bulk 1'] = attrs['bulk 1']
                a, b = attrs['bulk 0'], attrs['bulk 1']
                require(type(a) is int and type(b) is int and 0 <= a < 4 and 0 <= b < 4 and a != b,
                        'Unknown native interface bulk references')
                require(set(attrs['name'].split('+')) == {regions[a]['name'], regions[b]['name']},
                        'Native interface name/bulk references differ')
        _check_attrs(groups[GEO + '/region_%d' % n], expected)
        regions.append(dict(index=n, name=attrs['name'], material=attrs.get('material', 'Contact' if n < 8 else 'Interface'),
                            native_attributes=attrs))
    require({r['name']: r['material'] for r in regions[:4]} == physical
            and {r['name'] for r in regions[4:8]} == contacts, 'Native HDF5 region/contact coverage differs')
    fields = []
    for n in range(16):
        path = GEO + '/state_0/dataset_%d' % n
        attrs = _attrs(groups[path]); rid, name = attrs['region'], attrs['name']
        require(type(rid) is int and 0 <= rid < 4 and name in FIELDS, 'Unsupported original per-region field')
        count = attrs['number of values']
        require(type(count) is int and count > 0, 'Invalid field value count')
        expected = {'conversion factor': 1., 'location type': 0, 'name': name, 'number of values': count,
                    'quantity': name, 'region': rid, 'structure type': 0, 'value type': 2}
        expected.update(_unit('um' if name == 'DelVorWeight' else 'cm^-3'))
        _check_attrs(groups[path], expected, ('number of values',))
        require(datasets[path + '/values']['dtype'] == {'kind': 'H5T_IEEE_F64LE'}
                and datasets[path + '/values']['shape'] == [count], 'Original field storage dtype/shape differs')
        fields.append(dict(path=path + '/values', region=regions[rid]['name'], region_index=rid, field=name,
                           count=count, unit=attrs['unit:name'], quantity=name, stored_dtype='H5T_IEEE_F64LE'))
    require(len({(f['region_index'], f['field']) for f in fields}) == 16, 'Duplicate/missing per-region native fields')
    for path, node in datasets.items():
        attrs = node['attributes']
        opaque = [name for name in attrs if re.fullmatch(r'dhm[0-9a-f]+', name)]
        require(len(opaque) == 1 and attrs[opaque[0]]['dtype'] == {'kind': 'H5T_STD_I8LE'}
                and attrs[opaque[0]]['shape'] == [20], 'Missing/unknown vendor opaque HDF5 attribute')
        remaining = {k: v for k, v in attrs.items() if k != opaque[0]}
        if re.fullmatch(re.escape(GEO) + r'/region_\d+/elements_0', path):
            values = {k: v['value'] for k, v in remaining.items()}
            count = values.get('number of elements')
            require(type(count) is int and count > 0, 'Invalid native element count')
            _check_attrs({'attributes': remaining}, {'name': 'part_0', 'number of elements': count})
            require(node['dtype'] == {'kind': 'H5T_STD_I32LE'}, 'Native element dtype differs')
        else:
            require(not remaining, 'Unknown native dataset attributes')
    require(datasets[GEO + '/vertex']['shape'] == [nvertices]
            and datasets[GEO + '/vertex']['dtype'] == {'kind': 'H5T_COMPOUND', 'members':
                 [['x', 'H5T_IEEE_F64LE'], ['y', 'H5T_IEEE_F64LE'], ['z', 'H5T_IEEE_F64LE']]}, 'Native coordinate storage differs')
    for name, count in (('/offset', 3), ('/transformation/A', 9), ('/transformation/b', 3)):
        require(datasets[GEO + name]['shape'] == [count] and datasets[GEO + name]['dtype'] == {'kind': 'H5T_IEEE_F64LE'},
                'Native coordinate transform type/shape differs')
    require(datasets['/collection/pi/data']['dtype'] == {'kind': 'H5T_STD_I8LE'}, 'Native PI type differs')
    return nvertices, regions, fields


def _records(path, width):
    require(path.stat().st_size % (4 * width) == 0, 'Truncated native fixed-width element record')
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(4 * width * 16384), b''):
            for record in struct.iter_unpack('<' + 'i' * width, part):
                yield record


def _face(a, b, c, nvertices):
    a, b, c = sorted((a, b, c))
    # Arbitrary precision Python integers: no imposed vertex count ceiling.
    return (a * nvertices + b) * nvertices + c


def _point(vertices, index):
    n = 3 * index
    return vertices[n], vertices[n + 1], vertices[n + 2]


def _triangle(vertices, ids):
    p, q, r = [_point(vertices, i) for i in ids]
    a, b, c = (q[i] - p[i] for i in range(3))
    d, e, f = (r[i] - p[i] for i in range(3))
    area = .5 * math.sqrt((b*f-c*e)**2 + (c*d-a*f)**2 + (a*e-b*d)**2)
    require(math.isfinite(area) and area > 0., 'Degenerate/nonfinite native triangle')
    return area


def _range(path):
    count, nonzero, lo, hi = 0, 0, math.inf, -math.inf
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 65536), b''):
            require(len(block) % 8 == 0, 'Truncated native F64 values')
            for item in struct.iter_unpack('<d', block):
                value = item[0]
                require(math.isfinite(value), 'Nonfinite original native field')
                count += 1; nonzero += int(value != 0.)
                if value < lo: lo = value
                if value > hi: hi = value
    require(count > 0, 'Empty native field')
    return dict(count=count, min=lo, max=hi, nonzero=nonzero)


def _rows(path):
    with Path(path).open(encoding='utf-8', newline='') as stream:
        table = csv.DictReader(stream)
        require(table.fieldnames and len(set(table.fieldnames)) == len(table.fieldnames), 'Missing/duplicate native CSV headers')
        result = list(table)
    require(result and all(None not in row and None not in row.values() for row in result), 'Malformed native CSV')
    return result


def _mesh_representation(raw, export):
    """Keep original metadata identity separate from an explicitly active v16 file.

    Operation/archive provenance is checked by metadata_continuation. This layer
    checks the exact file identities needed by its native observations; it never
    accepts origin and active hashes as interchangeable alternatives.
    """
    root = Path(raw)
    original = export['manifest']['original_mesh_sha256']
    binding_path = root / 'metadata-source-binding.json'
    context_path = root / 'observation-context.json'
    binding = _json(binding_path) if binding_path.exists() else {}
    context = _json(context_path) if context_path.exists() else {}
    active = (binding.get('schema') == ACTIVE_BINDING_SCHEMA
              or context.get('schema') == ACTIVE_CONTEXT_SCHEMA)
    if not active:
        require(not any(key in item for item in (binding, context) for key in
                ('origin_mesh_sha256', 'active_solver_mesh_sha256', 'mesh_representation')),
                'Active mesh identity requires its explicit binding/context schema')
        mesh = root / 'cell_msh.tdr'
        require(mesh.is_file() and not mesh.is_symlink() and sha(mesh) == original,
                'Original mesh hash differs from native HDF5 source')
        return dict(mode='original_mesh', origin_mesh_sha256=original)
    require(binding.get('schema') == ACTIVE_BINDING_SCHEMA and context.get('schema') == ACTIVE_CONTEXT_SCHEMA
            and binding.get('recipe') == 'native-hdf5-v16-active-mesh-r1'
            and binding.get('mesh_representation') == context.get('mesh_representation') == ACTIVE_REPRESENTATION
            and binding.get('backend') == context.get('geometry_observation_backend') == 'native_hdf5_v16_export',
            'Active v16 requires the exact new binding/context/recipe')
    require(binding.get('origin_mesh_file') == 'scientific-origin-mesh.tdr'
            and binding.get('active_solver_mesh_file') == 'cell_msh.tdr'
            and binding.get('origin_binding_file') == 'metadata-origin-binding.json',
            'Active v16 file roles cannot be aliased')
    prior_path = _file(root, 'metadata-origin-binding.json')
    require(sha(prior_path) == binding.get('origin_binding_sha256'), 'Original metadata binding bytes changed')
    prior = _json(prior_path)
    require(prior.get('schema') == 'dram-see-v4-metadata-hdf5-source-binding-r1'
            and prior.get('recipe') == 'native-hdf5-v16-r1' and prior.get('backend') == 'native_hdf5_v16_export'
            and prior.get('scientific_qualification') is False, 'Active v16 original binding scope differs')
    active_sha = binding.get('active_solver_mesh_sha256')
    origin_size = binding.get('origin_mesh_size_bytes')
    active_size = binding.get('active_solver_mesh_size_bytes')
    require(binding.get('origin_mesh_sha256') == prior.get('mesh_sha256') == original
            and origin_size == prior.get('mesh_size_bytes') and type(origin_size) is int and origin_size > 0,
            'Active v16 original mesh identity differs')
    require(isinstance(active_sha, str) and re.fullmatch(r'[a-f0-9]{64}', active_sha) is not None
            and active_sha != original and active_sha == prior.get('hdf5_sha256') == binding.get('hdf5_sha256')
            == binding.get('mesh_sha256') == export['manifest']['source_sha256'] == export['request']['source_sha256']
            and active_size == prior.get('hdf5_size_bytes') == binding.get('hdf5_size_bytes')
            == binding.get('mesh_size_bytes') == export['request']['source_bytes']
            and type(active_size) is int and active_size > 0,
            'Active v16 converted/export/solver identity differs')
    for name, expected_sha, expected_size in (
            ('scientific-origin-mesh.tdr', original, origin_size), ('cell_msh.tdr', active_sha, active_size)):
        path = _file(root, name)
        require(path.stat().st_size == expected_size and sha(path) == expected_sha,
                'Active v16 file bytes/size differ: ' + name)
    with (root / 'cell_msh.tdr').open('rb') as stream:
        require(stream.read(8) == b'\x89HDF\r\n\x1a\n', 'Active v16 file is not the bound HDF5 representation')
    binding_sha = sha(_file(root, 'metadata-source-binding.json'))
    require(context.get('metadata_source_binding_sha256') == binding_sha
            and context.get('origin_mesh_sha256') == original
            and context.get('active_solver_mesh_sha256') == context.get('mesh_sha256') == active_sha
            and context.get('origin') == 'native_pipeline' and context.get('synthetic') is False,
            'Active v16 current observation context differs')
    current = _rows(_file(root, 'mesh-identity.csv'))
    run_id = context.get('producer_run_id')
    require(isinstance(run_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', run_id) is not None
            and len(current) == 2 and [row['phase'] for row in current] == ['BEFORE', 'AFTER']
            and all(set(row) == {'phase', 'path', 'sha256', 'run_id', 'command_status'} for row in current)
            and all(row['sha256'] == active_sha and row['run_id'] == run_id and row['command_status'] == 'OK' for row in current)
            and current[0]['path'] == current[1]['path'] and current[0]['path'].startswith('/')
            and current[0]['path'].endswith('/' + run_id + '/cell_msh.tdr'),
            'Active v16 SVisual interval differs from current solver identity')
    original_path = prior.get('metadata_original_path')
    require(isinstance(original_path, str) and original_path.startswith('/')
            and binding.get('metadata_original_path') == original_path and current[0]['path'] != original_path,
            'Active v16 cannot rewrite the original metadata path')
    for phase in ('BEFORE', 'AFTER'):
        interval = _json(_file(root, 'current-mesh-' + phase.lower() + '.json'))
        require(interval == dict(schema='dram-see-v4-current-mesh-integrity-r1', phase=phase,
                run_id=run_id, path=current[0]['path'], sha256=active_sha),
                'Active v16 current integrity interval differs')
    return dict(mode=ACTIVE_REPRESENTATION, origin_mesh_sha256=original, origin_mesh_size_bytes=origin_size,
                origin_mesh_file='scientific-origin-mesh.tdr', active_solver_mesh_sha256=active_sha,
                active_solver_mesh_size_bytes=active_size, active_solver_mesh_file='cell_msh.tdr',
                metadata_source_binding_sha256=binding_sha, origin_binding_sha256=sha(prior_path),
                original_metadata_path=original_path, current_mesh_identity=current)


def _metadata(raw, export, grid, datasets, mesh_identity=None):
    original = export['manifest']['original_mesh_sha256']
    mesh_identity = mesh_identity if mesh_identity is not None else _mesh_representation(raw, export)
    identity = _rows(Path(raw) / 'tdr-topology-identity.csv')
    require(len(identity) == 2 and [r['phase'] for r in identity] == ['BEFORE', 'AFTER']
            and all(set(r) == {'phase', 'path', 'sha256'} for r in identity)
            and all(r['sha256'] == original for r in identity) and identity[0]['path'] == identity[1]['path'],
            'Original native TDX before/after identity is incomplete')
    if mesh_identity['mode'] == ACTIVE_REPRESENTATION:
        require(identity[0]['path'] == mesh_identity['original_metadata_path'],
                'Active v16 metadata must retain its original owner path')
    status = _json(Path(raw) / 'tdr-region-status.json')
    require(status['schema'] == 'dram-see-v4-tdr-region-observation-r2' and status['completed'] is True
            and status['original_mesh_sha256'] == original and status['source_modified'] is False
            and status['conversion_performed'] is False and status['scientific_acceptance'] is False,
            'Original native TDX metadata status is incomplete')
    geometry = _rows(Path(raw) / 'tdr-geometry.csv')
    require(len(geometry) == 1, 'Ambiguous original TDX geometry')
    g = geometry[0]
    require(set(g) == {'geometry_index', 'geometry_name', 'geometry_type', 'dimension', 'regions', 'states', 'transform', 'shift'}
            and g['geometry_index'] == '0' and g['geometry_type'] == 'mixed_element' and g['dimension'] == '3'
            and g['regions'] == '13' and g['states'] == '1' and g['geometry_name'] == 'geometry_0'
            and list(map(float, g['transform'].split())) == IDENTITY and list(map(float, g['shift'].split())) == [0.] * 3,
            'Original TDX/HDF5 geometry/transform differ')
    regions = {r['name']: r for r in grid['regions']}
    fields = {(r['region'], r['field']): r for r in datasets}
    seen, seen_regions, boundary_rows = set(), set(), set()
    for row in _rows(Path(raw) / 'tdr-region-datasets.csv'):
        require(set(row) == {'geometry_index', 'region_index', 'region_name', 'material', 'region_type', 'region_dimension',
                             'state_index', 'dataset_index', 'dataset_name', 'num_values', 'quantity', 'unit', 'location', 'command_status'},
                'Unknown original TDX inventory columns')
        name = row['region_name']; require(name in regions, 'Unknown original TDX region')
        r = regions[name]; seen_regions.add(name)
        typ = 'bulk' if r['index'] < 4 else 'contact' if r['index'] < 8 else 'interface'
        material = r['material'] if typ == 'bulk' else '<' + typ + '>'
        require(row['geometry_index'] == '0' and row['state_index'] == '0' and row['region_index'] == str(r['index'])
                and row['material'] == material and row['region_type'] == typ
                and row['region_dimension'] == ('3' if typ == 'bulk' else '2'), 'Original TDX/HDF5 region identity differs')
        if typ != 'bulk':
            require(row['command_status'] == 'NO_DATASETS' and row['dataset_index'] == '-1'
                    and row['dataset_name'] == '' and row['num_values'] == '0' and name not in boundary_rows,
                    'Unexpected/duplicate native boundary fields')
            boundary_rows.add(name)
            continue
        key = (name, row['dataset_name'])
        require(key in fields and key not in seen, 'Missing/duplicate original TDX field')
        f = fields[key]; seen.add(key)
        require(row['command_status'] == 'OK' and row['dataset_index'] == str(FIELDS.index(f['field']))
                and row['location'] == 'vertex' and row['quantity'] == f['quantity']
                and row['unit'] == f['unit'] and int(row['num_values']) == f['count'] == r['vertices'],
                'Original TDX/HDF5 field quantity/unit/count differs')
    require(seen == set(fields) and seen_regions == set(regions), 'Original TDX/HDF5 coverage differs')
    return identity


def read_native(plan, raw, progress=None):
    """Complete original-data audit; does not assert SVisual or 148-check success."""
    export = load_export(raw)
    mesh_identity = _mesh_representation(raw, export)
    nvertices, regions, fields = _schema(export, plan)
    files, desc = export['files'], export['ddl']['datasets']
    vertices = _binary(files[GEO + '/vertex'], 'd', 3 * nvertices)
    require(all(math.isfinite(v) for v in vertices), 'Nonfinite native global coordinate')
    offset = list(_binary(files[GEO + '/offset'], 'd', 3))
    transform = list(_binary(files[GEO + '/transformation/A'], 'd', 9))
    translate = list(_binary(files[GEO + '/transformation/b'], 'd', 3))
    require(offset == [0.] * 3 and transform == IDENTITY and translate == [0.] * 3, 'Unsupported native nonidentity coordinate mapping')
    bounds = [[min(vertices[a::3]), max(vertices[a::3])] for a in range(3)]
    targets, target_vertices = {}, bytearray(nvertices)
    surface_keys, explicit_nodes, triangle_nodes = {}, {}, {}
    for r in regions[4:]:
        path = GEO + '/region_%d/elements_0' % r['index']
        values = _binary(files[path], 'i', desc[path]['shape'][0])
        keys, used, points = [], bytearray(nvertices), bytearray(nvertices)
        areas, pos, records, point_count = [], 0, 0, 0
        while pos < len(values):
            tag = values[pos]; pos += 1; records += 1
            require(tag == 2 or (r['index'] >= 8 and tag == 0), 'Unsupported native surface record tag')
            width = 3 if tag == 2 else 1
            require(pos + width <= len(values), 'Truncated native surface record')
            ids = values[pos:pos + width]; pos += width
            require(all(0 <= v < nvertices for v in ids) and len(set(ids)) == width, 'Invalid native surface vertex references')
            if tag == 0:
                require(not points[ids[0]], 'Duplicate native interface point record')
                points[ids[0]] = 1; point_count += 1
                continue
            for v in ids: used[v] = 1; target_vertices[v] = 1
            key = _face(ids[0], ids[1], ids[2], nvertices)
            keys.append(key); targets.setdefault(key, 0)
            areas.append(_triangle(vertices, ids))
        require(records == _attrs(desc[path])['number of elements'] and len(set(keys)) == len(keys)
                and keys, 'Native surface record count/face uniqueness differs')
        ids = [i for i, value in enumerate(used) if value]
        r.update(element_count=records, triangles=len(keys), point_records=point_count, vertices=len(ids),
                 bounds=[[min(vertices[3*i+a] for i in ids), max(vertices[3*i+a] for i in ids)] for a in range(3)],
                 mesh_measure=math.fsum(areas))
        surface_keys[r['index']] = keys; triangle_nodes[r['index']] = used
        if r['index'] >= 8:
            require(points == used, 'Original interface explicit points differ from triangle vertices')
            explicit_nodes[r['index']] = points
        else:
            require(point_count == 0, 'Unexpected contact point record')
        if progress: progress('surface', r['name'])
    bulk_nodes = []
    for r in regions[:4]:
        path = GEO + '/region_%d/elements_0' % r['index']
        expected = _attrs(desc[path])['number of elements']
        require(desc[path]['shape'] == [5 * expected], 'Native tetra storage/count differs')
        used = bytearray(nvertices); bit = 1 << r['index']
        parts, block, count, negative = [], [], 0, 0
        minimum = math.inf
        for tag, a, b, c, d in _records(files[path], 5):
            require(tag == 5 and min(a, b, c, d) >= 0 and max(a, b, c, d) < nvertices
                    and a != b and a != c and a != d and b != c and b != d and c != d,
                    'Invalid native tetra tag/vertex references')
            used[a] = used[b] = used[c] = used[d] = 1
            p, q, s, t = _point(vertices, a), _point(vertices, b), _point(vertices, c), _point(vertices, d)
            ux, uy, uz = (q[k] - p[k] for k in range(3))
            vx, vy, vz = (s[k] - p[k] for k in range(3))
            wx, wy, wz = (t[k] - p[k] for k in range(3))
            determinant = ux*(vy*wz-vz*wy) - uy*(vx*wz-vz*wx) + uz*(vx*wy-vy*wx)
            require(math.isfinite(determinant) and determinant != 0., 'Degenerate/nonfinite native tetrahedron')
            volume = abs(determinant) / 6.; require(volume > 0., 'Native tetra volume underflow')
            negative += int(determinant < 0.); minimum = min(minimum, volume)
            block.append(volume); count += 1
            if len(block) == 16384:
                parts.append(math.fsum(block)); block = []
            if target_vertices[a] + target_vertices[b] + target_vertices[c] + target_vertices[d] >= 3:
                for x, y, z in ((a, b, c), (a, b, d), (a, c, d), (b, c, d)):
                    key = _face(x, y, z, nvertices)
                    if key in targets:
                        require(not targets[key] & bit, 'Native target face has multiple tetra incidences within one bulk')
                        targets[key] |= bit
        require(count == expected, 'Native tetra record count differs')
        parts.append(math.fsum(block))
        r.update(element_count=count, tetrahedra=count, vertices=sum(used), mesh_measure=math.fsum(parts),
                 minimum_tetra_volume=minimum, negative_orientations=negative)
        bulk_nodes.append(used)
        if progress: progress('bulk', r['name'])
    require(all(any(used[i] for used in bulk_nodes) for i in range(nvertices)), 'Original bulk mesh leaves unused global vertices')
    for r in regions[4:]:
        masks = {targets[k] for k in surface_keys[r['index']]}
        if r['index'] < 8:
            require(len(masks) == 1 and next(iter(masks)) in (1, 2, 4, 8),
                    'Contact has missing, multiple or inconsistent actual bulk face ownership')
            mask = next(iter(masks)); owner = mask.bit_length() - 1
            r['actual_face_bulk_indices'] = [owner]
            r['native_bulk_0_interpretation'] = 'preserved opaque; not assumed global index'
            require(all(not used or bulk_nodes[owner][i] for i, used in enumerate(triangle_nodes[r['index']])),
                    'Contact vertex is absent from actual adjacent bulk')
        else:
            a, b = r['native_attributes']['bulk 0'], r['native_attributes']['bulk 1']
            require(masks == {(1 << a) | (1 << b)}, 'Interface face does not belong exactly once to both declared bulks')
            require(all(bool(value) == bool(bulk_nodes[a][i] and bulk_nodes[b][i])
                        for i, value in enumerate(explicit_nodes[r['index']])),
                    'Interface points differ from complete shared bulk vertex set')
            r['actual_face_bulk_indices'] = [a, b]
    del targets, target_vertices, surface_keys, explicit_nodes, triangle_nodes
    for field in fields:
        summary = _range(files[field['path']])
        require(summary['count'] == field['count'] == regions[field['region_index']]['vertices'],
                'Native region unique vertices and original field count differ')
        field.update(summary)
    del vertices, bulk_nodes
    grid = dict(dimension=3, counts=dict(vertices=nvertices, regions=13,
                elements=sum(r['element_count'] for r in regions), tetrahedra=sum(r['tetrahedra'] for r in regions[:4])),
                bounds=bounds, offset=offset, transform=transform, translate=translate, regions=regions,
                contacts={r['name']: r for r in regions[4:8]})
    identity = _metadata(raw, export, grid, fields, mesh_identity)
    data = {(f['region'], f['field']): f for f in fields}
    physical = {r['name']: r['material'] for r in plan['expected_geometry']['regions']}
    output = {}
    for item in plan['measurements']:
        if item['category'] == 'contacts':
            require(item['entity_kind'] == 'region' and item['unit'] == 'um' and item['field'] in 'XYZ'
                    and item['operation'] in ('min', 'max'), 'Unsupported native HDF5 contact observation')
            value = grid['contacts'][item['entity']]['bounds']['XYZ'.index(item['field'])][('min', 'max').index(item['operation'])]
            source = 'native_hdf5_contact_vertices'
        elif item['id'].startswith('outside_si.'):
            require(item['entity_kind'] == 'region' and item['unit'] == 'cm^-3' and item['entity'] in physical
                    and physical[item['entity']] != 'Silicon' and item['operation'] in ('min', 'max'),
                    'Unsupported native HDF5 non-silicon observation')
            key = (item['entity'], item['field'])
            require(key in data and data[key]['unit'] == item['unit'], 'Original non-silicon native field is absent/wrong-unit')
            value = data[key][item['operation']]; source = 'native_hdf5_region_dataset'
        else:
            continue
        require(item['id'] not in output, 'Duplicate native HDF5 observation id')
        output[item['id']] = dict(value=value, source=source)
    audit = dict(schema=SCHEMA, backend='native_hdf5_v16_export', grid=grid, datasets=fields,
                 original_mesh_sha256=export['manifest']['original_mesh_sha256'],
                 converted_hdf5_sha256=export['manifest']['source_sha256'],
                 export_manifest_sha256=export['export_manifest_sha256'], attributes_sha256=export['attributes_sha256'],
                 original_attributes=export['ddl'], verified_export_members=export['checked'], original_tdx_identity=identity,
                 coordinate_interpretation='Native F64LE x/y/z; original TDX identity transform/zero shift and HDF5 identity A/zero offset/b; no rotation/scale',
                 length_unit='um', length_unit_basis='Native HDF5 unit:name/long name/exponent/significand plus original TDX; SVisual corroboration still required',
                 field_order_interpretation='Per-region ranges only; local values-to-global vertex ordering is not assumed or certified',
                 storage_type_scope='Actual converted v16 storage only; not inferred original Ogawa dtype',
                 opaque_vendor_attribute_scope='Complete original dhm attributes preserved; no undocumented digest algorithm inferred',
                 all_native_data_visited=True, independent_native_crosschecks=[], scientific_qualification=False)
    if mesh_identity['mode'] == ACTIVE_REPRESENTATION:
        audit.update(schema=ACTIVE_SCHEMA, mesh_representation=ACTIVE_REPRESENTATION,
                     origin_mesh_sha256=mesh_identity['origin_mesh_sha256'],
                     active_solver_mesh_sha256=mesh_identity['active_solver_mesh_sha256'],
                     mesh_sha256=mesh_identity['active_solver_mesh_sha256'], mesh_identity_binding=mesh_identity)
    return output, audit


def observe(plan, raw):
    output, audit = read_native(plan, raw)
    visual_rows = _rows(Path(raw) / 'material-measurements.csv')
    visual = {row['id']: row for row in visual_rows}
    require(len(visual) == len(visual_rows), 'Duplicate original SVisual corroboration')
    crosschecks = []
    for axis, limits in zip('XYZ', audit['grid']['bounds']):
        for operation, actual in zip(('min', 'max'), limits):
            name = 'domain.' + axis + '.' + operation
            require(name in visual and visual[name]['command_status'] == 'OK', 'Original SVisual domain corroboration is missing')
            match = re.fullmatch(r'\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(?:\s+\{([^{}]+)\})?\s*',
                                 visual[name]['raw_value'])
            require(match is not None, 'Nonfinite/malformed SVisual corroboration')
            observed = float(match[1]); require(math.isfinite(observed), 'Nonfinite SVisual coordinate')
            if match[2] is not None:
                coordinates = list(map(float, match[2].split()))
                require(len(coordinates) == 3 and all(math.isfinite(c) for c in coordinates), 'Invalid SVisual corroboration coordinate')
            require(abs(actual - observed) <= plan['comparison_policy']['coordinate_absolute_um'],
                    'Native HDF5/SVisual coordinate or unit corroboration differs: ' + name)
            crosschecks.append(dict(id=name, native_hdf5=actual, svisual=observed, absolute_delta=abs(actual - observed)))
    audit['independent_native_crosschecks'] = crosschecks
    audit['length_unit_basis'] += '; independently corroborated against original SVisual domain coordinates'
    return output, audit
