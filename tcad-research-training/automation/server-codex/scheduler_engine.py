"""Deterministic production adapter around the original Runtime and runners."""
import collections
import importlib.util
import json
from pathlib import Path
import sys
import time
import uuid


def sidecar(name):
    key = "tcad_autonomy_" + name
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, Path(__file__).with_name(name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


runtime = sidecar("runtime")
collector = sidecar("scheduler_collector")
probe_module = sidecar("scheduler_probe")
admission_module = sidecar("scheduler_admission")


class SchedulerEngine(runtime.Runtime):
    def __init__(self, policy, ready, read_only=False):
        super().__init__(policy, ready)
        self.read_only = read_only
        if read_only:
            self.can_submit = lambda: False
        self.channel = None if read_only else collector.AsyncCollectorPool(policy.get("collect_concurrency", 1))
        self.probe = probe_module.BatchRemoteProbe(policy, read_only=read_only)
        self.admission = admission_module.ResourceAdmissionController(policy)
        self.snapshot = {"ok": False, "runs": {}}
        self._deferred_events = []
        self._queue_cache = None
        self._queue_signature = None
        self._admission_blocks = {}

    def _save(self):
        if not self.read_only:
            super()._save()

    def _load_tasks(self):
        try:
            meta = self.queue_file.stat()
            signature = (meta.st_mtime_ns, meta.st_size, meta.st_ino)
        except OSError:
            signature = None
        if signature is None or signature != self._queue_signature:
            self._queue_cache = super()._load_tasks()
            self._queue_signature = signature
        tasks, errors = self._queue_cache
        return dict(tasks), list(errors)

    def _delay(self, intent, error):
        if error.get("kind") == "operation_pending":return
        category = collector.classify_collection_error(error)
        metadata = intent.setdefault("scheduler", {})
        attempt = metadata.get("failures", 0) + 1
        metadata.update(failures=attempt, error_class=category, error=error)
        counts=self.state.setdefault("scheduler_metrics",{}).setdefault("errors_by_class",{})
        counts[category]=counts.get(category,0)+1
        delays = {"TRANSIENT_LOCK_BUSY": (2, 5, 10, 30), "TRANSIENT_NETWORK": (5, 15, 45, 120, 300)}
        delay = delays.get(category, (300,))[min(attempt - 1, len(delays.get(category, (300,))) - 1)]
        intent["next_probe_at"] = time.time() + delay
        intent["reconciliation_error"] = error
        if category == "TRANSIENT_LOCK_BUSY" and attempt >= 6:
            metadata["manual_attention"] = True
        self._save()

    def _invoke(self, intent, command):
        if self.read_only:
            raise RuntimeError("Read-only reconciliation cannot invoke an original runner")
        if command == "status":
            key = next(key for key, item in self.intents.items() if item is intent)
            observed = self.snapshot.get("runs", {}).get(key)
            if self.snapshot.get("ok") and observed and not observed.get("error"):
                return {"ok": True, "payload": observed}
            return {"ok": False, "kind": "endpoint_unavailable"}
        if self.channel.submit(intent["run_id"], command, self._argv(intent, command), self.workspace,
                               self._runner_environment(), self.timeout,
                               self.can_submit if command == "run" else None):
            meta=intent.setdefault('scheduler',{});meta['operation']=command
            stats=self.state.setdefault('scheduler_metrics',{})
            if command=='run':
                task_id=next(key for key,item in self.intents.items() if item is intent)
                since=stats.get('ready_since',{}).pop(task_id,None)
                if since is not None:
                    stats['dispatch_seconds']=stats.get('dispatch_seconds',0)+max(0,time.time()-since)
                    stats['dispatch_count']=stats.get('dispatch_count',0)+1
        return {"ok": False, "kind": "operation_pending"}

    def _preflight_rejected(self, intent, receipt):
        if intent['backend']!='tcad' or not isinstance(receipt,dict):return False
        cfg=self._intent_profile(intent)
        root=Path(cfg['local_state_root'])/'preflight-failures';path=Path(receipt['path'])
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):raise ValueError('Original preflight receipt escapes state root')
        if runtime.file_digest(path)!=receipt['sha256']:raise ValueError('Original preflight receipt changed')
        value=runtime.read_json(path);proof=value.get('remote_proof',{});policy=proof.get('request',{}).get('policy',{})
        expected={key:cfg[key] for key in ('backend','ssh_target','runtime_entry','remote_root')}
        return (value.get('schema')=='tcad-original-preflight-receipt-r1' and value.get('run_id')==intent['run_id']
                and value.get('input_sha256')==intent['input_sha256'] and value.get('connection_identity')==expected
                and proof.get('schema')=='tcad-original-preflight-rejection-r1'
                and proof.get('reservation_acquired') is False and proof.get('solver_launched') is False
                and all(proof.get(key) is True for key in ('target_lease_absent','target_directory_absent','gate_held','allocator_held'))
                and policy.get('work_id')==intent['run_id'] and policy.get('slot')==intent['slot']
                and policy.get('remote_directory')==cfg['remote_root'].rstrip('/')+'/runs/'+intent['run_id'])

    def _switch_ready(self, task, live):
        snapshot=dict(self.snapshot);telemetry=dict(snapshot.get('telemetry',{}));snapshot['telemetry']=telemetry
        telemetry['mem_available_gib']=telemetry.get('mem_available_gib',0)+sum(
            (item.get('rss_kib') or 0)/1048576 for item in self.snapshot.get('runs',{}).values())
        reserve=len(live)*self.admission.cfg.get('collection_reserve_gib',1.0)
        for field in ('host_disk_free_gib','remote_disk_free_gib','backing_disk_free_gib'):
            if type(telemetry.get(field)) in (int,float):telemetry[field]=max(0,telemetry[field]-reserve)
        for slot in self._eligible_slots(task):
            width=self._slot_resources(slot,self.profiles[task['backend']]['cfg'])['requested_threads']
            verdict=self.admission.evaluate(task,width,snapshot,(),action='post_drain')
            if verdict['allowed']:return True
        self._admission_blocks[task['id']]=verdict
        return False

    def _reservations(self):
        values = []
        for key, intent in self.intents.items():
            if intent.get("scheduler",{}).get("not_invoked") or intent.get("scheduler",{}).get("preflight_receipt"):continue
            try:
                record = self._record(intent)
                if record and self._receipt(intent, record) and record.get("parallel_slot_released") is True:continue
            except (OSError, ValueError, KeyError, TypeError):
                pass  # An unresolved reservation still consumes its full allowance.
            values.append({"backend": intent["backend"],
                           "width": intent.get("requested_resources", {}).get("requested_threads", 1),
                           "rss_kib": self.snapshot.get("runs", {}).get(key, {}).get("rss_kib")})
        return values

    def _ready(self, task):
        self._ready_now.add(task['id'])
        self.state.setdefault('scheduler_metrics',{}).setdefault('ready_since',{}).setdefault(task['id'],time.time())

    def _admission(self, task, slot):
        if self.channel and self.channel.operations:
            verdict={"allowed":False,"blocking_dimension":"runner_channel","detail":"Original owner-locked runner channel busy"}
            self._admission_blocks[task['id']]=verdict
            return verdict
        width = self._slot_resources(slot, self.profiles[task["backend"]]["cfg"])["requested_threads"]
        verdict = self.admission.evaluate(task, width, self.snapshot, self._reservations())
        if not verdict["allowed"]:self._admission_blocks[task["id"]] = verdict
        return verdict

    def _stop_stalled(self, intent, reason):
        # First production revision follows the plan's alert-only watchdog policy.
        return {"status": "alert_only", "reason": reason, "cancel_supported": True,
                "action": "An explicit operator cancel request is required"}

    def _observe(self, task_id, intent, events, probe=True):
        meta = intent.setdefault("scheduler", {})
        if self.channel:
            completed = self.channel.completed(intent["run_id"])
            if completed:
                command, outcome = completed
                meta['last_operation']={'command':command,'ok':outcome.get('ok'),'duration_seconds':outcome.get('duration_seconds')}
                if command=='collect' and outcome.get('ok'):
                    stats=self.state.setdefault('scheduler_metrics',{})
                    stats['collect_seconds']=stats.get('collect_seconds',0)+outcome.get('duration_seconds',0)
                    stats['collect_count']=stats.get('collect_count',0)+1
                meta.pop("operation", None)
                if outcome.get("not_invoked") and command == "run":
                    # Local proof: subprocess.run was never entered; do not replay this ID.
                    meta.update(not_invoked=True, state="FAILED_UNLAUNCHED")
                elif (command=='run' and isinstance(outcome.get('payload'),dict)
                      and outcome['payload'].get('status')=='ORIGINAL_PREFLIGHT_REJECTED'
                      and self._preflight_rejected(intent,outcome['payload'].get('receipt'))):
                    meta.update(preflight_receipt=outcome['payload']['receipt'],state='FAILED_UNLAUNCHED')
                    events.append({'type':'preflight_rejected','id':task_id,'run_id':intent['run_id']})
                elif outcome["ok"]:
                    for key in ("failures", "error_class", "error", "manual_attention"):
                        meta.pop(key, None)
                    intent.pop("next_probe_at", None)
                    intent.pop("reconciliation_error", None)
                    if command=='cancel':
                        result=outcome['payload'].get('execution_outcome');meta['cancel_outcome']=result
                        if result not in ('TERMINATED_BY_OPERATOR','NATURAL_COMPLETION'):meta['cancel_manual_attention']=True
                    events.append({"type": "collected" if command == "collect" else command + "_completed",
                                   "id": task_id, "run_id": intent["run_id"]})
                else:
                    self._delay(intent, outcome)
                    if command=='cancel' and meta.get('error_class') not in ('TRANSIENT_NETWORK','TRANSIENT_LOCK_BUSY'):meta['cancel_manual_attention']=True
                    observed = self.snapshot.get("runs", {}).get(task_id, {})
                    if (command == "collect" and meta.get("error_class") == "PERMANENT_CONTRACT_ERROR"
                            and self.snapshot.get("ok") and observed.get("status") == "FINISHED"
                            and observed.get("alive") is False and not observed.get("error")):
                        meta.update(state="QUARANTINED", quarantined_at=time.time())
                        events.append({"type": "quarantined", "id": task_id, "run_id": intent["run_id"]})
        view = super()._observe(task_id, intent, events, probe=False)
        if view["collected"]:
            record = self._record(intent)
            state = ("TERMINATED" if record.get("execution_outcome") == "TERMINATED_BY_OPERATOR" else
                     "INTERRUPTED" if record.get("state") == "INTERRUPTED_COLLECTED" else
                     "SUCCEEDED" if view["success"] else "FAILED")
            view["task_state"] = state
            if not view["occupied"]:return view
        else:
            view["task_state"] = "SUBMITTING"
        if meta.get('preflight_receipt') and self._record(intent) is None:
            if not self._preflight_rejected(intent,meta['preflight_receipt']):raise ValueError('Original preflight receipt no longer verifies')
            view.update(status='failed_unlaunched',terminal_reconciled=True,occupied=False,
                        task_state='FAILED_UNLAUNCHED',reason='original_preflight_rejected')
            return view
        if meta.get("not_invoked"):
            view.update(status="failed_unlaunched", terminal_reconciled=True, occupied=False,
                        task_state="FAILED_UNLAUNCHED", reason="local_subprocess_not_invoked")
            return view
        if meta.get("state") == "QUARANTINED":
            view.update(status="reconciliation_pending",task_state="QUARANTINED", reason="archive_contract_requires_review")
            return view
        if meta.get("manual_attention"):
            view["reason"] = "runner_lock_retries_exhausted"
            return view
        alert = intent.get("watchdog_triggered")
        if alert:view.update(watchdog_triggered=True, watchdog_reason=alert["reason"])
        observed = self.snapshot.get("runs", {}).get(task_id)
        fresh = self.snapshot.get("ok") and observed and not observed.get("error")
        if not fresh:
            view.update(status="reconciliation_pending",task_state="UNKNOWN_REMOTE",reason="remote_observation_unavailable",remote_observation_fresh=False)
            return view
        view["remote_observation_fresh"] = True
        view["remote_observed_at"] = self.snapshot["observed_at"]
        view["remote_exit_code"] = observed.get("remote_exit_code")
        if observed.get("status") == "RUNNING":
            view.update(status="running", task_state="RUNNING")
            if intent["backend"] == "tcad":
                self._observe_watchdog(task_id, intent, view, events, observed, self._record(intent))
        elif not view['collected']:
            view['status']='reconciliation_pending'
            view['task_state']='COLLECTABLE' if observed.get('status')=='FINISHED' and observed.get('alive') is False else 'UNKNOWN_REMOTE'
        if meta.get('cancel_manual_attention'):view['reason']='cancellation_requires_operator_review'
        elif meta.get('cancel_request') and observed.get('status')=='RUNNING':view['task_state']='CANCEL_REQUESTED'

        if self.channel and self.channel.command(intent["run_id"]):
            command = self.channel.command(intent["run_id"])
            view["task_state"] = {"collect": "COLLECTING", "cancel": "TERMINATING", "run": "SUBMITTING"}[command]
        elif (not self.read_only and not self.channel.operations and time.time() >= intent.get("next_probe_at", 0)
              and (view["collected"] or (observed.get("status") == "FINISHED" and observed.get("alive") is False))):
            verdict = self.admission.evaluate(intent, view["requested_resources"]["requested_threads"],
                                              self.snapshot, self._reservations(), action="collect")
            if verdict["allowed"]:
                self._invoke(intent, "collect")
                view["task_state"] = "COLLECTING"
            else:
                view["reason"] = "collection_admission_" + verdict["blocking_dimension"]
        return view

    def _discovery(self):
        external, uncertain = super()._discovery()
        known = {item["run_id"]: item for item in self.intents.values()}
        for lease in self.snapshot.get("leases", []):
            if lease.get("state") == "COLLECTED":continue
            policy = lease.get("policy", {})
            run_id = policy.get("work_id")
            if run_id not in known:
                uncertain = True
            else:
                task_id=next(key for key,item in self.intents.items() if item['run_id']==run_id)
                expected=self._probe_records.get(task_id)
                if (not expected or policy!=expected.get('parallel_policy')
                        or lease.get('script_sha256')!=expected.get('script_sha256')
                        or lease.get('state') not in ('RESERVED','ACTIVE')):uncertain=True
                identity=self.snapshot.get('runs',{}).get(task_id,{}).get('identity')
                if lease.get('state')=='ACTIVE' and (not identity or lease.get('identity')!=identity):uncertain=True
        folders = {record["remote_directory"] for record in self._probe_records.values()}
        if any(process.get("cwd") not in folders for process in self.snapshot.get("processes_with_solver_names", [])):
            uncertain = True
        lease_slots={lease.get('policy',{}).get('slot') for lease in self.snapshot.get('leases',[]) if lease.get('state')!='COLLECTED' and lease.get('policy',{}).get('work_id') in known}
        conflicts=[]
        for lock in self.snapshot.get('locks',[]):
            name=Path(lock['path']).name
            if name=='allocation.lock' or (name=='.solver.lock' and (lock.get('mode')!='READ' or not lease_slots)):
                conflicts.append(lock)
            elif name.startswith('slot-') and int(name[5:-5]) not in lease_slots:conflicts.append(lock)
        self.snapshot['lock_conflicts']=conflicts
        return external,bool(uncertain or self._invalid_records or not self.snapshot.get('ok') or self.snapshot.get('locks_verified') is not True or conflicts)

    def cancel_task(self, task_id, reason, by="operator", grace_seconds=15):
        if self.read_only:raise ValueError("Read-only engine cannot cancel")
        matches = [(key, item) for key, item in self.intents.items() if key == task_id or item["run_id"] == task_id]
        if len(matches) != 1:raise ValueError("Cancellation requires one existing original task/run ID")
        key, intent = matches[0]
        record = self._record(intent)
        if record is None:raise ValueError("Original manifest unavailable; cancellation refused")
        if self._receipt(intent, record):return {"status": "already_collected", "id": key}
        if not reason.strip():raise ValueError("Cancellation reason is required")
        request = {"reason": reason, "by": by, "grace_seconds": grace_seconds, "requested_at": time.time()}
        meta=intent.setdefault('scheduler',{});previous=meta.get('cancel_request')
        if previous and any(previous.get(key)!=request[key] for key in ('reason','by','grace_seconds')):raise ValueError('Original cancellation request parameters are immutable')
        if not previous:meta['cancel_request']=request
        else:meta['cancel_retry_requested_at']=time.time()
        meta.pop('cancel_manual_attention',None);intent.pop('next_probe_at',None)
        self._save()
        return {"status": "requested", "id": key, "run_id": intent["run_id"]}

    def request_drain(self, target_profile, reason):
        if target_profile not in self.profiles:raise ValueError("Unknown configured backend")
        schema = self.profiles[target_profile]["resources"]["schema"]
        runtime.scheduler_pool.PoolStateMachine(self.state.setdefault("pool_state", {})).request_drain(schema, reason, time.time())
        self._save()

    def cancel_drain(self):
        runtime.scheduler_pool.PoolStateMachine(self.state.setdefault("pool_state", {})).cancel_drain()
        self._save()

    def _commands(self):
        directory = self.state_dir / "commands"
        if not directory.exists():return
        for path in sorted(directory.glob("*.json"))[:32]:
            if path.name.endswith(".receipt.json"):continue
            receipt = path.with_name(path.stem + ".receipt.json")
            if receipt.exists():continue
            try:
                command = runtime.read_json(path)
                if command["action"] == "cancel":
                    result = self.cancel_task(command["target"], command["reason"], command.get("by", "operator"), command.get("grace_seconds", 15))
                elif command["action"] == "drain":
                    self.request_drain(command["target"], command.get("reason", "operator request"));result = {"status": "requested"}
                elif command["action"] == "cancel_drain":
                    self.cancel_drain();result = {"status": "cancelled"}
                else:raise ValueError("Unknown operator action")
            except (OSError, ValueError, TypeError, KeyError) as exc:
                result = {"status": "refused", "detail": str(exc)}
            runtime.write_json(receipt, result)

    def _cancellations(self):
        for key, intent in self.intents.items():
            meta = intent.get("scheduler", {})
            request = meta.get("cancel_request")
            if not request or meta.get("cancel_manual_attention") or self.channel.operations or time.time()<intent.get("next_probe_at",0):continue
            observed = self.snapshot.get("runs", {}).get(key, {})
            if not self.snapshot.get("ok") or observed.get("error"):continue
            if observed.get("status") == "FINISHED":continue
            if observed.get("status") != "RUNNING":continue
            argv = self._argv(intent, "cancel") + ["--reason", request["reason"], "--requested-by", request["by"], "--grace-seconds", str(request["grace_seconds"])]
            # Persist before execution. On crash, runner cancellation receipts govern reconciliation.
            meta["cancel_invoked"] = True
            self._save()
            self.channel.submit(intent["run_id"], "cancel", argv, self.workspace, self._runner_environment(), max(self.timeout, request["grace_seconds"] + 30))

    def tick(self, allow_submit=True):
        started = time.monotonic()
        self._admission_blocks={}
        self._profile()
        records = {}
        invalid = []
        for key, intent in self.intents.items():
            try:
                record = self._record(intent)
                if record and not (self._receipt(intent, record) and record.get("parallel_slot_released") is True):records[key] = record
            except (OSError, ValueError, TypeError, KeyError) as exc:
                invalid.append({"id": key, "detail": str(exc)[:300]})
        self._probe_records, self._invalid_records = records, bool(invalid)
        self.snapshot = self.probe.probe(records, self.profiles)
        if not self.read_only:
            self._commands()
            self._cancellations()
        self._ready_now=set()
        observation = super().tick(allow_submit=allow_submit and not self.read_only)
        if invalid:observation["discovery_uncertain"] = True
        pool = self.state.get("pool_state", {})
        breakdown = dict(collections.Counter(item["reason"] for item in observation["pending_tasks"]))
        events = observation["events"]
        dispatched = [event["id"] for event in events if event["type"] == "submission_requested"]
        collected = [event["id"] for event in events if event["type"] == "collected"]
        quarantined = [item["id"] for item in observation["runs"] if item.get("task_state") == "QUARANTINED"]
        action = "dispatched" if dispatched else "collected" if collected else "waiting"
        reason=('slots_and_resources_available' if dispatched else
                'remote_or_original_identity_unresolved' if observation['discovery_uncertain'] else
                'original_runner_busy' if self.channel and self.channel.operations else
                'draining_'+str(pool.get('target')) if pool.get('state')=='DRAINING' else
                pool.get('blocked_reason') or next(iter(breakdown),'no_ready_tasks'))
        decision = {"action": action, "primary_reason": reason,
                    "summary": f"{pool.get('state', 'IDLE')}; dispatched={len(dispatched)}, collected={len(collected)}, quarantined={len(quarantined)}; {reason}",
                    "dispatched":dispatched,"collected":collected,"terminated":[item["id"] for item in observation["runs"] if item.get("task_state")=="TERMINATED"],"quarantined":quarantined,
                    "blocked_breakdown": breakdown, "tick_duration_ms": round((time.monotonic() - started) * 1000, 2)}
        diagnostics={item['id']:{key:item.pop(key) for key in ('task_state','remote_observation_fresh','remote_observed_at') if key in item} for item in observation['runs']}
        for key,metadata in diagnostics.items():
            metadata['operation']=self.channel.command(self.intents[key]['run_id']) if self.channel else None
            meta=self.intents[key].get('scheduler',{})
            metadata['error_class']=meta.get('error_class')
            metadata['manual_attention']=bool(meta.get('manual_attention') or meta.get('cancel_manual_attention'))
        observation["scheduler"] = {"schema": "tcad-scheduler-v3", "pool": dict(pool),
                                      "tasks":diagnostics,"read_only":self.read_only,"admission_blocks":self._admission_blocks,
                                     "resources": self.snapshot.get("telemetry", {}), "last_decision": decision,
                                     "probe": {k: v for k, v in self.snapshot.items() if k in ("ok", "observed_at", "error")},
                                     "invalid_records": invalid, "metrics": {"slot_utilization": observation["active_count"] / self.slots,
                                     "running_slot_ratio": observation["running_count"] / self.slots}}
        stats=self.state.setdefault('scheduler_metrics',{});now=time.time()
        stats['ready_since']={key:value for key,value in stats.get('ready_since',{}).items() if key in self._ready_now and key not in self.intents}
        intervals=[entry for entry in stats.get('idle_intervals',[]) if entry[0]>now-3600]
        delta=now-stats.get('last_tick_at',now)
        if stats.get('idle_with_ready') and 0<delta<=2*self.policy.get('poll_interval_seconds',5):intervals.append([now,delta])
        stats.update(idle_intervals=intervals,last_tick_at=now,idle_with_ready=bool(stats['ready_since'] and observation['active_count']<self.limit))
        phase=observation['pool_phase'].get('schema')
        if dispatched and phase:
            if stats.get('last_profile') and stats['last_profile']!=phase:stats['profile_switches_total']=stats.get('profile_switches_total',0)+1
            stats['last_profile']=phase
        observation['scheduler']['metrics'].update(
            idle_with_ready_seconds_1h=sum(entry[1] for entry in intervals),
            avg_dispatch_latency_s=stats.get('dispatch_seconds',0)/stats['dispatch_count'] if stats.get('dispatch_count') else None,
            avg_collect_duration_s=stats.get('collect_seconds',0)/stats['collect_count'] if stats.get('collect_count') else None,
            profile_switches_total=stats.get('profile_switches_total',0),errors_by_class=stats.get('errors_by_class',{}))
        states=collections.Counter(item.get('task_state') for item in diagnostics.values())
        observation['scheduler']['pool']['slots']={'total':self.slots,'running':observation['running_count'],'collecting':states['COLLECTING'],'quarantined':states['QUARANTINED'],'free':max(0,self.slots-observation['active_count'])}
        observation["scheduler"]["fresh_max_age_seconds"] = max(30, 3 * self.policy.get("poll_interval_seconds", 5))
        if not self.read_only:
            self._save()
            metrics = self.state_dir / "metrics.jsonl"
            if metrics.exists() and metrics.stat().st_size > 5 * 1024 * 1024:
                metrics.replace(metrics.with_suffix(".previous.jsonl"))
            with metrics.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"time":time.time(),**decision,"metrics":observation["scheduler"]["metrics"]}) + "\n")
        return observation

    def _maintain_results(self, views):
        if not self.read_only and not self.channel.operations:super()._maintain_results(views)

    def _offload_results(self, views):
        if not self.read_only and not self.channel.operations:super()._offload_results(views)

    def explain(self):
        path = self.state_dir / "observation.json"
        return runtime.read_json(path).get("scheduler", {}) if path.exists() else {"status": "no_observation"}

    def close(self):
        if self.channel:self.channel.close()
