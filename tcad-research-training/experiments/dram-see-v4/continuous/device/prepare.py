"""Prepare current DRAM SEE v4 inputs. Never schedules or launches native work.

Reuses the already-reviewed candidate payload. A0 can only be frozen after a
real D3 original archive is collected; D2 and D3 do not need future products.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import observer_patch
import doping_patch
import visual_patch
import mesh_patch
import physics_patch
import numerics_patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CANDIDATE = ROOT / 'local_runtime/dram-see-v4/s2-runner-integration-r1/20261016T155822Z/candidate-r2'
OUTPUT = ROOT / 'local_runtime/dram-see-v4/continuous/device/projects'
ROLES = ('B1-D2', 'B1-D3', 'B1-A0-main-b0', 'B1-A0-main-b1')
USER_INSTRUCTION = '''在 E:\\TCAD-Workspace\\tcad-research-training 按 experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md 持续完成 DRAM SEE v4 的完整课程项目。
不要再设置调用次数、CPU小时、fit次数、训练时间或项目存储额度；只记实际使用量。同步修改运行代码中的预算/分轮审批/预测签字拦截，不靠伪填approved绕过。旧预算、冻结包、验收与失败原档保留为历史，不恢复旧队列。
已授权项目内调整细节、代码修改、应用补丁、编译、仿真、提取、训练和必要调优。沿用现有软件与资源，按真实日志自主解决问题，不重复索要同一许可，不原样盲目重试。原生运行维持唯一调度、原runner/owner/共享锁、严格SSH和串行单核单线程；不另建runner或operation。
先实际跑通二维DC、三维DC和两bit写读，接着α、质子、多参数数据、物理训练与预测、演示和最终交付。
保留输入/结果对应、单位、真实退出、源电荷和必要物理检查。不能伪造结果、删除不利样本或调整判据制造成功；最终留出不参与调优。'''


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def obj(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def prepare(role, run_id, runner, output=None, d3_source=None):
    if role not in ROLES or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', run_id) is None:
        raise ValueError('Unknown role or unsafe run ID')
    if role.startswith('B1-A0'):
        # Keep the original CLI usable, with the complete current source/model
        # contract and declared ILS branch supplied by the controlled assembler.
        import prepare_case
        import case_contract
        request = dict(schema=case_contract.SCHEMA, kind='transient', gate_top_depth_nm=80,
            dimension=3, variant='main', stored_bit=int(role[-1]), source_case='A0',
            d3_source_run=str(Path(d3_source).resolve()) if d3_source else '')
        return prepare_case.prepare(request, run_id, runner, output)
    target = Path(output) if output else OUTPUT / run_id
    target = target.resolve()
    allowed = (ROOT / 'local_runtime/dram-see-v4/continuous/device').resolve()
    if allowed not in target.parents or target.exists():
        raise ValueError('Output must be new and below local_runtime/dram-see-v4/continuous/device')
    runner = Path(runner).resolve()
    if runner != (ROOT / 'scripts/tcad.py').resolve() or not runner.is_file():
        raise ValueError('Use the original scripts/tcad.py runner')
    source = CANDIDATE / 'roles' / role
    reuse = role.startswith('B1-A0')
    if reuse and not d3_source:
        raise ValueError('A0 requires --d3-source pointing to a real collected D3 run')
    import geometry_bridge as bridge
    cfg = dict(schema=bridge.GEOMETRY_SCHEMA, mode='reuse' if reuse else 'produce', role_id=role,
               run_id=run_id, producer_run_id=Path(d3_source).name if reuse else run_id,
               execution_enabled=True, synthetic=False)
    bundle = None
    if reuse:
        cfg['source_run_directory'] = str(Path(d3_source).resolve())
        bundle = bridge.geometry_source_bundle(target, cfg)
        cfg.update(source_manifest_sha256=bundle['manifest_sha256'], source_archive_sha256=bundle['archive_sha256'],
                   mesh_sha256=bundle['mesh_sha256'], geometry_validation_sha256=bundle['geometry_validation_sha256'])
    target.mkdir(parents=True, exist_ok=False)
    names = ['device.cmd', 'physics.par', 'Silicon.par', 'Oxide.par', 'physics-manifest.json',
             'geometry-contract.json', 'metrics.py', 'model.proposed.json']
    if reuse:
        names += ['extract_fields.tcl', 'field-contract.json', 'windows.tcldata',
                  'source-spec.json', 'source-contract.json', 'alpha-reference.json', 'alpha-profile.csv']
    else:
        names += ['geometry-with-measurements.scm', 'measure-geometry.tcl', 'measurement-plan.json']
    original_hashes = {}
    for name in names:
        shutil.copyfile(str(source / name), str(target / name))
        original_hashes[name] = sha(source / name)
    native_repairs = []
    physics = physics_patch.apply((target / 'device.cmd').read_text(encoding='utf-8'),
        (target / 'physics.par').read_text(encoding='utf-8'), obj(target / 'physics-manifest.json'), obj(target / 'model.proposed.json'))
    for filename, key in (('device.cmd','device'), ('physics.par','parameters'),
                          ('physics-manifest.json','manifest'), ('model.proposed.json','model')):
        value = physics[key]
        text = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n') if isinstance(value,dict) else value
        (target / filename).write_text(text, encoding='utf-8', newline='\n')
        native_repairs.append(dict(patch_id=physics_patch.PATCH_ID, failure_run_id=physics_patch.FAILURE_RUN,
             file=filename, original_sha256=original_hashes.pop(filename), current_sha256=sha(target / filename),
             patch_code_sha256=sha(HERE / 'physics_patch.py'), assumption_id=physics_patch.ASSUMPTION_ID,
             changes_physical_model=True, changes_geometry_mesh_bias_timeline_source=False,
             changes_comparison_thresholds=False, parameter_fitting=False,
             equivalence='Only the uniform-field reference parameter mapping; not general nonlocal equivalence',
             native_syntax_license_verified=False))
    dimension = 2 if role == 'B1-D2' else 3
    if dimension == 3:
        before_numerics = sha(target / 'device.cmd')
        (target / 'device.cmd').write_text(numerics_patch.apply(
            (target / 'device.cmd').read_text(encoding='utf-8'), dimension, mixed=reuse),
            encoding='utf-8', newline='\n')
        write(target / 'numerical-method.json', numerics_patch.contract(dimension, mixed=reuse))
        native_repairs.append(dict(patch_id=numerics_patch.PATCH_ID, file='device.cmd',
            original_sha256=before_numerics, current_sha256=sha(target / 'device.cmd'),
            patch_code_sha256=sha(HERE / 'numerics_patch.py'), changes_physical_parameters=False,
            changes_comparison_thresholds=False, native_ILS_verified=False,
            decision_basis='Actual 2D ParDiSo peak plus 3D direct-fill risk; use documented vendor 3D default set=1, no memory cap'))
    if not reuse:
        name = 'geometry-with-measurements.scm'
        repaired = observer_patch.apply((target / name).read_text(encoding='utf-8'), 2 if role == 'B1-D2' else 3)
        (target / name).write_text(repaired, encoding='utf-8', newline='\n')
        native_repairs.append(dict(patch_id=observer_patch.PATCH_ID, failure_run_id=observer_patch.FAILURE_RUN,
             file=name, original_sha256=original_hashes.pop(name), current_sha256=sha(target / name),
             patch_code_sha256=sha(HERE / 'observer_patch.py'), changes_physical_geometry=False,
             changes_comparison_thresholds=False))
        before_doping_sha = sha(target / name)
        repaired = doping_patch.apply((target / name).read_text(encoding='utf-8'), 2 if role == 'B1-D2' else 3)
        (target / name).write_text(repaired, encoding='utf-8', newline='\n')
        native_repairs.append(dict(patch_id=doping_patch.PATCH_ID, failure_run_id=doping_patch.FAILURE_RUN,
             file=name, original_sha256=before_doping_sha, current_sha256=sha(target / name),
             patch_code_sha256=sha(HERE / 'doping_patch.py'), changes_physical_geometry=False,
             changes_peak_junction_depth_blend=False, changes_comparison_thresholds=False,
             numerical_tail_floor_max_cm3=doping_patch.MAX_ADDED_DONOR_CM3,
             mathematical_equivalence='unchanged where unclamped apart from floating arithmetic; tail guarded below normal exp range'))
        before_mesh_sha = sha(target / name)
        dimension = 2 if role == 'B1-D2' else 3
        repaired = mesh_patch.apply((target / name).read_text(encoding='utf-8'), dimension)
        (target / name).write_text(repaired, encoding='utf-8', newline='\n')
        native_repairs.append(dict(patch_id=mesh_patch.PATCH_ID, failure_run_id=mesh_patch.FAILURE_RUN,
             file=name, original_sha256=before_mesh_sha, current_sha256=sha(target / name),
             patch_code_sha256=sha(HERE / 'mesh_patch.py'), additional_refinement=mesh_patch.specification(dimension),
             changes_physical_geometry=False, changes_doping_parameters=False,
             changes_probe_locations=False, changes_comparison_thresholds=False))
        name = 'measure-geometry.tcl'
        repaired = visual_patch.apply((target / name).read_text(encoding='utf-8'))
        (target / name).write_text(repaired, encoding='utf-8', newline='\n')
        native_repairs.append(dict(patch_id=visual_patch.PATCH_ID, failure_run_id=visual_patch.FAILURE_RUN,
             file=name, original_sha256=original_hashes.pop(name), current_sha256=sha(target / name),
             patch_code_sha256=sha(HERE / 'visual_patch.py'), changes_physical_parameters=False,
             changes_comparison_thresholds=False))
    for name in ('geometry_bridge.py', 'mesh_resource_guard.py') + (() if reuse else
            ('evaluate.py', 'dfise_observer.py', 'observe_tdr_topology.tcl')):
        shutil.copyfile(str(HERE / name), str(target / name))
    role_contract = obj(source / 'role-contract.json')
    role_contract['schema'] = 'dram-see-v4-continuous-role-contract-r1'
    role_contract['execution_enabled'] = True
    role_contract['stop_conditions'] = [s.replace('resource/budget/lock/owner failure', 'actual resource/lock/owner failure')
                                         for s in role_contract['stop_conditions']]
    write(target / 'role-contract.json', role_contract)
    spec = obj(source / 'project.review.json')
    spec.update(name='v4-continuous-' + role.lower(), schema='dram-see-v4-continuous-project-r1',
                execution_enabled=True, runner='original scripts/tcad.py', s2_geometry=cfg)
    spec.pop('release_required', None)
    if not reuse:
        spec['steps'][2:2] = [
            dict(tool='tdx', args=['-tcl', 'observe_tdr_topology.tcl', 'cell_msh.tdr'],
                 outputs=['tdr-region-datasets.csv', 'tdr-geometry.csv', 'tdr-topology-identity.csv', 'tdr-region-status.json']),
            dict(tool='tdx', args=['-dd', '-M', '0', '-S', '0', 'cell_msh.tdr', 'mesh-observed'],
                 outputs=['mesh-observed.grd', 'mesh-observed.dat'])]
        native_repairs.append(dict(patch_id='native-dfise-contact-and-region-observation-r1',
             failure_run_id='20261017T044000Z-v4-continuous-b1-d2-r6',
             verified_diagnostic_operation='cgoal-tdr-observe-20261017t045517z',
             verified_source_mesh_sha256='53f384abfffe7156302df49ae8b2aa50009a2c65dbac953081beb09784854484',
             observer_sha256=sha(HERE / 'dfise_observer.py'), metadata_script_sha256=sha(HERE / 'observe_tdr_topology.tcl'),
             changes_physical_parameters=False, changes_comparison_thresholds=False,
             original_svisual_nan_rows_retained=True,
             measurement_routes=['Contact coordinates from actual converted mesh vertices',
                                 'Non-silicon doping extrema from complete actual region dataset values'],
             coordinate_policy='Require unchanged identity transform and zero shift; never rotate or scale implicitly'))
    write(target / 'project.json', spec)
    write(target / 'resource-policy.json', dict(schema='dram-see-v4-actual-resource-policy-r1', role=role,
          observation_only=True, imported_mesh_sha256=bundle['mesh_sha256'] if bundle else None,
          resource_limits=None, reason='Current user instruction removes quotas and forecast-signature gates.'))
    write(target / 'task-authorization.json', dict(schema='dram-see-v4-current-user-authorization-r1',
          source='current_user_instruction', client_date='2026-10-16', synthetic=False,
          role_ids=list(ROLES), instruction=USER_INSTRUCTION,
          plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',
          plan_sha256=sha(ROOT / 'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md')))
    write(target / 'provenance.json', dict(schema='dram-see-v4-continuous-input-provenance-r1',
          original_candidate=str(CANDIDATE.relative_to(ROOT)).replace('\\', '/'), role=role,
          unchanged_payload_sha256=original_hashes,
          native_repairs=native_repairs,
          reused_offline_report='local_runtime/dram-see-v4/s2-release-contract-r1/20261017T033504Z/report.md',
          generation_code_sha256=sha(HERE / 'prepare.py'), native_run_completed=False))
    hashes = {str(p.relative_to(target)).replace('\\', '/'): sha(p) for p in target.iterdir() if p.is_file()}
    if bundle:
        if set(hashes) & set(bundle['exports']):
            raise ValueError('D3 export collides with current role payload')
        hashes.update(bundle['exports'])
    write(target / 'input-manifest.json', dict(schema='dram-see-v4-continuous-inputs-r1',
          role_id=role, run_id=run_id, files_sha256=hashes))
    write(target / 'execution-context.json', dict(schema='dram-see-v4-continuous-run-context-r1',
          run_id=run_id, role_id=role, producer_run_id=cfg['producer_run_id'], synthetic=False,
          expected_runner_sha256=sha(runner), input_manifest_sha256=sha(target / 'input-manifest.json'),
          authorization_sha256=sha(target / 'task-authorization.json')))
    bridge.geometry_admit(target, spec, sha(runner))
    if bundle:
        bridge.geometry_stage_reuse(target, cfg)
    return dict(project=str(target), role_id=role, run_id=run_id,
                input_manifest_sha256=sha(target / 'input-manifest.json'), expected_runner_sha256=sha(runner),
                native_run_completed=False, native_syntax_verified=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--role', choices=ROLES, required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--runner', default=str(ROOT / 'scripts/tcad.py'))
    p.add_argument('--output')
    p.add_argument('--d3-source')
    a = p.parse_args()
    try:
        result = prepare(a.role, a.run_id, a.runner, a.output, a.d3_source)
    except (ValueError, OSError, KeyError) as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
