"""Compile the authorized bounded trace candidate; never qualify or dispatch it.

The root entry must hold supervisor_storage_r4.ownership() for the complete call.
Imports, package(), and validation do not launch anything.  The only native
launch is the original serialized operation adapter inside ensure_compiled().
The original PMI source, failed operations, and pmi/build.json stay untouched.
"""
import csv
import hashlib
import math
from pathlib import Path
import re

import common as c
import native_compile_r2 as archive_checks
import supervisor_storage_r4 as s


LABEL = 'nc-r1-pmi-trace-build-r10'
RELEASE = 'release-trace-r10.json'
SCOPE = 'single_authorized_qualification_zero_diagnostic'
SOURCE = 'pmi_source_trace_r10.C'
SOURCE_SHA256 = '576948a03e84aecf7c455b3ace5dfe6837043ecb08133859737457731bc5b8eb'
ORIGINAL_SOURCE_SHA256 = '2eab722cb20b1b66258fbbcd7d02b29436c5b4b243369143d6cc83dc7de3290c'
VECTOR_SHA256 = '43e6568f622da601c7a9dfd4d65cf73d8aacefca9c77581309ba35d873a2f40f'
PROBE_NAMES = ['zero', 'point', 'line', 'zero_chord_delayed', 'tail', 'subdivided']
SDK = '/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64'
CMI = '/usr/synopsys/sentaurus/W-2024.09/bin/cmi'
INC = '/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/lib/sdevice/include'
GENERIC = '/usr/synopsys/sentaurus/W-2024.09/bin/GENERIC'


def _manifest(text):
    result = {}
    for line in text.splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (\S+)', line)
        c.require(match is not None, 'Invalid native SHA256 manifest line')
        digest, name = match.groups()
        c.require(name not in result, 'Duplicate native SHA256 manifest member')
        result[name] = digest
    c.require(bool(result), 'Empty native SHA256 manifest')
    return result


def _context():
    spec = c.read(c.HERE / 'pmi-recovery-r2.json')
    c.require(spec.get('schema') == 'nuclear-closure-pmi-recovery-r2' and
              spec.get('sdk') == SDK, 'Scoped SDK evidence changed')
    c.require(c.sha(c.HERE / SOURCE) == SOURCE_SHA256, 'Trace candidate changed')
    c.require(c.sha(c.HERE / 'pmi_source.C') == ORIGINAL_SOURCE_SHA256,
              'Original frozen source changed')
    vectors_path = c.check_ref(spec['original']['vectors'])
    c.require(c.sha(vectors_path) == VECTOR_SHA256, 'Original six-vector file changed')
    vectors = c.read(vectors_path)
    c.require([v['name'] for v in vectors['vectors']] == PROBE_NAMES,
              'Original six-vector order changed')
    for row in vectors['vectors']:
        c.check_ref(row['native'])
        values = row['xyz_um'] + row['window_s']
        c.require(len(row['xyz_um']) == 3 and len(row['window_s']) == 2 and
                  all(isinstance(x, (int, float)) and math.isfinite(x) for x in values),
                  'Invalid frozen arithmetic probe coordinates/window')
        c.require(math.isfinite(row['expected_cm_minus3_s_minus1']) and
                  math.isfinite(row['comparison_abs']) and row['comparison_abs'] >= 0 and
                  math.isfinite(row['comparison_relative']) and row['comparison_relative'] >= 0,
                  'Invalid original arithmetic probe thresholds')
    tool_file = c.OLD_OPS / 'operations/nc-r1-pmi-build/collected/native-tool-header-sha256.txt'
    tools = _manifest(tool_file.read_text(encoding='utf-8'))
    c.require(set(tools) == {CMI, INC + '/PMI.h', INC + '/PMIModels.h'},
              'Unexpected original tool/header inventory')
    runtime = dict(spec['runtime_hashes'])
    c.require(set(runtime) == {GENERIC, SDK + '/lib/libstdc++.so.6', SDK + '/lib/libgcc_s.so.1'},
              'Unexpected scoped runtime inventory')
    c.require(all(re.fullmatch('[0-9a-f]{64}', x) for x in runtime.values()),
              'Invalid scoped runtime digest')
    paths = [c.HERE / name for name in (
        'native_trace_compile_r10.py', SOURCE, 'pmi_source.C', 'common.py',
        'native_compile_r2.py', 'supervisor.py', 'supervisor_storage_r4.py',
        'contract.json', 'pmi-recovery-r2.json')]
    paths += [vectors_path, tool_file] + [c.check_ref(v['native']) for v in vectors['vectors']]
    return dict(spec=spec, vectors=vectors, vectors_path=vectors_path,
                tool_file=tool_file, tools=tools, runtime=runtime, paths=paths)


