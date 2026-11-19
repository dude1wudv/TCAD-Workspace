"""S2 native-deck text only; no native process, network, or execution permission."""
import hashlib
import json
import math
from pathlib import Path

MATERIAL_HASHES = {
    "Silicon.par": "ce02ba3cc28d8b1319ae070315371469fc4f97c4834d9a72d23f99f686108790",
    "Oxide.par": "1fcb91c12e98e3969cc3fd3b9c6b76f09457d955ed42ad536ba1fd18a6ff23fb",
}
BTBT = {"Apath": 4e14, "Bpath": 1.9e7, "Dpath": 0, "Ppath": .037,
        "Rpath": 0, "MaxTunnelLength": 1e-5}
PHYSICS = """Fermi EffectiveIntrinsicDensity(OldSlotboom)
 Mobility(DopingDep HighFieldSaturation Enormal)
 Recombination(SRH(DopingDep) Auger Band2Band(Model=NonlocalPath))"""
PLOTS = """eDensity hDensity Potential ElectricField/Vector Doping
 DonorConcentration AcceptorConcentration
 TotalCurrent/Vector eCurrent/Vector hCurrent/Vector
 eBand2BandGeneration hBand2BandGeneration"""
TIMING_NS = [0, 2, 2.1, 6, 6.1, 6.2, 8.1, 14.9984, 15.0016,
             19.9, 20, 20.1, 21.9, 22, 22.1, 25]
SCOPE_ROLES = ("B1-D2", "B1-D3", "B1-A0-main-b0", "B1-A0-main-b1")
PARENT_MODEL_SHA256 = "a89d30d0429defaa6dd491869470e168a6574125af1b8f27cb7689e4f8241481"


def validate_model(model):
    path = Path(__file__).resolve().parent.parent / "course-plan-r13/model-contract.proposed.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PARENT_MODEL_SHA256:
        raise ValueError("Frozen r13 model proposal changed; new S2 implementation contract required")
    if model != json.loads(raw):
        raise ValueError("S2 deck constants only implement the exact frozen r13 model")


