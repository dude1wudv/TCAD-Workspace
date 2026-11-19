"""Read-only live observations and append-only reports; never submits or adopts."""
from datetime import datetime,timezone
import common as c
import supervisor as s


def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out=c.RT/'progress-checks'/stamp
    state=c.read(c.RT/'status.json');budget=s.budget();rows=s.local_processes();remote=s.remote_probe()
    label=state.get('active_label');operation=None
    if label and (c.OLD_OPS/'operations'/label/'operation.json').exists():
        operation=c.read(c.OLD_OPS/'operations'/label/'operation.json')
    accepted=[p.stem for p in (c.RT/'device/gates').glob('*.json') if c.read(p).get('passed') is True]
    reports=[c.ref(p) for name in ('stages','stages-r3','stages-index-r5') for p in (c.RT/'transport'/name).glob('*.json')]
    stages=[dict(path=r['path'],stage=c.read(c.ROOT/r['path'])['stage'],
                 witness=c.read(c.ROOT/r['path'])['qualifying_event_found']) for r in reports]
    owner=state.get('owner_pid');live_owner=next((r for r in rows if r['ProcessId']==owner),None)
    report=dict(schema='nuclear-closure-live-observation-r1',utc=c.utc(),state_record=state,authoritative_budget=budget,
        state_counter_warning='Initial status scalar counters/error may be historical. Budget comes from immutable attempt identities; process and original operation facts take priority.',
        active_entry=c.read(c.RT/'active-entry.json') if (c.RT/'active-entry.json').exists() else None,
        live_owner=live_owner,local_processes=rows,remote=remote,active_operation=operation,
        accepted_device_roles=accepted,completed_transport_stages=reports,
        selected_event=c.ref(c.RT/'selected-event.json') if (c.RT/'selected-event.json').exists() else None,
        actual_actions='Read local original records and strict-SSH process/resource/shared-lock facts only; zero submissions, adoption, solver or event calls.')
    c.write(out/'report.json',report)
    text='\n'.join(['# DRAM SEE v4 自然核闭环现场核查',
        '',report['utc'],'',
        '- 当前状态：'+state.get('state','UNKNOWN'),
        '- 本地唯一入口记录：'+str(report['active_entry']['entry']['path'] if report['active_entry'] else '未登记'),
        '- 状态中 owner PID：'+str(owner)+'；对应实际进程存在：'+str(live_owner is not None),
        '- 当前标签：'+str(label),
        '- 当前原操作状态：'+str(operation.get('state') if operation else '无当前transport/工程操作'),
        '- 远端锁空闲：'+str(remote['values']['LOCK_FREE']==1)+'；活动求解：'+str(remote['active_solver_lines']),
        '- 新输运正常调用：'+str(budget['transport_normal_calls'])+'/107；纠错：'+str(budget['transport_corrective_calls'])+'/2',
        '- 不同初级请求：'+str(budget['transport_unique_primaries_requested'])+'/1000008；重放：'+str(budget['transport_replay_primaries']),
        '- 新TCAD调用：'+str(budget['tcad_calls'])+'/18；编译/工程探针：'+str(budget['compile_calls'])+'；后处理：'+str(budget['postprocess_calls']),
        '- 已验收新器件角色：'+str(accepted),
        '- 已归档通过的输运阶段（含保留的旧审计版本）：'+str(stages),
        '- 已选自然核事件：'+str(report['selected_event']),
        '', '旧二维保留15/17、细网格A1科学失败、16新调用/含历史21；原A5退出旧队列。',
        '状态文件中的初始计数及旧error不作为现场事实；本报告预算从全部attempt重新计算。',
        '本轮仅核查，无提交、adopt或新计算。完整原操作、进程、资源和SHA引用见report.json。',''])
    (out/'report.md').write_text(text,encoding='utf-8',newline='\n')
    (c.RT/'latest-progress-check.txt').write_text(str(out/'report.md')+'\n',encoding='utf-8')
    print(out/'report.md')


if __name__=='__main__':main()
