"""Offline S2 BCAT geometry, contacts, doping, and SDE review-deck generator.

All lengths passed to material_at/donor_concentration are physical micrometres.
This module does not import the runner, call a native tool, or qualify a mesh.
See cad-assumptions.md before changing an implementation decision.
"""
from __future__ import annotations

import json
import math
from copy import deepcopy


def _number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Nonfinite geometry/deck number")
    return format(value, ".15g")


def _position(values):
    return "(position " + " ".join(_number(v) for v in values) + ")"


def _parameters(model):
    g, d, a, n = (model[k] for k in ("geometry", "doping", "alpha", "numerics"))
    nm = lambda value: float(value) / 1000.0
    domain = {axis: [nm(v) for v in g["silicon_domain_nm"][axis]] for axis in "xyz"}
    radius = nm(g["outer_rounding_radius_nm"])
    metal_radius = nm(g["metal_rounding_radius_nm"])
    oxide = nm(g["gate_oxide_side_and_bottom_nm"])
    active_half = nm(g["active_width_nm"]) / 2
    outer_y_half = active_half + nm(g["sti_each_side_width_nm"])
    metal_y_half = outer_y_half - oxide
    return {
        "domain": domain, "radius": radius, "metal_radius": metal_radius,
        "oxide": oxide, "center_z": nm(g["rounding_center_z_nm"]),
        "gate_top": nm(g["gate_top_depth_nm"]), "outer_y_half": outer_y_half,
        "metal_y_half": metal_y_half, "active_half": active_half,
        "sti_depth": nm(g["sti_depth_nm"]),
        "source": [[nm(v) for v in pair] for pair in g["sn_contact_box_xy_nm"]],
        "drain": [[nm(v) for v in pair] for pair in g["bl_contact_box_xy_nm"]],
        "donor_peak": float(d["peak_donor"]), "acceptor": float(d["uniform_acceptor"]),
        "sn_junction": nm(d["sn_junction_depth_nm"]),
        "bl_junction": nm(d["bl_junction_depth_nm"]), "blend": 0.005,
        "track": [nm(v) for v in a["position_nm"]],
        "track_width": nm(a["radial_Gaussian_w_nm"]),
        "oxide_edge": nm(n["near_oxide_max_edge_nm"]),
        "junction_edge": nm(n["near_junction_or_track_max_edge_nm"]),
        "bulk_edge": nm(n["far_bulk_max_edge_nm"]),
    }


def _in_round_bottom(x, z, radius, center_z, top):
    """Closed rectangle union disk; only the lower disk half is additional."""
    return (abs(x) <= radius and top <= z <= center_z) or (
        z >= center_z and x*x + (z-center_z)**2 <= radius*radius
    )


def material_at(model, x, y, z, *, dimension=3):
    """Nominal analytic material mask, not a native mesh observation.

    Shared boundaries use gate void > trench oxide > STI > silicon precedence.
    Physical y is ignored for the 2D y=0 center section.
    """
    if dimension not in (2, 3):
        raise ValueError("Only 2D center section and 3D finite width are supported")
    p = _parameters(model)
    if dimension == 2:
        y = 0.0
    if not all(p["domain"][axis][0] <= value <= p["domain"][axis][1]
               for axis, value in zip("xyz", (x, y, z))):
        return "Outside"
    if abs(y) <= p["metal_y_half"] and _in_round_bottom(
            x, z, p["metal_radius"], p["center_z"], p["gate_top"]):
        return "GateVoid"
    if abs(y) <= p["outer_y_half"] and _in_round_bottom(
            x, z, p["radius"], p["center_z"], 0.0):
        return "SiO2"
    if dimension == 3 and p["active_half"] <= abs(y) <= p["outer_y_half"] and z <= p["sti_depth"]:
        return "SiO2"
    return "Silicon"


def is_silicon(model, x, y, z, *, dimension=3):
    return material_at(model, x, y, z, dimension=dimension) == "Silicon"


def donor_concentration(model, x, y, z, *, dimension=3):
    """Exact nominal ArsenicActiveConcentration in cm^-3, zero outside Si."""
    p = _parameters(model)
    if not is_silicon(model, x, y, z, dimension=dimension):
        return 0.0
    log_ratio = math.log(p["donor_peak"] / p["acceptor"])
    a_sn, a_bl = p["sn_junction"] / math.sqrt(log_ratio), p["bl_junction"] / math.sqrt(log_ratio)
    weight = (1.0 - math.tanh(x / p["blend"])) / 2.0
    return p["donor_peak"] * (weight * math.exp(-(z/a_sn)**2)
                              + (1-weight) * math.exp(-(z/a_bl)**2))


