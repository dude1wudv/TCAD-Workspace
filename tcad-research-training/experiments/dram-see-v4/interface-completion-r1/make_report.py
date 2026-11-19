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
import sys
import uuid

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
RT=ROOT/'local_runtime/dram-see-v4'
STATE=RT/'interface-completion-r1'
OUTPUT=STATE/'reports'
V5=RT/'source-interface-r5'
BUNDLED_PYTHON=Path('C:/Users/sun/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')
SCHEMA='dram-see-v4-interface-completion-report-r3'


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


def budget_markdown(budget):
    """Presentation only; preserve the complete budget snapshot and its uncertainty."""
    b=budget.get('budget',{});unknown='未知'
    counts=[('本轮调用','new_attempts_consumed','maximum_new_attempts',21),
            ('主要角色（primary）','primary_attempts_consumed','primary_role_limit',17),
            ('纠错预留（reserve）','reserve_attempts_consumed','reserve_attempt_limit',4),
            ('含历史的累计调用','global_attempts_consumed','maximum_global_attempts',26)]
    rows=[{'项目':label,'已用 / 上限':str(b.get(used,unknown))+' / '+str(b.get(limit,default))} for label,used,limit,default in counts]
    def duration(row):
        seconds=row.get('known_seconds')
        if seconds is None:return unknown
        missing=row.get('missing_rows',0)
        if seconds==0 and missing:return f'未知（{missing} 项尚无已存耗时）'
        return f'{seconds/3600:.2f} 小时（{seconds:.1f} 秒）'+(f'；另有 {missing} 项耗时未知' if missing else '')
    timing=budget.get('wallclock',{})
    measured=[{'项目':'已知求解墙钟（含历史）','实测或边界':duration(timing.get('solver',{}))},
              {'项目':'本轮已知求解墙钟','实测或边界':duration(timing.get('new_round_solver',{}))},
              {'项目':'本轮后处理操作墙钟','实测或边界':duration(timing.get('postprocessing',{}))+'；含传输和归档，不是纯 SVisual 耗时'}]
    fine=budget.get('fine_a0_schedule_update',{}).get('measurements') or {}
    measured.append({'项目':'fine A0','实测或边界':duration({'known_seconds':fine.get('solver_wallclock_s')})+'；仅求解墙钟'})
    for role in ('a1-b1-fine','a5-b1-fine'):
        records=[r for r in budget.get('launches',[]) if r.get('role_id')==role and r.get('solver_wallclock_s') is not None]
        measured.append({'项目':role,'实测或边界':duration({'known_seconds':records[-1]['solver_wallclock_s']})+'；已存求解耗时，完成状态见状态表' if records else '未知；尚无已存实测求解耗时'})
    measured.append({'项目':'剩余整批成本','实测或边界':'耗时与完成日期未知，不能按调用次数直接推算'})
    text=table(rows,['项目','已用 / 上限'])+'\n'+table(measured,['项目','实测或边界'])
    text+='\n调用次数包含已登记失败或状态未知的尝试；后处理不新增 TCAD 调用。\n'
    path=budget.get('output_directory')
    if path:
        directory=Path(path);directory=directory if directory.is_absolute() else ROOT/directory
        links=[link(directory/name,name) for name in ('budget.json','budget.md') if (directory/name).is_file()]
        if links:text+='\n完整预算与审计细节：'+'；'.join(links)+'。\n'
        else:text+='\n完整预算对象保存在本报告 report.json；传入对象没有可核对的独立预算文件。\n'
    else:text+='\n完整预算对象保存在本报告 report.json；未提供独立预算文件路径。\n'
    return text


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


