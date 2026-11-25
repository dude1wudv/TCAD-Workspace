"""Prepare the feasible r0.6 inventory outside the scheduler heartbeat."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import time

import month_one_draw
import month_one_response
import month_one_transport
import month_one_wave
import scheduler_supply


RETRY_SECONDS = 120
RESPONSE_SLICE = 13
INTAKE_SCHEMA = 'tcad-r06-approved-supply-v1'
INTAKE_DIRECTORY = 'supply-approved'
ACCEPTANCE_REASONS = (
    'no enabled profile with a pinned P0 qualification',
    'awaiting P1 evidence', 'awaiting dual-state baseline evidence',
    'awaiting formal development acquisition', 'awaiting model freeze',
    'awaiting verified collection', 'awaiting same-deck collected zero',
    'frozen draw has zero silicon ionization; awaiting verified baseline reuse',
)
MATERIAL_REASONS = (
    'missing native navigation evidence', 'original native project missing or changed',
    'No unclaimed frozen response with matching baseline and source evidence',
    'awaiting pinned response context and profile source adapter', 'missing frozen',
    'frozen TCAD project lacks project.json', 'frozen Geant4 project lacks original transport inputs',
)


def publish_approval(policy, gate, batch_ref):
    work = Path(policy['workspace']).resolve()
    contract = gate.read_reference(work, policy['scientific_gate']['contract'])
    batch = gate.read_reference(work, batch_ref)
    entries = batch['entries']
    gate.need(batch.get('schema') == INTAKE_SCHEMA
              and batch.get('manifest_sha256') == contract['manifest']['sha256']
              and isinstance(entries, list) and entries, 'invalid approved supply batch')
    content = (json.dumps(batch, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')
    gate.need(len(content) <= 65536, 'approved supply batch is too large')
    directory = Path(policy['state_dir']) / INTAKE_DIRECTORY
    directory.mkdir(mode=0o700, exist_ok=True)
    gate.need(not directory.is_symlink(), 'approved supply directory must not be a symlink')
    destination = directory / (hashlib.sha256(content).hexdigest() + '.json')
    with NamedTemporaryFile(dir=directory) as pending:
        pending.write(content)
        pending.flush()
        try:
            os.link(pending.name, destination)
        except FileExistsError:
            gate.need(not destination.is_symlink() and destination.read_bytes() == content,
                      'existing approval differs from the published batch')
    return destination.name


def _approved_entries(policy, gate, work, manifest_sha, known, intents, skipped):
    directory = Path(policy['state_dir']) / INTAKE_DIRECTORY
    entries, blocked = [], {}
    if directory.is_symlink():
        return [], {'approved': 'approved supply directory must not be a symlink'}
    for path in sorted(directory.glob('*.json')):
        label = f'approved/{path.stem}'
        try:
            gate.need(not path.is_symlink() and path.is_file() and path.stat().st_size <= 65536,
                      'invalid approved supply receipt file')
            raw = path.read_bytes()
            gate.need(hashlib.sha256(raw).hexdigest() == path.stem, 'approved supply receipt hash differs')
            receipt = json.loads(raw)
            gate.need(receipt.get('schema') == INTAKE_SCHEMA and receipt.get('manifest_sha256') == manifest_sha,
                      'approved supply receipt belongs to another plan')
            rows = receipt['entries']
            gate.need(isinstance(rows, list) and rows, 'expected approved supply entries')
        except scheduler_supply.INVALID as error:
            blocked[label] = str(error)[:200]
            continue
        for index, entry in enumerate(rows):
            try:
                task = scheduler_supply.read_proposal(work, gate, entry['proposal'])
                key = task['id']
                if key in known or key in intents or key in skipped:
                    continue
                gate.need(task['backend'] == 'tcad', 'transport pools require the frozen transport recipe')
                entries.append((key, entry))
            except scheduler_supply.INVALID as error:
                blocked[f'{label}/{index}'] = str(error)[:200]
    unique = {}
    for key, entry in entries:
        if key in unique and entry != unique[key]:
            blocked[key] = 'conflicting approved receipts for one task'
        unique[key] = entry
    return [entry for key, entry in unique.items() if key not in blocked], blocked


def _baselines(work, gate, settings, known, intents):
    entries, blocked = [], {}
    for index, entry in enumerate(settings.get('baselines', [])):
        label = f'baseline-{index}'
        try:
            task = scheduler_supply.read_proposal(work, gate, entry['proposal'])
            label = task['id']
            if label in known or label in intents or label in settings['skip_task_ids']:
                continue
            gate.need(label.startswith('r06-p0-'), 'baseline requires a P0 task')
            spec = gate.read(gate.path_at(work, task['project'] + '/project.json'))
            gate.need(spec['native_threads'] == spec['native_cores'] == 1, 'matched zero requires one core')
            entries.append(entry)
        except scheduler_supply.INVALID as error:
            blocked[label] = str(error)[:200]
    return entries, blocked


def _later_entries(work, gate, contract, manifest, settings, known, intents):
    entries, blocked = [], {}
    order = {case['case_id']: index for index, case in enumerate(manifest['cases'])}
    for index, entry in enumerate(settings.get('later_entries', [])):
        label = f'later-entry-{index}'
        try:
            task = scheduler_supply.read_proposal(work, gate, entry['proposal'])
            label = task['id']
            if label in known or label in intents or label in settings['skip_task_ids']:
                continue
            admission = gate.read_reference(work, entry['admission'])
            gate.need(month_one_wave.later_scope(task, admission, contract, settings['profiles']),
                      'later proposal requires approved acquisition or model freeze')
            rank = -1 if task['backend'] == 'geant4' else order[admission['case_id']]
            entries.append((rank, index, entry))
        except scheduler_supply.INVALID as error:
            blocked[label] = str(error)[:200]
    return [entry for _, _, entry in sorted(entries)], blocked


def _responses(work, gate, contract, manifest, known, intents, settings, claimed):
    """Feed each recipe once through the response helper's 13-entry cap."""
    catalog = settings.get('responses', [])
    gate.need(isinstance(catalog, list) and len(catalog) <= len(manifest['cases']),
              'invalid frozen response catalog')
    entries, blocked = [], {}
    for start in range(0, len(catalog), RESPONSE_SLICE):
        part = catalog[start:start + RESPONSE_SLICE]
        staged, reasons = month_one_response.prepare(work, gate, contract, manifest, known, intents,
                                                     {**settings, 'responses': part}, len(part), claimed=claimed)
        entries.extend(staged)
        for label, reason in reasons.items():
            if label.startswith('response-'):
                label = f'response-{start + int(label.removeprefix("response-"))}'
            blocked[label] = reason
    return entries, blocked