def _cross_section_area(radius, center_z, top):
    return 2*radius*(center_z-top) + math.pi*radius*radius/2


def _map_position(physical, dimension):
    x, y, z = physical
    return [x, z, 0.0] if dimension == 2 else [x, y, z]


def _contacts(p, dimension):
    contacts = []
    for name, circuit_node in (("source", "SN"), ("drain", "BL")):
        xy = p[name]
        center = [(xy[0][0]+xy[0][1])/2, (xy[1][0]+xy[1][1])/2, 0.0]
        contacts.append({
            "name": name, "circuit_node": circuit_node, "material": "Silicon",
            "physical_probe_um": center, "sde_probe_um": _map_position(center, dimension),
            "physical_box_xy_um": deepcopy(xy),
            "measure": ((xy[0][1]-xy[0][0]) if dimension == 2
                        else (xy[0][1]-xy[0][0])*(xy[1][1]-xy[1][0])),
            "measure_unit": "um" if dimension == 2 else "um^2",
        })
    gate_z = (p["gate_top"]+p["center_z"])/2
    gate_probes = [
        {"surface": "top", "point": [0, 0, p["gate_top"]], "outward": [0, 0, -1]},
        {"surface": "side_sn", "point": [-p["metal_radius"], 0, gate_z], "outward": [-1, 0, 0]},
        {"surface": "side_bl", "point": [p["metal_radius"], 0, gate_z], "outward": [1, 0, 0]},
        {"surface": "round_bottom", "point": [0, 0, p["center_z"]+p["metal_radius"]], "outward": [0, 0, 1]},
    ]
    if dimension == 3:
        gate_probes += [
            {"surface": "end_yminus", "point": [0, -p["metal_y_half"], gate_z], "outward": [0, -1, 0]},
            {"surface": "end_yplus", "point": [0, p["metal_y_half"], gate_z], "outward": [0, 1, 0]},
        ]
    for probe in gate_probes:
        probe["sde_point_um"] = _map_position(probe["point"], dimension)
    gate_perimeter = 2*p["metal_radius"] + 2*(p["center_z"]-p["gate_top"]) + math.pi*p["metal_radius"]
    gate_area = _cross_section_area(p["metal_radius"], p["center_z"], p["gate_top"])
    contacts.append({
        "name": "gate", "circuit_node": "WL", "material": "SiO2",
        "physical_body_probe_um": [0, 0, gate_z],
        "sde_body_probe_um": _map_position([0, 0, gate_z], dimension),
        "boundary_probes": gate_probes, "temporary_material": "Metal", "metal_removed": True,
        "measure": gate_perimeter if dimension == 2 else gate_perimeter*2*p["metal_y_half"]+2*gate_area,
        "measure_unit": "um" if dimension == 2 else "um^2",
    })
    body = [0, 0, p["domain"]["z"][1]]
    contacts.append({
        "name": "body", "circuit_node": "BODY", "material": "Silicon",
        "physical_probe_um": body, "sde_probe_um": _map_position(body, dimension),
        "measure": p["domain"]["x"][1]-p["domain"]["x"][0],
        "measure_unit": "um" if dimension == 2 else "um^2",
    })
    if dimension == 3:
        contacts[-1]["measure"] *= p["domain"]["y"][1]-p["domain"]["y"][0]
    return contacts


