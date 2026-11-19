#!/usr/bin/env python3
"""Opt-in paid Sol -> native Astra -> same-ID follow-up check.

Creates an isolated Codex home and empty read-only workspace. Never invokes the
controller service, original runner, SSH, a solver or the research task queue.
Run on the server as the existing tcad user, with an explicitly new output path.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid

import advisor
import controller


def inspect_evidence(output):
    """Audit persisted native records without sending any model request."""
    output = Path(output)
    probe = controller.read_json(output / "probe.json")
    native = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines() if line.strip()]
    root = next(x["thread_id"] for x in native if x.get("type") == "thread.started")
    sessions = []
    for path in (output / "state/codex-home/sessions").rglob("*.jsonl"):
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        meta = rows[0].get("payload", {})
        turns = [x["payload"] for x in rows if x.get("type") == "turn_context"]
        calls = [x["payload"] for x in rows if x.get("type") == "response_item"
                 and x.get("payload", {}).get("type") == "function_call"]
        answers = [x["payload"].get("last_agent_message", "") for x in rows
                   if x.get("type") == "event_msg"
                   and x.get("payload", {}).get("type") == "task_complete"]
        usage = [x["payload"].get("info", {}).get("total_token_usage") for x in rows
                 if x.get("type") == "event_msg"
                 and x.get("payload", {}).get("type") == "token_count"
                 and x.get("payload", {}).get("info")]
        sessions.append({"path": path, "meta": meta, "turns": turns, "calls": calls,
                         "answers": answers, "usage": usage[-1] if usage else None})
    primary = next(s for s in sessions if s["meta"].get("id") == root)
    children = [s for s in sessions if s["meta"].get("agent_role") == "astra_advisor"]
    checks = {
        "one_advisor": len(children) == 1,
        "main_sol_high": bool(primary["turns"]) and all(
            x.get("model") == "auto/gpt-6.1-sol" and x.get("effort") == "high"
            for x in primary["turns"]),
        "one_native_spawn": sum(x.get("name", "").split(".")[-1] == "spawn_agent"
                                for x in primary["calls"]) == 1,
        "parent_completed": bool(primary["answers"]),
    }
    child = children[0] if len(children) == 1 else None
    if child:
        meta = child["meta"]
        spawn = (meta.get("source") or {}).get("subagent", {}).get("thread_spawn", {})
        handle = meta.get("agent_path", spawn.get("agent_path"))
        followups = [json.loads(x["arguments"]) for x in primary["calls"]
                     if x.get("name", "").split(".")[-1] in ("followup_task", "send_input")]
        allowed = {"spawn_agent", "wait_agent", "wait", "followup_task", "send_input",
                   "list_agents", "tool_search", "close_agent"}
        checks.update({
            "native_parent_link": spawn.get("parent_thread_id") == root,
            "astra_high_both_turns": len(child["turns"]) == 2 and all(
                x.get("model") == "auto/gpt-6-astra" and x.get("effort") == "high"
                for x in child["turns"]),
            "same_native_followup": len(followups) == 1 and
                (followups[0].get("target") == handle or followups[0].get("id") == meta.get("id")),
            "two_real_answers": len(child["answers"]) == 2 and all(
                probe["nonce"] in text for text in child["answers"]),
            "advisor_no_tool_execution": not child["calls"],
            "parent_only_collaboration_tools": all(
                x.get("name", "").split(".")[-1] in allowed for x in primary["calls"]),
            "readonly_isolated_turns": all(
                x.get("sandbox_policy", {}).get("type") == "read-only"
                and x.get("cwd") == probe["workspace"]
                for x in primary["turns"] + child["turns"]),
        })
    result = {
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "passed": all(checks.values()), "checks": checks,
        "root_thread_id": root,
        "advisor_thread_id": child["meta"].get("id") if child else None,
        "advisor_task_name": child["meta"].get("agent_path") if child else None,
        "root_usage": primary["usage"], "advisor_usage": child["usage"] if child else None,
        "advisor_answers": child["answers"] if child else [],
        "native_files": {str(s["path"]): hashlib.sha256(s["path"].read_bytes()).hexdigest()
                         for s in [primary] + ([child] if child else [])},
        "boundary": "Functional native consultation proof using artificial inputs; not scientific validation",
    }
    controller.write_json(output / "verified-evidence.json", result)
    return result


def verify(policy_path, output):
    policy = controller.policy_at(policy_path)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.chmod(output, 0o700)
    workspace = output / "empty-workspace"
    workspace.mkdir()
    isolated = dict(policy, state_dir=str(output / "state"), workspace=str(workspace))
    route = controller.route_at(policy)
    if route["model"] != "auto/gpt-6.1-sol" or route["effort"] != "high":
        raise ValueError("Expected the existing Sol high route; source route was not changed")
    env = controller.prepare_codex(isolated, route)
    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {k: {"type": "string"} for k in
                       ("advisor_id", "diagnosis", "followup_answer", "next_action")},
        "required": ["advisor_id", "diagnosis", "followup_answer", "next_action"],
    }
    controller.write_json(output / "answer.schema.json", schema)
    nonce = uuid.uuid4().hex[:12]
    prompt = f"""
