"""Finish the known post-link failure with the original ELF and scoped SDK libs.

This is an engineering operation, never a solver qualification or a new PMI
implementation. The original failed operation and source remain immutable.
"""
import csv
import hashlib
import math
from pathlib import PurePosixPath
import re
import tarfile
import common as c
import supervisor as s

LABEL = 'nc-r1-pmi-link-r2'
ORIGINAL = 'nc-r1-pmi-build'
CONTRACT = 'pmi-recovery-r2.json'


def verify_archive(operation):
    op = c.read(operation / 'operation.json')
    archive_path = operation / 'results.tar'
    c.require(op['archive_sha256'] == c.sha(archive_path), 'Operation archive mismatch')
    output = operation / 'collected'
    c.require(not any(p.is_symlink() for p in output.rglob('*')), 'Collected output contains a symbolic link')
    seen = set()
    with tarfile.open(archive_path) as archive:
        for member in archive.getmembers():
            name = PurePosixPath(member.name)
            c.require(not name.is_absolute() and '..' not in name.parts and not member.issym() and not member.islnk(), 'Unsafe archive member')
            if member.isdir():
                continue
            c.require(member.isfile() and str(name) not in seen, 'Invalid or duplicate archive member')
            seen.add(str(name))
            h = hashlib.sha256()
            with archive.extractfile(member) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(block)
            c.require(h.hexdigest() == c.sha(output / str(name)), 'Collected file differs from archive: ' + str(name))
    c.require(seen == {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}, 'Archive inventory differs')