def _mesh_windows(p, dimension, mesh_scale):
    d = p["domain"]
    common = [d["x"][0], d["y"][0], d["z"][0]], [d["x"][1], d["y"][1], d["z"][1]]
    windows = []
    def add(name, low, high, edge, materials=None):
        low = [max(low[i], common[0][i]) for i in range(3)]
        high = [min(high[i], common[1][i]) for i in range(3)]
        axes = (0, 2) if dimension == 2 else (0, 1, 2)
        windows.append({"name": name, "physical_min_um": low, "physical_max_um": high,
                        "sde_min_um": _map_position(low, dimension),
                        "sde_max_um": _map_position(high, dimension),
                        "max_size_um": [edge*mesh_scale for _ in axes],
                        "min_size_um": [edge*mesh_scale/2 for _ in axes],
                        "materials": materials or []})
    add("All", *common, p["bulk_edge"])
    add("Junction", common[0], [d["x"][1], d["y"][1], 0.160], p["junction_edge"], ["Silicon"])
    halo = p["oxide_edge"]
    add("GateOxide", [-p["radius"]-halo, -p["outer_y_half"]-halo, 0],
        [p["radius"]+halo, p["outer_y_half"]+halo, p["center_z"]+p["radius"]+halo], p["oxide_edge"])
    radius = 4*p["track_width"]
    add("AlphaTrack", [p["track"][0]-radius, p["track"][1]-radius, 0],
        [p["track"][0]+radius, p["track"][1]+radius, d["z"][1]], p["junction_edge"], ["Silicon"])
    return windows


def describe_geometry(model, dimension=3):
    """Return the one analytic geometry description used by CAD and source masks."""
    if dimension not in (2, 3):
        raise ValueError("dimension must be 2 or 3")
    p = _parameters(model)
    dx = p["domain"]["x"][1]-p["domain"]["x"][0]
    dy = p["domain"]["y"][1]-p["domain"]["y"][0]
    dz = p["domain"]["z"][1]-p["domain"]["z"][0]
    outer_area = _cross_section_area(p["radius"], p["center_z"], 0)
    metal_area = _cross_section_area(p["metal_radius"], p["center_z"], p["gate_top"])
    total = dx*dz if dimension == 2 else dx*dy*dz
    trench = outer_area if dimension == 2 else outer_area*2*p["outer_y_half"]
    gate = metal_area if dimension == 2 else metal_area*2*p["metal_y_half"]
    sti_each = 0 if dimension == 2 else dx*(p["outer_y_half"]-p["active_half"])*p["sti_depth"]
    overlap_each = 0 if dimension == 2 else outer_area*(p["outer_y_half"]-p["active_half"])
    silicon = total-trench-2*sti_each+2*overlap_each
    regions = [{"name": "R.Silicon", "material": "Silicon", "measure": silicon},
               {"name": "R.Trench", "material": "SiO2", "measure": trench-gate}]
    if dimension == 3:
        regions.extend({"name": "R.STI."+side, "material": "SiO2", "measure": sti_each-overlap_each}
                       for side in ("minus", "plus"))
    depth_var = "y" if dimension == 2 else "z"
    initialization = ";".join([
        "s2_npk="+_number(p["donor_peak"]), "s2_na="+_number(p["acceptor"]),
        "s2_asn="+_number(p["sn_junction"])+"/sqrt(log("+_number(p["donor_peak"] / p["acceptor"])+"))",
        "s2_abl="+_number(p["bl_junction"])+"/sqrt(log("+_number(p["donor_peak"] / p["acceptor"])+"))",
        "s2_blend="+_number(p["blend"]),
    ])
    formula = ("s2_npk*((1-tanh(x/s2_blend))/2*exp(-("+depth_var+"/s2_asn)^2)"
               "+(1-(1-tanh(x/s2_blend))/2)*exp(-("+depth_var+"/s2_abl)^2))")
    return {
        "schema": "s2-bcat-analytic-geometry-r1", "status": "OFFLINE_REVIEW_ONLY",
        "native_qualified": False, "dimension": dimension, "length_unit": "um",
        "model_id": model["model_id"], "size_id": "S2",
        "coordinates": "physical x,y,z_depth" if dimension == 3 else "physical x,z_depth -> SDE x,y; SDE z=0",
        "domain_um": deepcopy(p["domain"]),
        "outer_trench": {"x_half_width_um": p["radius"], "y_half_width_um": p["outer_y_half"],
                          "top_um": 0.0, "round_center_z_um": p["center_z"], "radius_um": p["radius"],
                          "bottom_um": p["center_z"]+p["radius"], "construction": "rectangle/cuboid union circle/cylinder"},
        "gate_void": {"x_half_width_um": p["metal_radius"], "y_half_width_um": p["metal_y_half"],
                      "top_um": p["gate_top"], "round_center_z_um": p["center_z"], "radius_um": p["metal_radius"],
                      "bottom_um": p["center_z"]+p["metal_radius"], "temporary_material": "Metal",
                      "retained_as_volume": False},
        "sti": {"included": dimension == 3, "x_um": deepcopy(p["domain"]["x"]),
                "y_intervals_um": [[-p["outer_y_half"], -p["active_half"]], [p["active_half"], p["outer_y_half"]]],
                "z_um": [0, p["sti_depth"]]},
        "nominal_oxide_um": {"side": p["oxide"], "bottom": p["oxide"],
                             "y_end_cap": p["oxide"] if dimension == 3 else None, "top_cap": p["gate_top"]},
        "regions": regions,
        "measure_unit": "um^2" if dimension == 2 else "um^3",
        "measures": {"domain": total, "outer_trench": trench, "gate_void": gate,
                     "sti_gross_each": sti_each, "sti_trench_intersection_each": overlap_each,
                     "silicon": silicon, "oxide": sum(r["measure"] for r in regions if r["material"] == "SiO2"),
                     "retained": total-gate},
        "contacts": _contacts(p, dimension),
        "doping": {"donor_species": "ArsenicActiveConcentration", "acceptor_species": "BoronActiveConcentration",
                   "material_restriction": "Silicon", "acceptor_cm3": p["acceptor"], "peak_cm3": p["donor_peak"],
                   "a_sn_um": p["sn_junction"]/math.sqrt(math.log(p["donor_peak"]/p["acceptor"])),
                   "a_bl_um": p["bl_junction"]/math.sqrt(math.log(p["donor_peak"]/p["acceptor"])),
                   "blend_um": p["blend"], "type": "General", "initialization": initialization,
                   "formula": formula, "failure_sentinel_cm3": -1.0,
                   "native_doping_audit_required": True},
        "mesh": {"windows": _mesh_windows(p, dimension, 1.0),
                 "interface": {"materials": ["Silicon", "SiO2"], "first_step_um": p["oxide_edge"],
                               "factor": 1.5, "DoubleSide": True, "minimum_um": p["oxide_edge"]/2},
                 "resource_forecast": "UNQUALIFIED; requested controls do not bound nodes, memory, or storage",
                 "mesh_output": "cell_msh.tdr", "guard_file": "mesh_resource_guard.py"},
    }


