"""Bounded independent read-only review; only the new review JSON is written."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import tarfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PREP = ROOT / "experiments/dram-se-r06/p0-bootstrap-r1/prepared-prefix-r1"
REVIEW = HERE / "independent-prefix-review.json"
ELF = "bb77b42878a41dbe2efc603409479b6e8d512da5996a2cb1b3b46eab411ce594"
SOURCE = "3d735507c8d7f976c217bcb2c6eb679bae70fb426f99adca0959a9e6a7a6c549"
RUN = "auto-r06-p0-o2-cmi-build-r1-8fcbf3ff83ef4722"
protected = {}
checks = []


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    path = Path(path)
    data = path.read_bytes()
    if path.is_relative_to(ROOT):
        protected[str(path.relative_to(ROOT))] = digest(data)
    return data


def obj(path):
    return json.loads(read(path))


def need(condition, detail):
    if not condition:
        raise ValueError(detail)
    checks.append(detail)


def physics_projection(source):
    source = source.replace('#include <cstdio>\n', '')
    source = re.sub(r'// O2 logging state is shared.*?}  // namespace r06_o2_logging\n\n', '', source, flags=re.S)
    source = source.replace('  std::atomic<std::uint64_t> callbacks_{0};\n', '')
    # Remove only initialization logging, after the identical source load.
    start = source.index('      source_ = r04nodal::Source::load_file("nodal-source.dat");')
    start = source.index('\n', start) + 1
    end = source.index('    } catch (const std::exception& error)', start)
    source = source[:start] + source[end:]
    # Remove callback accounting/logging after all physical output writes.
    start = source.index('      const std::uint64_t n = ')
    end = source.index('    } catch (const std::exception& error)', start)
    return source[:start] + source[end:]


def main():
    consumption = obj(HERE / 'build-review.json')
    operation_path = ROOT / consumption['operation']['path']
    operation = obj(operation_path)
    archive_path = ROOT / consumption['archive']['path']
    archive_sha = digest(read(archive_path))
    need(digest(read(operation_path)) == consumption['operation']['sha256'], 'original operation SHA matches consumption review')
    need(archive_sha == consumption['archive']['sha256'] == operation['archive_sha256'] == operation['collection_snapshot']['sha256'], 'original archive SHA independently matches all bindings')
    need(archive_path.stat().st_size == 276480 == operation['collected_bytes'] == consumption['archive_bytes'], 'original archive is exactly 276480 bytes')
    intent = json.loads(Path('/var/lib/tcad-autonomy/runtime.json').read_bytes())['intents']['r06-p0-o2-cmi-build-r1']
    need(operation['label'] == intent['run_id'] == consumption['run_id'] == RUN, 'original build run identity matches persistent Runtime intent')
    need(operation['input_sha256'] == intent['input_sha256'], 'original operation input manifest equals persistent intent')
    need(operation['input_directory'] == str(ROOT / intent['project']), 'original operation input directory equals persistent intent')
    need(operation['collection_verified'] is True and operation['parallel_slot_released'] is True, 'original collection verified and slot release recorded')
    need(all(type(operation[k]) is int and operation[k] == 0 for k in ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code', 'operation_task_exit_code')), 'all four original engineering exit codes are integer zero')
    need(operation['capture_exit_errors'] == {}, 'original collection reports no capture exit errors')
    need(operation['synthetic'] is False and operation['origin'] == 'native_pipeline', 'original operation is recorded as nonsynthetic native pipeline')
    policy = operation['parallel_policy']
    need(policy['schema'] == 'tcad-shared-gate-slots-r3' and policy['capacity'] == 9 and policy['slot'] == policy['cpu'] == 0, 'compile exception used original nine single-core slot zero')
    for reference in intent['scientific_admission'].values():
        if isinstance(reference, dict) and 'path' in reference and 'sha256' in reference:
            need(digest(read(ROOT / reference['path'])) == reference['sha256'], 'original intent scientific binding: ' + reference['path'])
    for name, sha in intent['input_sha256'].items():
        need(digest(read(ROOT / intent['project'] / name)) == sha, 'original compile input unchanged: ' + name)
    need(digest(read(operation_path.parent / 'inputs.tar')) == operation['inputs_archive_sha256'], 'original input archive SHA matches operation')
    with tarfile.open(archive_path) as tar:
        members = tar.getmembers()
        need(all(m.isfile() and not PurePosixPath(m.name).is_absolute() and '..' not in PurePosixPath(m.name).parts for m in members), 'original result archive has only safe regular members')
        need(len(members) == len({m.name for m in members}) == 32, 'original result archive has 32 unique files including index')
        files = {m.name: tar.extractfile(m).read() for m in members}
    index = json.loads(files['_collection-members.json'])
    need(set(index) == set(files) - {'_collection-members.json'} and len(index) == 31, 'original collection index covers all 31 payload members')
    returned = ROOT / consumption['returned_directory']
    need(set(consumption['returned_files']) == set(files), 'consumption review covers every returned archive member')
    for name, data in files.items():
        if name in index:
            need(index[name]['sha256'] == digest(data) and index[name]['size'] == len(data), 'independent tar index digest and size: ' + name)
        need(read(returned / name) == data and consumption['returned_files'][name] == digest(data), 'returned bytes match original archive and consumption: ' + name)
    for name, sha in intent['input_sha256'].items():
        need(digest(files[name]) == sha, 'original archive compile input matches intent: ' + name)
    for name in ('exit-code.txt', 'operation-task-exit-code.txt', 'cmi-exit-code.txt'):
        need(files[name].strip() == b'0', 'raw original exit marker: ' + name)
    need(b'V4_OPERATION_COMPLETED' in files['execution.log'], 'native original operation completion marker exists')
    need(json.loads(files['process-identity.json']) == operation['process_identity'] == operation['last_observation']['identity'], 'original archived process identity matches operation and final observation')
    receipt = json.loads(files['build-receipt.json'])
    need(read(PREP / 'build-receipt.json') == files['build-receipt.json'], 'prepared build receipt is byte-identical to original archive receipt')
    need(receipt['status'] == 'compiled_only' and receipt['solver_called'] is False and receipt['accepted_time_steps'] is None, 'build receipt claims compile-only and no solver steps')
    need(receipt['elf_sha256'] == digest(files['pmi_r04_nodal.so.linux64']) == ELF and receipt['source_sha256'] == digest(files['pmi_r04_nodal.C']) == SOURCE, 'compiled ELF and source match required exact hashes')
    for name, sha in receipt['evidence_sha256'].items():
        need(digest(files[name]) == sha, 'original build receipt evidence binding: ' + name)
    elf = files['pmi_r04_nodal.so.linux64']
    need(elf[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<HH', elf, 16) == (3, 62), 'ELF header is 64-bit little-endian x86-64 shared object')
    need(b'new_PMI_OpticalQuantumYield' in files['exported-symbols.txt'] and b'not found' not in files['linked-libraries.txt'], 'archived native symbol and library reports contain expected export and no missing library')
    plan = obj(PREP / 'diagnostic-plan.json')
    need(plan['recipe_id'] == 'zero_whr' and plan['profile_id'] == 'D0-nominal' and plan['frozen_before_submission'] is True and bool(plan['acceptance_criteria']), 'prefix plan is frozen zero_whr D0 diagnostic with acceptance criteria')
    need(plan['final_time_s'] == 1e-13 and plan['native_threads'] == plan['native_cores'] == 2, 'prefix plan freezes final time 1e-13 s and resources 2/2')
    need(plan['formal_case_id'] is None and plan['statistics_eligible'] is False and plan['formal_plan_completed_credit'] == 0 and plan['o2_scientific_gate_passed'] is False, 'plan grants no formal/statistical credit or O2 scientific pass')
    parent = ROOT / plan['parent_input']['path']
    for name, sha in plan['parent_input']['files'].items():
        need(digest(read(parent / name)) == sha, 'frozen parent input unchanged: ' + name)
    old_source = read(parent / 'pmi_r04_nodal.C').decode()
    new_source = files['pmi_r04_nodal.C'].decode()
    need(physics_projection(old_source) == physics_projection(new_source), 'physical code, native reads/writes, source loading and error call sites identical after isolating logging-only regions')
    need('initialization <= 4' in new_source and 'initialization == 5' in new_source and 'n <= 512' in new_source and 'n == 513' in new_source and '(n & (n - 1)) == 0' in new_source, 'source implements global 4 initialization / 512 callback detail limits and power-of-two progress')
    proposals = obj(PREP / 'proposals.json')['tasks']
    expected = ['r06-p0-d0-o2-zero-prefix-a-r1', 'r06-p0-d0-o2-zero-prefix-b-r1']
    need([task['id'] for task in proposals] == expected, 'only the frozen prefix a/b tasks are proposed')
    need(proposals[0]['depends_on'] == [] and proposals[1]['depends_on'] == [expected[0]], 'prefix b is sequentially dependent on prefix a')
    manifests = {}
    for task in proposals:
        project = ROOT / task['project']
        paths = sorted(project.rglob('*'))
        need(all(not p.is_symlink() and p.is_file() for p in paths), 'prepared input has only regular files: ' + task['id'])
        hashes = {str(p.relative_to(project)): digest(read(p)) for p in paths}
        manifests[task['id']] = hashes
        admission = obj(PREP / 'admissions' / (task['id'] + '.json'))
        need(admission['input_sha256'] == hashes and sorted(task['requires']) == sorted(str(p.relative_to(ROOT)) for p in paths), 'complete admission and proposal requirements cover exact input files: ' + task['id'])
        need(admission['task_id'] == task['id'] and admission['project'] == task['project'] and admission['backend'] == task['backend'] == 'tcad', 'admission binds exact task/project/backend: ' + task['id'])
        need(admission['schema'] == 'tcad-r06-p0-admission-v1' and admission['scope'] == 'p0_diagnostic' and admission['recipe_id'] == plan['recipe_id'] and admission['profile_id'] == plan['profile_id'], 'admission binds zero diagnostic scope/profile: ' + task['id'])
        need(admission['plan_id'] == plan['plan_id'] == 'dram-se-ddr5-lpddr5' and admission['revision'] == plan['revision'] == 'r0.6' and admission['owner'] == plan['owner'] == 'server-codex', 'admission frozen plan identity: ' + task['id'])
        need(admission['formal_case_id'] is None and admission['statistics_eligible'] is False and admission['budget_account'] == 'p0_diagnostics', 'admission has no formal/statistical credit: ' + task['id'])
        need(admission['diagnostic_plan'] == {'path': str((PREP / 'diagnostic-plan.json').relative_to(ROOT)), 'sha256': digest(read(PREP / 'diagnostic-plan.json'))}, 'admission binds exact diagnostic plan SHA: ' + task['id'])
        project_obj = obj(project / 'project.json')
        need(project_obj['name'] == task['id'] and project_obj['native_threads'] == project_obj['native_cores'] == 2 and len(project_obj['steps']) == 1 and project_obj['steps'][0]['tool'] == 'sdevice' and project_obj['steps'][0]['args'] == ['device.cmd'], 'project explicitly requests original native 2/2 single sdevice step: ' + task['id'])
        for name in ('cell_msh.tdr', 'device.cmd', 'nodal-source.dat', 'source-original.dat', 'reference-apd.plx', 'reference-spectrum.txt', 'nodal_source.hpp', 'voxel_source.hpp'):
            need(read(project / name) == read(parent / name), 'prepared physical input byte-identical to parent: ' + task['id'] + '/' + name)
        need(read(project / 'pmi_r04_nodal.C') == files['pmi_r04_nodal.C'] and read(project / 'pmi_r04_nodal.so.linux64') == elf, 'prepared source and ELF byte-identical to original compile: ' + task['id'])
        header = read(project / 'nodal-source.dat').splitlines()[0].decode()
        need(header == 'R04_NODAL_SOURCE 1 10170 0 0', 'nodal header has zero records / zero allocations: ' + task['id'])
        need(re.findall(r'FinalTime\s*=\s*([^\s)]+)', read(project / 'device.cmd').decode()) == ['1e-13'], 'unchanged deck has exactly final time 1e-13: ' + task['id'])
        lineage = obj(project / 'bootstrap-lineage.json')
        need(lineage['parent_input'] == plan['parent_input'] and lineage['elf_sha256'] == ELF and lineage['source_zero'] is True and lineage['source_time_shifted'] is False and lineage['formal_case_id'] is None and lineage['statistics_eligible'] is False, 'lineage retains exact parent, zero source and diagnostic boundary: ' + task['id'])
    a, b = (manifests[key] for key in expected)
    need(set(a) == set(b) and [name for name in a if a[name] != b[name]] == ['project.json'], 'a/b complete input manifests differ only in project task name')
    pa = obj(ROOT / proposals[0]['project'] / 'project.json')
    pb = obj(ROOT / proposals[1]['project'] / 'project.json')
    pa.pop('name'); pb.pop('name')
    need(pa == pb, 'a/b project objects differ only by task name')
    # A final read makes this report a stable hash snapshot, not a stale precheck.
    need(all(digest((ROOT / path).read_bytes()) == sha for path, sha in protected.items()), 'all protected evidence hashes stable through review')
    report = {
        'schema': 'tcad-r06-independent-prefix-review-v1',
        'utc': datetime.now(timezone.utc).isoformat(),
        'ready_for_original_queue_proposal': True,
        'status': 'prefix_inputs_verified_for_original_gate_and_queue_proposal_only',
        'task_ids': expected,
        'original_build_run_id': RUN,
        'original_intent_object_sha256': digest(json.dumps(intent, sort_keys=True, separators=(',', ':')).encode()),
        'new_elf_sha256': ELF,
        'new_source_sha256': SOURCE,
        'protected_files_sha256': dict(sorted(protected.items())),
        'checks_passed': checks,
        'check_count': len(checks),
        'resource_boundary': 'project.json explicitly 2/2; unchanged historical deck literal Number_Of_Threads=1 retained, with execution resource application left to the original r4 runner and actual gate',
        'scientific_gate_passed': False,
        'o2_scientific_gate_passed': False,
        'formal_case_credit': 0,
        'statistics_eligible': False,
        'compiler_solver_ssh_collect_gate_or_queue_called_by_reviewer': False,
        'not_verified': ['No solver completion, convergence or actual 2-thread execution yet', 'No native waveform/source-integral/log-volume scientific acceptance yet', 'No full WHR, D0 baseline qualification, 22 ns timing or formal response label', 'Original Runtime actual gate and admission/queue publication remain the main agent responsibility'],
    }
    with REVIEW.open('x') as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'ready_for_original_queue_proposal': True, 'check_count': len(checks), 'protected_files': len(protected), 'review': str(REVIEW.relative_to(ROOT))}))


if __name__ == '__main__':
    main()
