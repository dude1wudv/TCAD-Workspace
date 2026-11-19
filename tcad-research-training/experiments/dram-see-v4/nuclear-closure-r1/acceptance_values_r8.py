# Independent native value parsing identity; physical thresholds unchanged.
# Independent field-implementation binding; electrical gates unchanged.
"""Independent electrical observables, BE current balance and full-grid comparisons."""
import bisect
import csv
import io
import math
from datetime import datetime,timezone
from pathlib import Path
import common as c


def original():
    return c.module(c.HERE.parent/'source-probe/audit_probe.py','_nc_original_archive_parser')


def curves(run):
    old=original();out={}
    with old.Archive(Path(run)/'results.tar') as archive:
        for key,name in [('circuit','circuit.plt'),('device','access_device.plt')]:
            names,raw=old.parse_plt(archive.read(name).decode())
            c.require('time' in names,'Native curve lacks time')
            out[key+'_raw']=raw
            out[key]=old.legacy.clean(raw)
            c.require(out[key][0]['time']==0 and abs(out[key][-1]['time']-4e-9)<=1e-20,'Incomplete 0..4 ns curve')
    return out


def samples(rows,key,times):
    x=[r['time'] for r in rows];result=[]
    for t in times:
        c.require(x[0]-1e-21<=t<=x[-1]+1e-21,'Curve extrapolation forbidden')
        i=bisect.bisect_left(x,t)
        if i==len(x):i-=1
        if abs(x[i]-t)<=1e-21:result.append(rows[i][key]);continue
        c.require(i>0,'Missing interpolation bracket')
        f=(t-x[i-1])/(x[i]-x[i-1]);result.append(rows[i-1][key]*(1-f)+rows[i][key]*f)
    return result


def be_integrals(rows,key,times,start=.95e-9):
    """Right-endpoint native BE intervals, including fractional boundary intervals."""
    c.require(all(rows[i]['time']>rows[i-1]['time'] for i in range(1,len(rows))),'Nonunique accepted times')
    x=[r['time'] for r in rows];prefix=[0.0]
    for left,right in zip(rows,rows[1:]):
        prefix.append(prefix[-1]+right[key]*(right['time']-left['time']))
    def evaluate(t):
        c.require(x[0]<=t<=x[-1],'BE extrapolation forbidden')
        i=bisect.bisect_right(x,t)-1
        if i==len(x)-1:return prefix[i]
        return prefix[i]+rows[i+1][key]*(t-x[i])
    zero=evaluate(start)
    return [(evaluate(t)-zero)*1e15 for t in times]


def matched_response(signal,control):
    times=sorted({r['time'] for bundle in (signal,control) for r in bundle['circuit']})
    out=[{'time_s':t} for t in times]
    for key in ('v(sn)','v(bl)','v(ref)','v(wl)'):
        values=samples(signal['circuit'],key,times);zeros=samples(control['circuit'],key,times)
        for row,v,z in zip(out,values,zeros):row[key]=v;row['a0_'+key]=z;row['delta_'+key]=v-z
    return out


def circuit_balance(signal,control):
    start=.95e-9;times=sorted({start,4e-9}|{r['time'] for b in (signal,control) for r in b['circuit'] if r['time']>=start})
    voltage=[samples(b['circuit'],'v(sn)',times) for b in (signal,control)]
    cap=1e-14
    qstore=[cap*((v-voltage[0][0])-(z-voltage[1][0]))*1e15 for v,z in zip(*voltage)]
    independent=[];parts={}
    for key in ('i(access,sn)','i(rsn,sn)'):
        parts[key]=[a-b for a,b in zip(be_integrals(signal['circuit'],key,times,start),be_integrals(control['circuit'],key,times,start))]
    qterminal=[a+b for a,b in zip(parts['i(access,sn)'],parts['i(rsn,sn)'])]
    residual=[a+b for a,b in zip(qstore,qterminal)]
    scale=max([abs(v) for v in qstore+qterminal]+[0.0])
    tol=c.contract()['tolerances'];limit=max(tol['kcl_charge_abs_fC'],tol['kcl_relative']*scale)
    peak=max(map(abs,residual));index=max(range(len(times)),key=lambda i:abs(residual[i]))
    return dict(passed=peak<=limit,maximum_residual_fC=peak,limit_fC=limit,charge_scale_fC=scale,
        worst_time_s=times[index],storage_capacitance_F=cap,interval_s=[start,4e-9],
        terminal_charge_fC=parts['i(access,sn)'][-1],leakage_charge_fC=parts['i(rsn,sn)'][-1],
        definition='C times signal-minus-A0 voltage change plus independently BE-integrated access/drain and storage-leak currents; no use of capacitor current as a substitute',
        rows=[dict(time_s=t,delta_storage_fC=a,delta_terminal_fC=b,residual_fC=r) for t,a,b,r in zip(times,qstore,qterminal,residual)])


