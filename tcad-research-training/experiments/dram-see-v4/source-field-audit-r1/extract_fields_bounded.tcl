# Bounded-memory revision: same native measurements; release plot then dataset per frame.
# Original extract_fields.tcl remains frozen. APIs: W-2024.09 UG pp347 and343.
# Native SVisual read-only field extraction. Run in a copied evidence directory.
# svisual --threads 1 --max_threads 1 -b -tcl -script extract_fields.tcl
# UG W-2024.09 pp237/426: existing fields are referenced as <field-name>.
# Actual archived r2 inventory lists exact coordinate fields X and Y and exact G.
# No time is inferred from file number, requested Time, or source waveform.
proc csvCell {value} {return "\"[string map [list \" \"\"] $value]\""}
proc csvRow {stream values} {
    set encoded {}
    foreach value $values {lappend encoded [csvCell $value]}
    puts $stream [join $encoded ,]
    flush $stream
}
set inventory [open field-inventory.csv {WRONLY CREAT EXCL}]
set measurements [open field-measurements.csv {WRONLY CREAT EXCL}]
set metadata [open tdr-state-metadata.csv {WRONLY CREAT EXCL}]
csvRow $inventory {source_file dataset object_type native_name}
csvRow $measurements {source_file field native_field scope operation raw_value command_status}
csvRow $metadata {source_file property raw_value command_status}
set mandatoryErrors 0
set completedFiles 0
proc errorRow {sourceFile field scope operation value} {
    global measurements mandatoryErrors
    csvRow $measurements [list $sourceFile $field {} $scope $operation $value ERROR]
    incr mandatoryErrors
}
proc measure {sourceFile field native scope operation command} {
    global measurements
    if {[catch {uplevel #0 $command} value]} {
        errorRow $sourceFile $field $scope $operation $value
    } else {
        csvRow $measurements [list $sourceFile $field $native $scope $operation $value OK]
    }
}
proc releaseFrame {sourceFile plot data} {
    global measurements
    set commands {}
    if {$plot ne ""} {lappend commands remove_plots [list remove_plots [list $plot]]}
    if {$data ne ""} {lappend commands remove_datasets [list remove_datasets [list $data]]}
    foreach {operation command} $commands {
        if {[catch {uplevel #0 $command} value]} {
            errorRow $sourceFile {} {} $operation $value
        } elseif {![string is integer -strict $value] || $value != 0} {
            errorRow $sourceFile {} {} $operation "Nonzero or malformed cleanup result: $value"
        } else {
            csvRow $measurements [list $sourceFile {} {} {} $operation $value OK]
        }
    }
}
set windows {
    Total {0 0 0.85 1.2}
    Left {0 0 0.425 1.2}
    Right {0.425 0 0.85 1.2}
    Center {0.395 0 0.455 1.2}
    Low {0 0 0.85 0.45}
    Middle {0 0.45 0.85 0.75}
    High {0 0.75 0.85 1.2}
    LowerLeft {0 0 0.425 0.6}
    UpperLeft {0 0.6 0.425 1.2}
}
set snapshots {gfield_0_access_des.tdr gfield_1_access_des.tdr gfield_2_access_des.tdr gfield_3_access_des.tdr gfield_4_access_des.tdr}
# Optional full-frame list contains one simple relative basename per line.
# Its hashes and exact membership are checked by the independent Python auditor.
if {[file exists tdr-files.txt]} {
    set stream [open tdr-files.txt r]
    set snapshots [split [string trim [read $stream]] "\n"]
    close $stream
}
set seen {}
foreach sourceFile $snapshots {
    set sourceFile [string trim $sourceFile]
    if {![regexp {^[A-Za-z0-9_.-]+\.tdr$} $sourceFile] || [dict exists $seen $sourceFile]} {
        errorRow $sourceFile {} {} input_name "Unsafe or duplicate TDR basename"
        continue
    }
    dict set seen $sourceFile 1
    if {![file isfile $sourceFile] || [file type $sourceFile] eq "link"} {
        errorRow $sourceFile {} {} load_file "Missing or linked TDR"
        continue
    }
    if {[catch {load_file $sourceFile -alldata} data]} {
        errorRow $sourceFile {} {} load_file $data
        continue
    }
    if {[catch {create_plot -dataset $data} plot]} {
        errorRow $sourceFile {} {} create_plot $plot
        releaseFrame $sourceFile {} $data
        continue
    }
    csvRow $inventory [list $sourceFile $data plot $plot]
    csvRow $inventory [list $sourceFile $data geometry $data]
    foreach {property command} [list state_names [list list_tdr_states -plot $plot] current_state [list get_plot_prop -plot $plot -tdr_state] current_state_index [list get_plot_prop -plot $plot -tdr_state_index]] {
        if {[catch {uplevel #0 $command} value]} {
            csvRow $metadata [list $sourceFile $property $value ERROR]
        } else {
            csvRow $metadata [list $sourceFile $property $value OK]
        }
    }
    if {[catch {list_fields -plot $plot} fields]} {
        errorRow $sourceFile {} {} list_fields $fields
        releaseFrame $sourceFile $plot $data
        continue
    }
    foreach field $fields {csvRow $inventory [list $sourceFile $data field $field]}
    set missing 0
    foreach required {HeavyIonGeneration X Y} {
        if {[llength [lsearch -all -exact $fields $required]] != 1} {
            errorRow $sourceFile $required {} native_inventory "Required native field missing or ambiguous"
            set missing 1
        }
    }
    if {$missing} {releaseFrame $sourceFile $plot $data; continue}
    if {[catch {list_materials -plot $plot} materials]} {
        errorRow $sourceFile {} {} list_materials $materials
        releaseFrame $sourceFile $plot $data
        continue
    }
    foreach material $materials {csvRow $inventory [list $sourceFile $data material $material]}
    if {[lsearch -exact $materials Silicon] < 0} {
        errorRow $sourceFile {} {} native_inventory "Silicon material absent"
        releaseFrame $sourceFile $plot $data
        continue
    }
    set calculated [list G HeavyIonGeneration]
    foreach {role name formula} {
        ONE SFA_One {0*<HeavyIonGeneration>+1}
        XG SFA_XG {<X>*<HeavyIonGeneration>}
        YG SFA_YG {<Y>*<HeavyIonGeneration>}
    } {
        if {[catch {create_field -plot $plot -geom $data -name $name -function $formula} native]} {
            errorRow $sourceFile $role {} create_field $native
        } else {
            lappend calculated $role $native
            csvRow $inventory [list $sourceFile $data in_memory_field $native]
            csvRow $inventory [list $sourceFile $data formula "$name=$formula"]
        }
    }
    foreach {role native} $calculated {
        set command [list integrate_field -plot $plot -geom $data -field $native -materials {Silicon}]
        measure $sourceFile $role $native SILICON_NO_WINDOW integral $command
        foreach {roi window} $windows {
            measure $sourceFile $role $native $roi integral [concat $command [list -window $window]]
        }
    }
    foreach coordinate {X Y} {
        foreach extreme {-min -max} {
            measure $sourceFile $coordinate $coordinate SILICON_NO_WINDOW $extreme \
                [list calculate_field_value -plot $plot -geom $data -field $coordinate -materials {Silicon} $extreme]
        }
    }
    releaseFrame $sourceFile $plot $data
    incr completedFiles
}
close $inventory
close $measurements
close $metadata
set status [open diagnostic-status.txt {WRONLY CREAT EXCL}]
puts $status "schema=source-field-audit-r1-extraction"
puts $status "memory_release=plot_then_dataset_per_frame"
puts $status "files_requested=[llength $snapshots]"
puts $status "files_completed=$completedFiles"
puts $status "mandatory_command_errors=$mandatoryErrors"
puts $status "No solver executed; native TDR fields only; no physical acceptance claim."
close $status
if {$mandatoryErrors != 0 || $completedFiles != [llength $snapshots]} {
    puts "FIELD_AUDIT_FAILED mandatory_errors=$mandatoryErrors"
    exit 2
}
puts "FIELD_AUDIT_COMPLETED mandatory_errors=0"
exit 0
