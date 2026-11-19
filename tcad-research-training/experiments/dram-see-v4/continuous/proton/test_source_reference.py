"""Only new finite-Si quadrature/clock checks; fixtures are never native results."""
import copy
import math
import unittest
import source_reference as ref
import source_clock as clock

GEOMETRY=ref.ROOT/'local_runtime/dram-see-v4/transport-probe/operations/cgoal-bcat-build-20261017t043911z/collected/geometry-contract.json'


def source(p0=(0,0,.6),p1=None,t0=15e-9,t1=None,q=1.):
    return list(p0)+list(p0 if p1 is None else p1)+[t0,t0 if t1 is None else t1,q,.03,2e-12]


class IndependentSiliconReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.contract=ref.read_json(GEOMETRY)

    def test_analytic_volume_and_bulk_gaussian(self):
        mask=ref.SiliconMask(self.contract)
        self.assertAlmostEqual(mask.volume(),mask.g['measures']['silicon'],delta=1e-11)
        center=(.3,.17,.65)
        observed=mask.spatial(center,.03)
        expected=ref.enclosing_box(center,.03,mask.domain)
        for a,b in zip(observed,expected):self.assertAlmostEqual(a,b,delta=1e-12)

    def test_curved_trench_against_independent_x_first_integration(self):
        mask=ref.SiliconMask(self.contract);center=(-.011,.008,.148);w=.03
        box=ref.enclosing_box(center,w,mask.domain)
        # Independent complement construction: two STI boxes, rectangular
        # trench only in active y, and circular cap integrated in x, not z.
        removed=[]
        for ya,yb in mask.sti_y:
            removed.append(ref.enclosing_box(center,w,[mask.domain[0],ya,0,mask.domain[3],yb,mask.sti_z[1]]))
        active_lo=mask.sti_y[0][1];active_hi=mask.sti_y[1][0]
        removed.append(ref.enclosing_box(center,w,[-mask.r,active_lo,0,mask.r,active_hi,mask.center]))
        fy,my=ref.gaussian_interval(active_lo,active_hi,center[1],w)
        def at(theta):
            x=mask.r*math.sin(theta);zmax=mask.center+mask.r*math.cos(theta)
            fz,mz=ref.gaussian_interval(mask.center,zmax,center[2],w)
            factor=math.exp(-((x-center[0])/w)**2)/(math.sqrt(math.pi)*w)*mask.r*math.cos(theta)
            return [factor*fy*fz,factor*x*fy*fz,factor*my*fz,factor*fy*mz]
        n=4096;step=math.pi/n
        cap=[]
        for k in range(4):
            cap.append(step/3*math.fsum((1 if i in (0,n) else 4 if i%2 else 2)*at(-math.pi/2+i*step)[k] for i in range(n+1)))
        removed.append(cap)
        expected=[box[k]-math.fsum(v[k] for v in removed) for k in range(4)]
        actual=mask.spatial(center,w)
        for a,b in zip(actual,expected):self.assertAlmostEqual(a,b,delta=5e-10)

    def test_point_at_surface_is_clipped_and_never_renormalized(self):
        mask=ref.SiliconMask(self.contract)
        result=ref.step_integral(source((-.052,0,0)),mask,mask.domain,(-math.inf,math.inf))
        self.assertGreater(result[0],0.)
        self.assertLess(result[0],.5)
        self.assertLess(ref.enclosing_box((-.052,0,0),.03,mask.domain)[0],1.)

    def test_oblique_spatiotemporal_segment_splits_additively(self):
        mask=ref.SiliconMask(self.contract)
        row=source((.04,.008,.135),(-.025,-.009,.18),15e-9,15e-9+6e-12,q=.7)
        mid=[(a+b)/2 for a,b in zip(row[:3],row[3:6])];tm=(row[6]+row[7])/2
        left=source(row[:3],mid,row[6],tm,q=.35);right=source(mid,row[3:6],tm,row[7],q=.35)
        window=(15e-9+1e-12,15e-9+5e-12)
        full=ref.step_integral(row,mask,mask.domain,window)
        parts=ref.add_vectors([ref.step_integral(left,mask,mask.domain,window),ref.step_integral(right,mask,mask.domain,window)],5)
        for a,b in zip(full,parts):self.assertAlmostEqual(a,b,delta=2e-8)

    def test_late_point_preserved_and_interval_partition_closes(self):
        rows=[source(q=.3),source(t0=100e-9,q=.2)]
        clock_value={'accepted_intervals':[dict(accepted_index=i+1,start_s=a,end_s=b,dt_s=b-a)
            for i,(a,b) in enumerate(zip([0,14.98e-9,15e-9,15.02e-9],[14.98e-9,15e-9,15.02e-9,25e-9]))]}
        mask=ref.SiliconMask(self.contract)
        result=ref.reference(rows,self.contract,clock_value,{'Total':mask.domain})
        self.assertEqual(result['source_rows'],2);self.assertEqual(result['zero_length_sources'],2)
        self.assertAlmostEqual(result['allocated_all_space_all_time_fC'],.5)
        self.assertAlmostEqual(result['simulation_window_time_loss_fC'],.2,delta=1e-10)
        self.assertAlmostEqual(result['interval_charge_closure_fC'],0.,delta=1e-12)
        self.assertFalse(result['native_qualified'])

    def test_roi_partition_and_quadrature_refinement(self):
        rows=[source((-.011,.008,.148),q=.4)]
        coarse=ref.reference(rows,self.contract)
        fine=ref.reference(rows,self.contract,abs_tol=ref.ABS_TOL/4,rel_tol=ref.REL_TOL/4)
        check=ref.convergence(coarse,fine)
        self.assertLess(check['maximum_charge_difference_fC'],1e-8)
        for part in fine['partition_residuals_fC']:self.assertAlmostEqual(part['residual_fC'],0.,delta=1e-9)


