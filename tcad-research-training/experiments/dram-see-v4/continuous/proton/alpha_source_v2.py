"""Prescribed Si-surface alpha source: original ASTAR, actual ray-box length.

See ALPHA-V2-ASSUMPTIONS.md, established before this implementation.
No native dispatch, source normalization fit, or energy/length LUT scaling.
"""
from __future__ import annotations
from bisect import bisect_left,bisect_right
import csv
import hashlib
import io
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
ASTAR=ROOT/'experiments/dram-see-v4/course-plan-r13/evidence/alpha-astar-silicon.csv'
ASTAR_SHA256='208f8e36d2f7d231fd6a1134ae3c3a68174b46c6b328dd0f647456a4aabc177b'
FC_PER_MEV=1e6/3.6*1.602176634e-19*1e15
RHO_FACTOR=2.33e-4
WIDTH=.05
SIGMA_PS=.2


def require(ok,message):
    if not ok:raise ValueError(message)


class Stopping:
    def __init__(self,raw=None):
        raw=ASTAR.read_bytes() if raw is None else raw
        require(hashlib.sha256(raw).hexdigest()==ASTAR_SHA256,'Original ASTAR input bytes changed')
        self.rows=[{key:float(value) for key,value in row.items()} for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))]
        self.energies=[row['energy_MeV'] for row in self.rows]
        require(len(self.rows)==121 and all(a<b for a,b in zip(self.energies,self.energies[1:]))
                and all(math.isfinite(value) for row in self.rows for value in row.values()),'Invalid original ASTAR table')

    def coefficients(self,energy):
        require(math.isfinite(energy) and self.energies[0]<energy<=self.energies[-1],
                'ASTAR range cannot support this remaining energy; no extrapolation')
        # Descending energy uses the bin immediately below an exact table knot.
        index=max(0,bisect_left(self.energies,energy)-1)
        lo,hi=self.rows[index:index+2];de=hi['energy_MeV']-lo['energy_MeV'];coeff=[]
        for name in ('electronic_MeV_cm2_g','nuclear_MeV_cm2_g'):
            a=(hi[name]-lo[name])/de;coeff.append((a,lo[name]-a*lo['energy_MeV']))
        return lo['energy_MeV'],coeff

    def stopping(self,energy):
        _,coeff=self.coefficients(energy)
        return tuple(a*energy+b for a,b in coeff)

    def integrate(self,energy,length):
        require(math.isfinite(length) and length>=0,'Invalid actual Si path length')
        initial=energy;remaining=length;electronic=[];nuclear=[];segments=[]
        while remaining>0:
            lower,((ae,be),(an,bn))=self.coefficients(energy);a,b=ae+an,be+bn
            stop=a*energy+b;stop_lower=a*lower+b
            require(stop>0 and stop_lower>0,'Nonpositive ASTAR stopping')
            distance=(math.log1p(a*(energy-lower)/stop_lower)/(RHO_FACTOR*a)
                      if a else (energy-lower)/(RHO_FACTOR*b))
            h=min(remaining,distance)
            require(h>0,'Energy-bin integration did not advance')
            next_energy=energy+stop*math.expm1(-RHO_FACTOR*a*h)/a if a else energy-RHO_FACTOR*b*h
            if h==distance:next_energy=lower
            loss=energy-next_energy
            if a:
                ee=ae/a*loss+RHO_FACTOR*(be-ae/a*b)*h
                en=an/a*loss+RHO_FACTOR*(bn-an/a*b)*h
            else:
                integrated_energy=energy*h-RHO_FACTOR*b*h*h/2
                ee=RHO_FACTOR*(ae*integrated_energy+be*h);en=RHO_FACTOR*(an*integrated_energy+bn*h)
            require(next_energy>=lower and loss>=0 and ee>=0 and en>=0,'Invalid physical CSDA energy step')
            electronic.append(ee);nuclear.append(en)
            segments.append(dict(length_um=h,entry_MeV=energy,exit_MeV=next_energy,electronic_MeV=ee,nuclear_MeV=en,
                                 interpolation_lower_energy_MeV=lower))
            remaining-=h;energy=next_energy
        ee=math.fsum(electronic);en=math.fsum(nuclear);residual=initial-energy-ee-en
        require(abs(residual)<=1e-11,'ASTAR electronic/nuclear energy ledger failed to close')
        return dict(entry_energy_MeV=initial,exit_energy_MeV=energy,electronic_deposition_MeV=ee,
                    nuclear_deposition_MeV=en,energy_balance_residual_MeV=residual,
                    electronic_line_charge_fC=ee*FC_PER_MEV,energy_intervals=segments)