def check_release():
    """Bind the root's explicit one-diagnostic release, including authorization."""
    path = c.HERE / RELEASE
    release = c.read(path)
    c.require(release.get('schema') == 'nuclear-closure-trace-release-r10' and
              release.get('execution_enabled') is True and release.get('scope') == SCOPE,
              'This one-diagnostic trace build is not released')
    files = release.get('files')
    c.require(isinstance(files, list) and bool(files), 'Missing trace release file inventory')
    names = [item['path'] for item in files]
    c.require(len(names) == len(set(names)), 'Duplicate release evidence identity')
    for item in files:
        c.check_ref(item)
    authorization = release.get('authorization')
    c.require(isinstance(authorization, dict), 'Missing explicit diagnostic authorization')
    c.check_ref(authorization)
    context = _context()
    for p in context['paths']:
        c.require(c.ref(p) in files, 'Trace release does not bind required evidence: ' + c.ref(p)['path'])
    if 'contract_sha256' in release:
        c.require(release['contract_sha256'] == c.sha(c.HERE / 'contract.json'),
                  'Original scientific contract changed')
    return c.ref(path), authorization, context


def package():
    """Return deterministic bytes for a single compilation, without writing."""
    release, authorization, context = check_release()
    vectors = context['vectors']
    request = dict(schema='nuclear-closure-native-trace-build-request-r10', label=LABEL,
                   source=c.ref(c.HERE / SOURCE), original_source=c.ref(c.HERE / 'pmi_source.C'),
                   release=release, authorization=authorization, scope=SCOPE,
                   expected_binary='pmi_nuclear_source.so.linux64', version='W-2024.09',
                   model='pmi_nuclear_source', qualified=False,
                   runtime_evidence=c.ref(c.HERE / 'pmi-recovery-r2.json'),
                   vectors=c.ref(context['vectors_path']))
    files = {'pmi_nuclear_source.C': (c.HERE / SOURCE).read_bytes(),
             'native-oracle-vectors.json': context['vectors_path'].read_bytes(),
             'build-request.json': c.encoded(request)}
    for row in vectors['vectors']:
        files['probes/' + row['name'] + '.dat'] = c.check_ref(row['native']).read_bytes()
    expected = dict(context['runtime'])
    expected.update(context['tools'])
    expected.update({name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()})
    files['expected-sha256.txt'] = ''.join(digest + '  ' + name + '\n'
                                         for name, digest in sorted(expected.items())).encode()
    script = '''set -euo pipefail
SDK=/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64
CMI=/usr/synopsys/sentaurus/W-2024.09/bin/cmi
INC=/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/lib/sdevice/include
export LD_LIBRARY_PATH="$SDK/lib:$SDK/tcad_mpi_mpich_ifort/lib:$SDK/lib/gds2tcadLib:$SDK/lib/gds2tcadLib/tbcload1.7:${LD_LIBRARY_PATH-}"
if [ ! -e /lib64/libudev.so.0 ]; then export LD_LIBRARY_PATH="$SDK/lib/patch:$LD_LIBRARY_PATH"; fi
printf '%s\\n' "$LD_LIBRARY_PATH" > scoped-library-path.txt
sha256sum -c expected-sha256.txt > verified-input-runtime-hashes.txt
command -v g++ > compiler-path.txt
g++ --version > compiler-version.txt
"$CMI" -a > cmi-actual-compiler.txt
"$CMI" --compiler-version > cmi-vendor-compiler.txt
sha256sum "$CMI" "$INC/PMI.h" "$INC/PMIModels.h" > native-tool-header-sha256.txt
set +e
"$CMI" -O -v pmi_nuclear_source.C
code=$?
set -e
printf '%s\\n' "$code" > cmi-exit-code.txt
if [ "$code" -ne 0 ]; then exit "$code"; fi
test -s pmi_nuclear_source.so.linux64
file pmi_nuclear_source.so.linux64 > binary-format.txt
nm -D pmi_nuclear_source.so.linux64 > exported-symbols.txt
grep -E '[[:space:]]T[[:space:]]new_PMI_Recombination$' exported-symbols.txt
grep -E '[[:space:]]T[[:space:]]PMI_Recombination_ElectricField$' exported-symbols.txt
check_dependencies() {
  set +e
  ldd "$1" > "$2.txt" 2> "$2.stderr.txt"
  code=$?
  set -e
  printf '%s\\n' "$code" > "$2.exit-code.txt"
  if [ "$code" -ne 0 ] || grep -q 'not found' "$2.txt" "$2.stderr.txt"; then exit 78; fi
  grep -F "libstdc++.so.6 => $SDK/lib/libstdc++.so.6" "$2.txt"
  grep -F "libgcc_s.so.1 => $SDK/lib/libgcc_s.so.1" "$2.txt"
}
check_dependencies ./pmi_nuclear_source.so.linux64 linked-libraries
readlink -f "$SDK/lib/libstdc++.so.6" "$SDK/lib/libgcc_s.so.1" > resolved-runtime-paths.txt
sha256sum "$SDK/lib/libstdc++.so.6" "$SDK/lib/libgcc_s.so.1" > resolved-runtime-sha256.txt
set +e
g++ -O2 -std=c++14 -DNUCLEAR_SOURCE_STANDALONE pmi_nuclear_source.C -o source_probe
code=$?
set -e
printf '%s\\n' "$code" > probe-compiler-exit-code.txt
if [ "$code" -ne 0 ]; then exit "$code"; fi
check_dependencies ./source_probe probe-linked-libraries
sha256sum pmi_nuclear_source.C pmi_nuclear_source.so.linux64 source_probe > native-build-sha256.txt
printf 'name,actual\\n' > native-oracle.csv
'''
    for row in vectors['vectors']:
        script += "printf '" + row['name'] + ",' >> native-oracle.csv\n"
        script += ' '.join(['./source_probe', 'probes/' + row['name'] + '.dat'] +
                           [format(x, '.17g') for x in row['xyz_um'] + row['window_s']]) + ' >> native-oracle.csv\n'
    files['task.sh'] = script.encode()
    return files


