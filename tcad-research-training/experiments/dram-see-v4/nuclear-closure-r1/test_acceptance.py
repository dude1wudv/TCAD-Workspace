"""Isolated analytic verification; synthetic curves are not native evidence."""
import unittest
from unittest.mock import patch
import acceptance as a


def capacitor(times,volts):
    rows=[]
    for i,(t,v) in enumerate(zip(times,volts)):
        current=0. if i==0 else -1e-14*(v-volts[i-1])/(t-times[i-1])
        rows.append({'time':t,'v(sn)':v,'v(bl)':v/3,'v(ref)':.5,'v(wl)':0.,
            'i(access,sn)':current,'i(access,bl)':0.,'i(rsn,sn)':0.})
    return {'circuit':rows,'device':[{'time':t,'IntegrSemiconductor PMIRecombination':-1e25} for t in times]}


class ElectricalAudit(unittest.TestCase):
    def test_be_is_right_interval_not_trapezoid(self):
        rows=[{'time':0.,'i':100.},{'time':1.,'i':2.},{'time':3.,'i':4.}]
        self.assertEqual(a.be_integrals(rows,'i',[1.,2.,3.],start=0),[2e15,6e15,10e15])

    def test_no_extrapolation(self):
        with self.assertRaises(ValueError):a.samples([{'time':0.,'v':0.},{'time':1.,'v':1.}],'v',[2.])

    def test_independent_capacitor_balance_different_native_grids(self):
        signal=capacitor([0,.95e-9,1e-9,2e-9,4e-9],[.9,.9,.92,.94,.93])
        zero=capacitor([0,.95e-9,1.5e-9,4e-9],[.9,.9,.901,.902])
        result=a.circuit_balance(signal,zero)
        self.assertTrue(result['passed']);self.assertLess(result['maximum_residual_fC'],1e-12)
        # No capacitor current column exists, so the observed charge evidence is independent.
        signal['circuit'][-1]['i(access,sn)']+=1e-6
        self.assertFalse(a.circuit_balance(signal,zero)['passed'])

    def test_unique_native_excess_point_is_not_removed(self):
        ta=[0,.95e-9,1.0e-9,3.10e-9,3.12e-9,4e-9]
        tb=sorted(ta+[3.112e-9])
        sa=capacitor(ta,[.9,.9,.935,.935,.935,.935])
        sb=capacitor(tb,[.9,.9,.935,.935,.93956,.935,.935])
        ca=capacitor(ta,[.9]*len(ta));cb=capacitor(tb,[.9]*len(tb))
        base=dict(common_mesh_manifest_sha256='same',pmi_binary_sha256='same',geometry_contract_sha256='same',dimension=3,stored_bit=1,source_windows_s=[[.98e-9,1.02e-9]],source_sha256='same')
        data={role:dict(role=role,curves=curves,parameters={**base,'control_role':control,'mesh_key':'m1' if 'm1' in role else 'm0'},field={'mesh_sha256':'m1' if 'm1' in role else 'm0'}) for role,curves,control in
              [('event-m0-t0',sa,'a0-m0-t0'),('event-m1-t0',sb,'a0-m1-t0'),('a0-m0-t0',ca,''),('a0-m1-t0',cb,'')]}
        with patch.object(a,'load',side_effect=lambda r:data[r]),patch.object(a.c,'ref',return_value={'synthetic':True}):
            report,rows=a.compare_roles('event-m0-t0','event-m1-t0')
        self.assertFalse(report['passed']);self.assertEqual(len(rows),len(tb))
        self.assertAlmostEqual(report['metrics']['v(sn)']['error_V'],.00456)

    def test_five_predeclared_matrix_pairs(self):
        pairs=a.c.contract()['numerical']['comparisons']
        self.assertEqual(len(pairs),5)
        self.assertIn(['m0-t0','m1-t1'],pairs)
        self.assertEqual(len({tuple(p) for p in pairs}),5)


if __name__=='__main__':unittest.main()
