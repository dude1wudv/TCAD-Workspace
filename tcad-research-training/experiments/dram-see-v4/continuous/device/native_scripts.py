"""Render unexecuted native observers; this module never starts a native tool.

The measurement plan supplies questions and comparison expectations.  Generated
observers write only values returned by the native APIs, never expected values.
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping


def _text(value, label):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ValueError(f"{label} must be a nonempty single-line string")
    return value


def _position(value, dimension):
    if not isinstance(value, (list, tuple)) or len(value) not in ({2, 3} if dimension == 2 else {3}):
        raise ValueError("native_position has the wrong dimension")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError("native_position must contain finite numbers")
    point = list(value) + ([0] if len(value) == 2 else [])
    if dimension == 2 and point[2] != 0:
        raise ValueError("2D native_position must use X,Y with native Z=0")
    return point


def _validate(plan):
    if not isinstance(plan, Mapping) or type(plan.get("dimension")) is not int or plan["dimension"] not in (2, 3):
        raise ValueError("plan dimension must be 2 or 3")
    _text(plan.get("role_id"), "role_id")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(plan.get("geometry_contract_sha256", ""))):
        raise ValueError("geometry_contract_sha256 must be an exact SHA-256")
    if not isinstance(plan.get("expected_geometry"), Mapping):
        raise ValueError("expected_geometry is required as comparison metadata")
    measurements = plan.get("measurements")
    if not isinstance(measurements, list) or not measurements:
        raise ValueError("measurements must be a nonempty list")
    ids = set()
    for item in measurements:
        if not isinstance(item, Mapping):
            raise ValueError("measurement must be an object")
        item_id = _text(item.get("id"), "measurement id")
        if item_id in ids:
            raise ValueError("duplicate measurement id: " + item_id)
        ids.add(item_id)
        if item.get("category") not in {"materials", "contacts", "doping", "units"}:
            raise ValueError("unsupported measurement category")
        if item.get("entity_kind") not in {"region", "material", "all"}:
            raise ValueError("unsupported entity kind")
        if item["entity_kind"] != "all":
            _text(item.get("entity"), "entity")
        _text(item.get("field"), "field")
        if item.get("operation") not in {"integral", "min", "max", "probe"}:
            raise ValueError("unsupported measurement operation")
        if item["operation"] == "probe":
            _position(item.get("native_position"), plan["dimension"])
            if item["entity_kind"] != "all":
                raise ValueError("coordinate probe has no documented region/material filter; use entity_kind=all")
    probes = plan.get("contact_probes")
    if not isinstance(probes, list) or not probes:
        raise ValueError("contact_probes must be a nonempty list")
    probe_ids = set()
    for probe in probes:
        probe_id = _text(probe.get("id"), "contact probe id")
        if probe_id in probe_ids:
            raise ValueError("duplicate contact probe id: " + probe_id)
        probe_ids.add(probe_id)
        _text(probe.get("contact"), "contact")
        _position(probe.get("native_position"), plan["dimension"])
    material_probes = plan.get("material_probes")
    if not isinstance(material_probes, list) or not material_probes:
        raise ValueError("material_probes must be a nonempty list")
    material_ids = set()
    for probe in material_probes:
        probe_id = _text(probe.get("id"), "material probe id")
        if probe_id in material_ids:
            raise ValueError("duplicate material probe id: " + probe_id)
        material_ids.add(probe_id)
        _position(probe.get("native_position"), plan["dimension"])


def _scheme(value):
    return json.dumps(value, ensure_ascii=False)


def _number(value):
    return format(value, ".17g")


def _tcl(value):
    """One Tcl word with substitutions disabled, including for untrusted names."""
    value = str(value)
    for old, new in (("\\", "\\\\"), ('"', '\\"'), ("$", "\\$"), ("[", "\\["), ("]", "\\]"),
                     ("\r", "\\r"), ("\n", "\\n"), ("\t", "\\t")):
        value = value.replace(old, new)
    return '"' + value + '"'


def render_sde(plan) -> str:
    """Return an observer to append to a copied, unchanged geometry.scm."""
    _validate(plan)
    dimension = plan["dimension"]
    get_entities = "sdegeo:get-contact-edgelist" if dimension == 2 else "sdegeo:get-contact-facelist"
    measure = "edge:length" if dimension == 2 else "face:area"
    unit = "um" if dimension == 2 else "um^2"
    probes = []
    for probe in plan["contact_probes"]:
        point = " ".join(_number(v) for v in _position(probe["native_position"], dimension))
        find = f"(find-edge-id (position {point}) (get-body-list))" if dimension == 2 else f"(find-face-id (position {point}))"
        probes.append(f"    (s2-observe-contact-probe {_scheme(probe['id'])} {_scheme(probe['contact'])} {find} s2-probe-port)")
    material_probes = []
    for probe in plan["material_probes"]:
        point = " ".join(_number(v) for v in _position(probe["native_position"], dimension))
        material_probes.append(f"    (s2-observe-material-probe {_scheme(probe['id'])} (find-body-id (position {point})) s2-material-port)")
    header = (
        "; Offline candidate: not executed or released. Append only to a copied geometry.scm.\n"
        "; Read-only CAD observation; it does not build, mesh, solve, or export geometry.\n"
        f"; role_id={plan['role_id']} dimension={dimension}\n"
        f"; geometry_contract_sha256={plan['geometry_contract_sha256']}\n"
        "; Coordinates are native coordinates; 2D physical x,z maps to native X,Y.\n"
        "; CAD contact measure is not a measurement of the final mesh boundary.\n"
    )
    body = r'''
(define (s2-csv-field value port)
  (let ((text (if (string? value) value (number->string value))))
    (display "\"" port)
    (for-each
      (lambda (ch)
        (if (char=? ch #\") (display "\"\"" port) (display ch port)))
      (string->list text))
    (display "\"" port)))

(define (s2-csv-row values port)
  (let loop ((remaining values) (first #t))
    (if (not (null? remaining))
      (begin
        (if (not first) (display "," port))
        (s2-csv-field (car remaining) port)
        (loop (cdr remaining) #f))))
  (newline port))

(define (s2-contact-entities name)
  (__GET_ENTITIES__ name))

(define (s2-observe-contact name port)
  (let ((entities (s2-contact-entities name)))
    (if (null? entities)
      (sde:error (string-append "S2 contact has no attached entities: " name))
      (let* ((bounds (bbox-exact entities))
             (lower (car bounds))
             (upper (cdr bounds))
             (measure (apply + (map __MEASURE__ entities))))
        (s2-csv-row
          (list name (length entities) measure "__UNIT__"
            (position:x lower) (position:y lower) (position:z lower)
            (position:x upper) (position:y upper) (position:z upper)) port)))))

(define (s2-observe-contact-probe id name matches port)
  (let* ((entities (s2-contact-entities name))
         (count (length matches))
         (attached (if (and (= count 1) (member (car matches) entities)) 1 0)))
    (s2-csv-row (list id name count attached) port)))

(define (s2-observe-material-probe id bodies port)
  (let ((count (length bodies)))
    (if (= count 1)
      (let ((region (generic:get (car bodies) "region"))
            (material (generic:get (car bodies) "material")))
        (s2-csv-row (list id count
          (if (string? region) region "")
          (if (string? material) material "")) port))
      (s2-csv-row (list id count "" "") port))))

; The working directory has one owner. The fixed-name guard rejects old files
; and dangling symlinks before any standard Scheme output port is opened.
; The observation remains incomplete if any command or close operation fails.
(if (= (system:command "test ! -e sde-contact-measurements.csv && test ! -L sde-contact-measurements.csv && test ! -e sde-contact-probes.csv && test ! -L sde-contact-probes.csv && test ! -e sde-material-probes.csv && test ! -L sde-material-probes.csv && test ! -e sde-geometry-status.txt && test ! -L sde-geometry-status.txt") 0)
  (let ((s2-contact-port (open-output-file "sde-contact-measurements.csv"))
        (s2-probe-port (open-output-file "sde-contact-probes.csv"))
        (s2-material-port (open-output-file "sde-material-probes.csv")))
    (s2-csv-row (list "contact" "entity_count" "measure" "unit"
      "min_x" "min_y" "min_z" "max_x" "max_y" "max_z") s2-contact-port)
    (s2-csv-row (list "id" "contact" "matched_count" "attached") s2-probe-port)
    (s2-csv-row (list "id" "matched_count" "region" "material") s2-material-port)
    (for-each (lambda (name) (s2-observe-contact name s2-contact-port))
      (sdegeo:contact-sets))
__PROBES__
__MATERIAL_PROBES__
    (close-output-port s2-contact-port)
    (close-output-port s2-probe-port)
    (close-output-port s2-material-port)
    ; Exclusive creation is the shell noclobber operation, after all closes.
    (if (not (= (system:command "( set -C; printf '%s\\n' S2_SDE_GEOMETRY_OBSERVATION_COMPLETED > sde-geometry-status.txt )") 0))
      (sde:error "S2 observation completion marker could not be created exclusively")))
  (sde:error "S2 observation refuses to overwrite an existing output"))
'''
    return (header + body.replace("__GET_ENTITIES__", get_entities).replace("__MEASURE__", measure)
            .replace("__UNIT__", unit).replace("__PROBES__", "\n".join(probes))
            .replace("__MATERIAL_PROBES__", "\n".join(material_probes)))


def render_svisual(plan) -> str:
    """Return Tcl observation source, with no valid input descriptor included."""
    _validate(plan)
    calls = []
    for item in plan["measurements"]:
        position = _position(item["native_position"], plan["dimension"]) if item["operation"] == "probe" else []
        words = [item["id"], item["category"], item["field"], item["entity_kind"],
                 item.get("entity", "") or "", item["operation"]]
        calls.append("s2_measure " + " ".join(_tcl(v) for v in words) + " [list " + " ".join(_number(v) for v in position) + "]")
    header = (
        "# Offline candidate: not executed, released, or supplied with a mesh descriptor.\n"
        "# mesh-input.tcldata is DATA: one Tcl list (path expected_sha producer_run_id).\n"
        "# The input descriptor is read and parsed with list operations, never sourced/evaled.\n"
        f"# geometry_contract_sha256={plan['geometry_contract_sha256']}\n"
        f"set s2_dimension {plan['dimension']}\n"
        f"set s2_role_json {_tcl(json.dumps(plan['role_id'], ensure_ascii=False))}\n"
        f"set s2_need_one {int(any(m['field'] == 'ONE' for m in plan['measurements']))}\n"
    )
    body = r'''
set s2_errors 0
set s2_channels [dict create]
set s2_dataset ""
set s2_plot ""
set s2_mesh ""
set s2_expected_sha ""
set s2_run_id ""
set s2_fields [list]
set s2_regions [list]
set s2_materials [list]
set s2_ready 0
set s2_load_attempted 0
set s2_prior_datasets [list]
set s2_prior_plots [list]
set s2_owned_datasets [list]
set s2_owned_plots [list]

proc s2_csv {channel values} {
    set cells [list]
    foreach value $values {
        lappend cells "\"[string map [list "\"" "\"\""] $value]\""
    }
    puts $channel [join $cells ,]
}

proc s2_fail {stage detail} {
    global s2_errors
    incr s2_errors
    puts stderr "S2 ${stage}: $detail"
}

proc s2_unique {items label} {
    if {[llength $items] != [llength [lsort -unique $items]]} {
        error "$label contains duplicate names"
    }
    return $items
}

proc s2_identity {phase} {
    global s2_mesh s2_expected_sha s2_run_id s2_channels
    set digest ""
    set status OK
    if {[catch {
        if {$s2_mesh eq "" || $s2_run_id eq ""} {error "no valid mesh input descriptor"}
        set output [exec sha256sum -- $s2_mesh]
        if {![regexp {^([0-9a-fA-F]{64})[ *]} $output unused digest]} {
            error "sha256sum did not return a digest"
        }
        set digest [string tolower $digest]
        if {$digest ne $s2_expected_sha} {error "mesh SHA-256 differs from input descriptor"}
    } detail]} {
        set status ERROR
        s2_fail "mesh identity $phase" $detail
    }
    s2_csv [dict get $s2_channels identity] [list $phase $s2_mesh $digest $s2_run_id $status]
    return [expr {$status eq "OK"}]
}

proc s2_inventory {} {
    global s2_dataset s2_channels s2_materials s2_regions s2_fields
    set out [dict get $s2_channels inventory]
    set s2_materials [s2_unique [list_materials -dataset $s2_dataset] materials]
    set s2_regions [s2_unique [list_regions -dataset $s2_dataset] regions]
    set s2_fields [s2_unique [list_fields -dataset $s2_dataset] fields]
    if {![llength $s2_materials] || ![llength $s2_regions] || ![llength $s2_fields]} {
        error "native geometry inventory is empty"
    }
    set assigned [dict create]
    foreach material $s2_materials {
        s2_csv $out [list material $material ""]
        set children [s2_unique [list_regions -dataset $s2_dataset -material $material] "regions of $material"]
        foreach region $children {
            if {[lsearch -exact $s2_regions $region] < 0 || [dict exists $assigned $region]} {
                error "region has no unique native material mapping: $region"
            }
            dict set assigned $region $material
            s2_csv $out [list region $region $material]
        }
    }
    if {[llength [dict keys $assigned]] != [llength $s2_regions]} {
        error "native material mapping does not cover all regions"
    }
    if {[lsearch -exact $s2_materials Contact] < 0} {error "Contact material is absent"}
    set contacts [s2_unique [list_regions -dataset $s2_dataset -material Contact] contacts]
    if {![llength $contacts]} {error "native Contact material has no regions"}
    foreach contact $contacts {s2_csv $out [list contact $contact Contact]}
    foreach field $s2_fields {s2_csv $out [list field $field ""]}
}

proc s2_measure {id category field entity_kind entity operation point} {
    global s2_ready s2_fields s2_regions s2_materials s2_dataset s2_plot s2_channels
    set key [expr {$category eq "units" ? "materials" : $category}]
    set status OK
    set raw ""
    if {[catch {
        if {!$s2_ready} {error "original mesh/inventory was not established"}
        if {[lsearch -exact $s2_fields $field] < 0} {error "required field is absent: $field"}
        if {$entity_kind eq "region" && [lsearch -exact $s2_regions $entity] < 0} {
            error "required region is absent: $entity"
        }
        if {$entity_kind eq "material" && [lsearch -exact $s2_materials $entity] < 0} {
            error "required material is absent: $entity"
        }
        switch -- $operation {
            integral {set command [list integrate_field -dataset $s2_dataset -field $field]}
            min {set command [list calculate_field_value -dataset $s2_dataset -field $field -min]}
            max {set command [list calculate_field_value -dataset $s2_dataset -field $field -max]}
            probe {
                if {$entity_kind ne "all"} {error "coordinate probes cannot establish material/region membership"}
                set command [list probe_field -plot $s2_plot -field $field -coord $point]
            }
            default {error "unsupported measurement operation"}
        }
        if {$operation ne "probe"} {
            if {$entity_kind eq "region"} {lappend command -regions [list $entity]}
            if {$entity_kind eq "material"} {lappend command -materials [list $entity]}
        }
        set raw [{*}$command]
        if {[string trim $raw] eq ""} {error "native command returned an empty result"}
    } detail]} {
        set raw $detail
        set status ERROR
        s2_fail "measurement $id" $detail
    }
    s2_csv [dict get $s2_channels $key] [list $id $raw $status]
}

# No old output is replaced, including a dangling symlink. Tcl EXCL also closes
# the race between this preflight and creation of every output stream.
set s2_output_files [list geometry-inventory.csv mesh-identity.csv material-measurements.csv contact-measurements.csv doping-measurements.csv geometry-status.json]
foreach name $s2_output_files {
    if {![catch {file lstat $name existing_stat}]} {error "S2 refuses to overwrite $name"}
}
if {[catch {
    foreach {key name} {inventory geometry-inventory.csv identity mesh-identity.csv materials material-measurements.csv contacts contact-measurements.csv doping doping-measurements.csv} {
        set channel [open $name {WRONLY CREAT EXCL}]
        dict set s2_channels $key $channel
        fconfigure $channel -encoding utf-8 -translation lf
    }
    s2_csv [dict get $s2_channels inventory] {kind name parent}
    s2_csv [dict get $s2_channels identity] {phase path sha256 run_id command_status}
    foreach key {materials contacts doping} {s2_csv [dict get $s2_channels $key] {id raw_value command_status}}
} detail]} {
    foreach channel [dict values $s2_channels] {catch {close $channel}}
    error "S2 output creation failed: $detail"
}

set s2_descriptor_ok 0
set s2_input_channel ""
if {[catch {
    set s2_input_channel [open mesh-input.tcldata r]
    fconfigure $s2_input_channel -encoding utf-8
    set descriptor [read $s2_input_channel 65537]
    close $s2_input_channel
    set s2_input_channel ""
    if {[string length $descriptor] > 65536 || [llength $descriptor] != 3} {
        error "mesh input must be exactly one three-item Tcl list"
    }
    set supplied_path [lindex $descriptor 0]
    set s2_expected_sha [string tolower [lindex $descriptor 1]]
    set s2_run_id [lindex $descriptor 2]
    if {$supplied_path eq "" || [regexp {[\r\n\t]} $supplied_path]} {error "invalid mesh path"}
    if {![regexp {^[0-9a-f]{64}$} $s2_expected_sha]} {error "invalid expected mesh SHA-256"}
    if {![regexp {^[A-Za-z0-9_.-]+$} $s2_run_id]} {error "invalid producer_run_id"}
    set s2_mesh [file normalize $supplied_path]
    if {![file isfile $s2_mesh] || ![file readable $s2_mesh]} {error "original mesh file is not readable"}
    set s2_descriptor_ok 1
} detail]} {
    if {$s2_input_channel ne ""} {catch {close $s2_input_channel}}
    s2_fail "mesh input" $detail
}

set s2_before_ok [s2_identity BEFORE]
if {$s2_descriptor_ok && $s2_before_ok} {
    if {[catch {
        set s2_prior_datasets [list_datasets]
        set s2_prior_plots [list_plots]
        if {[lsearch -exact $s2_prior_datasets S2GeometryObserverMesh] >= 0 || [lsearch -exact $s2_prior_plots S2GeometryObserverPlot] >= 0} {
            error "observer dataset/plot name is already occupied"
        }
        set s2_load_attempted 1
        set s2_dataset [load_file $s2_mesh -alldata -name S2GeometryObserverMesh]
        if {$s2_dataset ne "S2GeometryObserverMesh"} {error "load_file did not return the unique requested dataset"}
        set s2_plot [create_plot -dataset $s2_dataset -name S2GeometryObserverPlot]
        if {$s2_plot ne "S2GeometryObserverPlot"} {error "create_plot did not return the unique requested plot"}
        s2_inventory
        if {$s2_need_one} {
            if {[lsearch -exact $s2_fields ONE] >= 0} {error "reserved in-memory field ONE already exists"}
            if {[lsearch -exact $s2_fields X] < 0} {error "coordinate field X required to derive ONE is absent"}
            set derived [create_field -dataset $s2_dataset -name ONE -function {0*<X>+1}]
            if {$derived ne "ONE"} {error "constant in-memory field creation failed"}
            lappend s2_fields ONE
        }
        set s2_ready 1
    } detail]} {
        s2_fail "original mesh setup" $detail
    }
}

if {$s2_load_attempted} {
    if {[catch {
        foreach dataset [list_datasets] {
            if {[lsearch -exact $s2_prior_datasets $dataset] < 0} {lappend s2_owned_datasets $dataset}
        }
        foreach plot [list_plots] {
            if {[lsearch -exact $s2_prior_plots $plot] < 0} {lappend s2_owned_plots $plot}
        }
    } detail]} {s2_fail "resource ownership capture" $detail; set s2_ready 0}
}

if {[catch {
__MEASUREMENTS__
} detail]} {s2_fail "measurement output" $detail}

# Dispose only the objects created by this observer, including on a prior error.
foreach plot $s2_owned_plots {
    if {[catch {
        set release_result [remove_plots [list $plot]]
        if {[llength $release_result] != 1 || [lindex $release_result 0] ne $plot} {
            error "remove_plots did not return the exact removed object"
        }
        set remaining [list_plots]
        if {[lsearch -exact $remaining $plot] >= 0} {error "observer plot remains after release"}
    } detail]} {s2_fail "plot release" $detail}
}
foreach dataset $s2_owned_datasets {
    if {[catch {
        set release_result [remove_datasets [list $dataset]]
        if {[llength $release_result] != 1 || [lindex $release_result 0] ne $dataset} {
            error "remove_datasets did not return the exact removed object"
        }
        set remaining [list_datasets]
        if {[lsearch -exact $remaining $dataset] >= 0} {error "observer dataset remains after release"}
    } detail]} {s2_fail "dataset release" $detail}
}
if {[catch {s2_identity AFTER} detail]} {s2_fail "identity output" $detail}
foreach channel [dict values $s2_channels] {
    if {[catch {close $channel} detail]} {s2_fail "output close" $detail}
}

set s2_completed [expr {$s2_errors == 0 ? "true" : "false"}]
set s2_status_channel [open geometry-status.json {WRONLY CREAT EXCL}]
fconfigure $s2_status_channel -encoding utf-8 -translation lf
puts $s2_status_channel [format {{"schema":"s2-geometry-observation-status-r1","completed":%s,"mandatory_errors":%d,"dimension":%d,"reference_mode":"original_mesh","plan_role":%s}} $s2_completed $s2_errors $s2_dimension $s2_role_json]
close $s2_status_channel
if {$s2_errors != 0} {error "S2 geometry observation failed; raw evidence was retained"}
'''
    return header + body.replace("__MEASUREMENTS__", "\n".join(calls))