def prepare(policy, gate, limit, skipped, transport_room=2):
    """Sweep all enabled recipes. The legacy limit arguments no longer cap preparation."""
    work = Path(policy['workspace']).resolve()
    contract = gate.read_reference(work, policy['scientific_gate']['contract'])
    manifest = gate.read_reference(work, contract['manifest'])
    reference = policy['scheduler_supply']['continuous']
    settings = gate.read_reference(work, reference)
    gate.need(settings.get('schema') == 'tcad-r06-continuous-supply-v1'
              and settings.get('manifest_sha256') == contract['manifest']['sha256'],
              'continuous supply recipe belongs to another frozen plan')
    profiles = set(month_one_wave.ANCHORS)
    phase_blocks = {}
    post_p2 = False
    release_ref = settings.get('p2_release')
    lhs = settings.get('lhs_evidence')
    if lhs and not release_ref:
        path = gate.path_at(work, lhs['p2_release_path'])
        if path.is_file():
            release_ref = {'path': lhs['p2_release_path'], 'sha256': gate.sha(path)}
    if release_ref:
        try:
            release = gate.read_reference(work, release_ref)
            gate.need(release.get('manifest_sha256') == contract['manifest']['sha256']
                      and release.get('p2_authorized') is True, 'P2 release is not authorized for this plan')
            if lhs and not settings.get('p2_release'):
                gate.need(release.get('schema') == 'tcad-r06-p2-release-v1', 'invalid P2 release schema')
                evidence = release.get('p1_evidence', {}).get('decision')
                gate.referenced(work, evidence)
                gate.need(release.get('threshold_bracket_observed') is True
                          or release.get('censoring_accepted') is True,
                          'P2 release lacks a measured P1 threshold or accepted censoring decision')
            profiles.update(row['id'] for row in manifest['profiles'] if row['partition'] == 'development')
            post_p2 = True
        except scheduler_supply.INVALID as error:
            phase_blocks['LHS'] = str(error)[:200]
    else:
        phase_blocks['LHS'] = 'awaiting P1 evidence and frozen P2 release'
    if not post_p2 or not settings.get('later_entries'):
        phase_blocks['AL'] = 'awaiting formal development acquisition and matching inputs'
        phase_blocks['HR/HP'] = 'awaiting model freeze and matching holdout inputs'
    settings = {**settings, 'profiles': profiles, 'skip_task_ids': skipped, 'full_inventory': True}
    if post_p2 and lhs:
        transport = settings['transport']
        qualification_refs = dict(transport['p0_gates'])
        navigation = None
        navigation_ref = release.get('lhs_native_navigation')
        if navigation_ref is not None:
            try:
                report = gate.read_reference(work, navigation_ref)
                gate.need(report.get('schema') == 'tcad-r06-lhs-native-navigation-v1'
                          and report.get('geant4') == '10.7.3' and report.get('primaries') == 0
                          and isinstance(report.get('pools'), dict), 'invalid native navigation report')
                navigation = {'report': report['pools'], 'reference': navigation_ref}
            except scheduler_supply.INVALID as error:
                phase_blocks['LHS-navigation'] = str(error)[:200]
        for profile, name in lhs['p0_gate_paths'].items():
            try:
                path = gate.path_at(work, name)
                reference = {'path': name, 'sha256': gate.sha(path)}
                qualified = gate.common_gate(work, contract, {'p0_gate': reference})
                gate.qualified_profile(work, qualified, profile)
                qualification_refs[profile] = reference
            except scheduler_supply.INVALID as error:
                phase_blocks[profile] = f'awaiting dual-state baseline evidence: {error}'[:200]
        settings['transport'] = {**transport, 'p0_gates': qualification_refs,
                                 'lhs_navigation': navigation}
        path = gate.path_at(work, lhs['p2_release_path']).with_name('response-catalog.json')
        if path.is_file():
            try:
                catalog = gate.read(path)
                gate.need(catalog.get('schema') == 'tcad-r06-response-catalog-v1'
                          and catalog.get('manifest_sha256') == contract['manifest']['sha256'],
                          'response catalog belongs to another frozen plan')
                for key in ('responses', 'later_entries'):
                    rows = catalog.get(key, [])
                    gate.need(isinstance(rows, list) and len(rows) <= len(manifest['cases']),
                              f'invalid {key} catalog')
                for key in ('responses', 'later_entries'):
                    settings[key] = [*settings.get(key, []), *catalog.get(key, [])]
                if settings['later_entries']:
                    phase_blocks.pop('AL', None)
                    phase_blocks.pop('HR/HP', None)
            except scheduler_supply.INVALID as error:
                phase_blocks['response-catalog'] = str(error)[:200]
    _, known = scheduler_supply._queue(gate, Path(policy['queue_file']))
    intents = gate.read(Path(policy['state_dir']) / 'runtime.json')['intents']
    baselines, baseline_blocks = _baselines(work, gate, settings, known, intents)
    transport, transport_blocks = month_one_transport.prepare(
        work, gate, contract, manifest, known, intents, settings, float('inf'))
    claimed = month_one_response.claimed_cases(work, gate, contract, known, intents)
    reused, reuse_blocks = month_one_response.zero_reuse_cases(work, gate, manifest, contract['manifest']['sha256'],
                                                              month_one_draw.reuse_references(work, gate, settings))
    claimed.update(reused)
    responses, response_blocks = _responses(work, gate, contract, manifest, known, intents, settings, claimed)
    natural, natural_blocks = month_one_draw.recipes(work, gate, contract, manifest, known, intents,
                                                    settings, claimed)
    natural_entries, stage_blocks = _responses(
        work, gate, contract, manifest, known, intents, {**settings, 'responses': natural}, claimed)
    responses.extend(natural_entries)
    for case_id in claimed:
        response_blocks.pop(f'{case_id}-supply-r1', None)
    response_blocks.update(natural_blocks)
    response_blocks.update({f'natural-{key}' if key.startswith('response-') else key: reason
                            for key, reason in stage_blocks.items()})
    entries = baselines + transport + responses
    publication_profiles = profiles
    if post_p2 and settings.get('later_entries'):
        publication_profiles = profiles | {row['id'] for row in manifest['profiles']}
        later_settings = {**settings, 'profiles': publication_profiles}
        later, later_blocks = _later_entries(work, gate, contract, manifest, later_settings, known, intents)
        entries.extend(later)
        phase_blocks.update(later_blocks)
    approved, approval_blocks = _approved_entries(policy, gate, work, contract['manifest']['sha256'],
                                                    known, intents, skipped)
    baselines_enabled = bool(baselines) or bool(approved)
    entries.extend(approved)
    result = month_one_wave.prepare_entries(policy, gate, entries, profiles=publication_profiles,
                                           baselines=baselines_enabled, post_p2=post_p2) if entries else {}
    if not responses and not response_blocks:
        response_blocks = {'response': 'No unclaimed frozen response with matching baseline and source evidence'}
    return (result.get('entries', []), publication_profiles,
            {**baseline_blocks, **transport_blocks, **response_blocks, **reuse_blocks, **phase_blocks, **approval_blocks,
             **result.get('blocked', {})})


