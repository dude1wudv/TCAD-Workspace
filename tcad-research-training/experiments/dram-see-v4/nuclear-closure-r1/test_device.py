"""Isolated offline device/audit counterexamples; never dispatch native tools."""
from contextlib import contextmanager
import copy
import csv
import io
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import common as c
import build_cases as b
import field_audit as f


@contextmanager
def sandbox():
    root=c.RT/'device-dev';root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='offline-test-',dir=root) as directory:
        yield Path(directory)


def event_fixture():
    return b.kernel().canonical_source(dict(schema='nuclear-closure-source-r1',geometry_sha256=c.sha(c.GEOMETRY),
        steps=[b.step('fixture-event-line',[.3,.2,-.2],[.6,.8,.2],.4,1.008e-9),
               b.step('fixture-event-point',[.4,.5,.21],[.4,.5,.21],.1,1.012e-9)],
        provenance=dict(synthetic=False,unit_test_fixture_only=True)))


def fake_binary(folder):
    path=folder/'pmi_nuclear_source.so.linux64';path.write_bytes(b'\x7fELFUNIT_TEST_NOT_A_REAL_SHARED_LIBRARY')
    return path


class InputContracts(unittest.TestCase):
    def test_all_fourteen_roles_generate_immutable_inputs(self):
        with sandbox() as out:
            event=event_fixture();mesh=out/'mesh.json';c.write(mesh,b.freeze_mesh(event));binary=fake_binary(out)
            for role in c.contract()['primary_roles']:
                with self.subTest(role=role):
                    target=out/role;manifest=b.build(role,target,event,binary,mesh)
                    self.assertEqual(manifest['role'],role)
                    self.assertTrue(b.check_project(target)['passed'])
                    self.assertEqual(c.read(target/'project.json')['name'],'v4-nuclear-closure-r1-'+role)
                    with self.assertRaisesRegex(ValueError,'immutable'):b.build(role,target,event,binary,mesh)

    def test_qualification_does_not_depend_on_selected_event(self):
        with sandbox() as out:
            binary=fake_binary(out)
            for role in ('qualification-zero','qualification-point'):
                b.build(role,out/role,None,binary)
            self.assertTrue(b.check_control(out/'qualification-zero',out/'qualification-point')['passed'])
            deck=(out/'qualification-point/device.cmd').read_text()
            self.assertIn('v(qs) v(qd) i(access,qs) i(access,qd)',deck)
            self.assertNotIn('"gate"',deck)

    def test_device_requires_selected_frozen_common_mesh(self):
        with sandbox() as out:
            with self.assertRaisesRegex(ValueError,'common mesh'):
                b.build('a0-m0-t0',out/'no-mesh',event_fixture(),fake_binary(out))
            self.assertFalse((out/'no-mesh').exists())

    def test_all_artificial_share_m0t0_zero_mesh_and_deck(self):
        with sandbox() as out:
            event=event_fixture();mesh=out/'mesh.json';c.write(mesh,b.freeze_mesh(event));binary=fake_binary(out)
            b.build('a0-m0-t0',out/'a0',event,binary,mesh)
            for role in ('artificial-line','artificial-point','artificial-mixed','artificial-segmented','event-m0-t0'):
                b.build(role,out/role,event,binary,mesh)
                self.assertTrue(b.check_control(out/'a0',out/role)['passed'])

    def test_input_order_does_not_change_common_mesh_or_native_source(self):
        first=event_fixture();second=copy.deepcopy(first);second['steps'].reverse()
        self.assertEqual(b.freeze_mesh(first),b.freeze_mesh(second))
        self.assertEqual(b.kernel().native_bytes(first),b.kernel().native_bytes(second))

    def test_event_identity_change_cannot_reuse_mesh(self):
        with sandbox() as out:
            first=event_fixture();mesh=out/'mesh.json';c.write(mesh,b.freeze_mesh(first))
            second=copy.deepcopy(first);second['steps'][0]['charge_fC']*=2
            with self.assertRaisesRegex(ValueError,'does not reproduce'):
                b.build('event-m0-t0',out/'wrong',second,fake_binary(out),mesh)

    def test_mesh_m1_scales_every_length_target_and_keeps_geometry(self):
        mesh=b.freeze_mesh(event_fixture())
        a=b.render_geometry(mesh,'m0',False).decode();z=b.render_geometry(mesh,'m1',False).decode()
        fixed=lambda text:[line for line in text.splitlines() if 'define-refinement-size' not in line]
        self.assertEqual(fixed(a),fixed(z))
        for win in mesh['windows']:
            desired=' '.join(b.number(x*.75) for x in win['max_size_um']+win['min_size_um'])
            self.assertIn('"Mesh.'+win['name']+'" '+desired,z)

    def test_t1_halves_all_stage_max_steps_and_contains_t0_points(self):
        mesh=b.freeze_mesh(event_fixture());a,z=b.time_blocks(mesh,'t0'),b.time_blocks(mesh,'t1')
        self.assertEqual(len(a),len(z))
        for coarse,fine in zip(a,z):
            self.assertEqual(coarse['initial_s'],fine['initial_s'])
            self.assertEqual(coarse['final_s'],fine['final_s'])
            self.assertEqual(fine['max_step_s'],coarse['max_step_s']/2)
            self.assertTrue(set(coarse['turning_points_s'])<=set(fine['turning_points_s']))
        self.assertTrue(all(x['max_step_s']<=5e-12+1e-20 for x in a if x['initial_s']>=3e-9))

    def test_no_heavyion_or_interpolated_plot_intervals_and_all_clock_fields(self):
        deck=b.render_deck(b.time_blocks(b.freeze_mesh(event_fixture()),'t0'),False).decode()
        self.assertNotIn('HeavyIon',deck);self.assertNotIn('Intervals=',deck)
        self.assertIn('TurningPoints( (Condition (Time(',deck)
        for i in range(4):self.assertIn('PMIUserField'+str(i),deck)
        self.assertIn('PMIPath="."',deck);self.assertIn('Transient=BE',deck)

    def test_changed_source_input_bytes_rejected(self):
        with sandbox() as out:
            binary=fake_binary(out);b.build('qualification-point',out/'point',None,binary)
            with (out/'point/sources.dat').open('ab') as stream:stream.write(b'changed\n')
            with self.assertRaisesRegex(ValueError,'bytes changed'):b.check_project(out/'point')

    def test_non_elf_or_unknown_role_does_not_create_input(self):
        with sandbox() as out:
            binary=fake_binary(out);binary.write_bytes(b'not-elf')
            with self.assertRaisesRegex(ValueError,'not an ELF'):b.build('qualification-point',out/'bad',None,binary)
            with self.assertRaisesRegex(ValueError,'14 primary'):b.build('extra-event',out/'extra',None,binary)
            self.assertFalse((out/'bad').exists());self.assertFalse((out/'extra').exists())


