"""Conservative y-average of the existing correlated Gaussian proton G3.

All callable coordinates are physical um and seconds. G2 is cm^-3 s^-1.
This mathematical source is not a native source implementation or field result.
"""
from __future__ import annotations
import hashlib
import importlib.util
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
REFERENCE=HERE.parent/'proton/source_reference.py'
REFERENCE_SHA='82a5b47c685c9156f212787999c07d21d1aee249b22b3f783f89cf499da4e4ec'
raw=REFERENCE.read_bytes()
if hashlib.sha256(raw).hexdigest()!=REFERENCE_SHA:raise ValueError('Fixed independent quadrature reference changed')
spec=importlib.util.spec_from_file_location('_r14_projection_quadrature',REFERENCE)
R=importlib.util.module_from_spec(spec);exec(compile(raw,str(REFERENCE),'exec'),R.__dict__)
require=R.require
WIDTH_UM=.02
WIDTH_CM=2e-6
Y_BOUNDS=(-.01,.01)
E_C=1.602176634e-19
ABS_TOL=1e-11
REL_TOL=1e-8


def gaussian(lo,hi,center,width):return R.gaussian_interval(lo,hi,center,width)
def tails(lo,hi,center,width):
    return .5*(math.erfc((center-lo)/width)+math.erfc((hi-center)/width))
def density(x,center,width):return math.exp(-((x-center)/width)**2)/(math.sqrt(math.pi)*width)


class ResponseMask:
    """Finite x/z rectangle, optionally excluding the exact rounded BCAT trench."""
    def __init__(self,specification,abs_tol=ABS_TOL,rel_tol=REL_TOL):
        self.spec=specification;self.abs_tol=abs_tol;self.rel_tol=rel_tol
        require(specification['kind'] in ('bcat_center_section','historical_planar_rectangle','arithmetic_rectangle'),
                'Unsupported declared response Si mask')
        self.box=list(specification['bounds_xz_um']);self.trench=specification.get('outer_trench')
        require(len(self.box)==4 and all(math.isfinite(v) for v in self.box) and
                self.box[0]<self.box[2] and self.box[1]<self.box[3],'Invalid finite x/z response box')
        require(specification['kind']=='bcat_center_section' or self.trench is None,'Rectangle cannot hide a material exclusion')
        if self.trench:
            t=self.trench
            require(set(t)=={'radius_um','center_z_um','top_um'} and all(math.isfinite(v) for v in t.values()) and
                    t['radius_um']>0 and self.box[1]<=t['top_um']<t['center_z_um'] and
                    t['center_z_um']+t['radius_um']<=self.box[3],'Unsupported outer-trench boundary')
        self.cache={}

    def cut(self,z):
        if not self.trench:return 0.
        r,c,top=(self.trench[k] for k in ('radius_um','center_z_um','top_um'))
        if top<=z<=c:return r
        if c<z<c+r:return math.sqrt(max(0.,r*r-(z-c)**2))
        return 0.

    def contains(self,x,z):
        x0,z0,x1,z1=self.box
        return x0<=x<=x1 and z0<=z<=z1 and not (self.cut(z)>0 and abs(x)<=self.cut(z))

    def spatial(self,cx,cz,width):
        """Positive Si/non-Si masses and absolute physical x/z first moments."""
        key=(cx,cz,width)
        if key in self.cache:return self.cache[key]
        x0,z0,x1,z1=self.box
        def xparts(cut):
            if not cut:return (*gaussian(x0,x1,cx,width),0.,0.)
            lo=max(x0,-cut);hi=min(x1,cut)
            if hi<=lo:return (*gaussian(x0,x1,cx,width),0.,0.)
            left=gaussian(x0,lo,cx,width);right=gaussian(hi,x1,cx,width);excluded=gaussian(lo,hi,cx,width)
            return (left[0]+right[0],left[1]+right[1],*excluded)
        breaks={z0,z1}
        if self.trench:
            r,c,top=(self.trench[k] for k in ('radius_um','center_z_um','top_um'))
            breaks.update(v for v in (top,c,c+r) if z0<v<z1)
        breaks=sorted(breaks);answers=[]
        for lo,hi in zip(breaks,breaks[1:]):
            cap=bool(self.trench and lo>=c and hi<=c+r)
            if not cap:
                fs,mxs,fn,mxn=xparts(self.cut((lo+hi)/2));fz,mz=gaussian(lo,hi,cz,width)
                answers.append([fs*fz,mxs*fz,fs*mz,fn*fz,mxn*fz,fn*mz])
            else:
                ta=math.asin(max(0.,min(1.,(lo-c)/r)));tb=math.asin(max(0.,min(1.,(hi-c)/r)))
                points={ta,tb}
                for multiple in (-12,-8,-4,-2,0,2,4,8,12):
                    z=cz+multiple*width
                    if lo<z<hi:points.add(math.asin((z-c)/r))
                points=sorted(points)
                def angular(angle):
                    z=min(math.nextafter(hi,lo),max(math.nextafter(lo,hi),c+r*math.sin(angle)))
                    fs,mxs,fn,mxn=xparts(self.cut(z));factor=density(z,cz,width)*r*math.cos(angle)
                    return [fs*factor,mxs*factor,z*fs*factor,fn*factor,mxn*factor,z*fn*factor]
                answers.extend(R.integrate_vector(angular,a,b,self.abs_tol/len(points),self.rel_tol)
                               for a,b in zip(points,points[1:]))
        result=R.add_vectors(answers,6)
        require(result[0]>=0 and result[3]>=0 and all(math.isfinite(v) for v in result),'Invalid positive material partition')
        self.cache[key]=result
        return result


