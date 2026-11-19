"""Immutable native-3D event ledger with explicit offline kernel and 2D rejection."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
Q_PER_MEV_FC = 1e6 / 3.6 * 1.602176634e-4
WIDTH_UM = .03
TIME_S_NS = .002
OFFSET_NS = 1.0
WINDOW_NS = (0.0,4.0)
NODES = {n:np.polynomial.legendre.leggauss(n) for n in (24,48)}

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def rows(p):
    with p.open(encoding='utf-8',newline='') as f:
        return list(csv.DictReader(f))

def require(cond, message):
    if not cond:
        raise ValueError(message)

def segment_interval(a,b,bounds):
    low,high = 0.0,1.0
    for i,(lo,hi) in enumerate(bounds):
        d = b[i]-a[i]
        if abs(d) < 1e-30:
            if a[i] < lo-1e-9 or a[i] > hi+1e-9:
                return 0.0,0.0
        else:
            u,v = (lo-a[i])/d,(hi-a[i])/d
            low,high = max(low,min(u,v)),min(high,max(u,v))
    return (low,high) if high>low else (0.0,0.0)

def cdf_interval(lo,hi,center,width):
    return max(0.0,min(1.0,.5*(math.erf((hi-center)/width)-math.erf((lo-center)/width))))

def kernel_fractions(a,b,t0,t1,bounds):
    """Return geometry, spatial, joint fractions + quadrature discrepancy."""
    lo,hi = segment_interval(a,b,bounds)
    if hi<=lo:
        return 0.0,0.0,0.0,0.0
    d = [b[i]-a[i] for i in range(3)]
    # Split around every narrow transition; large thick-target segments cannot
    # hide the narrow boundary Gaussian between quadrature nodes.
    cuts = {lo,hi}
    for i in range(3):
        if d[i]:
            for boundary in bounds[i]:
                for k in (-8,-4,0,4,8):
                    u=(boundary+k*WIDTH_UM-a[i])/d[i]
                    if lo<u<hi: cuts.add(u)
    if t1!=t0:
        for boundary in WINDOW_NS:
            for k in (-8,-4,0,4,8):
                u=(boundary+k*2*TIME_S_NS-t0)/(t1-t0)
                if lo<u<hi: cuts.add(u)
    cuts=sorted(cuts)
    def integrate(n):
        nodes,weights=NODES[n]
        total=np.zeros(2)
        for l,h in zip(cuts,cuts[1:]):
            for node,weight in zip(nodes,weights):
                u=(l+h)/2+(h-l)*float(node)/2
                space=math.prod(cdf_interval(bounds[i][0],bounds[i][1],a[i]+u*d[i],WIDTH_UM) for i in range(3))
                center=t0+u*(t1-t0)
                normalization=.5*(1+math.erf(center/(2*TIME_S_NS)))
                require(normalization>0,'Non-normalizable nonnegative-time kernel')
                time=cdf_interval(*WINDOW_NS,center,2*TIME_S_NS)/normalization
                total += float(weight)*(h-l)/2*np.array([space,space*time])
        return total
    coarse,fine=integrate(24),integrate(48)
    return hi-lo,float(fine[0]),float(fine[1]),float(max(abs(fine-coarse)))

def step_entry(raw,run_id,bounds):
    a=[float(raw['pre_'+k+'_um']) for k in 'xyz']
    b=[float(raw['post_'+k+'_um']) for k in 'xyz']
    length=float(raw['step_um']); chord=math.dist(a,b)
    energy=float(raw['ionizing_MeV']); total=float(raw['edep_MeV']); niel=float(raw['niel_MeV'])
    require(all(math.isfinite(x) for x in a+b+[length,chord,energy,total,niel]),'Nonfinite step')
    require(length>=0 and energy>=0 and niel>=0 and total>=0,'Negative source quantity')
    require(math.isclose(energy,max(0,total-niel),abs_tol=1e-12,rel_tol=1e-9),'Eion components do not close')
    is_si=raw['pre_material']=='G4_Si'
    q=energy*Q_PER_MEV_FC if is_si else 0.0
    t0=float(raw['pre_t_ns'])+OFFSET_NS; t1=float(raw['post_t_ns'])+OFFSET_NS
    require(t1>=t0-1e-9,'Time reversed')
    account=dict(domain_out_fC=0.0,kernel_out_fC=0.0,window_out_fC=0.0,
                 candidate_in_fC=0.0,pending_point_kernel_fC=0.0)
    kind='zero_deposition' if energy==0 else ('point_deposition' if length==0 or chord==0 else 'finite_chord')
    err=0.0
    if q>0 and kind=='point_deposition':
        account['pending_point_kernel_fC']=q
    elif q>0:
        geometric,spatial,joint,err=kernel_fractions(a,b,t0,t1,bounds)
        require(-1e-12<=joint<=spatial+1e-12 and spatial<=geometric+1e-12 and geometric<=1+1e-12,'Kernel ordering failed')
        spatial=min(geometric,max(0,spatial)); joint=min(spatial,max(0,joint))
        account.update(domain_out_fC=q*(1-geometric),kernel_out_fC=q*(geometric-spatial),
                       window_out_fC=q*(spatial-joint),candidate_in_fC=q*joint)
    return dict(source_id=f"{run_id}:e{raw['event_id']}:t{raw['track_id']}:s{raw['step_id']}",
        run_id=run_id,event_id=int(raw['event_id']),track_id=int(raw['track_id']),parent_id=int(raw['parent_id']),step_id=int(raw['step_id']),
        particle=raw['particle'],pdg=int(raw['pdg']),pre_xyz_um=a,post_xyz_um=b,
        pre_t_ns=float(raw['pre_t_ns']),post_t_ns=float(raw['post_t_ns']),
        kernel_time_offset_ns=OFFSET_NS,pre_material=raw['pre_material'],post_material=raw['post_material'],
        pre_volume=raw['pre_volume'],post_volume=raw['post_volume'],
        actual_step_um=length,chord_um=chord,deposit_kind=kind,
        edep_MeV=total,niel_MeV=niel,ionizing_MeV=energy,
        local_ionizing_deposition_density_MeV_per_um=energy/length if length>0 else None,
        density_is_standard_LET=False,assigned_silicon_charge_fC=q,account=account,
        quadrature_difference_fC=err*q,tcad_eligible=False,
        tcad_block_reason='native_3d_requires_validated_3d_device_or_explicit_reduction_contract')

def reject_2d(manifest):
    require(manifest.get('dimensionality')!='native_3d','Undefined 3D to 2D reduction; all xyz preserved')
    raise ValueError('This exporter has no TCAD deck capability')

def build(run,event_id,destination):
    run=Path(run).resolve(); destination=Path(destination).resolve()
    require(run.is_relative_to((ROOT/'local_runtime/dram-see-v4').resolve()),'Not a v4 raw run')
    require(destination.is_relative_to((ROOT/'local_runtime/dram-see-v4').resolve()),'Output outside v4 runtime')
    require(not destination.exists(),'Output exists; immutable ledger')
    receipt=read(run/'record.json'); req=receipt['request']
    require(all(receipt.get(k)==0 for k in ('runner_exit_code','remote_exit_code','collection_exit_code')),'Unknown/failed raw exits')
    audit_path=ROOT/'local_runtime/dram-see-v4/transport-probe/audits'/run.name/'audit.json'
    audit=read(audit_path)
    require(audit.get('passed') is True,'Transport audit has not passed')
    for rel,expected in receipt['output_sha256'].items():
        require(sha(run/rel)==expected,'Raw receipt mismatch: '+rel)
    contract_name='witness-contract.json' if req['mode']=='witness' else 'probe-contract.json'
    contract=read(run/contract_name)
    bounds=contract['geometry']['silicon_bounds_um']
    selected=[r for r in rows(run/'steps.csv') if int(r['event_id'])==event_id]
    events=[r for r in rows(run/'events.csv') if int(r['event_id'])==event_id]
    tracks=[r for r in rows(run/'tracks.csv') if int(r['event_id'])==event_id]
    require(len(events)==1 and events[0]['event_complete']=='1','Missing or incomplete primary')
    require(len(selected)==int(events[0]['step_count']),'Missing step')
    require(len(tracks)==int(events[0]['track_count']),'Missing track')
    entries=[step_entry(r,run.name,bounds) for r in selected]
    require(len({r['source_id'] for r in entries})==len(entries),'Duplicate deposition allocation')
    q=sum(r['assigned_silicon_charge_fC'] for r in entries)
    energy=sum(r['ionizing_MeV'] for r in entries if r['pre_material']=='G4_Si')
    require(math.isclose(energy,float(events[0]['ionizing_si_MeV']),rel_tol=1e-9,abs_tol=1e-12),'Event energy does not close')
    keys=('domain_out_fC','kernel_out_fC','window_out_fC','candidate_in_fC','pending_point_kernel_fC')
    account={k:sum(r['account'][k] for r in entries) for k in keys}
    tolerance=max(1e-6,.001*q)
    error=abs(q-sum(account.values()))
    quadrature=sum(r['quadrature_difference_fC'] for r in entries)
    require(error<=tolerance and quadrature<=tolerance,'Ledger closure or quadrature failed')
    manifest=dict(schema='dram-see-v4-native-source-manifest-r1',dimensionality='native_3d',
        run_id=run.name,event_id=event_id,geometry_id=req['geometry_id'],
        geometry=contract['geometry'],coordinate_transform={'matrix':[[1,0,0],[0,1,0],[0,0,1]],'translation_um':[0,0,0],'scale':1},
        raw_reference={'path':run.relative_to(ROOT).as_posix(),'receipt_sha256':sha(run/'record.json'),
                       'audit_path':audit_path.relative_to(ROOT).as_posix(),'audit_sha256':sha(audit_path),
                       'files':{n:sha(run/n) for n in ('events.csv','tracks.csv','steps.csv',contract_name)}},
        contract_notes_sha256=sha(HERE/'README.md'),exporter_sha256=sha(Path(__file__)),
        kernel={'scope':'offline diagnostic only; not validated 3D TCAD', 'space':'isotropic_3d_gaussian_convolved_finite_chord',
                'width_um':WIDTH_UM,'time_s_ns':TIME_S_NS,'time_offset_ns':OFFSET_NS,'window_ns':WINDOW_NS,
                'pair_energy_eV':3.6,'elementary_charge_C':1.602176634e-19,'point_kernel':'unvalidated; pending'},
        totals={'step_count':len(entries),'track_count':len(tracks),'silicon_ionizing_MeV':energy,
                'non_silicon_ionizing_MeV':sum(r['ionizing_MeV'] for r in entries if r['pre_material']!='G4_Si'),
                'assigned_silicon_charge_fC':q,**account,'closure_error_fC':error,
                'quadrature_difference_fC':quadrature,'tolerance_fC':tolerance},
        offline_accounting_passed=True,tcad_ready=False,flip_label=None,sources=entries)
    try: reject_2d(manifest)
    except ValueError as exc: manifest['two_dimensional_entry_rejection']=str(exc)
    else: raise AssertionError('Native 3D erroneously accepted')
    destination.mkdir(parents=True,exist_ok=False)
    (destination/'source_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
    with (destination/'charge-ledger.csv').open('x',encoding='utf-8',newline='') as f:
        fields=['source_id','particle','deposit_kind','actual_step_um','chord_um','ionizing_MeV','assigned_silicon_charge_fC',*keys,'quadrature_difference_fC']
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader()
        for entry in entries: writer.writerow({k:entry['account'][k] if k in keys else entry[k] for k in fields})
    (destination/'tracks.json').write_text(json.dumps(tracks,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'run':run.name,'event':event_id,'path':str(destination),'totals':manifest['totals'],'tcad_ready':False}))
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('run',type=Path); p.add_argument('event_id',type=int); p.add_argument('destination',type=Path)
    a=p.parse_args(); build(a.run,a.event_id,a.destination)