def frame_fixture():
    params={'qualification':True,'source_windows_s':[[.984e-9,1.016e-9]],
            'time_blocks':[dict(index=0,initial_s=.984e-9,final_s=1.016e-9,max_step_s=8e-12,turning_points_s=[],active_source=True)]}
    times=[0.,.984e-9,.992e-9,1e-9,1.008e-9,1.016e-9,4e-9]
    source=b.artificial_source('qualification-point');names=[];index=[];log=[]
    rows=[]
    for time in times:rows.append({'time':time,f.SCALAR:0.})
    for i,(lo,hi) in enumerate(zip(times,times[1:]),1):
        q=b.kernel().integrated(source,b.QUAL_BOX,[lo,hi])['charge_fC']
        rows[i][f.SCALAR]=-q/(f.CONVERSION*(hi-lo))
        if i in (1,len(times)-1):continue
        name='gstep_b000_'+str(i)+'_access_des.tdr';names.append(name)
        index.append(dict(source_file=name,accepted_index=i,start_s=lo,end_s=hi,dt_s=hi-lo))
        log += ['Computing BE-step from '+b.number(lo)+' s to '+b.number(hi)+' s (Stepsize: '+b.number(hi-lo)+' s)',
                'Error smaller than 1',"Writing plot '"+name+"' (TDR format) ... done."]
    return params,source,names,index,rows,'\n'.join(log)


