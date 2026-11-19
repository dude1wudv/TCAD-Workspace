"""Render an unqualified APD/QY activation candidate; never prepare or run a solver.

This module does not create a proton source, a native role, a matched A0 receipt,
or a qualification. Real event tables remain the output of the frozen complete
BCAT adapter and prepare_pmi_candidate.prepare_source_inputs.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EVIDENCE = ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/proton-native-activation-r1'
COMPILE = ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/projection-implementation/pmi-2d-compile-inputs-r2'
SCHEMA = 'dram-see-v4-parameterized-proton-activation-input-r1'
MANIFEST_SCHEMA = 'dram-see-v4-parameterized-proton-activation-manifest-r1'
OPERATION_SHA = '97a5ea8cf6fb64bdfe345adaf09f4aa8f222b8b443d84819fd64c0f447e937a5'
METRICS_SHA = '0083e300fd1242d77616597f7a47e075386fff36d991070dd662b414e6f97bc2'
COMPILE_MANIFEST_SHA = '31dceb972a678be8bccd016d56a9866851a3af46071bc43fd645ccddab289eba'
CALLBACKS = {
    'pmi_projection_qy_r1.C': '1b8eb30bfcd001142235e9cf2f870cdfb38d98546305028d8ca70664805b05c6',
    'projection_pmi_math_r1.hpp': 'bb1ff7fa938adc36ed3cdf5c2a91d60c24d50afcb338ccc68d8840dab1943c77',
    'source_kernel_r12.hpp': '7fccf1497de68fb3ce993c02b00ac4ca324f4f9ee5b5065f367c0533a82c7383',
}
INPUT_NAMES = ('geometry-contract.json', 'dimensional-contract.json', 'operation-timing.json')
NREF = 1e35


def require(ok, message):
    if not ok:
        raise ValueError('Proton activation candidate: ' + message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')


def obj(raw):
    require(isinstance(raw, bytes), 'input must retain original bytes')
    value = json.loads(raw.decode('utf-8'))
    require(isinstance(value, dict), 'expected JSON object')
    return value


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def literal(value):
    require(finite(value), 'nonfinite input')
    return format(value, '.17g')


def reference(path):
    raw = path.read_bytes()
    return dict(path=path.relative_to(ROOT).as_posix(), size_bytes=len(raw), sha256=sha(raw))


def dependencies():
    paths = {
        'operating_transient_2d.py': (HERE / 'operating_transient_2d.py', OPERATION_SHA),
        'operating_metrics_2d.py': (HERE.parent / 'data/operating_metrics_2d.py', METRICS_SHA),
        'compile-input-manifest': (COMPILE / 'candidate-input-manifest.json', COMPILE_MANIFEST_SHA),
    }
    paths.update({name: (COMPILE / name, digest) for name, digest in CALLBACKS.items()})
    result = {}
    for key, (path, digest) in sorted(paths.items()):
        require(path.is_file() and not path.is_symlink(), 'missing fixed dependency ' + key)
        item = reference(path)
        require(item['sha256'] == digest, 'fixed dependency changed: ' + key)
        result[key] = item
    return result


def timing_api():
    path = HERE / 'operating_transient_2d.py'
    require(sha(path.read_bytes()) == OPERATION_SHA, 'timing validator changed')
    spec = importlib.util.spec_from_file_location('_proton_activation_fixed_operation', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate_payload(geometry_bytes, dimensional_bytes, timing_bytes):
    """Return exact file bytes plus contract; no archive, event, build or solver is run."""
    deps = dependencies()
    geometry, dimensional, timing = [obj(raw) for raw in (geometry_bytes, dimensional_bytes, timing_bytes)]
    timing = timing_api().validate_timing(timing)
    require(geometry.get('schema') == 's2-bcat-analytic-geometry-r1'
            and geometry.get('dimension') == 2 and geometry.get('length_unit') == 'um', 'explicit 2D geometry in um required')
    require(geometry.get('gate_void', {}).get('top_um') in (.07, .08), 'only 70/80 nm development geometry is supported')
    require(geometry.get('domain_um') == dict(x=[-1., 1.], y=[-.25, .25], z=[0., 1.]),
            'candidate window is limited to the existing finite development domain')
    expected = dict(schema='dram-see-v4-2d-equivalence-r1',
        branch_id='dram-see-v4-parameterized-d2-source-r1', native_dimension=2, physical_dimension=2,
        effective_width_nm=20, effective_width_um=.02, effective_width_cm=2e-6,
        native_reference_width_um=1, area_factor=.02, native_third_coordinate=0,
        native_coordinate_unit='um', out_of_plane_axis='y',
        native_to_physical_axes=dict(X='x', Y='z', Z='omitted_y'),
        port_current_already_width_scaled=True, explicit_capacitance_rescale=False,
        Cstore_fF=20, Cbl_fF=200, source_dimension=2)
    require(all(dimensional.get(k) == v for k, v in expected.items()), '2D width/axis/circuit convention differs')
    require(dimensional.get('geometry_contract_sha256') == sha(geometry_bytes), 'geometry identity differs')
    full, epoch = timing['simulation_window_s'], timing['source_epoch_s']
    require(full[0] <= epoch <= full[1], 'source epoch lies outside full physical operation')
    xmin, xmax = geometry['domain_um']['x']
    zmin, zmax = geometry['domain_um']['z']

    # A constant basis. The actual imported field must establish coverage and units;
    # this text is not evidence that Sentaurus has loaded it.
    plx = ('# Interface APD basis, not a physical optical experiment.\n'
        '"proton_reference_apd_r1"\n'
        'Wavelength = 1 [um] Theta = 0 [deg] Intensity = 1 [W*cm^-2]\n'
        '0 1e35\n' + literal(zmax - zmin) + ' 1e35\n').encode('ascii')
    spectrum = b'# wavelength [um], intensity [W/cm^2]; requested/loaded ratio = 1\n1 1\n'
    device_file = b'OpticalSolverInput = "proton-reference-apd.plx"\nIlluminationSpectrum = "proton-reference-spectrum.txt"\n'
    global_file = b'PMIPath = "."\n'
    physics = ('''Optics (
 OpticalGeneration (
  ComputeFromSpectrum ( RefreshEveryTime )
  QuantumYield ( pmiModel="pmi_projection_qy_r1" )
 )
 OpticalSolver (
  FromFile (
   DatasetName = AbsorbedPhotonDensity
   SpectralInterpolation = Off
   IdentifyingParameter = ("Wavelength")
  )
 )
 Excitation (
  Wavelength = 1
  Intensity = 1
  Theta = 0
  Window ("proton_reference_basis") (
   Origin = (0, ''' + literal(zmin) + ''')
   XDirection = (1, 0, 0)
   Line (X1 = ''' + literal(xmin) + ' X2 = ' + literal(xmax) + ''')
   -WeightedAPDintegration
  )
 )
)
''').encode('ascii')
    plot = (b'AbsorbedPhotonDensity QuantumYield OpticalGeneration\n'
            b'PMIUserField0 PMIUserField1 PMIUserField2 PMIUserField3 PMIUserField4 PMIUserField5\n'
            b'eDensity hDensity\n')
    solve = b'Optics\n'
    contract = dict(schema=SCHEMA, status='INPUT_CANDIDATE_NATIVE_ACTIVATION_UNVERIFIED',
        input_sha256=dict(zip(INPUT_NAMES, map(sha, (geometry_bytes, dimensional_bytes, timing_bytes)))),
        fixed_dependencies=deps,
        source_model=dict(pmi_model='pmi_projection_qy_r1', required_library='pmi_projection_qy_r1.so.linux64',
            library_sha256=None, native_build_exit=None, original_cpp_unchanged=True,
            reference_APD_cm_minus3_s_minus1=NREF, quantum_yield='G2_BE / Nref',
            requested_to_loaded_intensity_ratio=1, common_electron_hole_pair_source=True,
            separate_measured_electron_and_hole_source_fields=False, heat_feedback=False,
            carrier_only_interface=True, extra_source_charge_multiplier=None),
        illumination_basis=dict(input_dataset='AbsorbedPhotonDensity', wavelength_um=1, intensity_W_cm_minus2=1,
            optical_direction_native_positive_Y=True, physical_proton_direction_independent=True,
            native_window_x_um=[xmin, xmax], native_window_Y_um=zmin,
            plx_first_coordinate=[0., zmax-zmin], plx_coordinate_convention='same um convention as frozen input mesh',
            plx_coordinate_unit_metadata_read=False, full_Silicon_APD_coverage_verified=False,
            weighted_APD_integration=False, spectral_interpolation='Off',
            transient_TimeDependence_added=False, automatic_update='vendor default on',
            recomputation='ComputeFromSpectrum(RefreshEveryTime); native BE dispatch unverified'),
        physical_time=dict(epoch_s=epoch, complete_source_context_window_s=full,
            inherited_A0_observation_window_s=timing['native_observation_window_s'],
            inherited_A0_mathematical_window_s=timing['mathematical_source_window_s'],
            inherited_A0_charge_window_s=timing['charge_window_s'],
            proton_native_observation_window_s=None, proton_response_charge_window_s=None,
            source_context_uses_inherited_narrow_observation_window=False,
            raw_Geant4_time_unchanged=True, translation='source t_s = epoch_s + original t_ns * 1e-9, once',
            all_raw_events_required=True, late_event_policy='retain; matching operation timing must cover actual deposition',
            source_sigma_s=2e-12, source_width_um=.03, electrical_timing_or_steps_changed=False),
        event_inputs=dict(status='NO_EVENT_SUPPLIED',
            required_files=['projection-sources3d.dat', 'projection-context.dat',
                'input-only-projection-reference.json', 'full-original-event-source.json'],
            complete_batch_index='all-event-source-inputs.json',
            creator='projection2d/prepare_pmi_candidate.py::prepare_source_inputs',
            real_batch_verifier='projection2d/bcat_native_adapter.py::verify',
            actual_event_id=None, actual_source_table_sha256=None, actual_context_sha256=None),
        placements=dict(device_file='Add entries inside Device Cell/File; retain original file fields',
            global_file='Add PMIPath inside global File; retain Output',
            physics='Add inside Device Cell/Physics; retain all original physical models',
            plot='Add names inside existing global Plot; retain original fields',
            initial_solve='Insert Optics before the original initialization Coupled statements',
            transient='Retain actual matched-A0 PWL/Solve and BE equations; no second temporal multiplier'),
        quantities=dict(APD='cm^-3 s^-1', QuantumYield='1', OpticalGeneration='cm^-3 s^-1',
            eDensity='cm^-3', hDensity='cm^-3', PMIUserField0='callback G2 diagnostic, cm^-3 s^-1',
            PMIUserField1='callback raw time, s', PMIUserField2='callback raw dt, s',
            PMIUserField3='callback raw enum, not inferred from a log time', PMIUserField4='callback eta, 1',
            PMIUserField5='callback Nref diagnostic, cm^-3 s^-1'),
        required_native_observations=['real build/load and actual command exit',
            'all Silicon APD actual dtype/unit/range/coverage',
            'actual BE callbacks, retries and Undef records with no clock substitution',
            'independent OpticalGeneration versus APD*QuantumYield and frozen projected G2',
            'original accepted clock and all written field frames',
            'electron and hole continuity equations plus independent eDensity/hDensity responses',
            'complete all-event source ledger; source/field/waveform/width checks against actual reference'],
        native_activation_verified=False, native_source_qualified=False, matched_A0_verified=False,
        science_qualified=False, training_admitted=False, pmi_r12_fixed=False)
    files = dict(zip(('original/' + n for n in INPUT_NAMES), (geometry_bytes, dimensional_bytes, timing_bytes)))
    files.update({'proton-reference-apd.plx': plx, 'proton-reference-spectrum.txt': spectrum,
        'activation-device-file.inc': device_file, 'activation-global-file.inc': global_file,
        'activation-physics.inc': physics, 'activation-plot.inc': plot,
        'activation-initial-solve.inc': solve, 'activation-contract.json': encoded(contract)})
    manifest = dict(schema=MANIFEST_SCHEMA, implementation_sha256=sha(Path(__file__).read_bytes()),
        files={name: dict(sha256=sha(raw), size_bytes=len(raw)) for name, raw in sorted(files.items())},
        native_execution_performed=False, solver_project_generated=False)
    files['candidate-input-manifest.json'] = encoded(manifest)
    return dict(files=files, contract=contract, manifest=manifest)


def verify(directory):
    """Rebuild all candidate bytes from the three original inputs; no native claim."""
    directory = Path(directory).resolve()
    require(directory.is_dir() and not directory.is_symlink(), 'candidate directory is missing or is a symlink')
    paths = list(directory.rglob('*'))
    require(not any(p.is_symlink() for p in paths), 'candidate contains a symlink')
    actual = {p.relative_to(directory).as_posix(): p.read_bytes() for p in paths if p.is_file()}
    expected = candidate_payload(*(actual['original/' + name] for name in INPUT_NAMES))
    require(set(actual) == set(expected['files']), 'candidate has missing or extra members')
    for name, raw in expected['files'].items():
        require(actual[name] == raw, 'candidate bytes differ: ' + name)
    return dict(contract=expected['contract'], manifest=expected['manifest'],
                verification='INPUT_BYTES_REBUILT_ONLY', native_source_qualified=False, pmi_r12_fixed=False)


def write_candidate(geometry, dimensional, timing, output):
    output = Path(output).resolve()
    try:
        relative = output.relative_to(EVIDENCE.resolve())
    except ValueError:
        raise ValueError('Candidate output must be new under the assigned activation evidence directory')
    require(relative.parts and not output.exists(), 'output must be a new candidate directory')
    inputs = [Path(p).read_bytes() for p in (geometry, dimensional, timing)]
    payload = candidate_payload(*inputs)
    output.mkdir(parents=True)
    for name, raw in payload['files'].items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
    return verify(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command')
    q = sub.add_parser('render')
    for name in ('geometry', 'dimensional', 'timing', 'output'):
        q.add_argument('--' + name, required=True, type=Path)
    q = sub.add_parser('verify'); q.add_argument('candidate', type=Path)
    args = parser.parse_args()
    try:
        require(args.command in ('render', 'verify'), 'choose render or verify')
        result = (write_candidate(args.geometry, args.dimensional, args.timing, args.output)
                  if args.command == 'render' else verify(args.candidate))
        print(encoded(dict(status='INPUT_CANDIDATE_ONLY',
            candidate_manifest_sha256=sha(encoded(result['manifest'])),
            native_source_qualified=False, pmi_r12_fixed=False)).decode('utf-8').strip())
        return 0
    except Exception as exc:
        print(encoded(dict(status='REFUSED', error=str(exc), native_source_qualified=False,
            pmi_r12_fixed=False)).decode('utf-8').strip())
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
