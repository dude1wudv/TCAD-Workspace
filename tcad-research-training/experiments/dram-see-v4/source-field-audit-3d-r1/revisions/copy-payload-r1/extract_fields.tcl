# Native 3D volume audit. SVisual W-2024.09 UG pp309-310: six-coordinate windows.
# No solver, 2D thickness or AreaFactor multiplier. All missing values remain missing.
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
    if {$plot ne ""} {lappend commands remove_plots $plot [list remove_plots [list $plot]]}
    if {$data ne ""} {lappend commands remove_datasets $data [list remove_datasets [list $data]]}
    foreach {operation expected command} $commands {
        if {[catch {uplevel #0 $command} value]} {
            errorRow $sourceFile {} {} $operation $value
        } elseif {[catch {llength $value} count] || $count != 1 || [lindex $value 0] ne $expected} {
            errorRow $sourceFile {} {} $operation "Deleted object mismatch; expected $expected; actual $value"
        } else {
            csvRow $measurements [list $sourceFile {} $expected {} $operation $value OK]
        }
    }
}
set windows {
    Total {0 0 -0.5 0.85 1.2 0.5}
    Left {0 0 -0.5 0.425 1.2 0.5}
    Right {0.425 0 -0.5 0.85 1.2 0.5}
    Center {0.395 0 -0.5 0.455 1.2 0.5}
    Low {0 0 -0.5 0.85 0.45 0.5}
    Middle {0 0.45 -0.5 0.85 0.75 0.5}
    High {0 0.75 -0.5 0.85 1.2 0.5}
    LowerLeft {0 0 -0.5 0.425 0.6 0.5}
    UpperLeft {0 0.6 -0.5 0.425 1.2 0.5}
    ZNegative {0 0 -0.5 0.85 1.2 0}
    ZPositive {0 0 0 0.85 1.2 0.5}
    CenterTube {0.395 0 -0.03 0.455 1.2 0.03}
}
set stream [open source-case.txt r]
set sourceCase [string trim [read $stream]]
close $stream
if {$sourceCase ni {A0 A1}} {error "Unknown source case"}
set stream [open tdr-files.txt r]
set snapshots [split [string trim [read $stream]] "\n"]
close $stream
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
    foreach required {X Y Z} {
        if {[llength [lsearch -all -exact $fields $required]] != 1} {
            errorRow $sourceFile $required {} native_inventory "Required native field missing or ambiguous"
            set missing 1
        }
    }
    set hasGeneration [expr {[llength [lsearch -all -exact $fields HeavyIonGeneration]] == 1}]
    if {!$hasGeneration && $sourceCase ne "A0"} {
        errorRow $sourceFile HeavyIonGeneration {} native_inventory "A1 generation field missing or ambiguous"
        set missing 1
    }
    if {[llength [lsearch -all -exact $fields HeavyIonGeneration]] > 1} {
        errorRow $sourceFile HeavyIonGeneration {} native_inventory "Generation field is ambiguous"
        set missing 1
    }
    csvRow $metadata [list $sourceFile generation_evidence [expr {$hasGeneration ? "observed_native_field" : "structural_zero_not_measured_zero"}] OK]
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
    set calculated {}
    set formulas {ONE SFA3D_One {0*<X>+1}}
    if {$hasGeneration} {
        lappend calculated G HeavyIonGeneration
        lappend formulas XG SFA3D_XG {<X>*<HeavyIonGeneration>} YG SFA3D_YG {<Y>*<HeavyIonGeneration>} ZG SFA3D_ZG {<Z>*<HeavyIonGeneration>}
    }
    foreach {role name formula} $formulas {
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
    foreach coordinate {X Y Z} {
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
puts $status "schema=source-field-audit-3d-r1-extraction"
puts $status "dimension=3"
puts $status "integration=volume_um3"
puts $status "memory_release=plot_then_dataset_per_frame"
puts $status "cleanup_success=exact_deleted_object_name"
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