def ideal_values(params,source,index):
    boxes=f.roi_boxes(params['qualification']);result={}
    for item in index:
        values={};lo,hi=item['start_s'],item['end_s'];dt=hi-lo
        for scope,box in [('SILICON_NO_WINDOW',boxes['Total'])]+list(boxes.items()):
            expected=b.kernel().integrated(source,box,[lo,hi]);g=expected['charge_fC']/(f.CONVERSION*dt)
            for role,value in [('ONE',math.prod(z-a for a,z in zip(*box))),('G',g),('G_CHECK',g)]+[
                    (axis+'G',expected['spatial_first_moment_fC_um'][j]/(f.CONVERSION*dt)) for j,axis in enumerate('XYZ')]:
                values[role,scope,'integral']=value
        for j,axis in enumerate('XYZ'):
            values[axis,'SILICON_NO_WINDOW','-min']=b.QUAL_BOX[0][j]
            values[axis,'SILICON_NO_WINDOW','-max']=b.QUAL_BOX[1][j]
        for role,value in [('N',2.),('P',3.)]:values[role,'SILICON_NO_WINDOW','integral']=value
        for role,value in [('G',0.),('G_CHECK',0.),('T_PMI',hi),('DT_PMI',dt),('STEP_PMI',3.)]:
            for op in ('-min','-max'):values[role,'SILICON_NO_WINDOW',op]=value
        result[item['source_file']]=values
    return result