def ray_box(origin,direction,box):
    require(len(origin)==len(direction)==3 and len(box)==6 and
            all(math.isfinite(v) for v in (*origin,*direction,*box)),'Invalid ray/box coordinates')
    require(abs(math.fsum(v*v for v in direction)-1)<=1e-14,'Ray direction must be a unit vector')
    entry=-math.inf;leave=math.inf
    for axis in range(3):
        lo,hi=box[axis],box[axis+3];require(lo<hi,'Invalid source domain')
        if direction[axis]==0:require(lo<=origin[axis]<=hi,'Parallel ray misses the finite box')
        else:
            a=(lo-origin[axis])/direction[axis];b=(hi-origin[axis])/direction[axis]
            entry=max(entry,min(a,b));leave=min(leave,max(a,b))
    entry=max(0.,entry);require(math.isfinite(leave) and leave>entry,'Forward ray has no finite material path')
    return dict(entry_parameter_um=entry,exit_parameter_um=leave,length_um=leave-entry,
        entry_um=[x+entry*d for x,d in zip(origin,direction)],exit_um=[x+leave*d for x,d in zip(origin,direction)])


def validate_inputs(model,geometry,request,reference):
    g=geometry.get('geometry',geometry);mg=model['geometry'];d=model['doping'];a=model['alpha']
    require(request==make_request(request['energy_MeV'],request['theta_deg']),
            'Source request differs from the explicit supported input contract')
    require(request['schema']=='continuous-alpha-source-request-v2' and request['energy_MeV'] in (3,5,7)
            and request['theta_deg'] in (0,30) and request['phi_deg']==180,'Unsupported prescribed alpha condition')
    require(mg['gate_top_depth_nm'] in (70,80,90) and d['sn_junction_depth_nm'] in (82,87,92),'Unsupported device condition')
    required_geometry=dict(trench_outer_width_nm=24,outer_rounding_radius_nm=12,rounding_center_z_nm=142,
        metal_rounding_radius_nm=8,metal_bottom_z_nm=150,oxide_outer_bottom_z_nm=154,active_width_nm=20,
        sti_each_side_width_nm=50,sti_depth_nm=200,gate_oxide_side_and_bottom_nm=4)
    require(all(mg.get(key)==value for key,value in required_geometry.items()),'Changed physical material geometry')
    require(mg['silicon_domain_nm']==dict(x=[-1000,1000],y=[-250,250],z=[0,1000]),'Unsupported source box')
    require(a['position_nm']==[-52,0,0] and a['time_center_ns']==15 and a['radial_Gaussian_w_nm']==50
            and a['temporal_sigma_ps']==.2 and a['eV_per_pair']==3.6,'Changed source regularization/origin')
    n=model['numerics']
    require(n['time_integrator']=='BE' and n['source_window_sigma']==8 and n['source_max_step_ps']==.04
            and n['source_refined_max_step_ps']==.02,'Changed prescribed source-window numerical controls')
    require(request['position_um']==[-.052,0.,0.] and request['epoch_s']==15e-9 and request['width_um']==WIDTH
            and request['sigma_ps']==SIGMA_PS,'Source request and fixed input kernel/origin differ')
    mask=reference.SiliconMask(geometry)
    require(mask.domain==[-1.,-.25,0.,1.,.25,1.] and mask.r==.012 and mask.center==.142 and mask.top==0.
            and abs(mask.hy-.06)<=1e-15 and mask.sti_z==[0.,.2] and len(mask.sti_y)==2
            and all(abs(x-y)<1e-15 for aa,bb in zip(mask.sti_y,[[-.06,-.01],[.01,.06]]) for x,y in zip(aa,bb)),
            'Actual input Si mask is unsupported')
    require(g['gate_void']['top_um']==mg['gate_top_depth_nm']/1000 and g['gate_void']['bottom_um']==.15,
            'Model and actual input gate coordinates differ')
    expected_asn=d['sn_junction_depth_nm']/1000/math.sqrt(math.log(d['peak_donor']/d['uniform_acceptor']))
    require(math.isclose(g['doping']['a_sn_um'],expected_asn,rel_tol=0,abs_tol=1e-14)
            and g['doping']['peak_cm3']==d['peak_donor'] and g['doping']['acceptor_cm3']==d['uniform_acceptor'],
            'Model and actual input SN-junction doping differ')
    require(abs(mask.volume()-g['measures']['silicon'])<=1e-11,'Declared Si volume differs from independent mask')
    theta=math.radians(request['theta_deg']);direction=[-math.sin(theta),0.,math.cos(theta)]
    path=ray_box(request['position_um'],direction,mask.domain)
    require(path['entry_parameter_um']==0. and max(path['entry_um'][0],path['exit_um'][0])<-mask.r
            and abs(path['entry_um'][1])<.01 and path['entry_um'][1]==path['exit_um'][1],
            'Centerline is not proven all-Si; non-Si energy loss requires a separate material model')
    path.update(direction=direction,transverse_u=[math.cos(theta),0.,math.sin(theta)],transverse_v=[0.,1.,0.],
                centerline_material='Silicon',material_proof='Entire x interval is left of outer trench; y=0 inside active; slab endpoints bound the finite box',
                material_proof_is_native_measurement=False,end_planes='Perpendicular to direction at s=0 and s=L')
    return path


