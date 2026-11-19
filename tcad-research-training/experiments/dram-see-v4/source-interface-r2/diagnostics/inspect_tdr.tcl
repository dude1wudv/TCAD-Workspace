# Read-only diagnostic of COMPLETED r2 TDRs. Never invoke sdevice/sde.
# Root copies the five archived TDRs into a NEW diagnostic directory and verifies
# their SHA256 before and after. Run only from that directory, never the old run:
# svisual --threads 1 --max_threads 1 -b -tcl -script inspect_tdr.tcl
# APIs: installed W-2024.09 SVisual UG pp24-25,227,309-310,319,322.

# No original run path or environment data are needed by this script.
set inputDir .
set outputDir .
proc csvCell {value} {
    return "\"[string map [list \" \"\"] $value]\""
}
proc csvRow {stream values} {
    set encoded {}
    foreach value $values {lappend encoded [csvCell $value]}
    puts $stream [join $encoded ,]
}

set inventory [open [file join $outputDir field-inventory.csv] {WRONLY CREAT EXCL}]
set measurements [open [file join $outputDir field-measurements.csv] {WRONLY CREAT EXCL}]
csvRow $inventory {source_file declared_time_s dataset object_type native_name}
csvRow $measurements {source_file declared_time_s field scope operation raw_value command_status}
set mandatoryErrors 0

proc measure {sourceFile time field scope operation command mandatory} {
    global measurements mandatoryErrors
    set code [catch {uplevel #0 $command} value options]
    if {$code != 0} {
        csvRow $measurements [list $sourceFile $time $field $scope $operation $value ERROR]
        if {$mandatory} {incr mandatoryErrors}
    } else {
        csvRow $measurements [list $sourceFile $time $field $scope $operation $value OK]
    }
    flush $measurements
}

# Same frozen rectangles as source_contract.json. No source or threshold changes.
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
set snapshots {
    gfield_0_access_des.tdr 9.95e-10
    gfield_1_access_des.tdr 1e-9
    gfield_2_access_des.tdr 1.005e-9
    gfield_3_access_des.tdr 1.01e-9
    gfield_4_access_des.tdr 1.015e-9
}
foreach {sourceFile time} $snapshots {
    set sourcePath [file join $inputDir $sourceFile]
    if {![file isfile $sourcePath] || [file type $sourcePath] eq "link"} {
        csvRow $measurements [list $sourceFile $time {} {} load_file "Missing or linked TDR" ERROR]
        incr mandatoryErrors
        continue
    }
    if {[catch {load_file $sourcePath} data]} {
        csvRow $measurements [list $sourceFile $time {} {} load_file $data ERROR]
        incr mandatoryErrors
        continue
    }
    if {[catch {list_fields -dataset $data} fields]} {
        csvRow $measurements [list $sourceFile $time {} {} list_fields $fields ERROR]
        incr mandatoryErrors
        continue
    }
    foreach field $fields {
        csvRow $inventory [list $sourceFile $time $data field $field]
    }
    if {[catch {list_materials -dataset $data} materials]} {
        csvRow $measurements [list $sourceFile $time {} {} list_materials $materials ERROR]
        incr mandatoryErrors
    } else {
        foreach material $materials {
            csvRow $inventory [list $sourceFile $time $data material $material]
        }
    }
    flush $inventory
    # Create a constant only in the loaded in-memory dataset; never save it to TDR.
    # Native integration of 1 tests area units/domain selection independently of HI.
    if {[catch {create_field -dataset $data -name R2_UnitField -function "1"} constantField]} {
        csvRow $measurements [list $sourceFile $time R2_UnitField {} create_field $constantField ERROR]
        incr mandatoryErrors
    } else {
        csvRow $inventory [list $sourceFile $time $data diagnostic_in_memory_field $constantField]
        set unitCommand [list integrate_field -dataset $data -field $constantField -materials {Silicon}]
        measure $sourceFile $time $constantField SILICON_NO_WINDOW integral_of_one $unitCommand 1
        foreach {roi window} $windows {
            measure $sourceFile $time $constantField $roi integral_of_one \
                [concat $unitCommand [list -window $window]] 1
        }
    }
    set sourceFields {}
    foreach field $fields {
        if {[string match "*HeavyIonGeneration*" $field]} {lappend sourceFields $field}
    }
    if {[llength $sourceFields] == 0} {
        csvRow $measurements [list $sourceFile $time {} {} source_field_inventory "No actual HeavyIonGeneration field" ERROR]
        incr mandatoryErrors
        continue
    }
    foreach field $sourceFields {
        set common [list integrate_field -dataset $data -field $field]
        measure $sourceFile $time $field ALL_REGIONS integral $common 1
        measure $sourceFile $time $field ALL_REGIONS domain_area [concat $common {-returndomain}] 1
        set silicon [concat $common {-materials {Silicon}}]
        measure $sourceFile $time $field SILICON_NO_WINDOW integral $silicon 1
        measure $sourceFile $time $field SILICON_NO_WINDOW domain_area [concat $silicon {-returndomain}] 1
        measure $sourceFile $time $field SILICON_NO_WINDOW maximum_and_location \
            [list calculate_field_value -dataset $data -field $field -materials {Silicon} -max] 0
        foreach {roi window} $windows {
            set command [concat $silicon [list -window $window]]
            measure $sourceFile $time $field $roi integral $command 1
            measure $sourceFile $time $field $roi domain_area [concat $command {-returndomain}] 1
        }
        # Diagnostic controls, not replacement ROIs and not new acceptance rules.
        measure $sourceFile $time $field EXPANDED_2D integral \
            [concat $silicon [list -window {-1 -1 2 2}]] 0
        measure $sourceFile $time $field EXPANDED_2D domain_area \
            [concat $silicon [list -window {-1 -1 2 2}] {-returndomain}] 0
        # Optional explicit-z domain tests whether this API rejects or accepts a 3D
        # window for a 2D dataset; an error is evidence and is never mapped to zero.
        measure $sourceFile $time $field EXPLICIT_Z_DIAGNOSTIC integral \
            [concat $silicon [list -window {0 0 -1 0.85 1.2 1}]] 0
    }
}
close $inventory
close $measurements
set status [open [file join $outputDir diagnostic-status.txt] {WRONLY CREAT EXCL}]
puts $status "DIAGNOSTIC_COLLECTION_COMPLETED"
puts $status "mandatory_command_errors=$mandatoryErrors"
puts $status "No solver executed. No acceptance threshold changed. These are native TDR snapshot measurements, not a time-integrated source audit."
close $status
if {$mandatoryErrors != 0} {
    puts "R2_NATIVE_TDR_DIAGNOSTIC_FAILED mandatory_errors=$mandatoryErrors"
    exit 2
}
puts "R2_NATIVE_TDR_DIAGNOSTIC_COMPLETED mandatory_errors=0"
exit 0
