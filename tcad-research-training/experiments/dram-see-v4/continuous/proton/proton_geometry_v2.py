"""Bind the supplied D3 input geometry to a separate BCAT compile-time header."""
from __future__ import annotations
import json
import math
from pathlib import Path
import importlib.util

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_proton_geometry_v2_common',HERE/'proton_common_v2.py')
F=importlib.util.module_from_spec(spec);exec(compile((HERE/'proton_common_v2.py').read_bytes(),str(HERE/'proton_common_v2.py'),'exec'),F.__dict__)
require=F.require


def validate(model,geometry):
    g=geometry.get('geometry',geometry);mg=model['geometry'];md=model['doping']
    require(mg['gate_top_depth_nm'] in (70,80,90) and md['sn_junction_depth_nm'] in (82,87,92),
            'Unsupported controlled gate/SN input')
    expected_geometry=dict(trench_outer_width_nm=24,outer_rounding_radius_nm=12,rounding_center_z_nm=142,
        metal_rounding_radius_nm=8,metal_bottom_z_nm=150,oxide_outer_bottom_z_nm=154,active_width_nm=20,
        sti_each_side_width_nm=50,sti_depth_nm=200,gate_oxide_side_and_bottom_nm=4)
    require(all(mg.get(key)==value for key,value in expected_geometry.items()) and
            mg['silicon_domain_nm']==dict(x=[-1000,1000],y=[-250,250],z=[0,1000]),'Changed BCAT material geometry')
    require(md['peak_donor']==1.45e20 and md['uniform_acceptor']==1e17 and md['bl_junction_depth_nm']==137.5,
            'Unregistered doping model change')
    expected=F.G.describe_geometry(model,3)
    keys=('dimension','length_unit','coordinates','domain_um','outer_trench','gate_void','sti','nominal_oxide_um',
          'regions','measure_unit','measures','contacts','doping')
    require(all(g.get(key)==expected[key] for key in keys),'Supplied D3 physical geometry/doping differs from its original model')
    mask=F.R.SiliconMask(g)
    require(abs(mask.volume()-g['measures']['silicon'])<=1e-11,'Independent Si volume differs from supplied D3 geometry')
    return dict(gate_top_depth_nm=mg['gate_top_depth_nm'],sn_junction_depth_nm=md['sn_junction_depth_nm'],
        size_id={70:'S1',80:'S2',90:'S3'}[mg['gate_top_depth_nm']],active_width_nm=20,metal_deepest_nm=150,
        gate_transport_material='G4_Galactic',native_geometry_qualified=False,
        doping_transport_rule='Doping is bound for device identity; original G4 Si material has no doping-dependent transport model')


def material_probes(model):
    p=F.G._parameters(model)
    axes=[sorted(set([p['domain'][a][0]+fraction*(p['domain'][a][1]-p['domain'][a][0]) for fraction in (.173,.827)]+extra))
          for a,extra in zip('xyz',[[-.052,-.011,-.007,-.001,.001,.007,.011,.052],
                                    [-.055,-.013,-.009,.001,.009,.013,.055],
                                    [.001,p['gate_top']-.001,p['gate_top']+.001,.139,.143,.149,.151,.153,.199,.201]])]
    rows=[];native={'Silicon':'G4_Si','SiO2':'G4_SILICON_DIOXIDE','GateVoid':'G4_Galactic','Outside':'G4_Galactic'}
    for x in axes[0]:
        for y in axes[1]:
            for z in axes[2]:rows.append(' '.join(format(v,'.17g') for v in (x,y,z))+' '+native[F.G.material_at(model,x,y,z)]+'\n')
    return ''.join(rows).encode()


