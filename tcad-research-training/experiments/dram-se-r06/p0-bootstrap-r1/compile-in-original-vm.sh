#!/bin/bash
# Compile only, dispatched by original Runtime/Geant4 operation, recipe pmi_build.
# This file deliberately contains no SSH, runner, queue, or solver invocation.
set -euo pipefail
set -o noclobber
cd -- "$(dirname -- "$0")"
test -f /etc/centos-release
grep -q 'CentOS Linux release 7' /etc/centos-release
test "$(uname -m)" = x86_64
CMI=/usr/synopsys/sentaurus/W-2024.09/bin/cmi
SDK=/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64
INC=/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/lib/sdevice/include
test -x "$CMI"
test ! -e pmi_r04_nodal.so.linux64
test ! -e build-receipt.json
sha256sum -c build-inputs.sha256 > verified-build-inputs.txt
printf '%s  %s\n' \
  6ceb8b7df42801c970b48c07a89013a4b1278702ec5403e9427fcd8901bc1514 "$INC/PMIModels.h" \
  991ec9fb842f692342fca9c30193e9fc43cc77e26abc09f02ae970ad9c1876c8 "$INC/PMI.h" \
  > vendor-headers.sha256
sha256sum -c vendor-headers.sha256 > verified-vendor-headers.txt
export LD_LIBRARY_PATH="$SDK/lib:$SDK/tcad_mpi_mpich_ifort/lib:$SDK/lib/gds2tcadLib:$SDK/lib/gds2tcadLib/tbcload1.7:${LD_LIBRARY_PATH-}"
if [ ! -e /lib64/libudev.so.0 ]; then
  export LD_LIBRARY_PATH="$SDK/lib/patch:$LD_LIBRARY_PATH"
fi
set +e
"$CMI" -O -v pmi_r04_nodal.C > cmi.stdout.txt 2> cmi.stderr.txt
rc=$?
set -e
printf '%s\n' "$rc" > cmi-exit-code.txt
if [ "$rc" -ne 0 ]; then exit "$rc"; fi
test -s pmi_r04_nodal.so.linux64
nm -D pmi_r04_nodal.so.linux64 > exported-symbols.txt
grep -E '[[:space:]]T[[:space:]]new_PMI_OpticalQuantumYield$' exported-symbols.txt
ldd pmi_r04_nodal.so.linux64 > linked-libraries.txt
if grep -q 'not found' linked-libraries.txt; then exit 78; fi
python3 - <<'PY'
from pathlib import Path
import datetime
import hashlib
import json
import os

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

source = Path("pmi_r04_nodal.C")
elf = Path("pmi_r04_nodal.so.linux64")
data = elf.read_bytes()
assert data[:6] == b"\x7fELF\x02\x01" and data[18:20] == b"\x3e\x00"
assert sha(elf) != "ca05ab0350b27777fbce6a7aedea2b0c811bedb8bdee7581433af18804c98f65"
receipt = {
    "schema": "tcad-r06-pmi-build-receipt-v1",
    "log_version": "r06-o2-global-r1",
    "status": "compiled_only",
    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "command": ["/usr/synopsys/sentaurus/W-2024.09/bin/cmi",
                "-O", "-v", "pmi_r04_nodal.C"],
    "build_environment": "original_centOS7_sentaurus_W-2024.09_vm",
    "centos_release": Path("/etc/centos-release").read_text().strip(),
    "source_sha256": sha(source),
    "elf_sha256": sha(elf),
    "evidence_sha256": {name: sha(name) for name in (
        "pmi_r04_nodal.C", "nodal_source.hpp", "voxel_source.hpp",
        "compile-in-original-vm.sh", "build-inputs.sha256", "build-request.json",
        "cmi-exit-code.txt", "cmi.stdout.txt", "cmi.stderr.txt",
        "exported-symbols.txt", "linked-libraries.txt",
        "vendor-headers.sha256", "verified-vendor-headers.txt",
        "verified-build-inputs.txt")},
    "solver_called": False,
    "accepted_time_steps": None,
}
with open("build-receipt.json", "x") as stream:
    json.dump(receipt, stream, indent=2)
    stream.write("\n")
print(json.dumps({"compiled_only": True, "elf_sha256": receipt["elf_sha256"]}))
PY