class NativeFieldGates(unittest.TestCase):
    def test_all_real_accepted_intervals_required_by_frame_index(self):
        params,_,names,index,rows,log=frame_fixture()
        got,_=f.index_frames(log,rows,names,params)
        self.assertEqual([v['accepted_index'] for v in got],[v['accepted_index'] for v in index])
        with self.assertRaisesRegex(ValueError,'Missing/extra'):f.index_frames(log,rows,names[:-1],params)

    def test_wrong_frame_block_or_duplicate_writing_rejected(self):
        params,_,names,_,rows,log=frame_fixture()
        wrong=names[0].replace('b000','b001');bad=log.replace(names[0],wrong)
        with self.assertRaisesRegex(ValueError,'prefix'):f.index_frames(bad,rows,[wrong]+names[1:],params)
        with self.assertRaisesRegex(ValueError,'more than once'):f.index_frames(log+'\n'+log,rows,names,params)

    def test_checkpoints_are_native_not_interpolated(self):
        params={'time_blocks':[dict(initial_s=0.,final_s=2e-9,max_step_s=2e-9,turning_points_s=[1e-9])]}
        with self.assertRaisesRegex(ValueError,'native checkpoint'):f.check_checkpoints([{'time':0.},{'time':2e-9}],params)
        self.assertTrue(f.check_checkpoints([{'time':x} for x in (0.,1e-9,2e-9)],params))

    def test_ideal_oracle_fixture_and_clock_counterexample(self):
        params,source,names,index,rows,_=frame_fixture();values=ideal_values(params,source,index)
        result,frames=f.native_metrics(index,values,rows,source,params)
        self.assertTrue(result['passed'],result['errors'])
        self.assertEqual(len(frames),len(index));self.assertIn('N_raw',frames[0]);self.assertIn('P_raw',frames[0])
        values[names[0]]['DT_PMI','SILICON_NO_WINDOW','-min']=0.
        result,_=f.native_metrics(index,values,rows,source,params)
        self.assertFalse(result['passed']);self.assertTrue(any('clock/step' in e for e in result['errors']))

    def test_wrong_user_rate_or_source_amount_cannot_pass(self):
        params,source,names,index,rows,_=frame_fixture();values=ideal_values(params,source,index)
        values[names[1]]['G_CHECK','SILICON_NO_WINDOW','integral']*=2
        result,_=f.native_metrics(index,values,rows,source,params)
        self.assertFalse(result['passed']);self.assertTrue(any('user rate' in e for e in result['errors']))
        values=ideal_values(params,source,index)
        for data in values.values():
            for key in list(data):
                if key[0] in ('G','G_CHECK','XG','YG','ZG') and key[2]=='integral':data[key]*=2
        result,_=f.native_metrics(index,values,rows,source,params)
        self.assertFalse(result['passed']);self.assertTrue(any('charge exceeds' in e for e in result['errors']))

    def test_parse_rejects_missing_clock_and_negative_source(self):
        params,source,names,index,_,_=frame_fixture();values=ideal_values(params,source,index)
        fields=['source_file','field','native_field','scope','operation','raw_value','command_status']
        mapping={**f.NATIVE_FIELDS,**f.OTHER_FIELDS,**{a:a for a in 'XYZ'}}
        def text(missing=False,negative=False):
            out=io.StringIO();writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader()
            for name,data in values.items():
                for (role,scope,op),value in data.items():
                    if missing and role=='DT_PMI':continue
                    if negative and role=='G':value=-1.
                    writer.writerow(dict(source_file=name,field=role,native_field=mapping[role],scope=scope,operation=op,raw_value=value,command_status='OK'))
            return out.getvalue()
        self.assertEqual(f.parse_measurements(text(),names,params),values)
        with self.assertRaisesRegex(ValueError,'Missing native'):f.parse_measurements(text(missing=True),names,params)
        with self.assertRaisesRegex(ValueError,'Negative native'):f.parse_measurements(text(negative=True),names,params)

    def test_native_charge_has_no_offline_absolute_tolerance_floor(self):
        params,source,names,index,rows,_=frame_fixture()
        for item in source['steps']:item['charge_fC']*=1e-10
        for row in rows:row[f.SCALAR]*=1e-10
        values=ideal_values(params,source,index)
        for data in values.values():
            for key in data:
                if key[0] in ('G','G_CHECK','XG','YG','ZG') and key[2]=='integral':data[key]*=2
        result,_=f.native_metrics(index,values,rows,source,params)
        self.assertFalse(result['passed'])
        self.assertTrue(any('charge exceeds' in e for e in result['errors']))

    def test_receipt_recovery_reproduces_without_overwriting(self):
        with sandbox() as out:
            (out/'collected').mkdir()
            c.write(out/'collected/source-evidence.json',dict(source_run_id='unit-test-not-a-native-run'))
            receipt=dict(schema='unit-test-receipt',physical_acceptance=False)
            with patch.object(f,'source_provenance',return_value=({},{})),patch.object(f,'operation_evidence',return_value=({},receipt)):
                first=f.collect_receipt(out);raw=(out/'field-extraction-record.json').read_bytes()
                stamp=(out/'field-extraction-record.json').stat().st_mtime_ns
                self.assertEqual(first,f.collect_receipt(out/'collected'))
                self.assertEqual((out/'field-extraction-record.json').read_bytes(),raw)
                self.assertEqual((out/'field-extraction-record.json').stat().st_mtime_ns,stamp)
            with patch.object(f,'source_provenance',return_value=({},{})),patch.object(f,'operation_evidence',return_value=({},dict(receipt,changed=True))):
                with self.assertRaisesRegex(ValueError,'does not reproduce'):f.collect_receipt(out)
            self.assertEqual((out/'field-extraction-record.json').read_bytes(),raw)

    def test_extractor_is_reference_only_and_requires_PMI_clock_fields(self):
        script=(c.HERE/'extract_fields.tcl').read_text()
        for token in ('GROUP_BEFORE','FRAME_BEFORE','FRAME_AFTER','GROUP_AFTER','originalDirectoryIdentity','sha256sum -- $original'):
            self.assertIn(token,script)
        for i in range(4):self.assertIn('PMIUserField'+str(i),script)
        self.assertNotIn('HeavyIonGeneration',script)
        self.assertNotIn('file delete',script)

    def test_native_serial_metadata_comes_from_actual_banner_and_affinity(self):
        banner='  Version W-2024.09 for linux64 - Aug 16, 2024\n  Changelist number: 9150440, Compile host: fixture\nMultithreading will use 1 threads.\n'
        metadata='svisual_requested=/usr/synopsys/sentaurus/W-2024.09/bin/svisual\nsvisual_resolved=/usr/synopsys/sentaurus/W-2024.09/tcad/current/linux64/bin/svisual\nOMP_NUM_THREADS=1\nOPENBLAS_NUM_THREADS=1\nMKL_NUM_THREADS=1\n'+banner
        affinity='Threads:\t1\nCpus_allowed_list:\t0\n'
        result=f.serial_metadata(metadata,affinity,banner)
        self.assertTrue(result['passed']);self.assertEqual(result['additional_native_invocations'],0)
        for broken in (metadata.replace('OMP_NUM_THREADS=1','OMP_NUM_THREADS=2'),
                       metadata.replace('OPENBLAS_NUM_THREADS=1\n',''),
                       metadata.replace('Multithreading will use 1 threads.\n',''),
                       metadata+'OMP_NUM_THREADS=1\n'):
            with self.subTest(metadata=broken),self.assertRaises(ValueError):f.serial_metadata(broken,affinity,banner)
        for broken in (affinity.replace('Threads:\t1','Threads:\t2'),
                       affinity.replace('Cpus_allowed_list:\t0','Cpus_allowed_list:\t0-1'),
                       affinity.replace('Cpus_allowed_list:\t0','Cpus_allowed_list:\t0,2')):
            with self.subTest(affinity=broken),self.assertRaises(ValueError):f.serial_metadata(metadata,broken,banner)
        for old,new in [('1 threads.','2 threads.'),('W-2024.09','W-2025.03'),('9150440','9999999')]:
            with self.subTest(native=old),self.assertRaises(ValueError):
                f.serial_metadata(metadata.replace(old,new),affinity,banner.replace(old,new))
        with self.assertRaisesRegex(ValueError,'not reproduced'):
            f.serial_metadata(metadata,affinity,banner.replace('fixture','different'))

    def test_field_operation_produces_every_serial_metadata_input(self):
        task=f.render_task()
        self.assertIn('} > tool-versions.txt',task)
        self.assertIn('svisual.log >> tool-versions.txt',task)
        for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
            self.assertIn('$'+name,task)
        self.assertEqual(task.count('svisual --threads 1 --max_threads 1'),1)
        self.assertTrue({'tool-versions.txt','affinity.txt'}<=f.NATIVE_OUTPUTS)
        script=(c.HERE/'field_audit.py').read_text()
        self.assertNotIn('lib.prior.r3.field.prior._serial_metadata',script)


