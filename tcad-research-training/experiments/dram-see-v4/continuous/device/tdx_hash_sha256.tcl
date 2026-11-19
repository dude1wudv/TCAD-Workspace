# Pure in-process SHA-256 for TDX metadata. The installed source is never modified.
# The safe interpreter receives bytes only; no I/O or parent-interpreter aliases.
namespace eval ::dram_tdx_sha256 {
    variable installed_path {/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/lib/tcllib1.16/sha1/sha256.tcl}
    variable expected_sha256 {107ef278e9752467718d0cfaf7dac868f31b7c91ff80fbc4700a07eac939dee1}
    variable expected_bytes 24595
    variable maximum_bytes 536870911
    variable chunk_bytes 65536
    variable child {}
    variable initialized 0
    variable provider_values {}
}

proc ::dram_tdx_sha256::_digest_bytes {data} {
    variable child
    variable chunk_bytes
    set token [interp eval $child {::sha2::SHA256Init}]
    set size [string length $data]
    for {set offset 0} {$offset < $size} {incr offset $chunk_bytes} {
        interp eval $child [list ::sha2::SHA256Update $token [string range $data $offset [expr {$offset+$chunk_bytes-1}]]]
    }
    set binary [interp eval $child [list ::sha2::SHA256Final $token]]
    binary scan $binary H* digest
    return [string tolower $digest]
}

proc ::dram_tdx_sha256::initialize {} {
    variable installed_path
    variable expected_sha256
    variable expected_bytes
    variable maximum_bytes
    variable chunk_bytes
    variable child
    variable initialized
    variable provider_values
    if {$initialized || $child ne {}} {error "SHA-256 provider was already initialized"}
    set stream {}
    set result [catch {
        if {![file isfile $installed_path] || [file type $installed_path] eq "link"} {
            error "Missing or linked fixed installed SHA-256 source"
        }
        if {[file size $installed_path] != $expected_bytes} {error "Installed SHA-256 source byte count differs"}
        set stream [open $installed_path r]
        fconfigure $stream -encoding binary -translation binary
        set library [read $stream]
        close $stream
        set stream {}
        if {[string length $library] != $expected_bytes} {error "Installed SHA-256 source read length differs"}
        set child [interp create -safe]
        interp eval $child {
            package unknown {}
            foreach name {tcllibc sha256c critcl} {
                if {[package provide $name] ne {} || [llength [package versions $name]] != 0} {
                    error "Accelerator package already registered in safe SHA interpreter"
                }
            }
            foreach name {exec load source open socket} {
                if {[llength [info commands $name]] != 0} {error "Unsafe command visible in SHA interpreter"}
            }
        }
        # Tcllib's normal accelerator discovery is retained, but there is no
        # unknown-package resolver and no registered accelerator to execute.
        interp eval $child $library
        if {[interp eval $child {package provide sha256}] ne "1.0.3"} {error "Unexpected installed SHA package version"}
        if {[interp eval $child {set ::sha2::loaded}] ne "tcl"} {error "SHA backend is not pure Tcl"}
        if {[interp eval $child {package unknown}] ne {}} {error "SHA package resolver changed"}
        interp eval $child {
            foreach name {tcllibc sha256c critcl} {
                if {[package provide $name] ne {} || [llength [package versions $name]] != 0} {
                    error "Accelerator registered while loading SHA source"
                }
            }
            foreach name {exec load source open socket} {
                if {[llength [info commands $name]] != 0} {error "Unsafe SHA command appeared during source load"}
            }
        }
        # The package's same-interpreter aliases are now defined. Hashing needs
        # no further interpreter management capability inside the child.
        interp hide $child interp
        if {![interp issafe $child] || [interp eval $child {info commands interp}] ne {}} {
            error "SHA interpreter confinement differs"
        }
        if {[_digest_bytes {}] ne "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"} {
            error "SHA-256 empty known vector failed"
        }
        if {[_digest_bytes abc] ne "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"} {
            error "SHA-256 abc known vector failed"
        }
        set source_sha [_digest_bytes $library]
        if {$source_sha ne $expected_sha256} {error "Installed SHA-256 source digest differs"}
        set provider_values [list dram-see-v4-tdx-sha256-provider-r1 $installed_path $source_sha $expected_bytes \
            [info patchlevel] sha256 [interp eval $child {package provide sha256}] tcl \
            [interp issafe $child] {} 1 {empty abc} $chunk_bytes $maximum_bytes 1]
        set initialized 1
    } detail]
    if {$result} {
        set failure_info $::errorInfo
        set failure_code $::errorCode
        if {$stream ne {}} {catch {close $stream}}
        if {$child ne {}} {catch {interp delete $child}}
        set child {}
        set initialized 0
        return -code error -errorinfo $failure_info -errorcode $failure_code $detail
    }
    return $provider_values
}

proc ::dram_tdx_sha256::provider {} {
    variable initialized
    variable provider_values
    if {!$initialized} {error "SHA-256 provider is not initialized"}
    return $provider_values
}

proc ::dram_tdx_sha256::digest_file {path} {
    variable initialized
    variable child
    variable chunk_bytes
    variable maximum_bytes
    if {!$initialized} {error "SHA-256 provider is not initialized"}
    if {![file isfile $path] || [file type $path] eq "link"} {error "SHA input is missing or linked"}
    # This old installed implementation writes a zero high 32-bit length word.
    # Reject unrepresentable input; this is not a project storage/resource quota.
    if {[file size $path] > $maximum_bytes} {
        error "sha256 1.0.3 cannot represent this file's full bit length; a correct 64-bit-length provider is required"
    }
    set stream {}
    set token {}
    set total 0
    set result [catch {
        set stream [open [file normalize $path] r]
        fconfigure $stream -encoding binary -translation binary
        set token [interp eval $child {::sha2::SHA256Init}]
        while {![eof $stream]} {
            set block [read $stream $chunk_bytes]
            incr total [string length $block]
            if {$total > $maximum_bytes} {error "SHA input grew beyond the provider's bit-length representation"}
            interp eval $child [list ::sha2::SHA256Update $token $block]
        }
        close $stream
        set stream {}
        set binary [interp eval $child [list ::sha2::SHA256Final $token]]
        set token {}
        binary scan $binary H* digest
        set digest [string tolower $digest]
        if {![regexp {^[0-9a-f]{64}$} $digest]} {error "Invalid in-process SHA-256 result"}
    } detail]
    if {$result} {
        set failure_info $::errorInfo
        set failure_code $::errorCode
        if {$stream ne {}} {catch {close $stream}}
        if {$token ne {}} {catch {interp eval $child [list unset $token]}}
        return -code error -errorinfo $failure_info -errorcode $failure_code $detail
    }
    return $digest
}