def _input_directory():
    return c.OLD_OPS / 'inputs' / LABEL


def _attempt_path():
    return c.RT / 'attempts' / (LABEL + '.json')


def _operation_directory():
    return c.OLD_OPS / 'operations' / LABEL


def _input_inventory(folder):
    c.require(folder.is_dir() and not folder.is_symlink(), 'Missing or linked trace input directory')
    c.require(not any(p.is_symlink() for p in folder.rglob('*')), 'Linked trace input member')
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob('*') if p.is_file()}


def prepare():
    """Create/reuse exact unsubmitted inputs only; never reconcile by resubmitting."""
    files = package()
    c.require(not _attempt_path().exists() and not _operation_directory().exists(),
              'Trace attempt/operation already exists; inspect its original evidence, do not prepare again')
    folder = _input_directory()
    if folder.exists():
        c.require(_input_inventory(folder) == files, 'Existing unsubmitted trace inputs differ; preserve them')
        return folder
    folder.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
    return folder


def validate(operation):
    """Read all original exits, inputs, archived members, hashes and six oracles."""
    release, authorization, context = check_release()
    operation = Path(operation)
    c.require(operation.resolve() == _operation_directory().resolve(), 'Wrong trace operation directory')
    c.require(_attempt_path().is_file(), 'Trace operation has no original attempt')
    attempt = c.read(_attempt_path())
    op = c.read(operation / 'operation.json')
    c.require(attempt.get('label') == LABEL and attempt.get('kind') == 'compile' and
              attempt.get('state') == 'EXECUTED' and attempt.get('exit_code') == 0 and
              attempt.get('request') is None and attempt.get('corrective') is False,
              'Trace adapter outcome unknown, failed, or mismatched; no resubmission')
    c.require(op.get('label') == LABEL and op.get('state') == 'COLLECTED_PENDING_AUDIT' and
              all(op.get(k) == 0 for k in ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code')),
              'Trace native/SSH/collection outcome unknown, failed, or mismatched')
    c.require(attempt.get('input_directory') == _input_directory().relative_to(c.ROOT).as_posix(),
              'Trace attempt input directory differs')
    expected = package()
    digests = {name: hashlib.sha256(raw).hexdigest() for name, raw in expected.items()}
    c.require(attempt.get('input_hashes') == digests == op.get('input_sha256'),
              'Trace original input ledgers differ')
    c.require(_input_inventory(_input_directory()) == expected, 'Trace original inputs changed')
    archive_checks.verify_archive(operation)
    output = operation / 'collected'
    for name, raw in expected.items():
        c.require((output / name).read_bytes() == raw, 'Archived trace input differs: ' + name)
    for name in ('exit-code.txt', 'cmi-exit-code.txt', 'probe-compiler-exit-code.txt'):
        c.require((output / name).read_text().strip() == '0', 'Native build exit unknown or failed: ' + name)
    for name in ('pmi_nuclear_source.so.linux64', 'source_probe'):
        with (output / name).open('rb') as stream:
            c.require(stream.read(4) == b'\x7fELF', 'Expected native ELF: ' + name)
    symbols = (output / 'exported-symbols.txt').read_text()
    for symbol in ('new_PMI_Recombination', 'PMI_Recombination_ElectricField'):
        c.require(re.search(r'\bT\s+' + symbol + r'\s*$', symbols, re.M), 'Trace native export missing: ' + symbol)
    for stem in ('linked-libraries', 'probe-linked-libraries'):
        c.require((output / (stem + '.exit-code.txt')).read_text().strip() == '0', 'Strict ldd failed or unknown')
        text = (output / (stem + '.txt')).read_text() + (output / (stem + '.stderr.txt')).read_text()
        c.require('not found' not in text, 'Unresolved trace runtime dependency/version')
        for library in ('libstdc++.so.6', 'libgcc_s.so.1'):
            c.require(library + ' => ' + SDK + '/lib/' + library in text, 'Unexpected trace runtime resolution')
    c.require(_manifest((output / 'native-tool-header-sha256.txt').read_text()) == context['tools'],
              'Native trace tool/header hashes changed')
    expected_runtime = {k: v for k, v in context['runtime'].items() if k.startswith(SDK + '/lib/')}
    c.require(_manifest((output / 'resolved-runtime-sha256.txt').read_text()) == expected_runtime,
              'Native trace scoped runtime hashes changed')
    build_hashes = _manifest((output / 'native-build-sha256.txt').read_text())
    c.require(build_hashes == {name: c.sha(output / name) for name in
                              ('pmi_nuclear_source.C', 'pmi_nuclear_source.so.linux64', 'source_probe')},
              'Native trace source/ELF/probe manifest differs')
    with (output / 'native-oracle.csv').open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        c.require(reader.fieldnames == ['name', 'actual'], 'Native oracle CSV header differs')
        rows = list(reader)
    c.require([row['name'] for row in rows] == PROBE_NAMES and
              all(set(row) == {'name', 'actual'} for row in rows), 'Original six-oracle identity differs')
    comparisons = []
    for row, vector in zip(rows, context['vectors']['vectors']):
        actual = float(row['actual']); expected_value = vector['expected_cm_minus3_s_minus1']
        error = abs(actual - expected_value)
        limit = max(vector['comparison_abs'], vector['comparison_relative'] * abs(expected_value))
        c.require(math.isfinite(actual) and error <= limit, 'Trace standalone arithmetic disagrees: ' + row['name'])
        comparisons.append(dict(name=row['name'], actual=actual, expected=expected_value,
                                error=error, limit=limit, passed=True))
    return output, comparisons


def required_evidence(operation):
    release, authorization, context = check_release()
    evidence = [release, authorization] + [c.ref(p) for p in context['paths']]
    evidence += [c.ref(_attempt_path()), c.ref(operation / 'operation.json'), c.ref(operation / 'results.tar')]
    evidence += [c.ref(p) for p in sorted((operation / 'collected').rglob('*')) if p.is_file()]
    return evidence


def ensure_compiled():
    """Caller owns the original lock; this dispatches at most the one new label."""
    release, authorization, context = check_release()
    operation = _operation_directory()
    proof = c.RT / 'pmi-root-cause-r10/native-build.json'
    if not proof.exists() and not _attempt_path().exists() and not operation.exists():
        inputs = prepare()
        operation = s.operation(LABEL, inputs, 'compile', timeout=1800)
    # Any existing attempt/op/proof uses read-only validation; no retry path.
    output, comparisons = validate(operation)
    evidence = required_evidence(operation)
    claims = dict(schema='nuclear-closure-pmi-trace-build-r10', label=LABEL,
                  compiled=True, qualified=False, release=release, authorization=authorization,
                  binary=c.ref(output / 'pmi_nuclear_source.so.linux64'),
                  source=c.ref(c.HERE / SOURCE), native_arithmetic=comparisons, evidence=evidence,
                  original_exits=dict(adapter=0, ssh=0, remote=0, collection=0, cmi=0, standalone_compiler=0),
                  cost_category='compile', source_interface='PMI_Recombination',
                  scope='Trace compilation and scoped link/arithmetic evidence only; native callback, ABI and scientific qualification remain unproven')
    if proof.exists():
        value = c.read(proof)
        c.require('created_utc' in value and {k: v for k, v in value.items() if k != 'created_utc'} == claims,
                  'Existing trace compilation receipt differs from original evidence')
        for item in value['evidence']:
            c.check_ref(item)
    else:
        c.write(proof, dict(claims, created_utc=c.utc()))
    return output / 'pmi_nuclear_source.so.linux64'


if __name__ == '__main__':
    raise SystemExit('Import only from the root-released r10 entry while holding the original owner lock')
