"""Real Geant4 Si deposits -> original source table + native HeavyIon candidate.

This is an explicit alternative source representation, not a PMI/R12 repair.
No native dispatch, expected clock injection, fitted charge or postprocess source.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
from pathlib import Path
import prepare

E_CHARGE=1.602176634e-19
WIDTH=.03
SIGMA=2e-12
EV_PAIR=3.6


def erf_difference(lo,hi):
    if lo>=0:return math.erfc(lo)-math.erfc(hi)
    if hi<=0:return math.erfc(-hi)-math.erfc(-lo)
    return math.erf(hi)-math.erf(lo)


def profile(s,length,width):
    """Longitudinal density, um^-1; full 3D isotropic Gaussian convolution."""
    if length==0:return math.exp(-(s/width)**2)/(math.sqrt(math.pi)*width)
    # Integrating along segment fraction gives the analytic erf profile.
    # Tiny segments use their point limit to avoid cancellation.
    if length<width*1e-7:
        return math.exp(-((s-length/2)/width)**2)/(math.sqrt(math.pi)*width)
    return erf_difference((s-length)/width,s/width)/(2*length)


def make_fragment(p0,p1,t0,t1,q_fC,index,spacing_fraction,time_slices):
    vector=[b-a for a,b in zip(p0,p1)];length=math.sqrt(sum(x*x for x in vector))
    direction=[x/length for x in vector] if length else [0.,0.,1.]
    margin=8*WIDTH
    # Uniform nodes preserve the Gaussian-convolution quadrature accurately.
    # Combining two differently phased endcap grids introduces trapezoid bias.
    intervals=math.ceil((length+2*margin)/(spacing_fraction*WIDTH))
    coords=[-margin+(length+2*margin)*i/intervals for i in range(intervals+1)]
    rates=[q_fC/1000*profile(s,length,WIDTH) for s in coords]
    integral=sum((b-a)*(u+v)/2 for a,b,u,v in zip(coords,coords[1:],rates,rates[1:]))*1000
    return dict(name='G4Deposit'+str(index),start_um=[a-margin*d for a,d in zip(p0,direction)],
        direction=direction,path_um=[x+margin for x in coords],let_pC_um=rates,
        temporal_center_s=(t0+t1)/2,width_um=WIDTH,sigma_s=SIGMA,
        source_charge_fC=q_fC,tabulated_all_space_charge_fC=integral,
        segment_length_um=length,source_time_span_s=t1-t0,time_subdivisions=time_slices,
        original_p0_um=p0,original_p1_um=p1)


def represent(source_rows,spacing_fraction=1/12,time_fraction=1/8):
    if not all(math.isfinite(x) and 0<x<=1 for x in (spacing_fraction,time_fraction)):
        raise ValueError('Resolution fractions must be positive and at most one kernel width')
    fragments=[]
    for row in source_rows:
        if len(row)!=11 or not all(math.isfinite(x) for x in row):raise ValueError('Invalid source record')
        p0,p1,t0,t1,q=row[:3],row[3:6],row[6],row[7],row[8]
        if q<=0 or t0<8*SIGMA or t1<t0 or row[9:]!=[WIDTH,SIGMA]:raise ValueError('Unsupported source units/kernel/time')
        n=max(1,math.ceil((t1-t0)/(SIGMA*time_fraction)))
        for i in range(n):
            lo=i/n;hi=(i+1)/n
            a=[x+lo*(y-x) for x,y in zip(p0,p1)];b=[x+hi*(y-x) for x,y in zip(p0,p1)]
            fragments.append(make_fragment(a,b,t0+lo*(t1-t0),t0+hi*(t1-t0),q/n,
                                          len(fragments),spacing_fraction,n))
    return fragments


def render(fragments):
    number=lambda x:format(x,'.17g')
    arr=lambda values:'['+' '.join(map(number,values))+']'
    vec=lambda values:'('+','.join(map(number,values))+')'
    physics=[];parameters=[]
    for f in fragments:
        physics.append('HeavyIon("'+f['name']+'") (\n StartPoint='+vec(f['start_um'])+
            ' Direction='+vec(f['direction'])+'\n Time='+number(f['temporal_center_s'])+
            '\n Length='+arr(f['path_um'])+'\n LET_f='+arr(f['let_pC_um'])+
            '\n Wt_hi='+arr([WIDTH]*len(f['path_um']))+'\n Gaussian PicoCoulomb\n)\n')
        coeff=dict(a_1=0.,a_2=0.,a_3=0.,a_4=0.,k_hi=1.,c_1=0.,c_2=1.,c_3=0.,c_4=1.,s_hi=SIGMA)
        parameters.append('HeavyIon("'+f['name']+'") {\n'+''.join(' '+k+' = '+number(v)+'\n' for k,v in coeff.items())+'}\n')
    return ''.join(physics),''.join(parameters)


def source_rows_from_steps(rows,event_id,epoch_s):
    sources=[];ledger={};selected=[];identities=set()
    for row in rows:
        if int(row['event_id'])!=event_id:continue
        identity=tuple(int(row[k]) for k in ('event_id','track_id','step_id'))
        if identity in identities:raise ValueError('Duplicate native Geant4 step')
        identities.add(identity)
        edep,niel,ion=(float(row[k]) for k in ('edep_MeV','niel_MeV','ionizing_MeV'))
        if not all(math.isfinite(x) and x>=0 for x in (edep,niel,ion)):raise ValueError('Invalid native deposited energy')
        if not math.isclose(edep-niel,ion,rel_tol=1e-8,abs_tol=1e-12):raise ValueError('Native ionizing != edep-NIEL')
        material=row['pre_material'];ledger[material]=ledger.get(material,0)+ion
        if material!='G4_Si' or ion==0:continue
        start=[float(row['pre_'+a+'_um']) for a in 'xyz'];end=[float(row['post_'+a+'_um']) for a in 'xyz']
        t0=epoch_s+float(row['pre_t_ns'])*1e-9;t1=epoch_s+float(row['post_t_ns'])*1e-9
        q=ion*1e6/EV_PAIR*E_CHARGE*1e15
        source=start+end+[t0,t1,q,WIDTH,SIGMA]
        if not all(math.isfinite(x) for x in source) or t0<0 or t1<t0:raise ValueError('Invalid native source coordinates/times')
        sources.append(source);selected.append(dict(identity=identity,ionizing_MeV=ion,charge_fC=q,
            particle=row['particle'],parent_id=int(row['parent_id']),deposit_kind=row['deposit_kind']))
    return sorted(sources),dict(all_material_ionizing_MeV=ledger,selected_si_steps=selected,
        total_si_charge_fC=sum(x[8] for x in sources),all_event_steps=len(identities),
        rule='All positive Si ionizing deposits; zero-length deposits preserved; no event/particle filtering')


def package_payload(operation,event_id,epoch_s=15e-9,spacing_fraction=1/12,time_fraction=1/8):
    """Construct the existing source files without writing an intermediate package."""
    operation,receipt=prepare.complete_operation(operation,('transport-exit-code.txt','status.json','metadata.json','events.csv','steps.csv','geometry-probes-native.csv'))
    folder=operation/'collected'
    if int((folder/'transport-exit-code.txt').read_text())!=0:raise ValueError('Transport did not exit successfully')
    status=json.loads((folder/'status.json').read_text(encoding='utf-8'))
    if status['state']!='COMPLETED':raise ValueError('Native transport is incomplete')
    metadata=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
    if metadata['primary_particle']!='proton':raise ValueError('Only proton primaries are in scope')
    with (folder/'geometry-probes-native.csv').open(newline='',encoding='utf-8') as stream:
        probes=list(csv.DictReader(stream))
    if not probes or any(row['passed']!='1' or row['expected_material']!=row['native_material'] for row in probes):
        raise ValueError('Native BCAT material probes not passed')
    with (folder/'events.csv').open(newline='',encoding='utf-8') as stream:
        events=[row for row in csv.DictReader(stream) if int(row['event_id'])==event_id]
    if len(events)!=1 or events[0]['event_complete']!='1':raise ValueError('Missing complete original event')
    with (folder/'steps.csv').open(newline='',encoding='utf-8') as stream:
        sources,ledger=source_rows_from_steps(csv.DictReader(stream),event_id,epoch_s)
    expected=float(events[0]['ionizing_si_MeV'])
    if not math.isclose(ledger['all_material_ionizing_MeV'].get('G4_Si',0),expected,rel_tol=1e-8,abs_tol=1e-12):
        raise ValueError('Step/event silicon ionizing energy mismatch')
    fragments=represent(sources,spacing_fraction,time_fraction)
    physics,parameters=render(fragments)
    contract=dict(schema='continuous-proton-heavyion-candidate-v1',native_qualified=False,pmi_r12_fixed=False,
        operation_path=str(operation),operation_sha256=prepare.sha(operation/'operation.json'),
        original_archive_sha256=receipt['archive_sha256'],source_steps_sha256=prepare.sha(folder/'steps.csv'),
        source_events_sha256=prepare.sha(folder/'events.csv'),event_id=event_id,metadata=metadata,
        epoch_s=epoch_s,source_units='um,s,fC; G cm^-3 s^-1',eV_per_pair=EV_PAIR,
        source_time_bounds_s=[min(r[6] for r in sources),max(r[7] for r in sources)] if sources else None,
        required_source_window_s=[min(r[6] for r in sources)-8*SIGMA,max(r[7] for r in sources)+8*SIGMA] if sources else None,
        kernel=dict(width_um=WIDTH,temporal_sigma_s=SIGMA,source='original isotropic Gaussian line-convolution'),
        approximation=dict(longitudinal_truncation_widths=8,let_node_width_fraction=spacing_fraction,
                           max_segment_time_sigma_fraction=time_fraction,no_charge_renormalization=True,
                           per_deposit_time_center='midpoint of actual Geant4 time subinterval'),
        ledger=ledger,fragment_count=len(fragments),
        tabulated_all_space_charge_fC=sum(f['tabulated_all_space_charge_fC'] for f in fragments),
        native_required=['actual native HeavyIonGeneration field and full source-window accepted BE intervals',
                         'independent Si-mask charge integral and source centroid/waveform',
                         'matched zero-source control and both carrier equations',
                         'LET spacing/time subdivision, TCAD mesh/timestep and Geant4 cuts/steps convergence'],
        distinction='Native HeavyIon clock/field must be measured; no PMI raw clock is invented; not R12 qualification')
    table='NUCLEAR_CLOSURE_SOURCE_V1 '+str(len(sources))+'\n'+''.join(' '.join(format(v,'.17g') for v in row)+'\n' for row in sources)
    files={'sources.dat':table.encode(),'heavyion.physics.inc':physics.encode(),'source.par':parameters.encode(),
           'source-contract.json':prepare.encoded(contract),'fragments.json':prepare.encoded(fragments),
           'heavyion.plot.inc':b'HeavyIonGeneration HeavyIonChargeDensity\n',
           'heavyion.currentplot.inc':b'CurrentPlot { HeavyIonGeneration(Integrate(Semiconductor)) }\n'}
    return files


def build(operation,event_id,output,epoch_s=15e-9,spacing_fraction=1/12,time_fraction=1/8):
    files=package_payload(operation,event_id,epoch_s,spacing_fraction,time_fraction)
    return prepare.write_package(output,files,'geant4_to_heavyion_candidate')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--operation',type=Path,required=True);p.add_argument('--event-id',type=int,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--epoch-s',type=float,default=15e-9)
    p.add_argument('--spacing-fraction',type=float,default=1/12);p.add_argument('--time-fraction',type=float,default=1/8)
    print(build(**vars(p.parse_args())))
