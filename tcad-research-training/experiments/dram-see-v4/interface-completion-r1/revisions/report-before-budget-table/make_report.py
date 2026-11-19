"""Read-only evidence report; writes a new UTC-unique reports directory only.

Use the bundled Python (ReportLab) and bundled Node/sharp for static SVG/PNG.
No SSH, solver, cleanup, installation, original document editing or labels.
"""
import argparse
import csv
from datetime import datetime,timezone
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import subprocess
import uuid

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
RT=ROOT/'local_runtime/dram-see-v4'
STATE=RT/'interface-completion-r1'
OUTPUT=STATE/'reports'
V5=RT/'source-interface-r5'


def module(path,name):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s)
    exec(compile(path.read_bytes(),str(path),'exec'),m.__dict__);return m


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def require(ok,message):
    if not ok:raise ValueError(message)
def link(path,label=None):return '['+(label or Path(path).name)+']('+Path(path).resolve().as_posix()+')'
def reference(path):return {'path':Path(path).resolve().as_posix(),'sha256':sha(path)}
def table(rows,keys):
    clean=lambda v:str(v).replace('|','／').replace('\n','；')
    return '| '+' | '.join(keys)+' |\n|'+'|'.join(['---']*len(keys))+'|\n'+''.join('| '+' | '.join(clean(r.get(k,'')) for k in keys)+' |\n' for r in rows)


def figure(folder,name,title,xlabel,ylabel,series,style='line',categories=None):
    """ReportLab scientific vector figure; sharp rasterizes the SAME SVG to PNG."""
    from reportlab.graphics.shapes import Drawing,Line,String,PolyLine,Rect,Circle
    from reportlab.graphics import renderSVG
    from reportlab.lib.colors import HexColor
    points=[p for s in series for p in s['points']]
    require(points and all(math.isfinite(v) for p in points for v in p),'Nonfinite/empty figure data')
    width,height=850,480;left,right,bottom,top=90,820,85,405
    xs=[p[0] for p in points];ys=[p[1] for p in points]
    xmin,xmax=min(xs),max(xs);ymin,ymax=min(0.,min(ys)),max(ys)
    if categories:xmin,xmax=-.6,len(categories)-.4
    if xmax==xmin:xmax=xmin+1
    if ymax==ymin:ymax=ymin+1
    padding=(ymax-ymin)*.08;ymin-=padding;ymax+=padding
    X=lambda x:left+(x-xmin)/(xmax-xmin)*(right-left)
    Y=lambda y:bottom+(y-ymin)/(ymax-ymin)*(top-bottom)
    d=Drawing(width,height);d.add(Rect(0,0,width,height,fillColor=HexColor('#ffffff'),strokeColor=None))
    d.add(String(left,447,title,fontName='Helvetica-Bold',fontSize=13))
    d.add(String((left+right)/2,23,xlabel,textAnchor='middle',fontSize=10))
    d.add(String(left,425,ylabel,fontSize=10))
    for i in range(6):
        y=ymin+(ymax-ymin)*i/5;yp=Y(y)
        d.add(Line(left,yp,right,yp,strokeColor=HexColor('#dce1e6'),strokeWidth=.5))
        d.add(String(left-9,yp-3,format(y,'.3g'),textAnchor='end',fontSize=9))
        if not categories:
            x=xmin+(xmax-xmin)*i/5;xp=X(x)
            d.add(String(xp,bottom-20,format(x,'.4g'),textAnchor='middle',fontSize=9))
    d.add(Line(left,bottom,right,bottom,strokeColor=HexColor('#233442')))
    d.add(Line(left,bottom,left,top,strokeColor=HexColor('#233442')))
    colors=['#1769aa','#d26a20','#238443','#8b4bb1']
    for j,s in enumerate(series):
        color=HexColor(colors[j%len(colors)]);pts=s['points']
        if style=='interval':
            for p,q in zip(pts[::2],pts[1::2]):d.add(Line(X(p[0]),Y(p[1]),X(q[0]),Y(q[1]),strokeColor=color,strokeWidth=1.2))
        elif style=='bar':
            for x,y in pts:
                bw=(right-left)/(xmax-xmin)*.32;offset=(j-(len(series)-1)/2)*bw
                d.add(Rect(X(x)+offset-bw/2,Y(0),bw,Y(y)-Y(0),fillColor=color,strokeColor=None))
        else:
            d.add(PolyLine([v for x,y in pts for v in (X(x),Y(y))],strokeColor=color,strokeWidth=1.3))
        d.add(Line(left+j*230,55,left+18+j*230,55,strokeColor=color,strokeWidth=2))
        d.add(String(left+24+j*230,52,s['label'],fontSize=9))
    if categories:
        for i,label in enumerate(categories):d.add(String(X(i),bottom-20,label,fontSize=7,textAnchor='middle'))
    svg=folder/(name+'.svg');png=folder/(name+'.png');renderSVG.drawToFile(d,str(svg))
    bundle=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
    node=bundle/'bin/node.exe';sharp=bundle/'node_modules/sharp'
    require(node.is_file() and (sharp/'package.json').is_file(),'Bundled SVG rasterizer unavailable; no installation attempted')
    code="require(process.argv[1])(process.argv[2],{density:160}).png().toFile(process.argv[3]).catch(e=>{process.stderr.write(String(e));process.exit(1)})"
    result=subprocess.run([str(node),'-e',code,str(sharp),str(svg),str(png)],capture_output=True,timeout=60)
    require(result.returncode==0,'Local SVG rasterization failed: '+result.stderr.decode(errors='replace')[:200])
    return {'title':title,'png':reference(png),'svg':reference(svg),'style':style,'data_rows':len(points)}


