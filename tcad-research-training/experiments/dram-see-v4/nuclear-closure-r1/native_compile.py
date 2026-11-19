"""Native cmi build on the existing installation; no installation or ABI inference."""
import shutil
import csv
import math
from pathlib import Path
import common as c
import supervisor as s

LABEL='nc-r1-pmi-build'


def prepare():
    folder=c.OLD_OPS/'inputs'/LABEL;folder.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(c.HERE/'pmi_source.C',folder/'pmi_nuclear_source.C')
    c.write(folder/'build-request.json',dict(schema='nuclear-closure-native-pmi-build-r1',
        source=c.ref(c.HERE/'pmi_source.C'),expected_binary='pmi_nuclear_source.so.linux64',
        version='W-2024.09',model='pmi_nuclear_source',qualified=False))
    vectors=c.read(c.RT/'source-dev/native-oracle-vectors-r1/vectors.json')
    c.write(folder/'native-oracle-vectors.json',vectors)
    (folder/'probes').mkdir()
    for row in vectors['vectors']:
        c.require(__import__('re').fullmatch('[a-z_]+',row['name']) is not None,'Invalid probe name')
        shutil.copyfile(c.check_ref(row['native']),folder/'probes'/(row['name']+'.dat'))
    script='''set -euo pipefail
CMI=/usr/synopsys/sentaurus/W-2024.09/bin/cmi
INC=/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/lib/sdevice/include
command -v g++ > compiler-path.txt
g++ --version > compiler-version.txt
sha256sum "$CMI" "$INC/PMI.h" "$INC/PMIModels.h" > native-tool-header-sha256.txt
"$CMI" -O -v pmi_nuclear_source.C
test -s pmi_nuclear_source.so.linux64
file pmi_nuclear_source.so.linux64 > binary-format.txt
nm -D pmi_nuclear_source.so.linux64 > exported-symbols.txt
grep -E '[[:space:]]T[[:space:]]new_PMI_Recombination$' exported-symbols.txt
grep -E '[[:space:]]T[[:space:]]PMI_Recombination_ElectricField$' exported-symbols.txt
ldd pmi_nuclear_source.so.linux64 > linked-libraries.txt
if grep -q 'not found' linked-libraries.txt; then exit 78; fi
g++ -O2 -std=c++14 -DNUCLEAR_SOURCE_STANDALONE pmi_nuclear_source.C -o source_probe
sha256sum pmi_nuclear_source.C pmi_nuclear_source.so.linux64 source_probe > native-build-sha256.txt
'''
    script+="printf 'name,actual\\n' > native-oracle.csv\n"
    for row in vectors['vectors']:
        script+="printf '"+row['name']+",' >> native-oracle.csv\n"
        script+=' '.join(['./source_probe','probes/'+row['name']+'.dat']+[format(x,'.17g') for x in row['xyz_um']+row['window_s']])+' >> native-oracle.csv\n'
    (folder/'task.sh').write_text(script,encoding='utf-8',newline='\n')
    return folder


def ensure_compiled():
    proof=c.RT/'pmi/build.json'
    if proof.exists():
        value=c.read(proof)
        for item in value['evidence']:c.check_ref(item)
        return c.check_ref(value['binary'])
    c.check_release('source')
    path=c.RT/'attempts'/(LABEL+'.json')
    inputs=c.OLD_OPS/'inputs'/LABEL if path.exists() else prepare()
    operation=s.operation(LABEL,inputs,'compile',timeout=1800)
    import transport
    transport.assert_operation_complete(operation)
    output=operation/'collected'
    c.require(c.sha(output/'pmi_nuclear_source.C')==c.sha(c.HERE/'pmi_source.C'),'Compiled PMI source differs')
    binary=output/'pmi_nuclear_source.so.linux64'
    c.require(binary.read_bytes().startswith(b'\x7fELF'),'Expected native ELF model library')
    with (output/'native-oracle.csv').open(newline='',encoding='utf-8') as stream:rows=list(csv.DictReader(stream))
    vectors=c.read(output/'native-oracle-vectors.json')['vectors'];comparisons=[]
    c.require([r['name'] for r in rows]==[r['name'] for r in vectors],'Native probe vector identity differs')
    for row,v in zip(rows,vectors):
        actual=float(row['actual']);expected=v['expected_cm_minus3_s_minus1']
        error=abs(actual-expected);limit=max(v['comparison_abs'],v['comparison_relative']*abs(expected))
        c.require(math.isfinite(actual) and error<=limit,'Native C++ arithmetic disagrees with independent Python oracle: '+row['name'])
        comparisons.append(dict(name=row['name'],actual=actual,expected=expected,error=error,limit=limit,passed=True))
    value=dict(schema='nuclear-closure-pmi-build-r1',compiled=True,qualified=False,created_utc=c.utc(),
        binary=c.ref(binary),evidence=[c.ref(operation/'operation.json'),c.ref(operation/'results.tar'),
            c.ref(c.HERE/'pmi_source.C'),c.ref(output/'native-tool-header-sha256.txt'),
            c.ref(output/'exported-symbols.txt'),c.ref(output/'linked-libraries.txt'),c.ref(output/'native-oracle.csv')],native_arithmetic=comparisons,
        scope='Compilation and exported symbol evidence only; two native solver qualification cases still required')
    c.write(proof,value)
    return binary