def validate_geometry(model):
    """Deterministic analytic consistency checks. This is not SDE validation."""
    errors, checks = [], []
    try:
        p = _parameters(model)
        g = model["geometry"]
    except (KeyError, TypeError, ValueError) as exc:
        return {"passed": False, "errors": [str(exc)], "native_qualified": False}
    def check(condition, name):
        checks.append({"name": name, "passed": bool(condition)})
        if not condition:
            errors.append(name)
    check(all(math.isfinite(v) for key in ("radius", "metal_radius", "oxide", "center_z", "gate_top",
          "outer_y_half", "metal_y_half", "active_half", "sti_depth", "donor_peak", "acceptor",
          "sn_junction", "bl_junction", "blend", "track_width", "oxide_edge", "junction_edge", "bulk_edge")
          for v in [p[key]]), "all scalar parameters finite")
    check(all(math.isfinite(v) for v in p["track"]
              + [v for bounds in p["source"]+p["drain"] for v in bounds]),
          "all contact and source coordinates finite")
    check(g["units"] == "nm" and model["doping"]["units"] == "cm^-3", "declared input units")
    check(all(len(interval) == 2 and all(math.isfinite(v) for v in interval) and interval[1] > interval[0]
              for interval in p["domain"].values()), "domain intervals finite and ordered")
    check(p["domain"]["z"][0] == 0 and 0 < p["gate_top"] < p["center_z"], "positive-depth buried gate")
    check(math.isclose(p["gate_top"], 0.080, rel_tol=0, abs_tol=1e-15), "this adapter is S2 only")
    check(p["radius"] > p["metal_radius"] > 0 and math.isclose(p["radius"]-p["metal_radius"], p["oxide"], abs_tol=1e-15), "side and circular-bottom oxide thickness")
    check(math.isclose(g["trench_outer_width_nm"]/1000, 2*p["radius"], abs_tol=1e-15), "outer width equals twice radius")
    check(math.isclose(g["metal_bottom_z_nm"]/1000, p["center_z"]+p["metal_radius"], abs_tol=1e-15)
          and math.isclose(g["oxide_outer_bottom_z_nm"]/1000, p["center_z"]+p["radius"], abs_tol=1e-15), "round-bottom depths")
    check(math.isclose(g["published_gate_recess_depth_nm"]/1000, p["center_z"]+p["metal_radius"], abs_tol=1e-15), "recess interpretation retained")
    check(0 < p["active_half"] < p["metal_y_half"] < p["outer_y_half"] < p["domain"]["y"][1]
          and -p["outer_y_half"] > p["domain"]["y"][0], "finite active and insulated gate endpoints fit domain")
    check(p["center_z"]+p["radius"] < p["sti_depth"] < p["domain"]["z"][1], "trench above STI bottom above body")
    check(g["body_contact_z_nm"]/1000 == p["domain"]["z"][1], "body contact equals bottom domain")
    check(p["donor_peak"] > p["acceptor"] > 0 and 0 < p["sn_junction"] < p["bl_junction"] < 0.160, "positive mixed Gaussian and junction window")
    check(0 < p["oxide_edge"] <= p["junction_edge"] <= p["bulk_edge"] and p["track_width"] > 0,
          "positive mesh controls and source width")
    check(model["alpha"]["angle_deg_from_positive_z"] == 0 and p["track"][2] == 0, "mesh source window supports normal surface alpha")
    if errors:
        return {"passed": False, "errors": errors, "checks": checks, "native_qualified": False}
    for dimension in (2, 3):
        desc = describe_geometry(model, dimension)
        measure = desc["measures"]
        check(all(r["measure"] > 0 for r in desc["regions"]), f"D{dimension} nonzero retained regions")
        check(math.isclose(measure["silicon"]+measure["oxide"]+measure["gate_void"], measure["domain"], abs_tol=1e-14), f"D{dimension} material/void partition closure")
        for contact in desc["contacts"]:
            if contact["name"] in ("source", "drain"):
                xspan, yspan = contact["physical_box_xy_um"]
                check(xspan[0] < xspan[1] and yspan == [-p["active_half"], p["active_half"]], f"D{dimension} {contact['name']} contact extent")
                check((xspan[1] < -p["radius"] if contact["name"] == "source" else xspan[0] > p["radius"])
                      and p["domain"]["x"][0] < xspan[0] < xspan[1] < p["domain"]["x"][1],
                      f"D{dimension} {contact['name']} contact avoids trench and domain sides")
                x, y, z = contact["physical_probe_um"]
                check(material_at(model, x, y, z+1e-8, dimension=dimension) == "Silicon", f"D{dimension} {contact['name']} inward probe is silicon")
            elif contact["name"] == "gate":
                for probe in contact["boundary_probes"]:
                    point, normal = probe["point"], probe["outward"]
                    outside = [a+1e-8*b for a,b in zip(point, normal)]
                    inside = [a-1e-8*b for a,b in zip(point, normal)]
                    check(material_at(model, *outside, dimension=dimension) == "SiO2" and
                          material_at(model, *inside, dimension=dimension) == "GateVoid",
                          f"D{dimension} gate {probe['surface']} separates oxide and removed metal")
            else:
                x, y, z = contact["physical_probe_um"]
                check(material_at(model, x, y, z-1e-8, dimension=dimension) == "Silicon", f"D{dimension} body inward probe is silicon")
    check(math.isclose(donor_concentration(model, -0.100, 0, p["sn_junction"]), p["acceptor"], rel_tol=1e-12), "SN asymptotic junction concentration")
    check(math.isclose(donor_concentration(model, 0.100, 0, p["bl_junction"]), p["acceptor"], rel_tol=1e-12), "BL asymptotic junction concentration")
    check(donor_concentration(model, 0, 0, 0.050) == 0 and donor_concentration(model, 0, 0, 0.100) == 0,
          "no dopant assigned to oxide or removed gate volume")
    check(all(donor_concentration(model, x, 0, 0) == p["donor_peak"] for x in (-0.052, 0.052)), "surface donor peak")
    return {"schema": "s2-cad-offline-validation-r1", "passed": not errors, "errors": errors,
            "checks": checks, "check_count": len(checks), "native_qualified": False,
            "not_verified": ["native SDE parser and Boolean topology", "native material/contact inventory",
                             "native doping values", "mesh quality, node count, resource cost"]}