def validated_frames(path,expected_sha=None):
    f=read(path)
    if expected_sha:require(sha(path)==expected_sha,'Registered field report changed')
    require(f['mode']=='full','Sparse frames are not a full-source figure')
    run=ROOT/'local_runtime/runs'/f['run_id'];m=read(run/'manifest.json')
    require(m['state']=='COLLECTED' and m.get('ssh_exit_code')==0 and sha(run/'manifest.json')==f['manifest_sha256'],'Field source manifest differs')
    require(sha(run/'results.tar')==f['archive_sha256']==m['results_sha256'],'Field source archive differs')
    record=f['extraction_record'];op=(ROOT/record['operation_record']).parent;native=op/'collected'
    require(sha(op/'field-extraction-record.json')==f['extraction_record_sha256'],'Field extraction receipt changed')
    raw=native/'field-measurements.csv'
    require(sha(raw)==record['native_outputs_sha256']['field-measurements.csv'],'Native measurement CSV changed')
    require(all(type(record.get(k)) is int and record[k]==0 for k in ['svisual_exit_code','remote_exit_code','runner_exit_code','collection_exit_code']),'Native extraction exit unknown/nonzero')
    if f['schema']=='source-field-audit-r2':
        frame_path=Path(f['frames_csv_path']);require(frame_path.resolve()==path.parent/'frames.csv' and sha(frame_path)==f['frames_csv_sha256'],'Published full-frame CSV changed')
        rows=list(csv.DictReader(frame_path.open(encoding='utf-8')))
        frames=[{k:(float(v) if k.endswith('_raw') or k in ('start_s','end_s','dt_s') else v) for k,v in r.items()} for r in rows]
    else:
        # Frozen r4/r1 has no published ROI columns. Recover only bound native rows.
        values={}
        for row in csv.DictReader(raw.open(encoding='utf-8')):
            if row['operation']=='integral' and row['field']=='G':
                require(row['command_status']=='OK','Failed native integral');values[row['source_file'],row['scope']]=float(row['raw_value'])
        frames=[]
        for step in f['accepted_intervals']:
            r=dict(step);r['G_silicon_raw']=values[step['source_file'],'SILICON_NO_WINDOW']
            for roi in f['roi_fraction_checks']:r['G_'+roi+'_raw']=values[step['source_file'],roi]
            frames.append(r)
    require(frames and all(r['end_s']>r['start_s'] for r in frames),'Empty/invalid BE intervals')
    require(all(abs(a['end_s']-b['start_s'])<=1e-18 for a,b in zip(frames,frames[1:])),'Missing frame interval; no interpolation allowed')
    return f,frames,[reference(path),reference(raw),reference(run/'manifest.json')]