def _generate(budget_report=None,runtime=None):
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
    mentor=mentor_rows(statuses)
    display_statuses=[{k:('通过' if v else '未通过' if r['状态'].startswith('失败') else '未验证') if isinstance(v,bool) else v for k,v in r.items()} for r in statuses]
    status_text=table(display_statuses,['角色','状态','原生场通过','单项源通过','最终role通过','调用数','待满足依赖','run_id'])
    mentor_text='# 导师八条批注：本批次回应\n\n只覆盖已核对的第一页八处批注，原文见'+link(HERE.parent/'mentor-response.md')+'。\n\n'+table(mentor,['编号','批注要点','本轮回应','边界'])
    mentor_text+='\n既有证据：'+link(HERE.parent/'stage2/mentor-response.md')+'；'+link(HERE.parent/'device-evidence-r2/README.md')+'。\n'
    report='# DRAM 二维接口批次汇报\n\n生成时间（UTC）：'+stamp.isoformat()+'。本报告仅为本地证据快照；运行中状态未作远端查询。\n\n'
    report+='本轮最终role通过 '+str(sum(r['最终role通过'] for r in statuses))+'/'+str(len(statuses))+'；单项源、场提取和最终role分别列示。实现存在不等于真实检查通过。\n\n'+status_text
    report+='\n## 调用与资源\n\n'+budget_markdown(budget)
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
    metadata={'schema':SCHEMA,'created_utc':stamp.isoformat(),'output_directory':str(folder),'runtime':runtime,
              'read_only_inputs':True,'new_solver_invocations':0,'publication_ready':not warnings,'report_errors':warnings,'reporter_sha256':sha(Path(__file__)),'campaign_sha256':sha(HERE/'campaign.json'),
              'roles':statuses,'gate_checks':gate_cache,'budget':budget,'figures':figures,'warnings':warnings,'input_evidence':evidence,
              'outputs':{p.name:sha(p) for p in folder.iterdir() if p.is_file()},'limits':['No live remote state inspection','No fabricated missing curves','No upset, probability, device calibration or training claim']}
    (folder/'report.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return metadata


def runtime_identity():
    return {'executable':str(Path(sys.executable).resolve()),'version':sys.version,'implementation':sys.implementation.name}


def object_sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')).hexdigest()


def runtime_fallback(budget,trace,budget_path=None):
    """One bounded local child; never installs, retries or changes scientific inputs."""
    stamp=datetime.now(timezone.utc);directory=STATE/'report-dev'/('runtime-'+stamp.strftime('%Y%m%dT%H%M%S.%fZ-')+uuid.uuid4().hex[:8])
    directory.mkdir(parents=True,exist_ok=False)
    trace.update(mode='bundled-child',evidence_directory=str(directory),parent=runtime_identity(),child_exit_code=None,automatic_retry=False)
    require(BUNDLED_PYTHON.is_file(),'Bundled Python is unavailable; no installation attempted')
    require(Path(sys.executable).resolve()!=BUNDLED_PYTHON.resolve(),'Bundled Python lacks ReportLab; recursive fallback refused')
    supplied=Path(budget_path).resolve() if budget_path else None
    if supplied is None and budget.get('output_directory'):
        p=Path(budget['output_directory']);p=p if p.is_absolute() else ROOT/p
        candidate=p/'budget.json'
        if candidate.is_file() and read(candidate)==budget:supplied=candidate.resolve()
    if supplied is None:
        supplied=directory/'budget-input.json'
        supplied.write_text(json.dumps(budget,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    require(read(supplied)==budget,'Budget file is not equal to supplied budget object')
    original_sha=sha(Path(__file__));binding=reference(supplied)
    request={'schema':'dram-see-v4-report-runtime-request-r1','parent':trace['parent'],'expected_child':str(BUNDLED_PYTHON.resolve()),
             'reporter_sha256':original_sha,'budget':binding,'budget_object_sha256':object_sha(budget),'created_utc':stamp.isoformat(),'automatic_retry':False}
    request_path=directory/'runtime-request.json';request_path.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
    trace.update(request=reference(request_path),budget=binding,budget_object_sha256=request['budget_object_sha256'])
    existing={p.resolve() for p in OUTPUT.iterdir()} if OUTPUT.exists() else set()
    command=[str(BUNDLED_PYTHON),'-B',str(Path(__file__).resolve()),'--native-child','--budget',str(supplied),'--runtime-request',str(request_path)]
    trace['command']=command
    try:
        result=subprocess.run(command,cwd=str(ROOT),capture_output=True,timeout=300)
        stdout,stderr=result.stdout,result.stderr;trace['child_exit_code']=result.returncode
    except subprocess.TimeoutExpired as exc:
        stdout,stderr=exc.stdout or b'',exc.stderr or b'';trace['timed_out']=True
        (directory/'child-stdout.txt').write_bytes(stdout);(directory/'child-stderr.txt').write_bytes(stderr)
        (directory/'runtime-result.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
        raise ValueError('Bundled report child timed out; no automatic retry') from exc
    (directory/'child-stdout.txt').write_bytes(stdout);(directory/'child-stderr.txt').write_bytes(stderr)
    trace.update(stdout=reference(directory/'child-stdout.txt'),stderr=reference(directory/'child-stderr.txt'))
    (directory/'runtime-result.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
    require(result.returncode==0,'Bundled report child failed, actual exit='+str(result.returncode))
    lines=[line[len('REPORT_RESULT '):] for line in stdout.decode('utf-8',errors='strict').splitlines() if line.startswith('REPORT_RESULT ')]
    require(len(lines)==1,'Child result sentinel missing or duplicated')
    receipt=json.loads(lines[0]);folder=Path(receipt['output_directory']).resolve()
    require(folder.parent==OUTPUT.resolve() and folder not in existing and folder.is_dir() and not folder.is_symlink(),'Child output is not a new direct report directory')
    report_path=folder/'report.json';require(report_path.is_file() and not report_path.is_symlink(),'Child metadata missing or linked')
    metadata=read(report_path)
    require(metadata['schema']==SCHEMA and metadata['reporter_sha256']==original_sha==sha(Path(__file__)),'Child reporter version differs')
    require(sha(report_path)==receipt['report_sha256'] and Path(metadata['output_directory']).resolve()==folder,'Child metadata binding differs')
    require(read(supplied)==budget and sha(supplied)==binding['sha256'] and metadata['budget']==budget,'Parent/child budget differs')
    require(metadata['runtime']['request']==reference(request_path) and Path(metadata['runtime']['child']['executable']).resolve()==BUNDLED_PYTHON.resolve(),'Child runtime/request identity differs')
    child_metadata=folder/'runtime-child-report.json';child_metadata.write_bytes(report_path.read_bytes())
    trace.update(child=metadata['runtime']['child'],child_output_directory=str(folder),child_metadata_before_parent=reference(child_metadata),validated=True)
    runtime_path=folder/'runtime-parent.json';runtime_path.write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
    metadata['runtime']=trace;metadata['outputs']['runtime-parent.json']=sha(runtime_path);metadata['outputs']['runtime-child-report.json']=sha(child_metadata)
    report_path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return metadata


def generate(budget_report=None,*,_native_child=False,_runtime_request=None,_budget_path=None):
    """Never stop the serial controller on reporting failure; forbid scientific publication."""
    trace={'mode':'native-child' if _native_child else 'direct','child' if _native_child else 'parent':runtime_identity(),'child_exit_code':None,
           'parent_exit_code':None,'parent_exit_code_semantics':'API caller remains running; only its owner can record its eventual process exit','automatic_retry':False}
    try:
        budget=budget_report if budget_report is not None else module(HERE/'budget_report.py','_report_budget').generate()
        if _native_child:
            require(_runtime_request is not None,'Native child requires a bound runtime request')
            request_path=Path(_runtime_request).resolve();request=read(request_path)
            require(request['schema']=='dram-see-v4-report-runtime-request-r1','Unknown runtime request')
            require(request['reporter_sha256']==sha(Path(__file__)),'Native child reporter differs from request')
            require(Path(sys.executable).resolve()==Path(request['expected_child']).resolve()==BUNDLED_PYTHON.resolve(),'Native child runtime differs')
            require(_budget_path is not None and Path(_budget_path).resolve()==Path(request['budget']['path']).resolve(),'Native child budget path differs')
            require(sha(_budget_path)==request['budget']['sha256'] and object_sha(budget)==request['budget_object_sha256'],'Native child budget content differs')
            trace.update(parent=request['parent'],request=reference(request_path),budget=request['budget'],budget_object_sha256=request['budget_object_sha256'])
        available=importlib.util.find_spec('reportlab') is not None
        if not available:
            require(not _native_child,'Native child lacks ReportLab; recursive fallback refused')
            return runtime_fallback(budget,trace,_budget_path)
        return _generate(budget,trace)
    except Exception as exc:
        stamp=datetime.now(timezone.utc);folder=OUTPUT/(stamp.strftime('%Y%m%dT%H%M%S.%fZ-error-')+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
        error=type(exc).__name__+': '+str(exc)
        metadata={'schema':SCHEMA,'created_utc':stamp.isoformat(),'output_directory':str(folder),'runtime':trace,
                  'read_only_inputs':True,'new_solver_invocations':0,'publication_ready':False,'report_errors':[error],
                  'figures':[],'warnings':[error],'reporter_sha256':sha(Path(__file__))}
        (folder/'report.md').write_text('# 报告生成错误\n\n证据读取或核验失败，本次停止科学发布；不修改队列或原始证据。\n\n'+error+'\n',encoding='utf-8')
        (folder/'report.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        return metadata


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget',type=Path);parser.add_argument('--native-child',action='store_true');parser.add_argument('--runtime-request',type=Path)
    args=parser.parse_args()
    result=generate(read(args.budget) if args.budget else None,_native_child=args.native_child,_runtime_request=args.runtime_request,_budget_path=args.budget)
    receipt={'output_directory':result['output_directory'],'figures':len(result['figures']),'publication_ready':result['publication_ready'],
             'warnings':result['warnings'],'report_sha256':sha(Path(result['output_directory'])/'report.json')}
    print(('REPORT_RESULT ' if args.native_child else '')+json.dumps(receipt,ensure_ascii=True))
    if args.native_child:raise SystemExit(0 if result['publication_ready'] else 1)
