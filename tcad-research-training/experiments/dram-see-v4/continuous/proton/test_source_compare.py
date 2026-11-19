"""Synthetic arithmetic-only field rows; no native qualification is inferred."""
import copy
import unittest
import source_compare as compare
import source_reference as ref
from test_source_reference import GEOMETRY,source


class MeasuredFieldArithmetic(unittest.TestCase):
    def fixture(self):
        rois={'Total':[-1,-.25,0,1,.25,1],'Left':[-1,-.25,0,0,.25,1],'Right':[0,-.25,0,1,.25,1]}
        q={'Total':1.,'Left':.3,'Right':.7}
        centers={'Total':[.12,0,.5],'Left':[-.3,0,.5],'Right':[.3,0,.5]}
        volumes={'Total':1.,'Left':.5,'Right':.5}
        clock=dict(schema='continuous-proton-source-clock-v1',source_field='HeavyIonGeneration',
            generation_columns=['IntegrSemiconductor HeavyIonGeneration'],required_source_window_indices=[1,2],
            frames=[dict(source_file='native'+str(i)+'.tdr',source_sha256=str(i)*64,accepted_index=i,start_s=i-1.,end_s=float(i),dt_s=1.) for i in (1,2)],
            source_scalars=[{'time':float(i),'IntegrSemiconductor HeavyIonGeneration':0. if i==0 else 1./ref.NATIVE_TO_FC} for i in (0,1,2)])
        reference=dict(rois_um=rois,roi_silicon_volumes_um3=volumes,allocated_all_space_all_time_fC=2.,partitions=[['Left','Right']],
            simulation_window={'Total':{'q_fC':2.}},comparison_tolerances={'values':dict(native_source_relative=.05,be_waveform_relative=.05,
                centroid_abs_um=.01,roi_fraction_abs=.05,time_centroid_abs_s=5e-13,partition_relative=.05)},
            accepted_interval_expectations=[dict(interval={'accepted_index':i},rois={roi:dict(q_fC=q[roi],centroid_um=centers[roi],
                time_moment_fC_s=q[roi]*(i-.5)) for roi in rois}) for i in (1,2)])
        measurements=dict(schema='continuous-proton-native-field-measurements-v1',field_name='HeavyIonGeneration',
            roi_boxes_um=rois,units=dict(G='cm^-3 s^-1 um^3',XG='cm^-3 s^-1 um^4',YG='cm^-3 s^-1 um^4',ZG='cm^-3 s^-1 um^4',ONE='um^3'),frames=[])
        for i in (1,2):
            values={roi:dict(G=q[roi]/ref.NATIVE_TO_FC,ONE=volumes[roi],
                **{key:centers[roi][j]*q[roi]/ref.NATIVE_TO_FC for j,key in enumerate(('XG','YG','ZG'))}) for roi in rois}
            measurements['frames'].append(dict(source_file='native'+str(i)+'.tdr',source_sha256=str(i)*64,accepted_index=i,rois=values))
        return reference,clock,measurements

    def test_unit_conversion_and_success_never_grants_qualification(self):
        result=compare.compare(*self.fixture())
        self.assertTrue(result['comparison_passed']);self.assertFalse(result['native_qualified'])
        self.assertFalse(result['upstream_extraction_provenance_verified'])
        self.assertAlmostEqual(result['observed_full_scalar_charge_fC'],2.)

    def test_missing_frame_wrong_hash_units_and_negative_generation_rejected(self):
        for change,reason in [
            (lambda m:m['frames'].pop(),'Complete original'),
            (lambda m:m['frames'][0].update(source_sha256='a'*64),'TDR hash'),
            (lambda m:m['units'].update(G='cm^-3 s^-1 cm^3'),'units'),
            (lambda m:m['frames'][0]['rois']['Total'].update(G=-1),'Negative')]:
            r,c,m=self.fixture();change(m)
            with self.assertRaisesRegex(ValueError,reason):compare.compare(r,c,m)

    def test_missing_peak_and_scalar_mismatch_fail_numeric_comparison(self):
        r,c,m=self.fixture()
        m['frames'][0]['rois']['Total']['G']=0.
        result=compare.compare(r,c,m)
        self.assertFalse(result['comparison_passed'])
        self.assertTrue(any('waveform' in error for error in result['errors']))
        self.assertTrue(any('support' in error for error in result['errors']))

    def test_reference_rejects_clock_gap(self):
        contract=ref.read_json(GEOMETRY);mask=ref.SiliconMask(contract)
        bad=dict(accepted_intervals=[dict(accepted_index=1,start_s=0.,end_s=1.,dt_s=1.),
                                     dict(accepted_index=2,start_s=2.,end_s=3.,dt_s=1.)])
        with self.assertRaisesRegex(ValueError,'gap'):ref.reference([source()],contract,bad,{'Total':mask.domain})


if __name__=='__main__':unittest.main()