def csv_write(path,rows):
    c.require(rows,'No data for CSV')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def csv_verify_or_write(path,rows):
    c.require(rows,'No data for CSV')
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
    writer.writeheader();writer.writerows(rows);data=stream.getvalue().encode('utf-8')
    if path.exists():c.require(path.read_bytes()==data,'Stored comparison CSV does not reproduce')
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as handle:handle.write(data)


def json_verify_or_write(path,value):
    if path.exists():c.require(c.read(path)==value,'Stored comparison does not reproduce')
    else:c.write(path,value)


def gate(role):
    path=c.RT/'device/gates'/(role+'.json');value=c.read(path)
    c.require(value['passed'] is True and value['role']==role,'Role not accepted')
    c.require(value['acceptance_sha256']==c.sha(Path(__file__)),'Acceptance code changed')
    for item in value['evidence']:c.check_ref(item)
    return value


def load(role):
    g=gate(role);project=c.ROOT/g['project'];run=c.ROOT/g['run']
    builder=c.module(c.HERE/'build_cases.py','_nc_accept_builder')
    builder.check_project(project)
    field=c.read(c.ROOT/g['field_audit'])
    c.require(field['field_audit_sha256']==c.sha(c.HERE/'field_audit_values_r8.py') and field['extractor_sha256']==c.sha(c.HERE/'extract_fields.tcl'),'Field implementation changed')
    c.require(field['archive_sha256']==c.sha(run/'results.tar') and field['manifest_sha256']==c.sha(run/'manifest.json'),'Raw result changed after acceptance')
    c.require(field['source_sha256']==builder.digest(c.read(project/'source-spec.json')),'Field source changed')
    result=dict(role=role,project=project,run=run,curves=curves(run),parameters=c.read(project/'parameters.json'),gate=g,field=field)
    return result