def mentor_rows(statuses):
    passed_roles=[r['角色'] for r in statuses if r['最终role通过']]
    actual='本轮最终通过角色：'+('、'.join(passed_roles) if passed_roles else '暂无；按实际状态表继续')
    return [
        {'编号':'C01','批注要点':'本次的批注比较宏观','本轮回应':actual,'边界':'区分实现、实测源量与最终角色验收。'},
        {'编号':'C02','批注要点':'给定尺寸、能量、方向、粒子或能谱，预测器件效应','本轮回应':'继续保存连续节点电压、端口电流和源场；本轮对象为二维人工接口。','边界':'未产生翻转标签、概率或器件校准结论。'},
        {'编号':'C03','批注要点':'重离子直接注入；质子次级种类、能谱、LET后引入TCAD','本轮回应':'本轮只补二维多源/错时/分段/细化；既有质子与核机制记录见stage2。','边界':'新二维人工源不是质子次级的三维联合响应。'},
        {'编号':'C04','批注要点':'Geant4到TCAD能否自动化','本轮回应':actual+'；按原生全接受步、退出码和hash关联。','边界':'缺帧与未知状态拒绝通过；真实3D未定义降维仍拒绝。'},
        {'编号':'C05','批注要点':'这部分目前不合理','本轮回应':'保留旧失败，检查多源分离、局部时间与分段，避免用一条均匀源代替事件。','边界':'当前仅完成状态表中有真实证据的二维检查。'},
        {'编号':'C06','批注要点':'特征尺寸还可以更小','本轮回应':'器件证据沿用Shin原图与条件核查；网格细化不等于缩小器件。','边界':'Park Table1/Fig10/Fig13原图仍未取得；未校准新尺寸器件。'},
        {'编号':'C07','批注要点':'能量是个变量','本轮回应':'既有能量探针证据见stage2；本轮源接口只用已登记人工电荷。','边界':'LET与能量不互换，不新增能谱事件率。'},
        {'编号':'C08','批注要点':'引入物理方程，从而“降低拟合准确性”','本轮回应':'保留原意待澄清；为后续约束保留独立电流、电压与源量。','边界':'训练暂缓，CΔV同义标签不能独自证明约束增益。'}]


def validated_response_csv(path,expected):
    with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    require(len(rows)==len(expected),'Response CSV row count differs from archived curves')
    for actual,wanted in zip(rows,expected):
        require(set(actual)==set(wanted),'Response CSV columns differ')
        require(all(math.isfinite(float(actual[k])) and math.isclose(float(actual[k]),float(wanted[k]),rel_tol=1e-12,abs_tol=1e-18) for k in wanted),'Response CSV differs from archived matched-control data')
    return [{k:float(v) for k,v in row.items()} for row in rows]


