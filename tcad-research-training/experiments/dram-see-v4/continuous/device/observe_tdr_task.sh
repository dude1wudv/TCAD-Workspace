#!/usr/bin/env bash
# Data-only payload for the EXISTING operation scheduler; acquires no new lock.
set -euo pipefail
set -C
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
source_tdr=/home/tcad/research-training/runs/20261017T044000Z-v4-continuous-b1-d2-r6/cell_msh.tdr
expected_sha=53f384abfffe7156302df49ae8b2aa50009a2c65dbac953081beb09784854484
tdx=/usr/synopsys/sentaurus/W-2024.09/bin/tdx
test -f "$source_tdr"
test ! -L "$source_tdr"
for name in source-before.sha256 source-after.sha256 metadata-stdout.log metadata-stderr.log metadata-exit-code.txt converter-stdout.log converter-stderr.log converter-exit-code.txt converter-skipped.txt mesh-observed.grd mesh-observed.dat; do
    if [ -e "$name" ] || [ -L "$name" ]; then
        printf 'Refusing to overwrite %s\n' "$name" >&2
        exit 87
    fi
done
sha256sum -- "$source_tdr" > source-before.sha256
read -r actual_before remainder < source-before.sha256
if [ "$actual_before" != "$expected_sha" ]; then
    printf 'Original r6 TDR hash mismatch\n' >&2
    exit 88
fi
if "$tdx" -tcl observe_tdr_topology.tcl "$source_tdr" > metadata-stdout.log 2> metadata-stderr.log; then
    metadata_rc=0
else
    metadata_rc=$?
fi
printf '%s\n' "$metadata_rc" > metadata-exit-code.txt
task_rc=$metadata_rc
if [ "$metadata_rc" -eq 0 ]; then
    if "$tdx" -dd -M 0 -S 0 "$source_tdr" mesh-observed > converter-stdout.log 2> converter-stderr.log; then
        converter_rc=0
    else
        converter_rc=$?
    fi
    printf '%s\n' "$converter_rc" > converter-exit-code.txt
    task_rc=$converter_rc
    if [ "$converter_rc" -eq 0 ] && { [ ! -s mesh-observed.grd ] || [ ! -s mesh-observed.dat ]; }; then
        printf 'Converter returned zero but native outputs are missing or empty\n' >&2
        task_rc=90
    fi
else
    printf 'Metadata command failed; converter was not invoked\n' > converter-skipped.txt
fi
# Run after both real commands, including a nonzero command exit.
sha256sum -- "$source_tdr" > source-after.sha256
read -r actual_after remainder < source-after.sha256
if [ "$actual_after" != "$expected_sha" ]; then
    printf 'Original r6 TDR changed during observation\n' >&2
    exit 89
fi
exit "$task_rc"