def inspect_original():
    spec = c.read(c.HERE / CONTRACT)
    for item in spec['evidence']:
        c.check_ref(item)
    paths = {name: c.check_ref(item) for name, item in spec['original'].items()}
    op = c.read(paths['operation'])
    attempt = c.read(paths['attempt'])
    c.require(op['label'] == ORIGINAL and op['state'] == 'FAILED_COLLECTED', 'Not the known failed original operation')
    c.require([op.get(k) for k in ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code')] == [78, 78, 0], 'Original exits differ or are unknown')
    c.require(attempt['label'] == ORIGINAL and attempt['kind'] == 'compile' and attempt['exit_code'] == 1, 'Original adapter outcome differs or is unknown')
    verify_archive(paths['operation'].parent)
    output = paths['operation'].parent / 'collected'
    c.require((output / 'exit-code.txt').read_text().strip() == '78', 'Original raw exit differs')
    c.require(op['input_sha256'] == attempt['input_hashes'], 'Original input ledgers differ')
    for name, digest in op['input_sha256'].items():
        c.require(c.sha(c.OLD_OPS / 'inputs' / ORIGINAL / name) == digest == c.sha(output / name), 'Original input changed: ' + name)
    c.require(c.sha(paths['source']) == c.sha(c.HERE / 'pmi_source.C'), 'Frozen source differs')
    c.require(paths['binary'].read_bytes().startswith(b'\x7fELF'), 'Original binary is not ELF')
    symbols = (output / 'exported-symbols.txt').read_text()
    for symbol in ('new_PMI_Recombination', 'PMI_Recombination_ElectricField'):
        c.require(re.search(r'\bT\s+' + symbol + r'\s*$', symbols, re.M), 'Original symbol missing: ' + symbol)
    old_ldd = (output / 'linked-libraries.txt').read_text()
    c.require('CXXABI_1.3.9' in old_ldd and 'GLIBCXX_3.4.21' in old_ldd and 'not found' in old_ldd, 'Failure is not the reviewed dependency mismatch')
    vectors = c.read(paths['vectors'])
    c.require([v['name'] for v in vectors['vectors']] == ['zero', 'point', 'line', 'zero_chord_delayed', 'tail', 'subdivided'], 'Frozen six probe identities differ')
    return spec, paths, vectors


def package(spec, paths, vectors):
    files = {'pmi_nuclear_source.C': paths['source'].read_bytes(),
             'pmi_nuclear_source.so.linux64': paths['binary'].read_bytes(),
             'native-oracle-vectors.json': paths['vectors'].read_bytes(),
             'recovery-request.json': c.encoded(spec)}
    for row in vectors['vectors']:
        files['probes/' + row['name'] + '.dat'] = c.check_ref(row['native']).read_bytes()
    expected = dict(spec['runtime_hashes'])
    expected['pmi_nuclear_source.C'] = c.sha(paths['source'])
    expected['pmi_nuclear_source.so.linux64'] = c.sha(paths['binary'])
    files['expected-sha256.txt'] = ''.join(digest + '  ' + path + '\n' for path, digest in sorted(expected.items())).encode()
    # The existing GENERIC launcher sets this environment only in its child.
    # Repeat its same-release scope for raw ldd and the standalone executable.
    script = '''set -euo pipefail
SDK=/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64
export LD_LIBRARY_PATH="$SDK/lib:$SDK/tcad_mpi_mpich_ifort/lib:$SDK/lib/gds2tcadLib:$SDK/lib/gds2tcadLib/tbcload1.7:${LD_LIBRARY_PATH-}"
if [ ! -e /lib64/libudev.so.0 ]; then export LD_LIBRARY_PATH="$SDK/lib/patch:$LD_LIBRARY_PATH"; fi
printf '%s\\n' "$LD_LIBRARY_PATH" > scoped-library-path.txt
sha256sum -c expected-sha256.txt > verified-input-runtime-hashes.txt
command -v g++ > compiler-path.txt
g++ --version > compiler-version.txt
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
g++ -O2 -std=c++14 -DNUCLEAR_SOURCE_STANDALONE pmi_nuclear_source.C -o source_probe
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


def prepare(spec, paths, vectors):
    folder = c.OLD_OPS / 'inputs' / LABEL
    files = package(spec, paths, vectors)
    if folder.exists():
        actual = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        c.require(actual == files and not any(p.is_symlink() for p in folder.rglob('*')), 'Existing repair package differs; preserve and inspect')
        return folder
    c.require(not (c.RT / 'attempts' / (LABEL + '.json')).exists() and
              not (c.OLD_OPS / 'operations' / LABEL).exists(), 'Repair attempt exists without its inputs; no resubmission')
    folder.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
    return folder


def validate(operation, spec, paths, vectors):
    import transport
    transport.assert_operation_complete(operation)
    c.require(c.read(operation / 'operation.json')['label'] == LABEL, 'Wrong repair operation identity')
    verify_archive(operation)
    output = operation / 'collected'
    c.require((output / 'exit-code.txt').read_text().strip() == '0', 'Repair raw remote exit differs')
    c.require(c.read(output / 'recovery-request.json') == spec, 'Repair request differs')
    for name, raw in package(spec, paths, vectors).items():
        c.require((output / name).read_bytes() == raw, 'Archived repair input differs: ' + name)
    c.require((output / 'pmi_nuclear_source.so.linux64').read_bytes() == paths['binary'].read_bytes(), 'Original binary must be reused byte for byte')
    for stem in ('linked-libraries', 'probe-linked-libraries'):
        c.require((output / (stem + '.exit-code.txt')).read_text().strip() == '0', 'Dependency check did not succeed')
        text = (output / (stem + '.txt')).read_text() + (output / (stem + '.stderr.txt')).read_text()
        c.require('not found' not in text, 'Unresolved native dependency/version')
        for library in ('libstdc++.so.6', 'libgcc_s.so.1'):
            c.require(library + ' => ' + spec['sdk'] + '/lib/' + library in text, 'Unexpected resolved runtime library')
    with (output / 'native-oracle.csv').open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    c.require([r['name'] for r in rows] == [r['name'] for r in vectors['vectors']], 'Native six-probe identity differs')
    comparisons = []
    for row, vector in zip(rows, vectors['vectors']):
        actual = float(row['actual']); expected = vector['expected_cm_minus3_s_minus1']
        error = abs(actual - expected)
        limit = max(vector['comparison_abs'], vector['comparison_relative'] * abs(expected))
        c.require(math.isfinite(actual) and error <= limit, 'Native arithmetic disagrees: ' + row['name'])
        comparisons.append(dict(name=row['name'], actual=actual, expected=expected, error=error, limit=limit, passed=True))
    return output, comparisons


def required_evidence(operation, paths):
    evidence = [c.ref(p) for p in paths.values()] + [c.ref(c.HERE / CONTRACT), c.ref(c.HERE / 'native_compile_r2.py'),
                c.ref(operation / 'operation.json'), c.ref(operation / 'results.tar')]
    evidence += [c.ref(p) for p in sorted((operation / 'collected').rglob('*')) if p.is_file()]
    return evidence


def ensure_compiled():
    c.check_release('source')
    spec, paths, vectors = inspect_original()
    proof = c.RT / 'pmi/build.json'
    if proof.exists():
        value = c.read(proof)
        c.require(value.get('schema') == 'nuclear-closure-pmi-build-r2' and value.get('compiled') is True and value.get('qualified') is False, 'Not the released compilation-only proof')
        operation = c.OLD_OPS / 'operations' / LABEL
        output, comparisons = validate(operation, spec, paths, vectors)
        c.require(value.get('evidence') == required_evidence(operation, paths), 'Compilation proof evidence inventory differs')
        c.require(value.get('native_arithmetic') == comparisons and value.get('original_failed_exits') == [78,78,0] and value.get('original_binary_reused') is True, 'Compilation proof claims differ from original evidence')
        for item in value['evidence']:
            c.check_ref(item)
        binary = c.check_ref(value['binary'])
        c.require(c.sha(binary) == c.sha(paths['binary']), 'Reused binary identity differs')
        return binary
    inputs = prepare(spec, paths, vectors)
    operation = s.operation(LABEL, inputs, 'compile', timeout=1800)
    output, comparisons = validate(operation, spec, paths, vectors)
    evidence = required_evidence(operation, paths)
    value = dict(schema='nuclear-closure-pmi-build-r2', compiled=True, qualified=False, created_utc=c.utc(),
                 binary=c.ref(output / 'pmi_nuclear_source.so.linux64'), original_failed_exits=[78,78,0],
                 original_binary_reused=True, evidence=evidence, native_arithmetic=comparisons,
                 scope='Original Cmi ELF plus scoped SDK dependency and arithmetic checks; native SDevice ABI/load/sign/carrier qualification remains required')
    c.write(proof, value)
    return output / 'pmi_nuclear_source.so.linux64'