class NativeClockBinding(unittest.TestCase):
    def fixture(self):
        rows=[{'time':t,'IntegrSemiconductor HeavyIonGeneration':g} for t,g in [(0.,0.),(1e-12,1.),(1e-12,1.),(2e-12,2.)]]
        log="""Computing BE-step from 0.0000e+00 s to 1.0000e-12 s (Stepsize: 1.0000e-12 s)
Finished, because |RHS| is less than 1.0000e-10.
Writing plot 'source_window0000.tdr' (TDR format) ... done.
Computing BE-step from 1.0000e-12 s to 3.0000e-12 s (Stepsize: 2.0000e-12 s)
Newton didn't converge
Computing BE-step from 1.0000e-12 s to 2.0000e-12 s (Stepsize: 1.0000e-12 s)
Error smaller than 1
Writing plot 'source_window0001.tdr' (TDR format) ... done.
"""
        return log,rows,['source_window0000.tdr','source_window0001.tdr']

    def test_real_tokens_and_retry_retained_without_pmi_clock(self):
        log,rows,files=self.fixture();result=clock.index(log,rows,files,window=(0,2e-12))
        self.assertEqual(result['accepted_BE_count'],2)
        self.assertEqual(len(result['rejected_or_unconverged_attempts']),1)
        self.assertEqual(result['repeated_block_initial_rows'],1)
        self.assertEqual(result['frames'][1]['start_s'],1e-12)
        self.assertFalse(result['pmi_clock_fabricated']);self.assertFalse(result['native_qualified'])

    def test_missing_frame_changed_duplicate_and_late_window_rejected(self):
        log,rows,files=self.fixture()
        with self.assertRaisesRegex(ValueError,'Missing native field'):clock.index(log,rows,files[:1],window=(0,2e-12))
        changed=copy.deepcopy(rows);changed[2]['IntegrSemiconductor HeavyIonGeneration']=0
        with self.assertRaisesRegex(ValueError,'repeated'):clock.index(log,changed,files)
        with self.assertRaisesRegex(ValueError,'late deposits'):clock.index(log,rows,files,window=(0,3e-12))

    def test_rejected_write_is_not_accepted(self):
        log,rows,files=self.fixture()
        log=log.replace("Newton didn't converge","Newton didn't converge\nWriting plot 'source_window_bad.tdr' (TDR format) ... done.")
        with self.assertRaisesRegex(ValueError,'Rejected/unconverged'):clock.index(log,rows,files+['source_window_bad.tdr'])


if __name__=='__main__':unittest.main()
