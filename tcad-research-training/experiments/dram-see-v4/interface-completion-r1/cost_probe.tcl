# Read-only five-frame load/inventory/release cost probe; no source-field verdict.
# APIs match the natively verified source-field-audit-r2 extractor.
proc csvRow {stream values} {
    set row {}
    foreach value $values {lappend row "\"[string map [list \" \"\"] $value]\""}
    puts $stream [join $row ,]
    flush $stream
}
set inventory [open cost-field-inventory.csv {WRONLY CREAT EXCL}]
set timing [open cost-timing.csv {WRONLY CREAT EXCL}]
csvRow $inventory {source_file dataset native_field}
csvRow $timing {source_file load_ms query_ms release_ms total_ms status}
set files {gfield_0_access_des.tdr gfield_1_access_des.tdr gfield_2_access_des.tdr gfield_3_access_des.tdr gfield_4_access_des.tdr}
set errors 0
set completed 0
foreach sourceFile $files {
    set start [clock milliseconds]
    set data ""
    set plot ""
    set ok 1
    if {![file isfile $sourceFile] || [file type $sourceFile] eq "link"} {
        set ok 0
        puts "COST_PROBE_ERROR $sourceFile missing_or_linked"
    } elseif {[catch {load_file $sourceFile -alldata} data]} {
        set data ""
        set ok 0
        puts "COST_PROBE_ERROR $sourceFile load_file"
    }
    set loaded [clock milliseconds]
    if {$ok} {
        if {[catch {create_plot -dataset $data} plot]} {
            set plot ""
            set ok 0
            puts "COST_PROBE_ERROR $sourceFile create_plot"
        } elseif {[catch {list_fields -plot $plot} fields] || [llength $fields] == 0} {
            set ok 0
            puts "COST_PROBE_ERROR $sourceFile list_fields"
        } else {
            # No field is constructed and HeavyIonGeneration is not required.
            foreach field $fields {csvRow $inventory [list $sourceFile $data $field]}
        }
    }
    set queried [clock milliseconds]
    foreach {operation expected} [list remove_plots $plot remove_datasets $data] {
        if {$expected eq ""} {continue}
        if {[catch {uplevel #0 [list $operation [list $expected]]} removed]
            || [catch {llength $removed} count] || $count != 1 || [lindex $removed 0] ne $expected} {
            set ok 0
            puts "COST_PROBE_ERROR $sourceFile $operation"
        }
    }
    set released [clock milliseconds]
    set loadMs [expr {$loaded-$start}]
    set queryMs [expr {$queried-$loaded}]
    set releaseMs [expr {$released-$queried}]
    set totalMs [expr {$released-$start}]
    if {$loadMs < 0 || $queryMs < 0 || $releaseMs < 0 || $totalMs < 0} {set ok 0}
    if {$ok} {incr completed; set status OK} else {incr errors; set status ERROR}
    csvRow $timing [list $sourceFile $loadMs $queryMs $releaseMs $totalMs $status]
}
close $inventory
close $timing
set status [open cost-status.txt {WRONLY CREAT EXCL}]
puts $status "schema=fine-a0-load-cost-r1"
puts $status "files_requested=5"
puts $status "files_completed=$completed"
puts $status "mandatory_command_errors=$errors"
puts $status "clock_unit=milliseconds"
puts $status "cleanup_success=exact_deleted_object_name"
puts $status "source_field_acceptance=false"
puts $status "roi_integrals_executed=0"
close $status
if {$errors != 0 || $completed != 5} {
    puts "COST_PROBE_FAILED mandatory_errors=$errors"
    exit 2
}
puts "COST_PROBE_COMPLETED mandatory_errors=0"
exit 0
