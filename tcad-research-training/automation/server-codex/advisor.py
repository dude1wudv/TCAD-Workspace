"""Native Codex advisor configuration and a small durable session index.

No API transport, background scheduler, solver calls or additional credentials.
Codex owns child threads, async messaging, usage and persisted transcripts.
"""
import hashlib
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import uuid


HERE = Path(__file__).resolve().parent
ROLE = "astra_advisor"
MODEL = "auto/gpt-6-astra"

GUIDANCE = """
## 按需 Astra 顾问（Codex 原生子代理）
你仍是主工程师。遇到复杂建模、难以区分的数值故障、结果矛盾或重要方案权衡，
可立即用原生 spawn_agent 创建 agent_type="astra_advisor" 的独立上下文。
不要求先失败几次、不设评分阈值、不逐项强制会诊。普通问题自行解决。
传递明确问题、希望得到的决定、必要证据/来源/单位、已尝试方法和约束；
不要复制整段聊天或把整个仓库发送给顾问。用精简任务包，不继承整段历史。
原生调用可能返回 task_name（例如 /root/advice_case）或 agent_id（UUID）。
保留并原样复用这个句柄。同一难题优先用原生 followup_task(target=task_name)
续问已完成/空闲的顾问；send_message 只投递消息，不会唤醒空闲代理。
旧版接口用 send_input(id=agent_id)；等待用 wait_agent/wait，字段以工具schema为准。
顾问异步工作时推进独立事项，不短间隔轮询，不把它变成必经审批。
优先复用同一问题已有答复，新证据或确有价值的追问可以继续。
记录本次问题、证据版本、原生会话 ID、建议、采用决定和实际验证结果；
建议不是科学验证结果。可把记录放在 local_runtime/server-codex/advice/。
控制器另存 advisory-sessions.json 及各轮原生 events.jsonl 作为会话导航。
恢复时先查这些记录和原生会话已有输出，并用 list_agents（若提供）确认句柄是否仍活跃。
同一根会话中的可用 task_name 直接续问；若当前工具提供 resume_agent，则用记录的UUID恢复。
task_name 只在所属原生代理树内有效，不把旧根会话的同名路径当作新会话句柄。
跨根会话时先读已持久化答复；需继续咨询而本版没有恢复原代理的工具时，
才创建精简接续咨询并注明旧UUID和新证据，不重复已经完成的问题。
不要仅因 SSH 断线或不知道答复状态就重新 spawn 或重发同一付费问题。
本轮结束前优先取回答复；若预算将尽，记录未完成会话 ID 和待恢复状态。
顾问不可用只标注该咨询，继续可处理任务；不要为了测试它反复调用模型。
所有仿真仍经原 queue_file 和原九槽运行器。顾问不得提交或收集作业。
"""


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def configure(home):
    """Only the controller's private CODEX_HOME, never the source Magpie config."""
    role = Path(home) / "agents" / (ROLE + ".toml")
    content = (HERE / (ROLE + ".toml")).read_text(encoding="utf-8")
    if not role.exists() or role.read_text(encoding="utf-8") != content:
        atomic_text(role, content)
    # Explicit declaration also works with Codex's legacy multi_agent backend.
    return [
        "[agents." + ROLE + "]",
        'description = "按需 Astra high 顾问，无失败次数门槛，无审批权。"',
        "config_file = " + json.dumps(str(role), ensure_ascii=False),
    ]


def native_sessions(home, root, event_file):
    """Inspect only the relevant day(s) in this controller's private home."""
    home, event_file = Path(home), Path(event_file)
    days = {datetime.fromtimestamp(event_file.stat().st_mtime, timezone.utc).date()}
    try:
        days.add(datetime.strptime(event_file.parent.name[:8], "%Y%m%d").date())
    except ValueError:
        pass
    days |= {day - timedelta(days=1) for day in tuple(days)}
    result = []
    for day in sorted(days):
        directory = home / "sessions" / day.strftime("%Y/%m/%d")
        for path in sorted(directory.glob("*.jsonl")):
            with path.open(encoding="utf-8", errors="replace") as stream:
                try:
                    first = json.loads(next(stream))
                except (StopIteration, ValueError):
                    continue
                if first.get("type") != "session_meta":
                    continue
                meta = first.get("payload", {})
                source = meta.get("source", {})
                spawn = source.get("subagent", {}).get("thread_spawn", {}) if isinstance(source, dict) else {}
                if spawn.get("parent_thread_id") != root or meta.get("agent_role", spawn.get("agent_role")) != ROLE:
                    continue
                record = {
                    "session_id": meta.get("id"), "parent_thread_id": root,
                    "task_name": meta.get("agent_path", spawn.get("agent_path")),
                    "role": ROLE, "rollout_path": str(path), "state": "unknown",
                }
                for line in stream:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    payload = row.get("payload", {})
                    if row.get("type") == "turn_context":
                        record.update(model=payload.get("model"), effort=payload.get("effort"))
                    if row.get("type") == "event_msg":
                        kind = payload.get("type")
                        if kind in ("task_started", "task_complete", "turn_aborted"):
                            record["state"] = kind
                        if kind == "task_complete":
                            record["last_answer"] = payload.get("last_agent_message", "")[:12000]
                        if kind == "token_count":
                            record["usage"] = (payload.get("info") or {}).get("total_token_usage")
                result.append(record)
    return result


def record_events(state, cycle, codex_home=None):
    """Keep native conversation handles even after a model timeout/restart.

    Store bounded native collaboration items verbatim, not a second task ledger.
    The canonical scientific state and native transcripts remain untouched.
    """
    state, cycle = Path(state), Path(cycle)
    source = cycle / "events.jsonl"
    if not source.exists():
        return
    native = []
    root = None
    with source.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                continue  # An interrupted final JSONL record may be partial.
            if event.get("type") == "thread.started":
                root = event.get("thread_id")
            item = event.get("item") or {}
            if isinstance(item, dict) and (
                item.get("type") == "collab_tool_call"
                or "collab" in str(item.get("type", ""))
            ):
                native.append(item)
    if not root and not native:
        return
    sessions = native_sessions(codex_home or state / "codex-home", root, source) if root else []
    # Retain completed consultations across ordinary cycles with no consultation.
    previous_path = state / "advisory-sessions.json"
    previous = {}
    if previous_path.exists():
        try:
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    retained = {x["session_id"]: x for x in previous.get("advisor_sessions", [])
                if isinstance(x, dict) and x.get("session_id")}
    retained.update({x["session_id"]: x for x in sessions if x.get("session_id")})
    record = {
        "schema": "tcad-native-advice-v1", "root_thread_id": root,
        "cycle": str(cycle), "native_events": native,
        "advisor_sessions": list(retained.values())[-128:],
        "event_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "semantics": "Native session navigation only; not job or scientific status",
    }
    atomic_text(cycle / "advisory-sessions.json",
                json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    # Full history stays in the native rollouts and each cycle's index. The
    # bounded latest index is referenced by path, never copied into the prompt.
    atomic_text(state / "advisory-sessions.json",
                json.dumps(record, ensure_ascii=False, indent=2) + "\n")