def validate_term(term):
    for key in ('p0_um','p1_um'):
        require(isinstance(term[key],list) and len(term[key])==3 and all(math.isfinite(v) for v in term[key]),'Invalid 3D source endpoint')
    require(all(math.isfinite(term[k]) for k in ('t0_s','t1_s','charge_fC','width_um','sigma_s')),'Nonfinite source kernel')
    require(0<=term['t0_s']<=term['t1_s'] and term['charge_fC']>0 and
            term['width_um']==.03 and term['sigma_s']==2e-12,'Source differs from existing positive Si G3 kernel')
    return term


def breakpoints(term,mask,window,point=None):
    p0,p1=term['p0_um'],term['p1_um'];width=term['width_um'];sigma=term['sigma_s']
    x0,z0,x1,z1=mask.box;faces=[[x0,x1],list(Y_BOUNDS),[z0,z1]]
    if mask.trench:
        r,c,top=(mask.trench[k] for k in ('radius_um','center_z_um','top_um'))
        faces[0]+=[-r,r];faces[2]+=[top,c,c+r]
    if point is not None:faces[0].append(point[0]);faces[2].append(point[1])
    points={0.,1.}
    for axis in range(3):
        delta=p1[axis]-p0[axis]
        if delta:
            for face in faces[axis]:
                for multiple in (-12,-8,-4,-2,0,2,4,8,12):
                    u=(face+multiple*width-p0[axis])/delta
                    if 0<u<1:points.add(u)
    duration=term['t1_s']-term['t0_s']
    if duration:
        for edge in window:
            for multiple in (-12,-8,-4,-2,0,2,4,8,12):
                u=(edge+multiple*sigma-term['t0_s'])/duration
                if 0<u<1:points.add(u)
    return sorted(points)


def average_u(fn,points,abs_tol,rel_tol):
    return R.add_vectors([R.integrate_vector(fn,a,b,abs_tol/len(points),rel_tol) for a,b in zip(points,points[1:])],len(fn(.5)))