def render_sde(model, dimension=3, mesh_scale=1.0):
    """Render a complete review-only SDE deck with the established serial mesh path."""
    if dimension not in (2, 3):
        raise ValueError("dimension must be 2 or 3")
    mesh_scale = float(mesh_scale)
    if not math.isfinite(mesh_scale) or mesh_scale <= 0:
        raise ValueError("mesh_scale must be finite and positive")
    validation = validate_geometry(model)
    if not validation["passed"]:
        raise ValueError("Invalid S2 geometry: " + "; ".join(validation["errors"]))
    p, desc = _parameters(model), describe_geometry(model, dimension)
    domain = p["domain"]
    lines = [
        "; OFFLINE REVIEW INPUT ONLY. Native parser, topology, doping and mesh NOT qualified.",
        "; S2 representative BCAT; not a commercial LPDDR5/6 process reproduction.",
        "; Lengths um. " + desc["coordinates"],
        "; Exact circle/cylinder union construction; see cad-assumptions.md CAD001-CAD010.",
        '(sde:clear)', '(sdegeo:set-default-boolean "ABA")',
        '(define (require-one entities message)',
        '  (if (not (= (length entities) 1)) (sde:error message))',
        '  entities)',
    ]
    def rect(variable, low, high, material, region):
        constructor = "create-rectangle" if dimension == 2 else "create-cuboid"
        lines.append(f'(define {variable} (sdegeo:{constructor} {_position(_map_position(low, dimension))} '
                     f'{_position(_map_position(high, dimension))} "{material}" "{region}"))')
    def round_solid(variable, radius, top, yhalf, material, region):
        rect(variable+"-rect", [-radius, -yhalf, top], [radius, yhalf, p["center_z"]], material, region)
        if dimension == 2:
            constructor = '(sdegeo:create-circle ' + _position([0, p["center_z"], 0])
        else:
            constructor = '(sdegeo:create-cylinder ' + _position([0, -yhalf, p["center_z"]]) + " " + _position([0, yhalf, p["center_z"]])
        lines.append(f'(define {variable}-round {constructor} {_number(radius)} "{material}" "{region}.Round"))')
        lines.append(f'(define {variable} (sdegeo:bool-unite (list {variable}-rect {variable}-round)))')
        lines.append(f'(if (not {variable}) (sde:error "Failed rounded union: {region}"))')
    rect("silicon", [domain[a][0] for a in "xyz"], [domain[a][1] for a in "xyz"], "Silicon", "R.Silicon")
    if dimension == 3:
        for side, low_y, high_y in (("minus", -p["outer_y_half"], -p["active_half"]),
                                    ("plus", p["active_half"], p["outer_y_half"])):
            rect("sti-"+side, [domain["x"][0], low_y, 0], [domain["x"][1], high_y, p["sti_depth"]], "SiO2", "R.STI."+side)
    round_solid("trench", p["radius"], 0, p["outer_y_half"], "SiO2", "R.Trench")
    round_solid("gate-metal", p["metal_radius"], p["gate_top"], p["metal_y_half"], "Metal", "R.GateTemporary")
    colors = {"source": "1 0 0", "drain": "0 0 1", "gate": "0 1 0", "body": "0 0 0"}
    for contact in desc["contacts"]:
        name = contact["name"]
        lines.append(f'(sdegeo:define-contact-set "{name}" 4 (color:rgb {colors[name]}) "##")')
    gate = next(c for c in desc["contacts"] if c["name"] == "gate")
    lines += ['; Gate is a contact on retained oxide; temporary Metal is removed.',
              '(require-one (find-body-id '+_position(gate["sde_body_probe_um"])+') "Expected one temporary gate body")',
              '(sdegeo:set-contact gate-metal "gate" "remove")',
              '(if (not (= (length (find-body-id '+_position(gate["sde_body_probe_um"])+')) 0)) (sde:error "Gate metal volume remains"))']
    finder = "find-edge-id" if dimension == 2 else "find-face-id"
    for probe in gate["boundary_probes"]:
        lines.append('(require-one ('+finder+' '+_position(probe["sde_point_um"])+') "Missing or ambiguous gate '+probe["surface"]+' boundary")')
    for contact in desc["contacts"]:
        name = contact["name"]
        if name == "gate":
            continue
        if name in ("source", "drain"):
            xy = contact["physical_box_xy_um"]
            if dimension == 2:
                for x in xy[0]:
                    lines.append('(sdegeo:insert-vertex '+_position([x, 0, 0])+')')
            else:
                lines.append(f'(define imprint-{name} (sdegeo:imprint-rectangular-wire '
                             +_position([xy[0][0], xy[1][0], 0])+" "+_position([xy[0][1], xy[1][1], 0])+'))')
                lines.append(f'(require-one imprint-{name} "Expected one imprinted {name} face")')
        lines += [f'(define contact-{name} (require-one ({finder} '+_position(contact["sde_probe_um"])
                  +f') "Missing or ambiguous {name} contact"))']
        if dimension == 3 and name in ("source", "drain"):
            lines.append(f'(if (not (equal? (car contact-{name}) (car imprint-{name}))) '
                         +f'(sde:error "Imprint/probe mismatch for {name}"))')
        lines.append(f'(sdegeo:set-contact contact-{name} "{name}")')
    doping = desc["doping"]
    lines += [
        '; One exact General function uses absolute device coordinates; material clipping is explicit.',
        '(sdedr:define-constant-profile "P.Body" "BoronActiveConcentration" '+_number(p["acceptor"])+')',
        '(sdedr:define-constant-profile-material "P.Body.Place" "P.Body" "Silicon" 0)',
    ]
    if dimension == 2:
        lines.append('(sdedr:define-refeval-window "Donor.Reference" "Line" '
                     +_position([domain["x"][0], 0, 0])+" "+_position([domain["x"][1], 0, 0])+')')
    else:
        lines.append('(sdedr:define-refeval-window "Donor.Reference" "Rectangle" '
                     +_position([domain["x"][0], domain["y"][0], 0])+" "
                     +_position([domain["x"][1], domain["y"][1], 0])+')')
    lines += [
        '(sdedr:define-analytical-profile "N.MixedGaussian" "ArsenicActiveConcentration" '
        +json.dumps(doping["initialization"])+" "+json.dumps(doping["formula"])+ ' -1 "General")',
        '(sdedr:define-analytical-profile-placement "N.MixedGaussian.Place" "N.MixedGaussian" '
        '"Donor.Reference" "Both" "NoReplace" "Eval" "Silicon" 0 "material")',
        '; Future native doping audit MUST reject the -1 failure sentinel and incorrect coordinates.',
    ]
    window_type = "Rectangle" if dimension == 2 else "Cuboid"
    for window in _mesh_windows(p, dimension, mesh_scale):
        name = window["name"]
        lines += ['(sdedr:define-refeval-window "Window.'+name+'" "'+window_type+'" '
                  +_position(window["sde_min_um"])+" "+_position(window["sde_max_um"])+')',
                  '(sdedr:define-refinement-size "Mesh.'+name+'" '
                  +" ".join(_number(v) for v in window["max_size_um"]+window["min_size_um"])+')']
        placement = '"Window.'+name+'"'
        if window["materials"]:
            placement = '(list "window" '+placement+' "material" "'+window["materials"][0]+'")'
        lines.append('(sdedr:define-refinement-placement "Place.'+name+'" "Mesh.'+name+'" '+placement+')')
    lines += [
        '(sdedr:define-refinement-size "Mesh.Interfaces" '
        +" ".join([_number(p["bulk_edge"]*mesh_scale)]*dimension
                 +[_number(p["oxide_edge"]*mesh_scale/2)]*dimension)+')',
        '(sdedr:define-refinement-function "Mesh.Interfaces" "MaxLenInt" "Silicon" "SiO2" '
        +_number(p["oxide_edge"]*mesh_scale)+' 1.5 "DoubleSide")',
        '(sdedr:define-refinement-placement "Place.Interfaces" "Mesh.Interfaces" "Window.All")',
        '; Uncontacted external boundaries retain natural insulating conditions.',
        '; The original runner owns shared lock, single-core affinity and single-thread execution.',
        '(sde:build-mesh "snmesh" "" "cell")',
        '; Same-stage guard supplied by package integration; no second mesh or solver invocation.',
        '(define resource-guard-status (system:command "/usr/bin/python3 mesh_resource_guard.py"))',
        '(if (not (equal? resource-guard-status 0)) (sde:error "Mesh resource guard blocked SDevice; see mesh-resource-report.json"))',
    ]
    return "\n".join(lines)+"\n"
