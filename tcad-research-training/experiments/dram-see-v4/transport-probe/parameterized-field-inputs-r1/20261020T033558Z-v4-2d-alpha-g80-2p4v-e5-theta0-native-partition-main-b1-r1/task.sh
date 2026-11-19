set -euo pipefail
set +e
/usr/synopsys/sentaurus/W-2024.09/bin/svisual --threads 1 --max_threads 1 -b -tcl -script extract_fields.tcl > svisual.log 2>&1
v4_field_rc=$?
printf "%s\n" "$v4_field_rc" > svisual-exit-code.txt
set -e
test "$v4_field_rc" -eq 0
grep -Fx 'FIELD_AUDIT_COMPLETED mandatory_errors=0' svisual.log
grep -Fx 'mandatory_command_errors=0' diagnostic-status.txt
grep -Fx 'reference_mode=referenced_original_tdr_not_copied' diagnostic-status.txt
test -s source-reference-checks.csv
test -s field-inventory.csv
test -s field-measurements.csv
echo NATIVE_FIELD_POSTPROCESS_COMPLETED