这是用户明确授权的一次原生顾问功能验证，不是仿真任务。你是 Sol high 主工程师。
必须真实调用一次原生 spawn_agent，agent_type=astra_advisor，独立上下文（不要 fork 历史）。
如果多代理工具延迟加载，请先查找原生 spawn_agent/send_input/wait 工具。
无需读取文件、执行命令、使用网络工具、修改环境或启动任何仿真；禁止这些动作。
请向顾问发送这个完整问题包：
“功能验证 {nonce}。以下均为人工示例而非真实实验：质子均匀照射面积 A=2e-6 cm²，
N=200000 个独立质子，记录翻转 k=0。定义 fluence=N/A，sigma=k/fluence；
给定零计数时95%单侧上限 sigma_upper=-ln(0.05)/fluence。
训练截面预测器时能否把这个零计数样本视为精确 sigma=0？
请给出判断、上述上限的数值/单位、应保存的统计信息；仅按给定公式，不引入文献或实测主张。
请在答复末尾写回验证标记 {nonce}。”
等待该顾问答复后，必须向刚才返回的同一个 task_name/agent_id 用 followup_task
（旧版则用 send_input；send_message 不会唤醒空闲代理）
追问一次：“保持原问题，只把 N 提高到2000000且仍k=0，上限如何变化？
请用一句话回复，并保留标记 {nonce}。”
再等待答复，最后输出schema要求的JSON，advisor_id填真实原生任务路径或会话ID。
诊断与追问结果应来自顾问实际答复。总共只创建一个顾问，不生成额外代理。
工具若失败如实报告，不伪造调用或ID。此次只验证调用和续问，不验证科学模型。
"""
    (output / "prompt.md").write_text(prompt, encoding="utf-8")
    command = [
        policy["codex_binary"], "exec", "--cd", str(workspace),
        "--skip-git-repo-check", "--sandbox", "read-only",
        "-c", 'approval_policy="never"',
        "-c", "features.shell_tool=false",
        "-c", "features.apps=false",
        "-c", "features.plugins=false",
        "-c", "features.memories=false",
        "--json", "--color", "never", "--output-schema", str(output / "answer.schema.json"),
        "--output-last-message", str(output / "answer.json"), "-",
    ]
    started = time.monotonic()
    controller.write_json(output / "probe.json", {
        "state": "starting", "utc": datetime.now(timezone.utc).isoformat(),
        "main_model": route["model"], "advisor_model": advisor.MODEL,
        "effort": "high", "nonce": nonce, "workspace": str(workspace),
        "simulation_submission": False,
    })
    with (output / "events.jsonl").open("wb") as events, (output / "stderr.log").open("wb") as errors:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=events,
                                 stderr=errors, env=env, cwd=str(workspace),
                                 start_new_session=True)
        try:
            child.communicate(prompt.encode("utf-8"), timeout=900)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
            raise
        finally:
            advisor.record_events(output, output, Path(env["CODEX_HOME"]))
    controller.write_json(output / "probe-result.json", {
        "exit_code": child.returncode, "elapsed_seconds": round(time.monotonic() - started, 3),
        "main_model": route["model"], "advisor_model_requested": advisor.MODEL,
        "effort": "high", "simulation_submission": False,
        "native_events": str(output / "events.jsonl"),
        "verification": "Inspect native spawn/message/wait events and child turn_context; answer alone is insufficient",
    })
    checked = inspect_evidence(output)
    return {"output": str(output), "exit_code": child.returncode, "verified": checked["passed"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy")
    parser.add_argument("--output", required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--live-model-check", action="store_true")
    modes.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args()
    if args.inspect_only:
        result = inspect_evidence(args.output)
        print(json.dumps({k: result[k] for k in ("passed", "checks", "root_thread_id", "advisor_thread_id")},
                         ensure_ascii=False))
    else:
        if not args.policy:
            parser.error("--live-model-check requires --policy")
        result = verify(args.policy, args.output)
        print(json.dumps(result, ensure_ascii=False))
    if not result.get("passed", result.get("verified", False)):
        raise SystemExit(1)
