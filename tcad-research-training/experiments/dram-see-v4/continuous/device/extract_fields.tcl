# S2 future native 3D volume audit, read-only references to original solver TDRs. SVisual W-2024.09 UG pp309-310: six-coordinate windows.
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
set references [open source-reference-checks.csv {WRONLY CREAT EXCL}]
csvRow $inventory {source_file dataset object_type native_name}
csvRow $measurements {source_file field native_field scope operation raw_value command_status}
csvRow $metadata {source_file property raw_value command_status}
csvRow $references {phase source_file source_path sha256 device inode bytes mtime ctime mode directory_identity command_status}
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
# Frozen data, not evaluated Tcl code. Bound by extractor input hashes.
set stream [open windows.tcldata r]
set windows [string trim [read $stream]]
close $stream
if {[llength $windows] != 32} {error "S2 window inventory differs"}
set stream [open source-case.txt r]
set sourceCase [string trim [read $stream]]
close $stream
if {$sourceCase ni {A0 Aalpha Z H split}} {error "Unknown source case"}
set stream [open tdr-files.txt r]
set snapshots [split [string trim [read $stream]] "\n"]
close $stream
# Source directory and hashes are immutable inputs bound to the local solver archive.
set stream [open source-directory.txt r]
set sourceDirectory [string trim [read $stream]]
close $stream
if {![regexp {^(/[A-Za-z0-9_.-]+)+$} $sourceDirectory] || [file normalize $sourceDirectory] ne $sourceDirectory} {
    error "Unsafe or noncanonical absolute source directory"
}
set stream [open tdr-sha256.txt r]
set hashLines [split [string trim [read $stream]] "\n"]
close $stream
set expectedHashes {}
foreach line $hashLines {
    if {![regexp {^([0-9a-f]{64})  ([A-Za-z0-9_.-]+\.tdr)$} $line -> digest basename] || [dict exists $expectedHashes $basename]} {
        error "Invalid or duplicate source hash row"
    }
    dict set expectedHashes $basename $digest
}
if {[lsort $snapshots] ne [lsort [dict keys $expectedHashes]]} {error "Source file/hash inventory mismatch"}
set initialIdentity {}
proc originalDirectoryIdentity {} {
    global sourceDirectory
    set current /
    set chain {}
    foreach component [file split $sourceDirectory] {
        if {$component ne "/"} {set current [file join $current $component]}
        file lstat $current d
        if {$d(type) ne "directory" || [file type $current] eq "link"} {error "Original directory includes a link/non-directory"}
        lappend chain "$current=$d(dev):$d(ino):$d(mode):$d(type)"
    }
    return [join $chain {|}]
}
proc inspectOriginal {sourceFile} {
    global sourceDirectory expectedHashes
    if {![regexp {^[A-Za-z0-9_.-]+\.tdr$} $sourceFile] || ![dict exists $expectedHashes $sourceFile]} {
        error "Unregistered source basename"
    }
    # lstat every directory both before and after hashing; normalize alone follows links.
    set chain [originalDirectoryIdentity]
    set original [file join $sourceDirectory $sourceFile]
    if {[file normalize $original] ne $original || [file dirname $original] ne $sourceDirectory} {error "Original path changed"}
    file lstat $original before
    if {$before(type) ne "file" || [file type $original] eq "link"} {error "Original TDR is not a regular nonlink file"}
    set raw [exec sha256sum -- $original]
    if {![regexp {^([0-9a-f]{64})  (.+)$} $raw -> digest actualPath] || $actualPath ne $original} {error "Malformed source SHA256 output"}
    file lstat $original after
    foreach key {dev ino size mtime ctime mode type} {
        if {$before($key) ne $after($key)} {error "Original TDR identity changed during hash"}
    }
    if {$chain ne [originalDirectoryIdentity]} {error "Original directory identity changed during hash"}
    if {$digest ne [dict get $expectedHashes $sourceFile]} {error "Original TDR hash differs from local archive"}
    return [list $original $digest $after(dev) $after(ino) $after(size) $after(mtime) $after(ctime) $after(mode) $chain]
}
proc verifyOriginal {sourceFile phase} {
    global references initialIdentity mandatoryErrors
    if {[catch {inspectOriginal $sourceFile} detail]} {
        csvRow $references [list $phase $sourceFile {} {} {} {} {} {} {} {} $detail ERROR]
        incr mandatoryErrors
        return 0
    }
    if {$phase eq "GROUP_BEFORE"} {
        if {[dict exists $initialIdentity $sourceFile]} {error "Duplicate global source identity"}
        dict set initialIdentity $sourceFile $detail
    } elseif {![dict exists $initialIdentity $sourceFile] || [dict get $initialIdentity $sourceFile] ne $detail} {
        csvRow $references [concat [list $phase $sourceFile] $detail [list ERROR]]
        incr mandatoryErrors
        return 0
    }
    csvRow $references [concat [list $phase $sourceFile] $detail [list OK]]
    return 1
}
foreach sourceFile $snapshots {verifyOriginal $sourceFile GROUP_BEFORE}
set seen {}
foreach sourceFile $snapshots {
    set sourceFile [string trim $sourceFile]
    if {![regexp {^[A-Za-z0-9_.-]+\.tdr$} $sourceFile] || [dict exists $seen $sourceFile]} {
        errorRow $sourceFile {} {} input_name "Unsafe or duplicate TDR basename"
        continue
    }
    dict set seen $sourceFile 1
    if {![verifyOriginal $sourceFile FRAME_BEFORE]} {continue}
    set originalPath [file join $sourceDirectory $sourceFile]
    if {[catch {load_file $originalPath -alldata -name [file rootname $sourceFile]} data]} {
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
    if {!$hasGeneration && $sourceCase ni {A0 Z}} {
        errorRow $sourceFile HeavyIonGeneration {} native_inventory "Nonzero configured generation field missing or ambiguous"
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
    set formulas {ONE S2_One {0*<X>+1}}
    if {$hasGeneration} {
        lappend calculated G HeavyIonGeneration
        lappend formulas XG S2_XG {<X>*<HeavyIonGeneration>} YG S2_YG {<Y>*<HeavyIonGeneration>} ZG S2_ZG {<Z>*<HeavyIonGeneration>}
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
    if {![verifyOriginal $sourceFile FRAME_AFTER]} {continue}
    incr completedFiles
}
foreach sourceFile $snapshots {verifyOriginal $sourceFile GROUP_AFTER}
close $references
close $inventory
close $measurements
close $metadata
set status [open diagnostic-status.txt {WRONLY CREAT EXCL}]
puts $status "schema=s2-native-field-extraction-r1"
puts $status "dimension=3"
puts $status "reference_mode=referenced_original_tdr_not_copied"
puts $status "integration=volume_um3"
puts $status "memory_release=plot_then_dataset_per_frame"
puts $status "cleanup_success=exact_deleted_object_name"
puts $status "files_requested=[llength $snapshots]"
puts $status "files_completed=$completedFiles"
puts $status "mandatory_command_errors=$mandatoryErrors"
puts $status "Extractor reads already completed original TDRs; no solver dispatched; no physical acceptance claim."
close $status
if {$mandatoryErrors != 0 || $completedFiles != [llength $snapshots]} {
    puts "FIELD_AUDIT_FAILED mandatory_errors=$mandatoryErrors"
    exit 2
}
puts "FIELD_AUDIT_COMPLETED mandatory_errors=0"
exit 0
