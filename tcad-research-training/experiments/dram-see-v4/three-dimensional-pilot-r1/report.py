"""Append-only pilot status/cost snapshot; never queries or dispatches a solver."""
import argparse
from collections import Counter
import importlib.util
from pathlib import Path
import sys
from uuid import uuid4

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('_pilot_report_control', HERE / 'control.py')
c = importlib.util.module_from_spec(spec); sys.modules[spec.name] = c; spec.loader.exec_module(c)


def generate():
    calls = c.prior_calls()
    operations = [c.read(p) for p in sorted((c.STATE / 'operations').glob('*/execution.json'))]
    prior = c.read(c.OLD / 'coordination.json')
    old_launches = list((c.RT / 'source-interface-r5/launches').glob('*/execution.json'))
    gates = [c.read(p) for p in sorted((c.STATE / 'gates').glob('*.json'))]
    count = Counter(r['kind'] for r in calls)
    out = dict(schema='dram-see-v4-3d-pilot-progress-r1', created_utc=c.utc(),
               state_source='Local records only; running states are not a live remote reconciliation',
               old_2d=dict(passed_roles=len(prior.get('completed_roles', [])), total_roles=17,
                           active_job=prior.get('active_job'), state=prior.get('state'),
                           new_calls=len(old_launches), new_cap=21, cumulative_calls=5+len(old_launches), cumulative_cap=26),
               pilot=dict(tcad_calls=count['tcad'], tcad_cap=4, corrective_calls=sum(r['category']=='reserve' for r in calls),
                          geant_calls=count['geant'], geant_cap=6, primary_events=sum(r.get('primary_events',0) for r in calls), primary_event_cap=8,
                          passed_roles=[g['role'] for g in gates if g.get('passed') is True]),
               calls=calls, operations=operations, nuclear_joint_response_completed=False, trained_models=0,
               future_batch_authorized=False)
    stamp=out['created_utc'].replace(':','').replace('-','').replace('+0000','Z')+'-'+uuid4().hex[:6]
    folder=c.STATE/'reports'/stamp
    c.save(folder/'report.json',out,new=True)
    lines=['# 三维试点进度与预算', '', '截至 '+out['created_utc']+'。状态来自本地记录，不把运行中视为通过。', '',
           '| 项目 | 已用/上限 |', '|---|---:|',
           f"| 旧二维验收角色 | {out['old_2d']['passed_roles']}/17 |",
           f"| 旧二维本轮调用 | {len(old_launches)}/21 |",
           f"| 旧二维含历史调用 | {5+len(old_launches)}/26 |",
           f"| 新三维TCAD调用 | {count['tcad']}/4 |",
           f"| 新三维纠错调用 | {out['pilot']['corrective_calls']}/2 |",
           f"| 匹配Geant调用 | {count['geant']}/6 |",
           f"| 匹配Geant初级事件 | {out['pilot']['primary_events']}/8 |", '',
           '## 调用记录', '', '| label | 类别 | 状态 | 开始 | 结束 |', '|---|---|---|---|---|']
    for r in calls+operations:
        lines.append(f"| {r['label']} | {r['kind']} | {r['state']} | {r.get('started_utc','')} | {r.get('finished_utc','未知')} |")
    if not calls and not operations:
        lines.append('| 尚未提交 | — | 等待旧队列与实现验收 | — | — |')
    lines += ['', '核次级联合器件响应尚未完成。离线输入/测试通过不能代替原生几何、输运和源场验收。',
              '三维A0/A1之后仅提出下一批建议；不自动执行额外矩阵、核事件搜索或训练。']
    (folder/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return {'report':c.rel(folder/'report.md'),'json':c.rel(folder/'report.json')}


if __name__=='__main__':
    import json
    print(json.dumps(generate(),ensure_ascii=False,indent=2))
