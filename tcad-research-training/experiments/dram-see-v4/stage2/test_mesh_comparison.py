import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('comparison',Path(__file__).with_name('compare_mesh_diagnostic.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def baseline(extra=None,q=1.,wave=.004):
    errors=[{'check':'native_spatial_temporal_source'}]
    if extra:errors.append({'check':extra})
    return dict(summary=dict(errors=errors,radiation=dict(legacy_generated_fC=q,
        waveform_checks={'legacy':{'relative_error':wave}})),source={'source_total_fC':1.})

class ComparisonTests(unittest.TestCase):
    def test_comparison_does_not_accept_any_other_coarse_failure(self):
        for extra in ('manifest_and_inputs','inherited_voltage_current_conservation'):
            with self.assertRaisesRegex(ValueError,'additional or different'):m.legacy_baseline(baseline(extra))
    def test_invalid_coarse_total_or_timing_cannot_be_used(self):
        for q,wave in [(1.06,.004),(1.,.06)]:
            with self.assertRaises(ValueError):m.legacy_baseline(baseline(q=q,wave=wave))
    def test_two_percent_denominator_is_original_coarse_baseline(self):
        r=m.charge_comparison(1.0201,1.)
        self.assertGreater(r['relative_difference'],r['limit'])
        self.assertLess(m.charge_comparison(1.0199,1.)['relative_difference'],.02)
    def test_zero_coarse_charge_is_not_a_valid_reference(self):
        with self.assertRaises(ValueError):m.charge_comparison(1.,0.)

if __name__=='__main__':unittest.main()
