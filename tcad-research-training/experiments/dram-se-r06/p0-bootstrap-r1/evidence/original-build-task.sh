#!/bin/bash
set -euo pipefail
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
sha256sum -c input-hashes.sha256 > verified-inputs.txt
SDK=/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64
CMI=/usr/synopsys/sentaurus/W-2024.09/bin/cmi
INC=/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/lib/sdevice/include
export LD_LIBRARY_PATH="$SDK/lib:$SDK/tcad_mpi_mpich_ifort/lib:$SDK/lib/gds2tcadLib:$SDK/lib/gds2tcadLib/tbcload1.7:${LD_LIBRARY_PATH-}"
if [ ! -e /lib64/libudev.so.0 ]; then export LD_LIBRARY_PATH="$SDK/lib/patch:$LD_LIBRARY_PATH"; fi
printf '%s  %s\n' 6ceb8b7df42801c970b48c07a89013a4b1278702ec5403e9427fcd8901bc1514 "$INC/PMIModels.h" 991ec9fb842f692342fca9c30193e9fc43cc77e26abc09f02ae970ad9c1876c8 "$INC/PMI.h" > vendor-headers.sha256
sha256sum -c vendor-headers.sha256 > verified-vendor-headers.txt
# Pure parsing/math tests run on the guest before CMI and expensive SDevice.
/usr/local/bin/g++ -std=c++14 -Wall -Wextra -pedantic test_kernel.cpp -o test_kernel > kernel-compile.stdout.txt 2> kernel-compile.stderr.txt
./test_kernel zero/nodal-source.dat > zero-kernel-check.txt
./test_kernel event/nodal-source.dat > event-kernel-check.txt
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
# One-shot inherited task affinity/thread evidence; no polling or dispatch.
printf 'task_pid=%s\n' "$$" > task-process-evidence.txt
while IFS= read -r line; do
 case "$line" in Name:*|Pid:*|PPid:*|Threads:*|Cpus_allowed:*|Cpus_allowed_list:*) printf '%s\n' "$line";; esac
done < /proc/self/status >> task-process-evidence.txt
for variant in zero event; do
 (
  cd "$variant"
  set +e
  /usr/synopsys/sentaurus/W-2024.09/bin/sdevice --threads 1 --exit-on-failure device.cmd > sdevice.stdout.txt 2> sdevice.stderr.txt
  rc=$?
  set -e
  printf '%s\n' "$rc" > sdevice-exit-code.txt
  if [ "$rc" -ne 0 ]; then exit "$rc"; fi
  test -s activation_des.plt
  test -s activation_des.log
  test -s final_des.tdr
  grep -q 'Sentaurus Device simulation finished' activation_des.log
  grep -q 'Good Bye !' activation_des.log
 )
done
sha256sum pmi_r04_nodal.so.linux64 zero/activation_des.plt zero/activation_des.log event/activation_des.plt event/activation_des.log > output-hashes.sha256
printf '%s\n' R04_NATIVE_NODAL_MATCHED_DIAGNOSTICS_COMPLETED > completion.txt
