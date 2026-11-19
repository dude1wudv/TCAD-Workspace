"""Pre-TCAD finite-Si raw moments. No file reads, clock, native field or response.

The reference module is supplied explicitly by the caller, so importing from
device code cannot accidentally resolve a sibling module named ``prepare``.
"""
from __future__ import annotations
import math


def gaussian_moments(a,b,center,width,origin,reference):
    """Integrals of 1,(x-origin),(x-origin)^2 for normalized exp(-(x-c)^2/w^2)."""
    reference.require(width>0 and all(math.isfinite(v) for v in (a,b,center,width,origin)),
                      'Invalid finite Gaussian interval')
    if b<=a:return [0.,0.,0.]
    aa,bb=(a-center)/width,(b-center)/width
    mass=.5*reference.erf_delta(aa,bb);ea,eb=math.exp(-aa*aa),math.exp(-bb*bb)
    delta=center-origin;root=math.sqrt(math.pi)
    first=delta*mass+width/(2*root)*(ea-eb)
    second=(delta*delta+width*width/2)*mass+delta*width/root*(ea-eb)+width*width/(2*root)*(aa*ea-bb*eb)
    reference.require(all(math.isfinite(v) for v in (mass,first,second)), 'Nonfinite Gaussian moment')
    return [mass,first,second]


class MomentMask:
    def __init__(self,reference,contract,r0,abs_tol=None,rel_tol=None):
        self.R=reference;self.r0=list(r0)
        reference.require(len(r0)==3 and all(math.isfinite(v) for v in r0),'Invalid prescribed moment origin')
        self.mask=reference.SiliconMask(contract,reference.ABS_TOL if abs_tol is None else abs_tol,
                                       reference.REL_TOL if rel_tol is None else rel_tol)
        self.cache={}

    def slice(self,z,box,center,width):
        rows=[]
        for x0,x1,y0,y1 in self.mask.rectangles(z,box):
            x=gaussian_moments(x0,x1,center[0],width,self.r0[0],self.R)
            y=gaussian_moments(y0,y1,center[1],width,self.r0[1],self.R)
            rows.append([x[0]*y[0],x[1]*y[0],x[0]*y[1],x[2]*y[0],x[1]*y[1],x[0]*y[2]])
        return self.R.add_vectors(rows,6)

    @staticmethod
    def combine(xy,z):
        f,x,y,xx,xy_,yy=xy;fz,mz,zz=z
        return [f*fz,x*fz,y*fz,f*mz,xx*fz,xy_*fz,x*mz,yy*fz,y*mz,f*zz]

    def spatial(self,center,width):
        key=(tuple(center),width)
        if key in self.cache:return self.cache[key]
        m=self.mask;box=m.domain;answers=[]
        self.R.require(width>0 and all(math.isfinite(v) for v in (*center,width)),'Invalid prescribed Gaussian source')
        breaks=sorted({box[2],box[5],*[z for z in (m.top,m.center,m.bottom,*m.sti_z) if box[2]<z<box[5]]})
        for lo,hi in zip(breaks,breaks[1:]):
            if lo>=m.center and hi<=m.bottom:
                angle=lambda z:math.asin(max(0.,min(1.,(z-m.center)/m.r)))
                points={angle(lo),angle(hi)}
                for multiple in (-12,-8,-4,-2,-1,0,1,2,4,8,12):
                    z=center[2]+multiple*width
                    if lo<z<hi:points.add(angle(z))
                points=sorted(points)
                def angular(theta):
                    z=min(math.nextafter(hi,lo),max(math.nextafter(lo,hi),m.center+m.r*math.sin(theta)))
                    dz=z-self.r0[2]
                    weight=math.exp(-((z-center[2])/width)**2)/(math.sqrt(math.pi)*width)*m.r*math.cos(theta)
                    return [v*weight for v in self.combine(self.slice(z,box,center,width),[1.,dz,dz*dz])]
                answers.extend(self.R.integrate_vector(angular,a,b,m.abs_tol/len(points),m.rel_tol)
                               for a,b in zip(points,points[1:]))
            else:
                xy=self.slice((lo+hi)/2,box,center,width)
                z=gaussian_moments(lo,hi,center[2],width,self.r0[2],self.R)
                answers.append(self.combine(xy,z))
        result=self.R.add_vectors(answers,10)
        self.R.require(all(math.isfinite(v) for v in result) and 0<=result[0]<=1+1e-10,'Invalid finite-Si moment integral')
        self.cache[key]=result;return result


