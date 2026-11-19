"""Explicit local BTBT model branch after a real unavailable-feature failure.

No license modification, native call or result-based parameter fitting occurs.
Installed material cards and all non-BTBT physics remain byte-identical.
"""
import copy
import re

PATCH_ID = 'local-hurkx-uniform-field-mapping-r1'
ASSUMPTION_ID = 'dram-see-v4-physics-local-hurkx-r1'
FAILURE_RUN = '20261017T050348Z-v4-continuous-b1-d2-r7'
SELECTOR_OLD = 'Band2Band(Model=NonlocalPath)'
SELECTOR_NEW = 'Band2Band(Model=Hurkx DensityCorrection=None)'
NONLOCAL = dict(Apath=4e14, Bpath=1.9e7, Dpath=0, Ppath=.037, Rpath=0, MaxTunnelLength=1e-5)
PARAMETERS = dict(Agen=4e14, Bgen=1.9e7, Pgen=2.5, Arec=4e14, Brec=1.9e7, Prec=2.5,
                  alpha=0, dDist=0, dPot=0, MinField=0)
UNITS = dict(Agen='cm^-3 s^-1', Bgen='V/cm', Pgen='1', Arec='cm^-3 s^-1', Brec='V/cm',
             Prec='1', alpha='1', dDist='cm', dPot='V', MinField='V/cm')
LIMITATIONS = [
    'This is a declared local model branch, not a nonlocal-path equivalent or a calibrated reproduction.',
    'A/B and exponent map the 300 K uniform-field phonon-assisted reference only; Fermi statistics, bandgap narrowing and nonuniform fields preclude general equality.',
    'Local generation/recombination lacks path integration, spatially separated electron/hole endpoints and reflection at insulator interfaces.',
    'dDist=dPot=0 retains the installed local defaults; abrupt trench fields and GIDL may have model-form bias of unproven magnitude or sign.',
    'DC, retention, charge collection and upset results remain conditional on this model; subsequent matched model sensitivity is required.',
    'Legal native availability and syntax are unverified until the original SDevice run actually checks out the required features.',
]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def parameter_values(text):
    blocks = re.findall(r'\bBand2BandTunneling\s*\{([^{}]*)\}', text)
    require(len(blocks) == 1, 'Expected one explicit BTBT parameter block')
    lines = [line.split('#',1)[0].strip() for line in blocks[0].splitlines()]
    values = {}
    for line in lines:
        if not line or line.startswith('*'):
            continue
        match = re.fullmatch(r'([A-Za-z][A-Za-z0-9_]*)\s*=\s*([+\-0-9.eE]+)', line)
        require(match is not None and match[1] not in values, 'Unexpected/duplicate BTBT parameter')
        values[match[1]] = float(match[2])
    return values


def apply(device, parameters, manifest, model):
    require(device.count(SELECTOR_OLD) == 1 and SELECTOR_NEW not in device, 'Original BTBT selector differs')
    require(parameter_values(parameters) == NONLOCAL, 'Original explicit nonlocal parameters differ')
    require(manifest.get('release') == 'W-2024.09' and manifest.get('btbt_explicit_overrides') == NONLOCAL
            and manifest.get('btbt_postprocessing') is False and manifest.get('temperature_K') == 300,
            'Original physics card/reference differs')
    require(manifest['model_selectors'].count(SELECTOR_OLD) == 1, 'Physics selector manifest differs')
    changed_device = device.replace(SELECTOR_OLD, SELECTOR_NEW)
    lines = ['Band2BandTunneling {']
    for name in ('Agen','Bgen','Pgen','Arec','Brec','Prec','alpha','dDist','dPot','MinField'):
        lines.append('  {} = {:.17g} # [{}]'.format(name, PARAMETERS[name], UNITS[name]))
    lines.append(' }')
    changed_parameters = re.sub(r'\bBand2BandTunneling\s*\{[^{}]*\}', '\n'.join(lines), parameters, count=1)
    require(parameter_values(changed_parameters) == PARAMETERS, 'Local BTBT parameter mapping failed')
    changed_manifest = copy.deepcopy(manifest)
    changed_manifest.update(schema='dram-see-v4-physics-card-r2', assumption_id=ASSUMPTION_ID,
        model_selectors=manifest['model_selectors'].replace(SELECTOR_OLD, SELECTOR_NEW),
        btbt_model='Hurkx', btbt_density_correction='None', btbt_explicit_overrides=dict(PARAMETERS),
        btbt_parameter_units=dict(UNITS), btbt_postprocessing=False, execution_enabled=True,
        native_syntax_verified=False, native_license_verified=False, native_calibration=False,
        btbt_mapping='Agen=Arec=Apath, Bgen=Brec=Bpath, Pgen=Prec=2.5 for the original phonon-assisted uniform-field reference; alpha=0 keeps the equilibrium generation/recombination factor.',
        reference_nonlocal=dict(model='NonlocalPath', parameters=dict(NONLOCAL), failed_run_id=FAILURE_RUN,
            native_exit_code=255, missing_feature='sdevice-pathsearchtun', flexnet_error='-5,234',
            limitation='Original run reached model/license initialization, not numerical iteration.'),
        evidence=dict(installed_material_card='Silicon.par lines 2352-2425; SHA frozen in default_cards_sha256',
            same_release_manual='Sentaurus Device W-2024.09 pp553-558 and 561-562',
            coefficient_reason='Installed nonlocal Apath1/Bpath1 and documented phonon-assisted exponent, also the manual Hurkx example; no outcome fitting'),
        scientific_limitations=list(LIMITATIONS),
        required_matched_sensitivity=['Use the same geometry, mesh, biases, read/write timeline and source normalization across physics variants.',
            'Compare off-state/GIDL, equilibrium net generation, read/hold leakage and transient collected charge across declared local-model alternatives.',
            'Keep the final holdout outside any tuning; retain the unavailable NonlocalPath reference as a limitation, not a passed control.'])
    changed_model = copy.deepcopy(model)
    changed_model.update(schema='dram-see-v4-continuous-model-assumptions-r1',
                         status='CURRENT_DECLARED_ASSUMPTIONS_UNCALIBRATED', execution_enabled=True,
                         physics_assumption_id=ASSUMPTION_ID)
    changed_model.pop('native_budget_authorized', None)
    changed_model.pop('release_blockers', None)
    physics = changed_model['materials_and_physics']
    physics['selected_btbt'] = dict(model='Hurkx', density_correction='None', parameters=dict(PARAMETERS),
                                    units=dict(UNITS), assumption_id=ASSUMPTION_ID, self_consistent=True)
    physics['scientific_limitations'] = list(LIMITATIONS)
    physics['required_evidence'] = ['Frozen installed-version physics manifest and original successful solver exits',
                                    'DC and actual two-bit write/read checks under this same physics assumption',
                                    'Matched model-form sensitivity with final holdout excluded from tuning']
    return dict(device=changed_device, parameters=changed_parameters, manifest=changed_manifest, model=changed_model)
