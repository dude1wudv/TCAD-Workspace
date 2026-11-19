"""Finite-domain moments of an oblique transverse-Gaussian alpha LUT.

At fixed world z, the LUT is piecewise linear in x. Gaussian primitives through
order three integrate all x moments exactly within each LUT/material interval.
No longitudinal Gaussian, TCAD field, measured clock or response is consumed.
"""
from bisect import bisect_right
import math


def gaussian_primitives(lo,hi,width,reference):
    if hi<=lo:return [0.]*4
    a,b=lo/width,hi/width;ea,eb=math.exp(-a*a),math.exp(-b*b);den=2*math.sqrt(math.pi)
    f=.5*reference.erf_delta(a,b)
    return [f,width*(ea-eb)/den,width**2*(f/2+(a*ea-b*eb)/den),
            width**3*((a*a+1)*ea-(b*b+1)*eb)/den]


class ObliqueIntegral:
    def __init__(self,rows,geometry,origin,direction,width,reference,abs_tol=None,rel_tol=None):
        self.R=reference;self.rows=rows;self.origin=list(origin);self.direction=list(direction);self.width=width
        self.paths=[row['path_um'] for row in rows];self.length=self.paths[-1]
        self.sin=-direction[0];self.cos=direction[2]
        reference.require(len(rows)>=2 and self.paths[0]==0 and all(a<b for a,b in zip(self.paths,self.paths[1:]))
            and all(math.isfinite(row['electronic_pC_um']) and row['electronic_pC_um']>0 for row in rows),
            'Invalid positive actual-path alpha LUT')
        reference.require(direction[1]==0 and self.sin>=0 and self.cos>0 and
            abs(self.sin*self.sin+self.cos*self.cos-1)<1e-14 and width>0,'Unsupported source coordinate transform')
        self.mask=reference.SiliconMask(geometry,reference.ABS_TOL if abs_tol is None else abs_tol,
                                       reference.REL_TOL if rel_tol is None else rel_tol)
        self.coefficients=[]
        for a,b in zip(rows,rows[1:]):
            slope=1000*(b['electronic_pC_um']-a['electronic_pC_um'])/(b['path_um']-a['path_um'])
            self.coefficients.append((slope,1000*a['electronic_pC_um']-slope*a['path_um']))

    def x_moments(self,left,right,z):
        zr=z-self.origin[2];x0=self.origin[0];sn,cs=self.sin,self.cos
        if not sn:
            if not 0<=zr<=self.length:return [0.]*3
            index=min(len(self.coefficients)-1,max(0,bisect_right(self.paths,zr)-1))
            slope,intercept=self.coefficients[index];density=slope*zr+intercept
            return [density*v for v in gaussian_primitives(left-x0,right-x0,self.width,self.R)[:3]]
        left=max(left,x0+(cs*zr-self.length)/sn);right=min(right,x0+cs*zr/sn)
        if right<=left:return [0.]*3
        points=[left,right]
        for s in self.paths[1:-1]:
            x=x0+(cs*zr-s)/sn
            if left<x<right:points.append(x)
        points=sorted(points);answers=[];beta=1/cs;gamma=-sn/cs*zr
        for a,b in zip(points,points[1:]):
            midpoint=(a+b)/2;s=-sn*(midpoint-x0)+cs*zr
            index=min(len(self.coefficients)-1,max(0,bisect_right(self.paths,s)-1))
            slope,intercept=self.coefficients[index]
            ca=intercept+slope*zr/cs;cb=-slope*sn/cs
            i0,i1,i2,i3=gaussian_primitives(cs*(a-x0)+sn*zr,cs*(b-x0)+sn*zr,self.width,self.R)
            answers.append([(ca*i0+cb*i1)/cs,
                (ca*(gamma*i0+beta*i1)+cb*(gamma*i1+beta*i2))/cs,
                (ca*(gamma*gamma*i0+2*gamma*beta*i1+beta*beta*i2)
                 +cb*(gamma*gamma*i1+2*gamma*beta*i2+beta*beta*i3))/cs])
        return self.R.add_vectors(answers,3)

    @staticmethod
    def product(x,y,z):
        f,mx,xx=x;fy,my,yy=y
        return [f*fy,mx*fy,f*my,f*fy*z,xx*fy,mx*my,mx*fy*z,f*yy,f*my*z,f*fy*z*z]

    def slice(self,z):
        box=self.mask.domain;zr=z-self.origin[2];cache={}
        def piece(x0,x1,y0,y1):
            key=(x0,x1)
            if key not in cache:cache[key]=self.x_moments(x0,x1,z)
            y=gaussian_primitives(y0-self.origin[1],y1-self.origin[1],self.width,self.R)[:3]
            return self.product(cache[key],y,zr)
        silicon=self.R.add_vectors([piece(*rectangle) for rectangle in self.mask.rectangles(z,box)],10)
        enclosing=piece(box[0],box[3],box[1],box[4])
        return silicon+enclosing

    def normal_box_moments(self):
        """Exact rectangular-box moments for d=+z; resolve tiny radial tails."""
        box=self.mask.domain;x0,y0,z0=self.origin
        fx,mx,xx=gaussian_primitives(box[0]-x0,box[3]-x0,self.width,self.R)[:3]
        fy,my,yy=gaussian_primitives(box[1]-y0,box[4]-y0,self.width,self.R)[:3]
        values=[]
        for index,(start,end) in enumerate(zip(self.paths,self.paths[1:])):
            lo=max(start,box[2]-z0);hi=min(end,box[5]-z0)
            if hi<=lo:continue
            slope,intercept=self.coefficients[index];h=hi-lo;density=slope*lo+intercept
            j0=density*h+slope*h*h/2
            local1=density*h*h/2+slope*h**3/3
            j1=lo*j0+local1
            j2=lo*lo*j0+2*lo*local1+density*h**3/3+slope*h**4/4
            values.append([fx*fy*j0,mx*fy*j0,fx*my*j0,fx*fy*j1,xx*fy*j0,mx*my*j0,
                           mx*fy*j1,fx*yy*j0,fx*my*j1,fx*fy*j2])
        return self.R.add_vectors(values,10)

    def integrate(self):
        m=self.mask;box=m.domain;lo,hi=box[2],box[5];z0=self.origin[2]
        breaks={lo,hi,*[v for v in (m.top,m.center,m.bottom,*m.sti_z) if lo<v<hi]}
        # LUT projections, exact intersections with fixed x faces, and physical
        # finite-end Gaussian transitions. These subdivide integration only.
        for s in self.paths:
            z=z0+self.cos*s
            if lo<z<hi:breaks.add(z)
            if self.sin:
                for x in (box[0],box[3],-m.r,m.r):
                    z=z0+(s+self.sin*(x-self.origin[0]))/self.cos
                    if lo<z<hi:breaks.add(z)
        for s in (0.,self.length):
            for multiple in (-12,-8,-4,-2,-1,0,1,2,4,8,12):
                z=z0+self.cos*s+multiple*self.sin*self.width
                if lo<z<hi:breaks.add(z)
        breaks=sorted(breaks);values=[]
        for a,b in zip(breaks,breaks[1:]):
            def physical(z):return self.slice(min(math.nextafter(b,a),max(math.nextafter(a,b),z)))
            if a>=m.center and b<=m.bottom:
                ta=math.asin(max(0.,min(1.,(a-m.center)/m.r)));tb=math.asin(max(0.,min(1.,(b-m.center)/m.r)))
                values.append(self.R.integrate_vector(lambda angle:[v*m.r*math.cos(angle) for v in physical(m.center+m.r*math.sin(angle))],
                                                        ta,tb,m.abs_tol/len(breaks),m.rel_tol))
            else:values.append(self.R.integrate_vector(physical,a,b,m.abs_tol/len(breaks),m.rel_tol))
        result=self.R.add_vectors(values,20)
        self.R.require(all(math.isfinite(v) for v in result) and result[0]>0 and result[10]>0,
                       'Positive alpha source did not resolve finite-domain moments')
        allocated=math.fsum((b['path_um']-a['path_um'])*(a['electronic_pC_um']+b['electronic_pC_um'])*500
                            for a,b in zip(self.rows,self.rows[1:]))
        enclosing_diagnostic=None
        if not self.sin:
            exact=self.normal_box_moments()
            enclosing_diagnostic=dict(adaptive=result[10:],analytic=exact,
                adaptive_minus_analytic=[a-b for a,b in zip(result[10:],exact)],
                reason='Normal-direction polynomial LUT and x/y Gaussian separate exactly; no tail clipping or renormalization')
            result[10:]=exact
        self.R.require(result[0]<=result[10]+1e-8 and result[10]<=allocated+1e-8,'Finite Si/box/line charge ordering failed')
        return dict(finite_si=result[:10],enclosing_box=result[10:],allocated_line_charge_fC=allocated,
            outer_box_loss_fC=allocated-result[10],non_silicon_loss_fC=result[10]-result[0],z_partitions=len(breaks)-1,
            normal_box_diagnostic=enclosing_diagnostic,
            method='Piecewise LET times Gaussian x moments through order3, analytic y, adaptive material/LUT z and circular-cap angle')


def source_moments(rows,geometry,request,path,reference,*,clock=None,abs_tol=None,rel_tol=None):
    reference.require(clock is None,'Pre-TCAD alpha v2 cannot consume an actual BE clock')
    result=ObliqueIntegral(rows,geometry,request['position_um'],path['direction'],request['width_um'],reference,abs_tol,rel_tol).integrate()
    q=result['finite_si'][0]
    result['raw_feature_moments']=result['finite_si']+[0.,q*request['sigma_ps']**2]
    result['clock']=None
    return result