class Replenisher:
    def __init__(self, policy, gate):
        self.policy = policy
        self.gate = gate
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='r06-supply')
        self.future = None
        self.entries = []
        self.profiles = month_one_wave.ANCHORS
        self.blocked = {}
        self.skipped = {}
        self.allowed = False
        self.refresh_requested = False
        self.retry_at = 0
        self.intake_signature = None

    def reconcile(self, now):
        if self.future is None or not self.future.done():
            return
        try:
            self.entries, self.profiles, self.blocked = self.future.result()
            for label, reason in self.blocked.items():
                entry, _, task_id = label.partition('/')
                if entry.startswith('entry-') and scheduler_supply.TASK_ID.fullmatch(task_id):
                    self.skipped[task_id] = (now + RETRY_SECONDS * 2, reason)
        except Exception as exc:
            self.blocked = {'producer': str(exc)}
        self.future = None
        self.retry_at = now + RETRY_SECONDS

    def advance(self, ready, allow, *, consumed=None, rejected=None, now=None, transport_room=2,
                collection_completed=False, evidence_changed=False):
        """Start a full sweep after the engine drains the staged inventory and permits prep."""
        now = time.monotonic() if now is None else now
        self.allowed = allow
        if rejected:
            self.skipped.update({key: (now + RETRY_SECONDS, reason) for key, reason in rejected.items()})
        self.skipped = {key: item for key, item in self.skipped.items() if item[0] > now}
        if consumed:
            self.entries = []
        if 'state_dir' in self.policy:
            directory = Path(self.policy['state_dir']) / INTAKE_DIRECTORY
            try:
                info = directory.stat()
                signature = (info.st_ino, info.st_mtime_ns)
            except FileNotFoundError:
                signature = None
            evidence_changed = evidence_changed or signature != self.intake_signature
            self.intake_signature = signature
        self.refresh_requested = self.refresh_requested or collection_completed or evidence_changed
        if (allow and self.future is None and not self.entries
                and (self.refresh_requested or now >= self.retry_at)):
            self.future = self.executor.submit(prepare, self.policy, self.gate, None,
                                               frozenset(self.skipped))
            self.refresh_requested = False

    def status(self, ready, last_publication):
        reasons = {**self.blocked, **{key: item[1] for key, item in self.skipped.items()}}
        breakdown = dict.fromkeys(('missing_material', 'awaiting_acceptance', 'other'), 0)
        for reason in reasons.values():
            if reason.startswith(ACCEPTANCE_REASONS):
                breakdown['awaiting_acceptance'] += 1
            elif reason.startswith(MATERIAL_REASONS):
                breakdown['missing_material'] += 1
            else:
                breakdown['other'] += 1
        preparing = self.future is not None
        waiting_reason = ('engine_gate' if not self.allowed else 'awaiting_publication' if self.entries else
                          None if preparing else 'awaiting_evidence_or_retry')
        return {'ready': ready, 'preparing': preparing, 'preparing_up_to': None if preparing else 0,
                'staged': len(self.entries), 'waiting_reason': waiting_reason, 'last_publication': last_publication,
                'blocked_count': len(reasons), 'blocked_by_stage': breakdown,
                'blocked': dict(list(reasons.items())[:40])}

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)


if __name__ == '__main__':
    import argparse
    import controller
    import r06_gate

    parser = argparse.ArgumentParser(description='Publish a frozen TCAD supply approval to the original scheduler')
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('batch', help='Workspace-relative batch JSON path')
    parser.add_argument('sha256', help='Approved batch SHA-256')
    args = parser.parse_args()
    print(publish_approval(controller.policy_at(args.policy), r06_gate,
                           {'path': args.batch, 'sha256': args.sha256}))