def construct(model_raw,device_geometry_raw,model_origin,geometry_origin,max_step_um=.002,cut_um=.001):
    require(all(math.isfinite(v) and v>0 for v in (max_step_um,cut_um)),'Positive finite physical step/cut required')
    model=F.parse(model_raw);device_geometry=F.parse(device_geometry_raw);semantic=validate(model,device_geometry)
    geometry=device_geometry.get('geometry',device_geometry);p=F.G._parameters(model)
    require(p['gate_top']<=p['center_z']-p['metal_radius'] and p['sti_depth']>=p['center_z']+p['radius'],
            'Original Boolean CSG assumptions do not hold')
    contract=dict(schema='continuous-bcat-proton-geometry-v2',version_id='v2-proton-bcat',geometry=geometry,
        model_source=str(model_origin),model_sha256=F.sha(model_raw),device_geometry_source=str(geometry_origin),
        device_geometry_sha256=F.sha(device_geometry_raw),device_parameters=semantic,
        geometry_code_sha256=F.FIXED['geometry'][1],adapter_sha256=F.sha(Path(__file__).read_bytes()),
        coordinate_transform='identity: TCAD x,y,z_depth in um = Geant4 x,y,z in um',
        gate_transport_material='G4_Galactic',gate_limitation='Ideal electrical gate boundary has no declared transport metal; no gate-metal scattering claim',
        material_densities_g_cm3={'G4_Si':2.33,'G4_SILICON_DIOXIDE':2.2},max_step_um=max_step_um,production_cut_um=cut_um,
        cpp_source_sha256=F.ORIGINAL_FILES['transport_bcat.cc'],parent_transport_sha256=F.FIXED['transport_parent'][1],
        native_geometry_qualified=False,numerical_status='Candidate; requires actual native geometry, range-cut and step sensitivity',
        input_geometry_status='Original supplied D3 input bytes; not a claim that its native mesh or DC passed')
    digest=F.sha(F.encoded(contract));arr=lambda values:'{{'+','.join(format(float(v),'.17g') for v in values)+'}}'
    header=['#pragma once','#include <array>','#include <string>','#include <vector>','namespace frozen {',
        'struct Request { std::array<double,3> surface,position,direction; bool hits=true; };',
        'struct Solid { const char* id; const char* material; double density; };',
        'const Solid solids[]={{"R.Silicon","G4_Si",2.33},{"R.Trench","G4_SILICON_DIOXIDE",2.2},{"R.STI.minus","G4_SILICON_DIOXIDE",2.2},{"R.STI.plus","G4_SILICON_DIOXIDE",2.2}};',
        'const char* geometry_id='+json.dumps(model['model_id'])+';',
        'const char* geometry_sha256="'+digest+'";','const char* contract_sha256="'+digest+'";',
        'const char* geometry_json=R"BCAT('+json.dumps(contract,ensure_ascii=True,separators=(',',':'))+')BCAT";']
    require(')BCAT"' not in json.dumps(contract),'Unsupported raw-string delimiter in bound provenance')
    for name,values in [('domain_lo',[p['domain'][a][0] for a in 'xyz']),('domain_hi',[p['domain'][a][1] for a in 'xyz']),
                        ('world_half_um',[max(abs(v) for v in p['domain'][a])+10 for a in 'xyz'])]:
        header.append('const std::array<double,3> '+name+'='+arr(values)+';')
    for name,value in dict(outer_radius=p['radius'],metal_radius=p['metal_radius'],outer_half_y=p['outer_y_half'],
        metal_half_y=p['metal_y_half'],active_half_y=p['active_half'],centre_z=p['center_z'],gate_top=p['gate_top'],
        sti_depth=p['sti_depth'],max_step_um=max_step_um,cut_um=cut_um).items():
        header.append('const double '+name+'='+format(value,'.17g')+';')
    header.append('}')
    return contract,('\n'.join(header)+'\n').encode(),material_probes(model)


def validate_files(folder):
    folder=Path(folder);actual=F.read(folder/'geometry-contract.json')
    require(actual.get('schema')=='continuous-bcat-proton-geometry-v2' and actual.get('version_id')=='v2-proton-bcat',
            'Original compiled input is not the multi-condition v2 contract')
    contract,header,probes=construct((folder/'model-input.json').read_bytes(),(folder/'device-geometry-contract.json').read_bytes(),
        actual['model_source'],actual['device_geometry_source'],actual['max_step_um'],actual['production_cut_um'])
    require(actual==contract and (folder/'geometry-contract.json').read_bytes()==F.encoded(contract)
            and (folder/'geometry.hh').read_bytes()==header and (folder/'geometry-probes.tsv').read_bytes()==probes,
            'Compiled source/header/probes do not reproduce from the bound D3 inputs')
    require(F.sha((folder/'transport_bcat.cc').read_bytes())==F.ORIGINAL_FILES['transport_bcat.cc'],
            'Native transport C++ differs from the original compiled protocol')
    return contract['device_parameters']
