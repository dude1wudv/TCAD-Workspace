# Metadata-only observation for the original operation scheduler: tdx -tcl SCRIPT SOURCE.tdr
# Uses installed W-2024.09 documented commands. Never saves/modifies SOURCE.
if {![info exists cmd_args(rest)] || [llength $cmd_args(rest)] != 1} {
    error "Require exactly one original TDR input path"
}
set source [file normalize [lindex $cmd_args(rest) 0]]
if {![file isfile $source] || [file type $source] eq "link"} {error "Missing or linked original mesh"}
foreach name {tdr-region-datasets.csv tdr-geometry.csv tdr-topology-identity.csv tdr-region-status.json tdr-hash-provider.csv tdr-metadata-failure.csv} {
    if {![catch {file lstat $name ignored}]} {error "Refusing to overwrite $name"}
}
proc csv {stream values} {
    set cells [list]
    foreach value $values {lappend cells "\"[string map [list "\"" "\"\""] $value]\""}
    puts $stream [join $cells ,]
}
proc record_failure {phase detail failure_info failure_code} {
    set stream [open tdr-metadata-failure.csv {WRONLY CREAT EXCL}]
    fconfigure $stream -encoding utf-8 -translation lf
    csv $stream {schema phase error_message error_info error_code}
    csv $stream [list dram-see-v4-tdx-metadata-failure-r1 $phase $detail $failure_info $failure_code]
    close $stream
}
proc digest {path} {return [::dram_tdx_sha256::digest_file $path]}
set phase HASH_PROVIDER_INIT
set result [catch {
    source [file join [file dirname [info script]] tdx_hash_sha256.tcl]
    ::dram_tdx_sha256::initialize
    set provider [open tdr-hash-provider.csv {WRONLY CREAT EXCL}]
    fconfigure $provider -encoding utf-8 -translation lf
    csv $provider {schema source_path source_sha256 source_bytes tcl_patchlevel package_name package_version backend safe_interpreter unsafe_commands_visible package_unknown_empty known_vectors_verified chunk_bytes maximum_supported_file_bytes algorithm_representation_limit_not_resource_quota}
    csv $provider [::dram_tdx_sha256::provider]
    close $provider
    set phase HASH_BEFORE
    set before [digest $source]
} detail]
if {$result} {
    set failure_info $::errorInfo
    set failure_code $::errorCode
    catch {record_failure $phase $detail $failure_info $failure_code}
    error $detail $failure_info $failure_code
}
set datasets [open tdr-region-datasets.csv {WRONLY CREAT EXCL}]
set geometry [open tdr-geometry.csv {WRONLY CREAT EXCL}]
set identity [open tdr-topology-identity.csv {WRONLY CREAT EXCL}]
foreach channel [list $datasets $geometry $identity] {fconfigure $channel -encoding utf-8 -translation lf}
csv $datasets {geometry_index region_index region_name material region_type region_dimension state_index dataset_index dataset_name num_values quantity unit location command_status}
csv $geometry {geometry_index geometry_name geometry_type dimension regions states transform shift}
csv $identity {phase path sha256}
csv $identity [list BEFORE $source $before]
set opened 0
set result [catch {
    set phase TDR_OPEN
    TdrFileOpen $source
    set opened 1
    set phase TDR_METADATA
    set count [TdrFileGetNumGeometry $source]
    if {$count != 1} {error "Expected exactly one original mesh geometry"}
    for {set ig 0} {$ig < $count} {incr ig} {
        set dimension [TdrGeometryGetDimension $source $ig]
        if {$dimension != 2 && $dimension != 3} {error "Original mesh has unexpected dimension"}
        set nr [TdrGeometryGetNumRegion $source $ig]
        set ns [TdrGeometryGetNumState $source $ig]
        if {$nr <= 0 || $ns != 1} {error "Expected nonempty mesh and one original state"}
        csv $geometry [list $ig [TdrGeometryGetName $source $ig] [TdrGeometryGetType $source $ig] $dimension $nr $ns [TdrGeometryGetTransform $source $ig] [TdrGeometryGetShift $source $ig]]
        for {set ir 0} {$ir < $nr} {incr ir} {
            set rn [TdrRegionGetName $source $ig $ir]
            set material [TdrRegionGetMaterial $source $ig $ir]
            set rt [TdrRegionGetType $source $ig $ir]
            set rd [TdrRegionGetDimension $source $ig $ir]
            for {set is 0} {$is < $ns} {incr is} {
                set nd [TdrRegionGetNumDataset $source $ig $ir $is]
                if {$nd == 0} {csv $datasets [list $ig $ir $rn $material $rt $rd $is -1 {} 0 {} {} {} NO_DATASETS]}
                for {set id 0} {$id < $nd} {incr id} {
                    csv $datasets [list $ig $ir $rn $material $rt $rd $is $id [TdrDatasetGetName $source $ig $ir $is $id] [TdrDatasetGetNumValue $source $ig $ir $is $id] [TdrDatasetGetQuantity $source $ig $ir $is $id] [TdrDatasetGetUnit $source $ig $ir $is $id] [TdrDatasetGetLocation $source $ig $ir $is $id] OK]
                }
            }
        }
    }
    set phase TDR_CLOSE
    TdrFileClose $source
    set opened 0
    set phase HASH_AFTER
    set after [digest $source]
    csv $identity [list AFTER $source $after]
    set phase HASH_COMPARE
    if {$before ne $after} {error "Original TDR changed during observation"}
} detail]
if {$result} {
    set failure_info $::errorInfo
    set failure_code $::errorCode
}
if {$opened} {catch {TdrFileClose $source}}
foreach channel [list $datasets $geometry $identity] {
    if {[catch {close $channel} close_detail] && !$result} {
        set result 1
        set phase CSV_CLOSE
        set detail $close_detail
        set failure_info $::errorInfo
        set failure_code $::errorCode
    }
}
if {$result} {
    catch {record_failure $phase $detail $failure_info $failure_code}
    error $detail $failure_info $failure_code
}
set status [open tdr-region-status.json {WRONLY CREAT EXCL}]
fconfigure $status -encoding utf-8 -translation lf
puts $status [format {{"schema":"dram-see-v4-tdr-region-observation-r2","completed":true,"conversion_performed":false,"original_mesh_sha256":"%s","source_modified":false,"scientific_acceptance":false}} $before]
close $status