def num(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Finite non-boolean numeric value required")
    return format(value, ".17g")


def physics_parameter_text():
    # All proprietary parameter content remains in private runtime packages only.
    overrides = "\n".join("  " + key + " = " + num(value) for key, value in BTBT.items())
    return ('Material="Silicon" {\n Insert="Silicon.par"\n Band2BandTunneling {\n'
            + overrides + '\n }\n}\nMaterial="Oxide" { Insert="Oxide.par" }\n')


def prepare_physics(private_directory, output):
    private_directory, output = Path(private_directory), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, expected in MATERIAL_HASHES.items():
        raw = (private_directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Installed material snapshot changed: " + name)
        if (output / name).exists():
            raise FileExistsError(output / name)
        (output / name).write_bytes(raw)
        files[name] = expected
    (output / "physics.par").write_text(physics_parameter_text(), encoding="utf-8", newline="\n")
    manifest = {
        "schema": "s2-physics-card-r1", "release": "W-2024.09",
        "source": "strict SSH cat of installed MaterialDB, not sdevice -P or a license probe",
        "model_selectors": PHYSICS, "temperature_K": 300,
        "default_cards_sha256": files, "btbt_explicit_overrides": BTBT,
        "btbt_mapping": "Installed Apath1/Bpath1/Dpath1/Ppath1/Rpath1 map to the single modern unnamed process; W-2024.09 UG pp553,562-566",
        "btbt_postprocessing": False, "native_syntax_verified": False,
        "native_calibration": False, "execution_enabled": False,
        "parameter_insert_evidence": "W-2024.09 SDevice UG p75",
        "private_material_files": list(MATERIAL_HASHES),
        "not_a_calibration": "Published paper did not disclose a full physics card. These are declared installed-model assumptions."
    }
    (output / "physics-manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    return manifest


def electrodes():
    return ('Electrode { {Name="source" Voltage=0} {Name="drain" Voltage=0}\n'
            ' {Name="gate" Voltage=0 WorkFunction=4.6} {Name="body" Voltage=0} }\n')


def math_block(mixed=False):
    return ('Math { CoordinateSystem { AsIs }\n'
            ' RelErrControl Digits=5 ErrRef(electron)=1e7 ErrRef(hole)=1e7\n'
            ' Iterations=30 Notdamped=100 ExitOnFailure\n'
            + (' Transient=BE Method=Blocked SubMethod=ParDiSo\n' if mixed else ' Method=ParDiSo\n')
            + '}\n')


def render_dc(model, dimension=3):
    validate_model(model)
    if dimension not in (2, 3):
        raise ValueError("DC dimension must be 2 or 3")
    area = .02 if dimension == 2 else 1
    text = ('* Offline S2 DC review input; no particle source.\n'
            'File { Grid="cell_msh.tdr" Current="dc" Plot="dc" Output="dc" Parameter="physics.par" }\n'
            + electrodes() + 'Physics { AreaFactor=' + num(area) + ' Temperature=300\n '
            + PHYSICS + '\n}\nPlot { ' + PLOTS + ' }\n' + math_block()
            + 'Solve {\n Coupled(Iterations=100) {Poisson}\n'
            ' Coupled(Iterations=100) {Poisson Electron Hole}\n Save(FilePrefix="equilibrium")\n')
    for label, drain in (("low", .1), ("high", 1.2)):
        text += (' Load(FilePrefix="equilibrium")\n NewCurrentPrefix="settle_' + label + '_"\n'
                 ' Quasistationary(InitialStep=0.001 MinStep=1e-8 MaxStep=0.02 Increment=1.3\n'
                 '  Goal {Name="gate" Voltage=-0.5} Goal {Name="drain" Voltage=' + num(drain) + '})\n'
                 ' { Coupled {Poisson Electron Hole} }\n NewCurrentPrefix="idvg_' + label + '_"\n'
                 ' Quasistationary(InitialStep=0.001 MinStep=1e-8 MaxStep=0.005 Increment=1.3\n'
                 '  Goal {Name="gate" Voltage=1.5}) {\n  Coupled {Poisson Electron Hole}\n'
                 '  CurrentPlot(Time=(Range=(0 1) Intervals=200))\n }\n')
    return text + ' Plot(FilePrefix="dc_final")\n}\n'


def transient_segments(model, time_scale=1):
    validate_model(model)
    if time_scale not in (1, .5):
        raise ValueError("Only main or dt/2 is defined")
    segments = []
    for lo, hi in zip(TIMING_NS, TIMING_NS[1:]):
        pulse = lo == 14.9984
        max_step = (4e-14 if pulse else (1e-11 if hi-lo <= .100000001 else 1e-10)) * time_scale
        segments.append({"start_s": lo*1e-9, "end_s": hi*1e-9,
                         "max_step_s": max_step,
                         "source_window": pulse,
                         "change_resistance_before": lo == 8.1})
    return segments


def render_transient(model, bit, source_block="", source_plot="", time_scale=1):
    validate_model(model)
    if type(bit) is not int or bit not in (0, 1):
        raise ValueError("Stored bit must be integer 0 or 1")
    c = model["circuit"]
    if c["Cstore_fF"] != 20 or c["Cbl_fF"] != 200:
        raise ValueError("S2 circuit changed; new contract required")
    vwrite = 1.2 * bit
    text = ('* Offline S2 actual write/hold/read; common clamped initialization, released before t=0.\n'
            'Device Cell {\n File { Grid="cell_msh.tdr" Current="device.plt" Plot="device.tdr" Parameter="physics.par" }\n'
            + electrodes() + ' Physics { AreaFactor=1 Temperature=300\n ' + PHYSICS + '\n' + source_block + '\n }\n}\n'
            'File { Output="transient" }\nPlot { ' + PLOTS + ' ' + source_plot + ' }\n'
            + math_block(True) + 'System {\n'
            ' Cell access ("source"=sn "drain"=bl "gate"=wl "body"=0)\n'
            ' Vsource_pset vwl (wl 0) {pwl=(0 -0.5 2e-9 -0.5 2.1e-9 1.8 6e-9 1.8 6.1e-9 -0.5 '
            '20e-9 -0.5 20.1e-9 1.8 22e-9 1.8 22.1e-9 -0.5 25e-9 -0.5)}\n'
            ' Vsource_pset vdrive (drive 0) {pwl=(0 ' + num(vwrite) + ' 6.1e-9 ' + num(vwrite) + ' 6.2e-9 0.6 25e-9 0.6)}\n'
            ' Vsource_pset vplate (plate 0) {dc=0.6}\n'
            ' Resistor_pset rdrive (bl drive) {resistance=1000}\n'
            ' Capacitor_pset cstore (sn plate) {capacitance=2e-14}\n'
            ' Capacitor_pset cbl (bl 0) {capacitance=2e-13}\n'
            ' Set(sn=0.6)\n'
            ' Plot "circuit.plt" (time() v(sn) v(bl) v(wl) v(plate) v(drive) '
            'i(access,sn) i(access,bl) i(access,wl) i(access,0) i(cstore,sn) i(cbl,bl) i(rdrive,bl))\n}\n'
            'Solve {\n Coupled(Iterations=100) {Poisson}\n'
            ' Coupled(Iterations=100) {Poisson Electron Hole Contact Circuit}\n'
            ' Plot(FilePrefix="initial")\n Unset(sn)\n')
    for n, seg in enumerate(transient_segments(model, time_scale)):
        if seg["change_resistance_before"]:
            text += ' Set(rdrive."resistance"=1e15)\n'
        step = seg["max_step_s"]
        text += (' Transient(InitialTime=' + num(seg["start_s"]) + ' FinalTime=' + num(seg["end_s"])
                 + ' InitialStep=' + num(min(step/10, 1e-13)) + ' MinStep=1e-18 MaxStep=' + num(step)
                 + ' Increment=1.3) {\n  Coupled {Poisson Electron Hole Contact Circuit}\n')
        if seg["source_window"]:
            text += ('  Plot(FilePrefix="source_window" Time=(Range=(' + num(seg["start_s"]) + ' '
                     + num(seg["end_s"]) + ')) NoOverwrite)\n')
        if n == len(TIMING_NS)-2:
            text += '  Plot(FilePrefix="final" Time=(25e-9))\n'
        text += ' }\n'
    return text + '}\n'


def project_review(role):
    if role not in SCOPE_ROLES:
        raise ValueError("Role outside first four")
    steps = []
    if role.startswith("B1-D"):
        steps.append({"tool": "sde", "args": ["-e", "-l", "geometry.scm"],
                      "outputs": ["cell_msh.tdr", "mesh-resource-passed.json"]})
        outputs = ["idvg_low_dc_des.plt", "idvg_high_dc_des.plt", "dc_final_des.tdr", "dc_des.log"]
    else:
        outputs = ["circuit.plt", "access_device.plt", "initial_access_des.tdr", "final_access_des.tdr", "transient_des.log"]
    steps.append({"tool": "sdevice", "args": ["device.cmd"], "outputs": outputs})
    return {"name": "v4-s2-r1-"+role.lower(), "schema": "s2-project-review-r1", "steps": steps,
            "execution_enabled": False, "role": role, "native_threads": 1, "native_cores": 1,
            "runner": "scripts/tcad.py (unchanged); never called by this preparer",
            "release_required": True}