def _generate(budget_report=None):
    stamp=datetime.now(timezone.utc);folder=OUTPUT/(stamp.strftime('%Y%m%dT%H%M%S.%fZ-')+uuid.uuid4().hex[:8])
    require(not folder.exists(),'Report output already exists');folder.mkdir(parents=True)
    campaign=read(HERE/'campaign.json');controller=module(HERE/'control.py','_report_readonly_controller')
    budget=budget_report if budget_report is not None else module(HERE/'budget_report.py','_report_budget').generate()
    warnings=[];evidence=[reference(HERE/'campaign.json')];figures=[];gate_cache={}
    def gate(role):
        if role not in gate_cache:
            try:gate_cache[role]=(True,controller.check_gate(role))
            except (ValueError,OSError,KeyError) as exc:gate_cache[role]=(False,str(exc))
        return gate_cache[role][0]
    launches=[(p,read(p)) for p in sorted((V5/'launches').glob('*/execution.json'))]
    outcomes=[(p,read(p)) for p in sorted((STATE/'outcomes').glob('*.json'))]
    registry=read(STATE/'evidence-registry.json') if (STATE/'evidence-registry.json').exists() else {'runs':{}}
    field_by_run={}
    for p in sorted((RT/'source-field-audit-r2/audit-dev').glob('*/audit.json')):
        f=read(p)
        if f.get('mode')=='full' and f.get('run_id'):field_by_run[f['run_id']]=p
    failed_roles={d['role_id'] for p,d in outcomes if d.get('passed') is False}
    statuses=[]
    for request in campaign['roles']:
        role=request['role_id'];actual=sorted([(p,d) for p,d in launches if d.get('role_id')==role],key=lambda x:x[1].get('started_utc',''))
        last=actual[-1] if actual else None;done=gate(role);source_ok=False;field_ok=False
        run_id=last[1].get('run_id') if last else None
        if last:
            evidence.append(reference(last[0]));p=V5/'audits'/last[1]['label']/'audit.json'
            if p.exists():
                source=read(p);source_ok=source.get('passed') is True and not source.get('errors');evidence.append(reference(p))
            if run_id in field_by_run:
                f=read(field_by_run[run_id]);field_ok=f.get('field_measurements_passed') is True and f.get('passed') is True
        missing=[r for r in request.get('requires',[]) if not gate(r)]
        if done:state='最终role通过'
        elif last and last[1].get('state') in ('RUNNING','PREPARING') and last[1].get('runner_exit_code') is None:state='运行中（本地记录）'
        elif role in failed_roles or last and last[1].get('runner_exit_code') not in (None,0):state='失败／待处理'
        elif source_ok:state='单项源通过；最终role待验收'
        elif field_ok:state='原生场通过；源综合待验收'
        elif last:state='已执行；审计未齐'
        elif any(r in failed_roles for r in missing):state='依赖暂停（未运行）'
        else:state='未运行'+('；等待依赖' if missing else '')
        statuses.append({'角色':role,'状态':state,'原生场通过':field_ok,'单项源通过':source_ok,'最终role通过':done,'run_id':run_id or '',
                         '待满足依赖':'、'.join(missing),'调用数':len(actual)})
    def safe_plot(action,label):
        try:action()
        except Exception as exc:warnings.append(label+': '+type(exc).__name__+': '+str(exc))
    field_inputs=[]
    for role,row in registry.get('runs',{}).items():
        if row.get('field_audit'):field_inputs.append((role,ROOT/row['field_audit'],row.get('field_audit_sha256'),'r4 reused reference' if '-r4-' in row['run'] else 'r5'))
    known={p.resolve() for role,p,h,label in field_inputs}
    for run_id,p in field_by_run.items():
        if p.resolve() not in known:field_inputs.append((run_id,p,None,'r5 saved field audit'))
    for role,path,expected,label in field_inputs:
        def draw_field(role=role,path=path,expected=expected,label=label):
            f,frames,refs=validated_frames(path,expected);evidence.extend(refs)
            display=role if len(role)<35 else f.get('case_id','source')+'-'+f['run_id'][:16]
            title=display+' | '+label+' | native BE intervals'
            names=['Total']+(['SourceLeft','SourceRight'] if any(k.startswith('G_SourceLeft') for k in frames[0]) and f.get('case_id') in ('A5','A6','A7') else [])
            series=[]
            for name in names:
                key='G_silicon_raw' if name=='Total' else 'G_'+name+'_raw'
                points=[p for r in frames for p in [((r['start_s']-1e-9)*1e12,r[key]*1.602176634e-28),((r['end_s']-1e-9)*1e12,r[key]*1.602176634e-28)]]
                series.append({'label':name+' (native TDR)','points':points})
            figure_record=figure(folder,role+'-source',title,'Time from 1 ns (ps)','Interval-mean generation (fC/ps)',series,'interval')
            figure_record.update(source='Native TDR spatial integral; accepted BE intervals only',evidence=refs,physical_pass=f.get('field_measurements_passed') is True)
            figures.append(figure_record)
            fractions=f.get('roi_fraction_checks',{});rois=list(fractions)
            require(rois and all(fractions[r].get('observed') is not None for r in rois),'ROI fractions unavailable')
            fig=figure(folder,role+'-roi',display+' | '+label+' | native ROI fractions','ROI (source-field window)','Fraction of silicon generation',
                       [{'label':'Measured','points':[(i,fractions[r]['observed']) for i,r in enumerate(rois)]},
                        {'label':'Analytic target','points':[(i,fractions[r]['expected']) for i,r in enumerate(rois)]}],'bar',rois)
            fig.update(evidence=refs,source='Native TDR ROI measurements; target is evaluation only',delay=f.get('A6_local_delay'))
            figures.append(fig)
        safe_plot(draw_field,role+' native field')
    # Reproduce matching against each signal's own registered A0, then use recorded CSV where available.
    acceptance=module(HERE/'acceptance.py','_report_readonly_acceptance');api=acceptance.api()
    bundles={}
    def registered(role):
        if role not in bundles:bundles[role]=acceptance.load_registered(api,registry,role)
        return bundles[role]
    for role,row in registry.get('runs',{}).items():
        if row['role'][0]=='A0':continue
        case,bit,profile=row['role'];control_id=f'a0-b{bit}-{profile}'
        if control_id not in registry['runs']:continue
        def draw_response(role=role,row=row,control_id=control_id):
            signal=registered(role);control=registered(control_id)
            api.matched_control(signal,control)
            curves=api.comparison_curves(signal,signal,control,control)['control-relative-curves']
            label='r4 reused reference' if '-r4-' in row['run'] else 'r5 matched A0'
            series=[{'label':node+' - matched A0','points':[(r['time_s']*1e9,r['a_delta_v('+node+')_V']*1000) for r in curves]} for node in ('sn','bl')]
            fig=figure(folder,role+'-response',role+' | '+label,'Time (ns)','Voltage perturbation (mV)',series)
            fig['evidence']=[reference(ROOT/row['audit']),reference(ROOT/registry['runs'][control_id]['audit'])];fig['source']='Recomputed from archived terminal curves after exact matching-control validation';figures.append(fig)
            for p in (V5/'responses').glob('*/control-relative-curves.csv'):
                if p.parent.name in [d.get('label') for q,d in launches if d.get('role_id')==role]:
                    validated_response_csv(p,curves);evidence.append(reference(p))
        safe_plot(draw_response,role+' matched response')
    for request in campaign['roles']:
        role=request['role_id'];mode=request.get('comparison_mode')
        if not mode or not gate(role) or role not in registry['runs']:continue
        def draw_comparison(role=role,mode=mode,request=request):
            case,bit,profile=registry['runs'][role]['role']
            baseline=(case.lower() if mode=='refinement' else 'a5' if case=='A7' else 'a1')+f'-b{bit}-main'
            a,b=registered(baseline),registered(role)
            ca,cb=registered(f'a0-b{bit}-main'),registered(f'a0-b{bit}-{profile}')
            api.matched_control(a,ca);api.matched_control(b,cb)
            rows=api.comparison_curves(a,b,ca,cb)['control-relative-curves']
            gate_record=read(STATE/'gates'/(role+'.json'))
            bound=[ROOT/r['path'] for r in gate_record['evidence'] if Path(r['path']).name=='comparison.json']
            require(len(bound)==1,'Final role has no unique bound comparison report')
            summary=read(bound[0]);require(summary.get('passed') is True and not summary.get('errors'),'Pair comparison did not pass')
            csv_path=bound[0].parent/'control-relative-curves.csv';rows=validated_response_csv(csv_path,rows)
            refs=[reference(bound[0]),reference(csv_path)];evidence.extend(refs)
            for node in ('sn','bl'):
                series=[{'label':label,'points':[(r['time_s']*1e9,r[prefix+'_delta_v('+node+')_V']*1000) for r in rows]} for prefix,label in [('a',baseline),('b',role)]]
                fig=figure(folder,role+'-'+mode+'-'+node,role+' | '+mode+' | each minus own A0','Time (ns)',node+' perturbation (mV)',series)
                fig.update(evidence=refs,source='Verified recorded comparison CSV; each signal minus its matched A0');figures.append(fig)
        safe_plot(draw_comparison,role+' '+mode+' comparison')
    mentor=mentor_rows(statuses);status_text=table(statuses,['角色','状态','原生场通过','单项源通过','最终role通过','调用数','待满足依赖','run_id'])
    mentor_text='# 导师八条批注：本批次回应\n\n只覆盖已核对的第一页八处批注，原文见'+link(HERE.parent/'mentor-response.md')+'。\n\n'+table(mentor,['编号','批注要点','本轮回应','边界'])
    mentor_text+='\n既有证据：'+link(HERE.parent/'stage2/mentor-response.md')+'；'+link(HERE.parent/'device-evidence-r2/README.md')+'。\n'
    report='# DRAM 二维接口批次汇报\n\n生成时间（UTC）：'+stamp.isoformat()+'。本报告仅为本地证据快照；运行中状态未作远端查询。\n\n'
    report+='本轮最终role通过 '+str(sum(r['最终role通过'] for r in statuses))+'/'+str(len(statuses))+'；单项源、场提取和最终role分别列示。实现存在不等于真实检查通过。\n\n'+status_text
    report+='\n## 调用与资源\n\n```json\n'+json.dumps(budget.get('budget',budget),ensure_ascii=False,indent=2)+'\n```\n\n未知耗时保留未知；不能以剩余调用数乘历史均时推算完工。\n'
    report+='\n## 真实数据图\n\n'
    if not figures:report+='当前没有满足绑定要求的可绘图数据，未生成占位曲线。\n'
    for f in figures:
        report+='\n'+f['title']+'\n\n!['+f['title']+']('+f['png']['path']+')\n\n'+link(f['svg']['path'],'SVG')+'；来源：'+f.get('source','原始证据')+'。\n'
        if 'physical_pass' in f:report+='\n对应原生场审计：'+('通过' if f['physical_pass'] else '未通过；此图仅展示已测数据，不能作为源放行证据')+'；最终role另见状态表。\n'
        if f.get('delay'):report+='\nA6实测局部延迟：`'+json.dumps(f['delay'],ensure_ascii=False)+'`。\n'
    report+='\n## 未完成边界\n\n本批次不输出翻转、截面、概率、校准或物理约束训练有效性结论。二维人工源不等于真实三维粒子事件耦合。Park目标原图仍未取得，Shin图证据不能补足全部器件参数。\n'
    report+='\n'+link(folder/'mentor-response.md','导师回应表')+'；'+link(folder/'status.csv','状态表CSV')+'。\n'
    if warnings:report+='\n## 缺项与拒绝绘图\n\n'+''.join('- '+w+'\n' for w in warnings)
    (folder/'report.md').write_text(report,encoding='utf-8');(folder/'mentor-response.md').write_text(mentor_text,encoding='utf-8')
    (folder/'status.md').write_text(status_text,encoding='utf-8')
    with (folder/'status.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(statuses[0]));w.writeheader();w.writerows(statuses)
    metadata={'schema':'dram-see-v4-interface-completion-report-r1','created_utc':stamp.isoformat(),'output_directory':str(folder),
              'read_only_inputs':True,'new_solver_invocations':0,'publication_ready':not warnings,'report_errors':warnings,'reporter_sha256':sha(Path(__file__)),'campaign_sha256':sha(HERE/'campaign.json'),
              'roles':statuses,'gate_checks':gate_cache,'budget':budget,'figures':figures,'warnings':warnings,'input_evidence':evidence,
              'outputs':{p.name:sha(p) for p in folder.iterdir() if p.is_file()},'limits':['No live remote state inspection','No fabricated missing curves','No upset, probability, device calibration or training claim']}
    (folder/'report.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return metadata


def generate(budget_report=None):
    """Never stop the serial controller on reporting failure; forbid scientific publication."""
    try:return _generate(budget_report)
    except Exception as exc:
        stamp=datetime.now(timezone.utc);folder=OUTPUT/(stamp.strftime('%Y%m%dT%H%M%S.%fZ-error-')+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
        error=type(exc).__name__+': '+str(exc)
        metadata={'schema':'dram-see-v4-interface-completion-report-r1','created_utc':stamp.isoformat(),'output_directory':str(folder),
                  'read_only_inputs':True,'new_solver_invocations':0,'publication_ready':False,'report_errors':[error],
                  'figures':[],'warnings':[error],'reporter_sha256':sha(Path(__file__))}
        (folder/'report.md').write_text('# 报告生成错误\n\n证据读取或核验失败，本次停止科学发布；不修改队列或原始证据。\n\n'+error+'\n',encoding='utf-8')
        (folder/'report.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        return metadata


if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    result=generate();print(json.dumps({'output_directory':result['output_directory'],'figures':len(result['figures']),'warnings':result['warnings']},ensure_ascii=False,indent=2))