def step_integrals(term,mask,window,origin_um,epoch_s):
    validate_term(term)
    require(len(window)==2 and all(math.isfinite(v) for v in window) and 0<=window[0]<window[1],'Explicit finite source/electrical time window required')
    require(len(origin_um)==3 and all(math.isfinite(v) for v in origin_um) and math.isfinite(epoch_s),'Invalid prescribed moment origins')
    x0,z0,x1,z1=mask.box;w=term['width_um'];sigma=term['sigma_s'];q=term['charge_fC']
    def at(u):
        c=[a+u*(b-a) for a,b in zip(term['p0_um'],term['p1_um'])];tc=term['t0_s']+u*(term['t1_s']-term['t0_s'])
        y=gaussian(*Y_BOUNDS,c[1],w)[0];outside_y=tails(*Y_BOUNDS,c[1],w)
        fx=gaussian(x0,x1,c[0],w)[0]
        outside_xz=tails(x0,x1,c[0],w)+fx*tails(z0,z1,c[2],w)
        si,mx,mz,non_si,_,_=mask.spatial(c[0],c[2],w)
        t,tm=R.temporal_interval(window[0]-epoch_s,window[1]-epoch_s,tc-epoch_s,sigma)
        outside_t=tails(window[0],window[1],tc,math.sqrt(2)*sigma)
        return [outside_y,y*outside_xz,y*non_si,y*si*outside_t,y*si*t,
                y*(mx-origin_um[0]*si)*t,y*(mz-origin_um[2]*si)*t,y*si*tm*1e12,
                y*mx*t,y*mz*t]
    vector=[q*v for v in average_u(at,breakpoints(term,mask,window),mask.abs_tol,mask.rel_tol)]
    names=('outside_y_strip_fC','inside_strip_outside_xz_box_fC','inside_strip_box_non_silicon_fC',
           'response_silicon_outside_time_window_fC','accepted_fC','accepted_Mx_relative_fC_um',
           'accepted_Mz_relative_fC_um','accepted_Mt_relative_fC_ps','accepted_Mx_absolute_fC_um','accepted_Mz_absolute_fC_um')
    require(all(math.isfinite(v) for v in vector) and all(v>=0 for v in vector[:5]),'Nonfinite/negative projected charge category')
    result=dict(zip(names,vector));result.update(original_positive_Si_charge_fC=q,
        charge_partition_residual_fC=q-math.fsum(vector[:5]),
        raw_deposition_outside_window=term['t0_s']<window[0] or term['t1_s']>window[1],
        zero_length_preserved=term['p0_um']==term['p1_um'])
    return result


def generation2d(terms,mask,x_um,z_um,time_s,window):
    """Mathematical G2, not a native HeavyIon/PMI field. Coordinates are um,s."""
    require(all(math.isfinite(v) for v in (x_um,z_um,time_s)),'Nonfinite G2 query')
    if not mask.contains(x_um,z_um) or not window[0]<=time_s<=window[1]:return 0.
    values=[]
    for term in terms:
        validate_term(term);w=term['width_um'];sigma=term['sigma_s']
        def at(u):
            c=[a+u*(b-a) for a,b in zip(term['p0_um'],term['p1_um'])];tc=term['t0_s']+u*(term['t1_s']-term['t0_s'])
            y=gaussian(*Y_BOUNDS,c[1],w)[0]
            return [density(x_um,c[0],w)*density(z_um,c[2],w)*y*density(time_s,tc,math.sqrt(2)*sigma)]
        probability=average_u(at,breakpoints(term,mask,(time_s,time_s),(x_um,z_um)),mask.abs_tol,mask.rel_tol)[0]
        values.append(term['charge_fC']*1e-15/E_C*1e12/WIDTH_UM*probability)
    return math.fsum(values)


def integrate(terms,response,window,origin_um,epoch_s,*,refined=False):
    factor=.25 if refined else 1.;mask=ResponseMask(response,ABS_TOL*factor,REL_TOL*factor)
    rows=[dict(uid=term['uid'],**step_integrals(term,mask,window,origin_um,epoch_s)) for term in terms]
    numeric_keys=('original_positive_Si_charge_fC','outside_y_strip_fC','inside_strip_outside_xz_box_fC',
        'inside_strip_box_non_silicon_fC','response_silicon_outside_time_window_fC','accepted_fC',
        'accepted_Mx_relative_fC_um','accepted_Mz_relative_fC_um','accepted_Mt_relative_fC_ps',
        'accepted_Mx_absolute_fC_um','accepted_Mz_absolute_fC_um','charge_partition_residual_fC')
    totals={name:math.fsum(row[name] for row in rows) for name in numeric_keys};q=totals['accepted_fC']
    gate=max(1e-6,.001*totals['original_positive_Si_charge_fC'])
    require(abs(totals['charge_partition_residual_fC'])<=gate,'Projection charge partition failed closure')
    return dict(rows=rows,totals=totals,offline_charge_gate_fC=gate,charge_partition_closed_within_offline_gate=True,
        centroids=dict(physical_x_um=totals['accepted_Mx_absolute_fC_um']/q if q else None,
            physical_z_um=totals['accepted_Mz_absolute_fC_um']/q if q else None,
            time_s=epoch_s+totals['accepted_Mt_relative_fC_ps']/q*1e-12 if q else None),
        raw_deposition_outside_window_uids=[row['uid'] for row in rows if row['raw_deposition_outside_window']],
        numerical_settings=dict(normalized_absolute=mask.abs_tol,relative=mask.rel_tol),
        qualified_native=False,actual_clock=None)
