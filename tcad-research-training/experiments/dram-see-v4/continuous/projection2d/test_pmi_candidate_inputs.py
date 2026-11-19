"""Input/oracle checks only. Deliberately never compiles or runs C++/PMI."""
import importlib.util
import math
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_test_projection_candidate',HERE/'prepare_pmi_candidate.py')
C=importlib.util.module_from_spec(spec);exec(compile((HERE/'prepare_pmi_candidate.py').read_bytes(),str(HERE/'prepare_pmi_candidate.py'),'exec'),C.__dict__)


class CandidateInputTests(unittest.TestCase):
    def test_01_frozen_point_G2_time_oracle_and_zero(self):
        t=15e-9;s=dict(uid='MATH_ONLY',p0_um=[-.052,0,.4],p1_um=[-.052,0,.4],t0_s=t,t1_s=t,charge_fC=1.,width_um=.03,sigma_s=2e-12)
        lo,hi=t-2e-12,t+2e-12
        actual=C.oracle_average([s],-.052,.4,lo,hi,[0,50e-9])
        expected=1e-15/C.K.E_C*1e12*math.erf(.01/.03)*math.erf((hi-lo)/(2*math.sqrt(2)*2e-12))/(math.pi*.03**2*.02*(hi-lo))
        self.assertAlmostEqual(actual/expected,1.,delta=2e-8)
        self.assertEqual(C.oracle_average([],0,0,lo,hi,[0,50e-9]),0.)

    def test_02_general_dy_dt_is_not_one_separable_heavyion(self):
        t=15e-9;s=dict(uid='MATH_ONLY_DY_DT',p0_um=[-.12,-.05,.3],p1_um=[-.02,.06,.5],
            t0_s=t-10e-12,t1_s=t+20e-12,charge_fC=.8,width_um=.03,sigma_s=2e-12)
        mask=C.K.ResponseMask(dict(kind='arithmetic_rectangle',bounds_xz_um=[-2,-1,2,2],outer_trench=None))
        values=[[C.K.generation2d([s],mask,x,z,time,[0,50e-9]) for time in (t-4e-12,t+14e-12)]
                for x,z in ((-.10,.34),(-.04,.46))]
        determinant=values[0][0]*values[1][1]-values[0][1]*values[1][0]
        normalized=determinant/max(abs(values[0][0]*values[1][1]),abs(values[0][1]*values[1][0]))
        self.assertGreater(abs(normalized),.9)
        print('GENERAL_DY_DT_NONSEPARABLE_SYNTHETIC_DETERMINANT='+str(normalized),flush=True)

    def test_03_source_table_preserves_physical_y_and_no_context_approval(self):
        s=dict(uid='MATH_ONLY',p0_um=[.1,.03,.4],p1_um=[.2,-.07,.5],t0_s=1e-9,t1_s=2e-9,charge_fC=.1,width_um=.03,sigma_s=2e-12)
        lines=C.source_table([s]).decode().splitlines();values=list(map(float,lines[1].split()))
        self.assertEqual(lines[0],'NUCLEAR_CLOSURE_SOURCE_V1 1');self.assertEqual(values[1],.03);self.assertEqual(values[4],-.07)
        self.assertIn(b'0.02',C.context_bytes([0,50e-9]))
        with self.assertRaises(ValueError):C.context_bytes([0,0])
        code=(HERE/'pmi_projection_qy_r1.C').read_text()
        self.assertIn('ReadTime()',code);self.assertIn('ReadTransientStepSize()',code);self.assertIn('ReadTransientStepType()',code)
        self.assertNotIn('GetTimeFromInput',code)
        # A stream insertion records<< is not a truncating comparison records<.
        self.assertNotRegex(code,r'\brecords\s*<(?!<)')


if __name__=='__main__':unittest.main(verbosity=2)