def proton_moments(rows,geometry,r0,epoch_s,reference,*,clock=None,abs_tol=None,rel_tol=None):
    """Full time Gaussian-line moments; time offsets are ps, coordinates um."""
    R=reference;R.require(clock is None,'Source features must not consume an actual BE clock')
    R.require(math.isfinite(epoch_s),'Invalid prescribed epoch')
    mask=MomentMask(R,geometry,r0,abs_tol,rel_tol);m=mask.mask;answers=[]
    for row in rows:
        R.require(len(row)==11 and all(math.isfinite(v) for v in row) and row[8]>0 and row[7]>=row[6]
                  and row[9]==.03 and row[10]==2e-12,'Unsupported proton source record/kernel')
        p0,p1=row[:3],row[3:6];t0,t1,q,width,sigma=row[6:]
        delta=[b-a for a,b in zip(p0,p1)];duration=t1-t0
        def at(u):
            spatial=mask.spatial([a+u*d for a,d in zip(p0,delta)],width)
            tau=(t0-epoch_s)*1e12+u*duration*1e12
            return [*spatial,spatial[0]*tau,spatial[0]*(tau*tau+(sigma*1e12)**2)]
        if duration==0 and not any(delta):answer=at(0.)
        else:
            points={0.,1.};d=m.domain
            boundaries=[(d[0],d[3],-m.r,m.r),(d[1],d[4],-m.hy,m.hy,*[v for pair in m.sti_y for v in pair]),
                        (d[2],d[5],m.top,m.center,m.bottom,*m.sti_z)]
            for axis in range(3):
                if delta[axis]:
                    for face in boundaries[axis]:
                        for multiple in (-8,-4,-2,0,2,4,8):
                            u=(face+multiple*width-p0[axis])/delta[axis]
                            if 0<u<1:points.add(u)
            points=sorted(points)
            answer=R.add_vectors([R.integrate_vector(at,a,b,m.abs_tol/len(points),m.rel_tol)
                                   for a,b in zip(points,points[1:])],12)
        answers.append([q*v for v in answer])
    result=R.add_vectors(answers,12)
    R.require(all(math.isfinite(v) for v in result),'Proton feature integration failed')
    R.require(not rows or result[0]>0,'Positive source failed to resolve finite-Si charge; not structural zero')
    return result


def alpha_moments(rows,geometry,r0,epoch_s,reference,alpha_reference,*,amplitude=1.,clock=None,abs_tol=None,rel_tol=None):
    """ASTAR longitudinal LUT times transverse Gaussian; no z convolution."""
    R=reference;R.require(clock is None,'Source features must not consume an actual BE clock')
    R.require(math.isfinite(epoch_s) and math.isfinite(amplitude) and amplitude in (0.,.5,1.),'Unsupported alpha source amplitude/epoch')
    mask=MomentMask(R,geometry,r0,abs_tol,rel_tol);m=mask.mask;box=m.domain
    R.require(r0==[-.052,0.,0.] and epoch_s==15e-9,'Only prescribed S2 alpha origin/epoch supported')
    breaks=sorted({box[2],box[5],*[r['path_um'] for r in rows if box[2]<r['path_um']<box[5]],
                   *[v for v in (m.top,m.center,m.bottom,*m.sti_z) if box[2]<v<box[5]]})
    values=[]
    for lo,hi in zip(breaks,breaks[1:]):
        def physical(z):
            z=min(math.nextafter(hi,lo),max(math.nextafter(lo,hi),z));dz=z-r0[2]
            weight=alpha_reference.line_charge_density(z,rows)*amplitude
            return [weight*v for v in mask.combine(mask.slice(z,box,r0,.05),[1.,dz,dz*dz])]
        if lo>=m.center and hi<=m.bottom:
            ta=math.asin(max(0.,min(1.,(lo-m.center)/m.r)));tb=math.asin(max(0.,min(1.,(hi-m.center)/m.r)))
            values.append(R.integrate_vector(lambda angle:[v*m.r*math.cos(angle) for v in physical(m.center+m.r*math.sin(angle))],
                                               ta,tb,m.abs_tol/len(breaks),m.rel_tol))
        else:values.append(R.integrate_vector(physical,lo,hi,m.abs_tol/len(breaks),m.rel_tol))
    spatial=R.add_vectors(values,10)
    # The alpha input places every LET ordinate at one prescribed time, sigma=.2ps.
    result=spatial+[0.,spatial[0]*.2**2]
    R.require(all(math.isfinite(v) for v in result),'Alpha feature integration failed')
    R.require(amplitude==0 or result[0]>0,'Positive alpha source failed to resolve charge; not structural zero')
    return result
