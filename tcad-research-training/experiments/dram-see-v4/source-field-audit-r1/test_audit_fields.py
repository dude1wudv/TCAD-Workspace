"""Independent offline counterexamples; synthetic fixtures are never research results."""
import copy
import csv
import io
import json
import math
from pathlib import Path
import tempfile
import tkinter
import unittest

HERE=Path(__file__).resolve().parent
import importlib.util
s=importlib.util.spec_from_file_location('_test_field_audit',HERE/'audit_fields.py')
a=importlib.util.module_from_spec(s)
exec(compile((HERE/'audit_fields.py').read_bytes(),str(HERE/'audit_fields.py'),'exec'),a.__dict__)


def fixture():
    times=[0.,.95e-9]+[.95e-9+i*.5e-12 for i in range(1,201)]+[4e-9]
    spec=a.r3.b.source_spec();proof=a.r3.b.offline_proof(spec)
    rows=[{'time':times[0],a.LEGACY:0.}];values={};index=[];logs=[]
    for i,(start,end) in enumerate(zip(times,times[1:]),1):
        # Independent erf CDF expression, not the production oracle.
        rate=(math.erf((end-1e-9)/(math.sqrt(2)*2e-12))-math.erf((start-1e-9)/(math.sqrt(2)*2e-12)))/(2*(end-start))
        rows.append({'time':end,a.LEGACY:rate/a.CONVERSION})
        if i==1 or i==len(times)-1:continue
        name=f'gstep_access_{i:04d}_des.tdr'
        r={'source_file':name,'accepted_index':i,'start_s':start,'end_s':end,'dt_s':end-start}
        index.append(r);v={};values[name]=v
        logs.extend([f'Computing BE-step from {start:.4e} s to {end:.4e} s (Stepsize: {end-start:.4e} s)',
                     'Finished, because...','Error smaller than 1 ( 1.0E-03 ).',f"    Writing plot '{name}' (TDR format) ... done."])
        for scope in a.SCOPES:
            roi='Total' if scope=='SILICON_NO_WINDOW' else scope
            q=proof['rois'][roi]['q_fC'];g=q*rate/a.CONVERSION
            rect=a.C['rois_um'][roi]
            v['G',scope]=g;v['XG',scope]=g*proof['rois'][roi]['centroid_x_um'];v['YG',scope]=g*proof['rois'][roi]['centroid_y_um']
            v['ONE',scope]=(rect[2]-rect[0])*(rect[3]-rect[1])
    return index,values,rows,spec,proof,'\n'.join(logs)


def csv_text(values):
    f=io.StringIO();w=csv.writer(f)
    w.writerow(['source_file','field','native_field','scope','operation','raw_value','command_status'])
    for name,v in values.items():
        for (role,scope),value in v.items():w.writerow([name,role,a.ROLES[role],scope,'integral',value,'OK'])
    return f.getvalue()