def accept(role,run,project,field_path,attempt_path):
    folder=c.RT/'device/audits'/role
    if folder.exists():
        if (folder/'audit.json').exists():c.require(c.read(folder/'audit.json')['passed'] is True,'Prior scientific failure must be diagnosed before a new audit revision')
        # An interrupted publication is reconstructed in a new evidence directory.
        # The original partial/successful audit and every byte remain intact.
        folder=folder.parent/(role+'-recovery-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    folder.mkdir(parents=True)
    report=dict(schema='nuclear-closure-response-audit-r1',role=role,passed=False,engineering_completed=False,
        calibration_passed=False,persistent_upset_label=None,created_utc=c.utc(),errors=[],acceptance_sha256=c.sha(Path(__file__)))
    evidence=[c.ref(attempt_path),c.ref(field_path),c.ref(Path(run)/'manifest.json'),c.ref(Path(project)/'input-manifest.json')]
    try:
        launch=c.read(attempt_path)
        c.require(launch['kind']=='tcad' and launch['role']==role and launch['exit_code']==0,'Original TCAD runner exit unknown or failed')
        field=c.read(field_path)
        c.require(field['schema']=='nuclear-closure-field-audit-r1' and field['passed'] is True and not field['errors'],'Native full-frame audit failed')
        c.require(field['run_id']==Path(run).name and field['role']==role,'Field run/role differs')
        f=c.module(c.HERE/'field_audit_values_r8.py','_nc_response_field')
        manifest,proof=f.source_provenance(run,project)
        for key in ('archive_sha256','manifest_sha256','source_sha256','mesh_sha256'):
            c.require(field[key]==proof[key],'Field and original native evidence differ: '+key)
        c.require(field['field_audit_sha256']==c.sha(c.HERE/'field_audit_values_r8.py') and field['extractor_sha256']==c.sha(c.HERE/'extract_fields.tcl'),'Field implementation differs')
        c.require(field['contract_sha256']==c.sha(c.HERE/'contract.json'),'Field contract changed')
        operation=c.check_ref(field['extraction_record']).parent
        recomputed=f.audit(run,operation,project)
        ignored={'frames_csv_path','frames_csv_sha256'}
        c.require({k:v for k,v in field.items() if k not in ignored}==recomputed,'Saved full-frame audit does not reproduce')
        c.require(c.sha(Path(field['frames_csv_path']))==field['frames_csv_sha256'],'Full-frame CSV changed')
        evidence.extend([c.ref(Path(run)/'results.tar'),c.ref(Path(field['frames_csv_path']))])
        value=curves(run);p=c.read(Path(project)/'parameters.json')
        report.update(engineering_completed=True,run_id=Path(run).name,native_source=field['native_metrics'])
        old=original()
        with old.Archive(Path(run)/'results.tar') as archive:
            resource=__import__('json').loads(archive.read('mesh-resource-report.json'))
            c.require(resource.get('passed') is True,'Actual mesh resource gate failed')
            c.require(archive.read('mesh-resource-report.json')==archive.read('mesh-resource-passed.json'),'Native mesh guard marker mismatch')
            c.require(resource['mesh_sha256']==field['mesh_sha256'],'Resource measurement belongs to different mesh')
            report['actual_cost']=dict(wall_seconds=launch.get('wall_seconds'),archive_bytes=(Path(run)/'results.tar').stat().st_size,
                original_output_bytes=sum(m.size for m in archive.members.values()),
                field_frame_bytes=sum(m.size for n,m in archive.members.items() if n.startswith('gstep_') and n.endswith('.tdr')),
                native_mesh=resource,peak_memory_bytes=None)
        for key in ('circuit','device'):
            csv_write(folder/(key+'-all-native.csv'),value[key+'_raw'])
        if not role.startswith(('a0-','qualification-')):
            zero=load(p['control_role']);builder=c.module(c.HERE/'build_cases.py','_nc_matching_builder')
            report['matching']=builder.check_control(zero['project'],project)
            c.require(field['mesh_sha256']==zero['field']['mesh_sha256'],'Actual native paired meshes differ')
            balance=circuit_balance(value,zero['curves']);csv_write(folder/'independent-circuit-balance.csv',balance.pop('rows'))
            report['circuit_balance']=balance
            response=matched_response(value,zero['curves']);csv_write(folder/'matched-response.csv',response)
            report['first_readout_margin_V']=samples(value['circuit'],'v(bl)',[4e-9])[0]-samples(value['circuit'],'v(ref)',[4e-9])[0]
            c.require(balance['passed'],'Independent circuit conservation failed')
            evidence.append(c.ref(c.RT/'device/gates'/(p['control_role']+'.json')))
        report['passed']=True
    except Exception as exc:report['errors'].append(repr(exc))
    c.write(folder/'audit.json',report)
    if report['passed']:
        evidence+=[c.ref(x) for x in sorted(folder.iterdir()) if x.is_file()]
        c.write(c.RT/'device/gates'/(role+'.json'),dict(schema='nuclear-closure-role-gate-r1',role=role,passed=True,
            run=Path(run).relative_to(c.ROOT).as_posix(),project=Path(project).relative_to(c.ROOT).as_posix(),
            field_audit=Path(field_path).relative_to(c.ROOT).as_posix(),acceptance_sha256=c.sha(Path(__file__)),evidence=evidence))
    return report


def compare_roles(left,right,mode='refinement'):
    a,b=load(left),load(right);ca=load(a['parameters']['control_role']);cb=load(b['parameters']['control_role'])
    pa,pb=a['parameters'],b['parameters']
    for key in ('common_mesh_manifest_sha256','pmi_binary_sha256','geometry_contract_sha256','dimension','stored_bit','source_windows_s'):
        c.require(pa[key]==pb[key],'Cross-case physical/common-mesh identity differs: '+key)
    if mode=='refinement':
        c.require(pa['source_sha256']==pb['source_sha256'],'Matrix cases do not contain the same complete event')
        c.require([left.removeprefix('event-'),right.removeprefix('event-')] in c.contract()['numerical']['comparisons'],'Comparison outside frozen matrix')
    else:
        c.require([left,right]==['artificial-mixed','artificial-segmented'],'Unregistered equivalent-source pair')
        c.require(pa['matching_contract']==pb['matching_contract'],'Equivalent-source numerical settings differ')
    same_mesh=pa['mesh_key']==pb['mesh_key']
    c.require((a['field']['mesh_sha256']==b['field']['mesh_sha256'])==same_mesh,'Actual mesh identity does not follow frozen mesh comparison')
    bundles=[a,b,ca,cb]
    times=sorted({r['time'] for x in bundles for r in x['curves']['circuit']})
    tol=c.contract()['tolerances'];report=dict(left=left,right=right,mode=mode,passed=True,metrics={},all_union_times_retained=True)
    rows=[dict(time_s=t) for t in times]
    for key in ('v(sn)','v(bl)'):
        vs=[samples(x['curves']['circuit'],key,times) for x in bundles]
        da=[x-y for x,y in zip(vs[0],vs[2])];db=[x-y for x,y in zip(vs[1],vs[3])]
        difference=[x-y for x,y in zip(da,db)];peak=max(map(abs,da+db));error=max(map(abs,difference))
        limit=tol['equivalent_voltage_abs_V'] if mode=='equivalent' else max(tol['refinement_voltage_abs_V'],tol['refinement_voltage_relative']*peak)
        report['metrics'][key]=dict(error_V=error,limit_V=limit,perturbation_peak_V=peak,passed=error<=limit)
        report['passed'] &= error<=limit
        for row,x,y,d in zip(rows,da,db,difference):row['left_'+key]=x;row['right_'+key]=y;row['difference_'+key]=d
    charge=[]
    for x,z in ((a,ca),(b,cb)):
        charge.append(be_integrals(x['curves']['circuit'],'i(access,sn)',[4e-9])[0]-be_integrals(z['curves']['circuit'],'i(access,sn)',[4e-9])[0])
    qerror=abs(charge[0]-charge[1]);qlimit=tol['equivalent_charge_abs_fC'] if mode=='equivalent' else tol['refinement_charge_relative']*abs(charge[0])
    report['metrics']['independent_collected_charge']=dict(values_fC=charge,error_fC=qerror,limit_fC=qlimit,passed=qerror<=qlimit)
    report['passed'] &= qerror<=qlimit
    # Source total is independently audited against the fixed analytic source in each run.
    native_key='IntegrSemiconductor PMIRecombination'
    qnative=[]
    for x in (a,b):qnative.append(-be_integrals(x['curves']['device'],native_key,[4e-9],0)[0]*1.602176634e-19*1e-12)
    # Native volume integral is expressed in um^3; convert pairs/cm^3 before C -> fC.
    qerror=abs(qnative[0]-qnative[1]);qlimit=tol['equivalent_charge_abs_fC'] if mode=='equivalent' else tol['refinement_charge_relative']*abs(qnative[0])
    report['metrics']['native_generated_charge']=dict(values_fC=qnative,error_fC=qerror,limit_fC=qlimit,passed=qerror<=qlimit)
    report['passed'] &= qerror<=qlimit
    if mode=='equivalent':
        dtimes=sorted({r['time'] for x in (a,b) for r in x['curves']['device']})
        for dataset,key,grid,absolute,relative in [('device',native_key,dtimes,0.0,tol['equivalent_generation_relative']),
                ('circuit','i(access,sn)',times,tol['equivalent_current_abs_A'],tol['equivalent_current_relative']),
                ('circuit','i(access,bl)',times,tol['equivalent_current_abs_A'],tol['equivalent_current_relative'])]:
            va=samples(a['curves'][dataset],key,grid);vb=samples(b['curves'][dataset],key,grid)
            err=max(abs(x-y) for x,y in zip(va,vb));limit=max(absolute,relative*max(map(abs,va)))
            report['metrics'][key]=dict(error=err,limit=limit,passed=err<=limit);report['passed'] &= err<=limit
    report['evidence']=[c.ref(c.RT/'device/gates'/(x['role']+'.json')) for x in bundles]
    return report,rows


def complete_matrix():
    dest=c.RT/'device/matrix';dest.mkdir(parents=True,exist_ok=True);results=[]
    pairs=[('artificial-mixed','artificial-segmented','equivalent')]+[
        ('event-'+a,'event-'+b,'refinement') for a,b in c.contract()['numerical']['comparisons']]
    for left,right,mode in pairs:
        report,rows=compare_roles(left,right,mode);name=left+'--'+right
        json_verify_or_write(dest/(name+'.json'),report);csv_verify_or_write(dest/(name+'.csv'),rows);results.append(report)
    report=dict(schema='nuclear-closure-numerical-matrix-r1',passed=all(r['passed'] for r in results),comparisons=results,
       interpretation='Only this event at the measured two mesh and two time settings; no universal or asymptotic convergence claim')
    json_verify_or_write(dest/'summary.json',report)
    return report
