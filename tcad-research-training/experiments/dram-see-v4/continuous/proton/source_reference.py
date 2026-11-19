"""Independent finite-Si reference for the exact original proton source kernel.

No import of couple.py/LET tables, no native dispatch, no native qualification.
Coordinates: um; charge: fC; time: s; native G: cm^-3 s^-1.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
RUNTIME=ROOT/'local_runtime/dram-see-v4/continuous/proton'
E_C=1.602176634e-19
NATIVE_TO_FC=1e-12*E_C*1e15
ABS_TOL=1e-11
REL_TOL=1e-8


def require(condition,message):
    if not condition:raise ValueError(message)


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite JSON: '+x)))


def write_new(path,value):
    path=Path(path).resolve()
    require(path.is_relative_to(RUNTIME.resolve()),'Reference output must stay in continuous/proton runtime')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')


def erf_delta(a,b):
    if a>=0:return math.erfc(a)-math.erfc(b)
    if b<=0:return math.erfc(-b)-math.erfc(-a)
    return math.erf(b)-math.erf(a)


def gaussian_interval(a,b,center,width):
    """Mass and first moment of exp(-(x-c)^2/w^2)/(sqrt(pi)*w)."""
    if b<=a:return 0.,0.
    aa,bb=(a-center)/width,(b-center)/width
    mass=.5*erf_delta(aa,bb)
    moment=center*mass+width/(2*math.sqrt(math.pi))*(math.exp(-aa*aa)-math.exp(-bb*bb))
    return mass,moment


def temporal_interval(a,b,center,sigma):
    """Unrenormalized Gaussian time mass and time moment, including tails."""
    return gaussian_interval(a,b,center,math.sqrt(2)*sigma)


def integrate_vector(fn,a,b,abs_tol=ABS_TOL,rel_tol=REL_TOL):
    if b<=a:return [0.]*len(fn(a))
    def simpson(lo,hi,left,mid,right):
        return [(hi-lo)*(x+4*y+z)/6 for x,y,z in zip(left,mid,right)]
    fa,fm,fb=fn(a),fn((a+b)/2),fn(b)
    def refine(lo,hi,left,mid,right,whole,tol,depth):
        center=(lo+hi)/2
        ll,rr=fn((lo+center)/2),fn((center+hi)/2)
        low=simpson(lo,center,left,ll,mid);high=simpson(center,hi,mid,rr,right)
        fine=[x+y for x,y in zip(low,high)]
        errors=[abs(x-y)/15 for x,y in zip(fine,whole)]
        if all(err<=tol+rel_tol*abs(value) for err,value in zip(errors,fine)):
            # Keep positive-weight Simpson sum; no Richardson-induced negative mass.
            return fine
        require(depth<26 and lo<center<hi,'Independent quadrature failed to resolve integrand')
        low=refine(lo,center,left,ll,mid,low,tol/2,depth+1)
        high=refine(center,hi,mid,rr,right,high,tol/2,depth+1)
        return [x+y for x,y in zip(low,high)]
    return refine(a,b,fa,fm,fb,simpson(a,b,fa,fm,fb),abs_tol,0)


def add_vectors(rows,count):
    return [math.fsum(row[i] for row in rows) for i in range(count)]


class SiliconMask:
    """Independent rectangle/circular-cap integration from the bound contract.

    The gate cavity is inside the outer oxide trench, so it is excluded from Si
    by the same material mask. It is never accidentally counted as silicon.
    """
    def __init__(self,contract,abs_tol=ABS_TOL,rel_tol=REL_TOL):
        g=contract['geometry'] if 'geometry' in contract else contract
        require(g['dimension']==3 and g['length_unit']=='um','3D geometry in um required')
        self.g=g;self.abs_tol=abs_tol;self.rel_tol=rel_tol
        d=g['domain_um'];self.domain=[d[a][0] for a in 'xyz']+[d[a][1] for a in 'xyz']
        require(all(math.isfinite(x) for x in self.domain) and all(self.domain[i]<self.domain[i+3] for i in range(3)), 'Invalid domain')
        tr=g['outer_trench'];self.r=float(tr['radius_um']);self.center=float(tr['round_center_z_um'])
        self.top=float(tr['top_um']);self.bottom=self.center+self.r;self.hy=float(tr['y_half_width_um'])
        require(tr['construction']=='rectangle/cuboid union circle/cylinder' and
                math.isclose(tr['x_half_width_um'],self.r,abs_tol=1e-15) and self.r>0,
                'Unsupported trench geometry')
        st=g['sti'];require(st['included'] is True and st['x_um']==d['x'],'STI must span the contracted x-domain')
        self.sti_z=list(map(float,st['z_um']));self.sti_y=[list(map(float,p)) for p in st['y_intervals_um']]
        gate=g['gate_void']
        require(0<gate['radius_um']<=self.r and 0<gate['y_half_width_um']<=self.hy and
                gate['round_center_z_um']==self.center and gate['top_um']>=self.top,
                'Gate cavity must remain a subset of the outer trench')
        self.cache={}

    def clip(self,roi):
        require(len(roi)==6 and all(math.isfinite(x) for x in roi) and
                all(roi[i]<roi[i+3] for i in range(3)),'Invalid ROI box in um')
        return [max(roi[i],self.domain[i]) for i in range(3)]+[min(roi[i+3],self.domain[i+3]) for i in range(3)]

    def halfwidth(self,z):
        if self.top<=z<=self.center:return self.r
        if self.center<z<self.bottom:return math.sqrt(max(0.,self.r*self.r-(z-self.center)**2))
        return 0.

    def contains(self,x,y,z):
        if not all(self.domain[i]<=v<=self.domain[i+3] for i,v in enumerate((x,y,z))):return False
        if self.sti_z[0]<z<self.sti_z[1] and any(a<y<b for a,b in self.sti_y):return False
        cut=self.halfwidth(z)
        return not (cut>0 and abs(y)<=self.hy and abs(x)<=cut)

    def rectangles(self,z,box):
        cuts={box[1],box[4]}
        for v in (-self.hy,self.hy,*[x for pair in self.sti_y for x in pair]):
            if box[1]<v<box[4]:cuts.add(v)
        ys=sorted(cuts);result=[];cut=self.halfwidth(z)
        for y0,y1 in zip(ys,ys[1:]):
            ym=(y0+y1)/2
            if self.sti_z[0]<z<self.sti_z[1] and any(a<ym<b for a,b in self.sti_y):continue
            xs=[(box[0],box[3])]
            if cut>0 and abs(ym)<self.hy:xs=[(box[0],min(box[3],-cut)),(max(box[0],cut),box[3])]
            result.extend((x0,x1,y0,y1) for x0,x1 in xs if x1>x0)
        return result

    def slice(self,z,box,center,width):
        result=[]
        for x0,x1,y0,y1 in self.rectangles(z,box):
            fx,mx=gaussian_interval(x0,x1,center[0],width)
            fy,my=gaussian_interval(y0,y1,center[1],width)
            result.append([fx*fy,mx*fy,fx*my,(x1-x0)*(y1-y0)])
        return add_vectors(result,4)

    def spatial(self,center,width,roi=None):
        roi=self.domain if roi is None else roi
        key=(tuple(center),width,tuple(roi))
        if key in self.cache:return self.cache[key]
        require(width>0 and math.isfinite(width) and all(math.isfinite(x) for x in center),'Invalid Gaussian center/width')
        box=self.clip(roi)
        if any(box[i]>=box[i+3] for i in range(3)):return [0.]*4
        breaks=sorted({box[2],box[5],*[z for z in (self.top,self.center,self.bottom,*self.sti_z) if box[2]<z<box[5]]})
        answers=[]
        for lo,hi in zip(breaks,breaks[1:]):
            if lo>=self.center and hi<=self.bottom:
                # z=c+r*sin(theta) removes the cap's square-root endpoint.
                ta=math.asin(max(0.,min(1.,(lo-self.center)/self.r)))
                tb=math.asin(max(0.,min(1.,(hi-self.center)/self.r)))
                points={ta,tb}
                for multiple in (-12,-8,-4,-2,-1,0,1,2,4,8,12):
                    z=center[2]+multiple*width
                    if lo<z<hi:points.add(math.asin((z-self.center)/self.r))
                points=sorted(points)
                def angular(theta):
                    z=self.center+self.r*math.sin(theta)
                    z=min(math.nextafter(hi,lo),max(math.nextafter(lo,hi),z))
                    f,mx,my,_=self.slice(z,box,center,width)
                    factor=math.exp(-((z-center[2])/width)**2)/(math.sqrt(math.pi)*width)*self.r*math.cos(theta)
                    return [f*factor,mx*factor,my*factor,z*f*factor]
                answers.extend(integrate_vector(angular,a,b,self.abs_tol/len(points),self.rel_tol)
                               for a,b in zip(points,points[1:]))
            else:
                f,mx,my,_=self.slice((lo+hi)/2,box,center,width)
                fz,mz=gaussian_interval(lo,hi,center[2],width)
                answers.append([f*fz,mx*fz,my*fz,f*mz])
        result=add_vectors(answers,4)
        require(result[0]>=0 and result[0]<=1+1e-10,'Gaussian mask integral outside [0,1]')
        self.cache[key]=result
        return result

    def volume(self,roi=None):
        box=self.clip(self.domain if roi is None else roi)
        if any(box[i]>=box[i+3] for i in range(3)):return 0.
        breaks=sorted({box[2],box[5],*[z for z in (self.top,self.center,self.bottom,*self.sti_z) if box[2]<z<box[5]]})
        values=[]
        for lo,hi in zip(breaks,breaks[1:]):
            area=lambda z:math.fsum((b-a)*(d-c) for a,b,c,d in self.rectangles(z,box))
            if lo>=self.center and hi<=self.bottom:
                ta=math.asin(max(0.,min(1.,(lo-self.center)/self.r)))
                tb=math.asin(max(0.,min(1.,(hi-self.center)/self.r)))
                def fn(theta):
                    z=min(math.nextafter(hi,lo),max(math.nextafter(lo,hi),self.center+self.r*math.sin(theta)))
                    return [area(z)*self.r*math.cos(theta)]
                values.append(integrate_vector(fn,ta,tb,self.abs_tol/32,self.rel_tol/32)[0])
            else:values.append((hi-lo)*area((lo+hi)/2))
        return math.fsum(values)


def enclosing_box(center,width,box):
    values=[gaussian_interval(box[i],box[i+3],center[i],width) for i in range(3)]
    f=math.prod(v[0] for v in values)
    return [f]+[values[i][1]*math.prod(values[j][0] for j in range(3) if j!=i) for i in range(3)]


def load_sources(path):
    lines=Path(path).read_text(encoding='utf-8').splitlines()
    require(lines,'Missing source header')
    header=lines[0].split();require(len(header)==2 and header[0]=='NUCLEAR_CLOSURE_SOURCE_V1','Wrong source format')
    count=int(header[1]);require(count>=0 and len(lines)==count+1,'Source count mismatch/trailing rows')
    rows=[]
    for line in lines[1:]:
        row=list(map(float,line.split()))
        require(len(row)==11 and all(math.isfinite(x) for x in row),'Nonfinite/malformed source row')
        require(row[6]>=0 and row[7]>=row[6] and row[8]>0 and row[9]==.03 and row[10]==2e-12,'Source time/charge/kernel changed')
        require(not rows or row>=rows[-1],'Source rows not canonical')
        rows.append(row)
    return rows


def default_rois(mask):
    d=mask.domain;r=mask.r;ys=sorted({d[1],d[4],*[x for pair in mask.sti_y for x in pair]})
    rois={'Total':list(d)};partitions=[]
    names=[]
    for name,a,b in [('XSN',d[0],-r),('XGate',-r,r),('XBL',r,d[3])]:
        if b>a:rois[name]=[a,d[1],d[2],b,d[4],d[5]];names.append(name)
    partitions.append(names);names=[]
    for i,(a,b) in enumerate(zip(ys,ys[1:])):
        name='Y'+str(i);rois[name]=[d[0],a,d[2],d[3],b,d[5]];names.append(name)
    partitions.append(names);names=[]
    for i,(a,b) in enumerate(zip([d[2],mask.bottom,mask.sti_z[1]],[mask.bottom,mask.sti_z[1],d[5]])):
        if b>a:
            name='Z'+str(i);rois[name]=[d[0],d[1],a,d[3],d[4],b];names.append(name)
    partitions.append(names)
    return rois,partitions


def step_integral(row,mask,roi,window,box_only=False):
    p0,p1=row[:3],row[3:6];t0,t1,q,width,sigma=row[6:]
    lo,hi=window;require(hi>lo,'Invalid time integration interval')
    delta=[b-a for a,b in zip(p0,p1)];duration=t1-t0
    def at(u):
        center=[a+u*v for a,v in zip(p0,delta)];time=t0+u*duration
        f,tm=temporal_interval(lo,hi,time,sigma)
        if f==0:return [0.]*5
        spatial=enclosing_box(center,width,roi) if box_only else mask.spatial(center,width,roi)
        return [spatial[0]*f,*[v*f for v in spatial[1:]],spatial[0]*tm*1e9]
    if duration==0 and all(v==0 for v in delta):return [q*v for v in at(0)]
    points={0.,1.}
    # Resolve Gaussian transitions at every actual material/ROI face, without
    # truncating any source tail. Subdivision changes integration only.
    boundaries=[(roi[0],roi[3],-mask.r,mask.r),
                (roi[1],roi[4],-mask.hy,mask.hy,*[v for pair in mask.sti_y for v in pair]),
                (roi[2],roi[5],mask.top,mask.center,mask.bottom,*mask.sti_z)]
    for axis in range(3):
        if delta[axis]:
            for face in boundaries[axis]:
                for multiple in (-8,-4,-2,0,2,4,8):
                    u=(face+multiple*width-p0[axis])/delta[axis]
                    if 0<u<1:points.add(u)
    if duration:
        for edge in (lo,hi):
            if math.isfinite(edge):
                for multiple in (-12,-8,-4,-2,0,2,4,8,12):
                    u=(edge+multiple*sigma-t0)/duration
                    if 0<u<1:points.add(u)
    points=sorted(points)
    values=[integrate_vector(at,a,b,mask.abs_tol/len(points),mask.rel_tol) for a,b in zip(points,points[1:])]
    return [q*v for v in add_vectors(values,5)]


def stats(vector,dt=None):
    q=vector[0]
    answer=dict(q_fC=q,moments_fC_um=vector[1:4],time_moment_fC_s=vector[4]*1e-9,
        centroid_um=[v/q if q else None for v in vector[1:4]],time_centroid_s=vector[4]*1e-9/q if q else None)
    if dt is not None:
        answer.update(dt_s=dt,mean_pair_rate_per_s=q*1e-15/E_C/dt,
                      expected_native_integral_cm3_s_um3=q/(dt*NATIVE_TO_FC),
                      expected_native_moment_integrals=[v/(dt*NATIVE_TO_FC) for v in vector[1:4]])
    return answer


def integrate_sources(rows,mask,rois,window):
    return {name:stats(add_vectors([step_integral(row,mask,box,window) for row in rows],5),
                                   window[1]-window[0] if all(math.isfinite(v) for v in window) else None)
            for name,box in rois.items()}


def reference(rows,contract,clock=None,rois=None,abs_tol=ABS_TOL,rel_tol=REL_TOL):
    mask=SiliconMask(contract,abs_tol,rel_tol)
    defaults,partitions=default_rois(mask)
    if rois is None:rois=defaults
    else:
        require('Total' in rois and rois['Total']==mask.domain,'Custom Total ROI must equal complete finite domain')
        partitions=[]
    alltime=integrate_sources(rows,mask,rois,(-math.inf,math.inf))
    box=stats(add_vectors([step_integral(row,mask,mask.domain,(-math.inf,math.inf),True) for row in rows],5))
    allocated=math.fsum(row[8] for row in rows)
    full=alltime['Total']['q_fC']
    require(0<=full<=box['q_fC']+1e-9 and box['q_fC']<=allocated+1e-9,'Finite-domain/Si charge ordering failed')
    volume=mask.volume();reported=mask.g['measures']['silicon']
    require(abs(volume-reported)<=max(1e-11,1e-9*abs(reported)),'Independent Si volume differs from bound geometry')
    windows=[]
    if clock is not None:
        intervals=clock['accepted_intervals']
        require(intervals and all(all(math.isfinite(i[k]) for k in ('start_s','end_s','dt_s')) and
                i['end_s']>i['start_s'] and i['dt_s']==i['end_s']-i['start_s'] for i in intervals),'No complete accepted BE intervals')
        require(all(a['end_s']==b['start_s'] and b['accepted_index']==a['accepted_index']+1
                    for a,b in zip(intervals,intervals[1:])),'Accepted BE intervals contain a gap, overlap or reordering')
        for interval in intervals:
            values=integrate_sources(rows,mask,rois,(interval['start_s'],interval['end_s']))
            windows.append(dict(interval=interval,rois=values))
        simulation=integrate_sources(rows,mask,rois,(intervals[0]['start_s'],intervals[-1]['end_s']))
        summed=math.fsum(row['rois']['Total']['q_fC'] for row in windows)
        closure=summed-simulation['Total']['q_fC']
    else:simulation=None;closure=None
    return dict(schema='continuous-proton-independent-source-reference-v1',is_tcad_result=False,
        native_qualified=False,pmi_r12_fixed=False,source_rows=len(rows),zero_length_sources=sum(row[:3]==row[3:6] for row in rows),
        units=dict(length='um',time='s',charge='fC',native_generation='cm^-3 s^-1',native_volume='um^3'),
        formula='sum q_j integral_0^1 Gaussian3D(r-r_j(u);w) GaussianTime(t-t_j(u);sigma) du',
        no_tail_renormalization=True,no_steps_deleted=True,rois_um=rois,partitions=partitions,
        allocated_all_space_all_time_fC=allocated,enclosing_box_all_time=box,finite_si_all_time=alltime,
        outer_domain_loss_fC=allocated-box['q_fC'],non_silicon_loss_fC=box['q_fC']-full,
        source_time_bounds_s=[min(row[6] for row in rows),max(row[7] for row in rows)] if rows else None,
        eight_sigma_observation_envelope_s=[min(row[6]-8*row[10] for row in rows),max(row[7]+8*row[10] for row in rows)] if rows else None,
        independent_si_volume_um3=volume,contract_si_volume_um3=reported,
        roi_silicon_volumes_um3={name:mask.volume(box) for name,box in rois.items()},
        partition_residuals_fC=[dict(regions=part,residual_fC=math.fsum(alltime[name]['q_fC'] for name in part)-full) for part in partitions],
        simulation_window=simulation,simulation_window_time_loss_fC=full-simulation['Total']['q_fC'] if simulation else None,
        accepted_interval_expectations=windows,interval_charge_closure_fC=closure,
        numerical_settings=dict(normalized_absolute=abs_tol,relative=rel_tol,
            method='analytic rectangular Gaussian integrals; circular-cap angular adaptive Simpson; independent segment-u quadrature'),
        source_clock_kind='precise PLT plus successful BE logs; no PMI clock synthesized' if clock else 'not supplied',
        missing_native_checks=['native HeavyIonGeneration and moments','both carrier responses and matched A0','mesh/timestep and LET/time-subdivision convergence'])


def convergence(coarse,fine):
    comparisons=[]
    def compare(label,a,b):
        values=[abs(a['q_fC']-b['q_fC'])]+[abs(x-y) for x,y in zip(a['moments_fC_um'],b['moments_fC_um'])]
        comparisons.append(dict(label=label,charge_difference_fC=values[0],max_space_moment_difference_fC_um=max(values[1:]),
            time_moment_difference_fC_s=abs(a['time_moment_fC_s']-b['time_moment_fC_s'])))
    for name in coarse['finite_si_all_time']:compare(name,coarse['finite_si_all_time'][name],fine['finite_si_all_time'][name])
    for a,b in zip(coarse['accepted_interval_expectations'],fine['accepted_interval_expectations']):
        for name in a['rois']:compare('BE'+str(a['interval']['accepted_index'])+'/'+name,a['rois'][name],b['rois'][name])
    tolerance=max(1e-6,.001*coarse['allocated_all_space_all_time_fC'])
    maximum=max((row['charge_difference_fC'] for row in comparisons),default=0.)
    return dict(compared_values=len(comparisons),maximum_charge_difference_fC=maximum,
        maximum_space_moment_difference_fC_um=max((row['max_space_moment_difference_fC_um'] for row in comparisons),default=0.),
        maximum_time_moment_difference_fC_s=max((row['time_moment_difference_fC_s'] for row in comparisons),default=0.),
        offline_charge_gate_fC=tolerance,offline_charge_gate_passed=maximum<=tolerance,
        coarse=coarse['numerical_settings'],refined=fine['numerical_settings'],
        interpretation='Numerical refinement evidence, not a rigorous error bound or native qualification')


def build(source,geometry,output,clock=None,roi_file=None):
    rows=load_sources(source);contract=read_json(geometry);clock_value=read_json(clock) if clock else None
    rois=read_json(roi_file) if roi_file else None
    result=reference(rows,contract,clock_value,rois)
    refined=reference(rows,contract,clock_value,rois,ABS_TOL/4,REL_TOL/4)
    result['refinement']=convergence(result,refined)
    require(result['refinement']['offline_charge_gate_passed'],'Independent quadrature refinement exceeds original charge gate')
    tolerance_path=ROOT/'experiments/dram-see-v4/nuclear-closure-r1/contract.json'
    tolerance=read_json(tolerance_path)['tolerances']
    result['comparison_tolerances']=dict(source_path=str(tolerance_path),source_sha256=digest(tolerance_path),
        values={k:tolerance[k] for k in ('native_source_relative','be_waveform_relative','centroid_abs_um','roi_fraction_abs',
            'time_centroid_abs_s','partition_relative','offline_charge_abs_fC','offline_charge_relative')},
        scope='Original proton source criteria; new BCAT ROI definitions explicit; not alpha qualification')
    result['inputs']={name:dict(path=str(Path(path).resolve()),sha256=digest(path)) for name,path in
                     [('sources',source),('geometry',geometry),*([('clock',clock)] if clock else []),*([('roi',roi_file)] if roi_file else [])]}
    result['implementation_sha256']=digest(__file__)
    write_new(output,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--geometry',type=Path,required=True)
    p.add_argument('--clock',type=Path);p.add_argument('--roi-file',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();answer=build(**vars(args))
    print(json.dumps(dict(output=str(args.output),source_rows=answer['source_rows'],
        finite_si_charge_fC=answer['finite_si_all_time']['Total']['q_fC'],native_qualified=False)))