class ResourceGuard(unittest.TestCase):
    def test_native_guard_blocks_unknown_mesh_and_low_space_without_changes(self):
        env={'__name__':'_offline_guard_test'};exec(compile(b.GUARD,'generated-mesh-guard','exec'),env)
        with sandbox() as out:
            policy=b.resource_policy(b.time_blocks(b.qualified_mesh(),'t0'))
            c.write(out/'parameters.json',dict(resource_guard=policy))
            c.write(out/'input-manifest.json',dict(schema='nuclear-closure-inputs-r1',files_sha256={}))
            (out/'cell_msh.tdr').write_bytes(b'UNIT_TEST_MESH')
            (out/'cell_msh.log').write_text('Optimizing elements...done. (100 vertices)\n')
            actual_read=Path.read_text
            def read_text(path,*args,**kwargs):
                if path.as_posix()=='/proc/meminfo':return 'MemAvailable: 16777216 kB\n'
                return actual_read(path,*args,**kwargs)
            import os
            previous=Path.cwd()
            try:
                os.chdir(out)
                with patch.object(Path,'read_text',read_text),patch('shutil.disk_usage',return_value=SimpleNamespace(free=0)):
                    report=env['inspect']()
                    self.assertFalse(report['passed']);self.assertFalse(report['checks']['disk'])
                    self.assertEqual((out/'cell_msh.tdr').read_bytes(),b'UNIT_TEST_MESH')
                (out/'cell_msh.log').write_text('unknown native mesh format\n')
                with patch.object(Path,'read_text',read_text),self.assertRaisesRegex(ValueError,'mesh vertex'):env['inspect']()
            finally:os.chdir(previous)


if __name__=='__main__':unittest.main()