class FieldAuditTests(unittest.TestCase):
    def test_named_cleanup_revision_native_return_and_wrong_names(self):
        source=(HERE/'extract_fields_bounded_r2.tcl').read_text()
        prior=(HERE/'extract_fields_bounded.tcl').read_text()
        self.assertEqual(source[source.index('set windows {'):source.index('close $inventory')],
                         prior[prior.index('set windows {'):prior.index('close $inventory')])
        proc=source[source.index('proc releaseFrame {'):source.index('set windows {')]
        for mode,action in [('name','return [lindex $names 0]'),('zero','return 0'),('wrong','return WrongPlot'),('empty','return {}'),('multiple','return {Plot_data OtherPlot}'),('error','error failure')]:
            t=tkinter.Tcl();t.eval('set measurements unused; set mandatoryErrors 0; set release_order {}; set output_rows {}')
            t.eval('proc errorRow {sourceFile field scope operation value} {incr ::mandatoryErrors; lappend ::output_rows [list $operation $value ERROR]}')
            t.eval('proc csvRow {stream values} {lappend ::output_rows $values}')
            t.eval('proc remove_plots {names} {lappend ::release_order plots; '+action+'}')
            t.eval('proc remove_datasets {names} {lappend ::release_order datasets; return [lindex $names 0]}')
            t.eval(proc);t.call('releaseFrame','frame.tdr','Plot_data','data')
            self.assertEqual(int(t.call('set','mandatoryErrors')),0 if mode=='name' else 1)
            self.assertEqual(t.splitlist(t.call('set','release_order')),('plots','datasets'))

    def test_named_cleanup_audit_binds_inventory_and_preserves_old_failure(self):
        header='source_file,field,native_field,scope,operation,raw_value,command_status\n'
        good=header+'frame.tdr,,Plot_data,,remove_plots,Plot_data,OK\nframe.tdr,,data,,remove_datasets,data,OK\n'
        inv='source_file,dataset,object_type,native_name\nframe.tdr,data,plot,Plot_data\nframe.tdr,data,geometry,data\n'
        self.assertTrue(a.check_cleanup(good,['frame.tdr'],'exact_deleted_object_name',inv))
        with self.assertRaises(ValueError):a.check_cleanup(good,['frame.tdr'],'integer_zero',inv)
        for bad in (good.replace('remove_plots,Plot_data','remove_plots,WrongPlot'),good.replace(',Plot_data,,remove_plots',',WrongPlot,,remove_plots'),good.replace(',OK',',ERROR',1),good.replace('remove_datasets,data','remove_datasets,0')):
            with self.assertRaises(ValueError):a.check_cleanup(bad,['frame.tdr'],'exact_deleted_object_name',inv)
        with self.assertRaises(ValueError):a.check_cleanup(good,['frame.tdr'],'exact_deleted_object_name',inv.replace('plot,Plot_data','plot,OtherPlot'))

    def test_bounded_revision_changes_only_cleanup_and_status(self):
        original=(HERE/'extract_fields.tcl').read_text()
        bounded=(HERE/'extract_fields_bounded.tcl').read_text()
        self.assertTrue(tkinter.Tcl().call('info','complete',bounded))
        text='\n'.join(bounded.split('\n')[2:])
        start=text.index('proc releaseFrame {');end=text.index('set windows {',start)
        text=text[:start]+text[end:]
        text=text.replace('if {$missing} {releaseFrame $sourceFile $plot $data; continue}','if {$missing} {continue}')
        text=text.replace('        releaseFrame $sourceFile {} $data\n','')
        text=text.replace('        releaseFrame $sourceFile $plot $data\n','')
        text=text.replace('    releaseFrame $sourceFile $plot $data\n','')
        text=text.replace('puts $status "memory_release=plot_then_dataset_per_frame"\n','')
        self.assertEqual(text,original)

    def test_cleanup_order_error_and_nonzero_are_not_swallowed(self):
        text=(HERE/'extract_fields_bounded.tcl').read_text()
        procedure=text[text.index('proc releaseFrame {'):text.index('set windows {')]
        for mode in ('success','error','nonzero'):
            t=tkinter.Tcl()
            t.eval('set measurements unused; set mandatoryErrors 0; set release_order {}; set output_rows {}')
            t.eval('proc errorRow {sourceFile field scope operation value} {incr ::mandatoryErrors; lappend ::output_rows [list $operation $value ERROR]}')
            t.eval('proc csvRow {stream values} {lappend ::output_rows $values}')
            action={'success':'return 0','error':'error "synthetic cleanup error"','nonzero':'return 1'}[mode]
            t.eval('proc remove_plots {names} {lappend ::release_order plots; '+action+'}')
            t.eval('proc remove_datasets {names} {lappend ::release_order datasets; return 0}')
            t.eval(procedure);t.call('releaseFrame','frame.tdr','Plot_data','data')
            self.assertEqual(t.splitlist(t.call('set','release_order')),('plots','datasets'))
            self.assertEqual(int(t.call('set','mandatoryErrors')),0 if mode=='success' else 1)

    def test_explicit_extractor_whitelist_and_cleanup_evidence(self):
        for digest,name in a.EXTRACTORS.items():self.assertEqual(a.checked_extractor(digest,HERE/name),name)
        with self.assertRaisesRegex(ValueError,'Unregistered'):a.checked_extractor('0'*64,HERE/'extract_fields.tcl')
        with self.assertRaisesRegex(ValueError,'Executed extractor'):
            a.checked_extractor(next(k for k,v in a.EXTRACTORS.items() if v=='extract_fields_bounded.tcl'),HERE/'extract_fields.tcl')
        header='source_file,field,native_field,scope,operation,raw_value,command_status\n'
        rows=['frame.tdr,,,,remove_plots,0,OK\n','frame.tdr,,,,remove_datasets,0,OK\n']
        self.assertTrue(a.check_cleanup(header+''.join(rows),['frame.tdr']))
        for text in (header+rows[0],header+''.join(reversed(rows)),header+''.join(rows).replace(',0,OK',',1,OK',1),header+''.join(rows)+rows[1]):
            with self.assertRaises(ValueError):a.check_cleanup(text,['frame.tdr'])

    def test_full_time_bijection_and_missing_frame(self):
        index,v,rows,spec,proof,log=fixture()
        actual,boundary=a.index_frames(log,rows,list(v),True)
        self.assertEqual(len(actual),200);self.assertFalse(boundary)
        self.assertEqual(actual[0]['start_s'],.95e-9)
        with self.assertRaisesRegex(ValueError,'Missing/extra'):
            a.index_frames(log,rows,list(v)[1:],True)

    def test_failed_step_duplicate_write_and_untrusted_number(self):
        index,v,rows,spec,proof,log=fixture();names=list(v)
        with self.assertRaisesRegex(ValueError,'successful BE'):
            a.index_frames(log.replace('Error smaller than 1 ( 1.0E-03 ).',"Newton didn't converge",1),rows,names)
        duplicate=log.splitlines()[:4];duplicate.append(duplicate[-1])
        with self.assertRaisesRegex(ValueError,'more than once'):
            a.index_frames('\n'.join(duplicate),rows,[names[0]])
        # Arbitrary filenames do not change times: only the Writing association does.
        changed=log.replace(names[0],'not_time_7654321.tdr')
        mapped,_=a.index_frames(changed,rows,['not_time_7654321.tdr']+names[1:])
        self.assertEqual(mapped[0]['end_s'],rows[2]['time'])

    def test_measurement_missing_duplicate_error_nonfinite(self):
        index,v,*_=fixture();one={next(iter(v)):next(iter(v.values()))}
        raw=csv_text(one);self.assertEqual(a.parse_measurements(raw,list(one)),one)
        lines=raw.splitlines()
        for bad in ('\n'.join(lines[:-1]),raw+'\n'+lines[-1],raw.replace(',OK',',ERROR',1),raw.replace(',SFA_XG,',',WrongNative,',1)):
            with self.assertRaises(ValueError):a.parse_measurements(bad,list(one))
        broken=copy.deepcopy(one);broken[next(iter(one))]['G','Total']=float('nan')
        with self.assertRaisesRegex(ValueError,'Nonfinite'):a.parse_measurements(csv_text(broken),list(one))

    def test_true_moments_and_center_failure_remain_visible(self):
        index,v,rows,spec,proof,_=fixture();out={}
        self.assertTrue(a.full_metrics(index,v,rows,spec,proof,out))
        self.assertAlmostEqual(out['charge']['TDR_window_fC'],1.,places=12)
        for value in v.values():value['G','Center']=.78320354*value['G','SILICON_NO_WINDOW']
        with self.assertRaisesRegex(ValueError,'ROI fraction differs: Center'):
            a.full_metrics(index,v,rows,spec,proof,out)
        self.assertGreater(out['roi_fraction_checks']['Center']['abs_error'],.05)

    def test_centroid_not_theoretical_filled_and_time_shift_rejected(self):
        index,v,rows,spec,proof,_=fixture()
        for value in v.values():value['XG','SILICON_NO_WINDOW']=.45*value['G','SILICON_NO_WINDOW']
        out={}
        with self.assertRaisesRegex(ValueError,'moment centroid'):a.full_metrics(index,v,rows,spec,proof,out)
        index,v,rows,spec,proof,_=fixture()
        shifted=copy.deepcopy(index)
        for r in shifted:r['start_s']+=2e-12;r['end_s']+=2e-12
        with self.assertRaisesRegex(ValueError,'time centroid'):a.full_metrics(shifted,v,rows,spec,proof,{})

    def test_outside_legacy_charge_is_measured_not_forced_zero(self):
        index,v,rows,spec,proof,_=fixture()
        outside=.02;rows[-1][a.LEGACY]=outside/a.CONVERSION/(rows[-1]['time']-rows[-2]['time'])
        out={};a.full_metrics(index,v,rows,spec,proof,out)
        self.assertAlmostEqual(out['charge']['legacy_outside_window_fC'],outside,places=13)
        self.assertAlmostEqual(out['charge']['TDR_plus_measured_legacy_outside_fC'],1.02,places=13)

    def test_unknown_extraction_exit_cannot_pass(self):
        a.OUTPUT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=a.OUTPUT) as temp:
            folder=Path(temp)
            (folder/'field-extraction-record.json').write_text(json.dumps({'schema':'dram-see-v4-native-field-extraction-receipt-r1','svisual_exit_code':None}))
            with self.assertRaisesRegex(ValueError,'Unknown/nonzero extraction exit'):
                a.extraction_evidence(folder,None,{}, {})


if __name__=='__main__':unittest.main(verbosity=2)