def make_request(energy,theta):
    return dict(schema='continuous-alpha-source-request-v2',energy_MeV=energy,theta_deg=theta,phi_deg=180,
                position_um=[-.052,0.,0.],epoch_s=15e-9,width_um=WIDTH,sigma_ps=SIGMA_PS,
                source_amplitude=1.,data_design_registered=False,native_qualified=False)


def profile(stopping,energy,length,spacing=.01):
    require(math.isfinite(spacing) and 0<spacing<=.01,'Profile spacing is a numerical resolution, at most the original .01um')
    points=[i*spacing for i in range(math.floor(length/spacing)+1)]
    if points[-1]<length:points.append(length)
    rows=[]
    for s in points:
        state=stopping.integrate(energy,s);se,sn=stopping.stopping(state['exit_energy_MeV'])
        rows.append(dict(path_um=s,energy_MeV=state['exit_energy_MeV'],electronic_MeV_cm2_g=se,nuclear_MeV_cm2_g=sn,
            electronic_pC_um=se*RHO_FACTOR*FC_PER_MEV/1000,
            cumulative_electronic_fC=state['electronic_line_charge_fC'],
            cumulative_electronic_MeV=state['electronic_deposition_MeV'],cumulative_nuclear_MeV=state['nuclear_deposition_MeV']))
    ledger=stopping.integrate(energy,length)
    ledger['tabulated_line_charge_fC']=math.fsum((b['path_um']-a['path_um'])*(a['electronic_pC_um']+b['electronic_pC_um'])*500
                                                for a,b in zip(rows,rows[1:]))
    ledger['lut_charge_error_fC']=ledger['tabulated_line_charge_fC']-ledger['electronic_line_charge_fC']
    require(abs(ledger['lut_charge_error_fC'])<=max(1e-6,.001*ledger['electronic_line_charge_fC']),
            'Actual-path LUT exceeds original offline charge mapping criterion')
    return rows,ledger


def line_density(s,rows):
    if s<0 or s>rows[-1]['path_um']:return 0.
    index=min(len(rows)-2,max(0,bisect_right([row['path_um'] for row in rows],s)-1))
    a,b=rows[index:index+2];fraction=(s-a['path_um'])/(b['path_um']-a['path_um'])
    return 1000*(a['electronic_pC_um']+fraction*(b['electronic_pC_um']-a['electronic_pC_um']))


def profile_bytes(rows):
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
    writer.writeheader();writer.writerows(rows);return stream.getvalue().encode()


def render(rows,request,path):
    number=lambda value:format(value,'.17g')
    array=lambda values:'['+' '.join(number(value) for value in values)+']'
    vector=lambda values:'('+','.join(number(value) for value in values)+')'
    name='AlphaASTARv2'
    physics='HeavyIon("'+name+'") (\n StartPoint='+vector(path['entry_um'])+' Direction='+vector(path['direction'])+'\n'
    physics+=' Time='+number(request['epoch_s'])+'\n Length='+array(row['path_um'] for row in rows)+'\n'
    physics+=' LET_f='+array(row['electronic_pC_um'] for row in rows)+'\n Wt_hi='+array(WIDTH for _ in rows)+'\n Gaussian PicoCoulomb\n)\n'
    parameters=dict(a_1=0.,a_2=0.,a_3=0.,a_4=0.,k_hi=1.,c_1=0.,c_2=1.,c_3=0.,c_4=1.,s_hi=SIGMA_PS*1e-12)
    text='HeavyIon("'+name+'") {\n'+''.join(' '+key+' = '+number(value)+'\n' for key,value in parameters.items())+'}\n'
    return physics.encode(),text.encode()
