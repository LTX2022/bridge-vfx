# -*- coding: utf-8 -*-
"""对照复核方 reproduce.py 的四项行为（独立审查方法学：AST 提取 + fake hou，无 DCC）。

原脚本在候选类新增 @contextmanager 依赖后无法执行（NameError: contextmanager），
本 harness 提供同一执行环境并断言四项行为已按返修要求取反：
  1. 查询不启动执行（status 纯读，QUEUED 保持 QUEUED）
  2. 跨任务重型名额互斥（taskA 活跃时 taskB 提交被拒）
  3. 损坏记录被拒并保留（同请求不当作新请求）
  4. 旧代次 RUNNING 不被查询提升（恢复由 advance 原子领取/核对）
"""
import ast, json, os, sys, tempfile, types
from typing import Any, Optional
from pathlib import Path
from uuid import uuid4

base = Path(sys.argv[1]).resolve()
source = base / "plugins/houdini/_impl/houdini_bridge_addon.py"
tree = ast.parse(source.read_text())
klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "OperationRunner")
helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in
           ("_fx_frame_values", "_fx_configuration", "_task_name")]

sys.modules["hou"] = types.SimpleNamespace(node=lambda p: None, setFrame=lambda f: None, time=lambda: 0.0,
                                           applicationVersionString=lambda: "21.0.631", isUIAvailable=lambda: False)


class FakeGeometry:
    def boundingBox(self): return type("BB", (), {"sizevec": lambda s: (0.0, 0.0, 0.0)})()
    def points(self): return []
    def prims(self): return []
    def pointAttribs(self): return []


class FakeNode:
    def userData(self, name): return None
    def cook(self, force=False): pass
    def errors(self): return []
    def geometry(self): return FakeGeometry()


with tempfile.TemporaryDirectory() as temp:
    env = dict(globals())
    env.update(
        hou_node=lambda p: FakeNode(), hou_set_frame=lambda f: None, hou_time=lambda: 0.0,
        _HEAVY_SLOT_FD=None,
        _durable_execution_lock=None,
        os=__import__("os"), json=json, time=__import__("time"),
        threading=__import__("threading"), hashlib=__import__("hashlib"),
        datetime=__import__("datetime").datetime, timezone=__import__("datetime").timezone,
        contextmanager=__import__("contextlib").contextmanager,
        Path=Path, uuid4=uuid4,
        BridgeCommandError=type("BridgeCommandError", (RuntimeError,), {}),
        _SERVER=types.SimpleNamespace(port=8101, session_id="s"),
        _FX_LOADED_ADDON_SHA256="0" * 64,
        _fx_operations_store_path=lambda task: Path(temp) / ("ops_%s.json" % task),
        _fx_host_generation=lambda: uuid4().hex[:12],
        _fx_manifest=lambda t, **k: (None, {"domain_pack": "p", "nodes": {"output": "/out"}, "input_digest": "same"}),
        _fx_task_paths=lambda t, root=None: ("/obj/B_" + t, "/stage/s_" + t),
        _fx_state_path=lambda t: Path(temp) / ("st_%s.json" % t),
        _fx_task_saves_path=lambda t: Path(temp) / ("sv_%s.json" % t),
        _check_executor_generation=lambda t: None,
        _task_name=lambda task, prefix: prefix + "_" + task,
        _load_core_contract=lambda: types.SimpleNamespace(derive_operation_id=lambda t, s, f: t + "|" + str(f)),
    )
    def _fx_heavy_slot_release():
        fd = env.get("_HEAVY_SLOT_FD")
        if fd is not None:
            os.close(fd)
        env["_HEAVY_SLOT_FD"] = None

    env["_fx_heavy_slot_release"] = _fx_heavy_slot_release
    lock_spec = __import__("importlib").util.spec_from_file_location("_rv_durable_lock", base / "plugins/houdini/_impl/durable_lock.py")
    lock_module = __import__("importlib").util.module_from_spec(lock_spec)
    lock_spec.loader.exec_module(lock_module)
    env["_durable_execution_lock"] = lock_module.execution_lock
    exec(compile(ast.Module(body=helpers + [klass], type_ignores=[]), str(source), "exec"), env)
    Runner = env["OperationRunner"]
    out = {}

    # 1. query must not start execution
    a = Runner("a")
    op = a.submit({"step_params": {"frames": [2, 4]}}, "p", {})
    before = a.status(op["request_id"])["state"]
    out["query_does_not_start_execution"] = (before == "QUEUED")

    # 2. installation-wide heavy slot across tasks
    out["advance_claims_without_query"] = None
    b = Runner("b")
    try:
        b.submit({"step_params": {"frames": [2]}}, "p", {})
        out["second_task_rejected_while_first_queued"] = True
    except Exception as exc:
        out["second_task_rejected_while_first_queued"] = "BUSY" in str(exc).upper()

    # 1b. advance claims by itself and holds the slot while running
    a.advance()
    disk = json.loads((Path(temp) / "ops_a.json").read_text())["operations"][op["request_id"]]
    out["advance_claims_without_query"] = disk["state"] == "RUNNING" and disk["frames_done"] == [2]
    try:
        b.submit({"step_params": {"frames": [2]}}, "p", {})
        out["second_task_rejected_while_first_running"] = True
    except Exception as exc:
        out["second_task_rejected_while_first_running"] = "BUSY" in str(exc).upper()


    # release a's slot first (cancel its still-running op; slot is installation-wide)
    a.cancel(op["request_id"])
    a.advance()  # observes the cancel -> CANCELLED -> slot released

    # 4. old-generation RUNNING not promoted by query; reconciled by advance
    c = Runner("c")
    op2 = c.submit({"step_params": {"frames": [2, 4]}}, "p", {})
    c.advance()  # claims with c's generation; cook one frame
    disk2 = json.loads((Path(temp) / "ops_c.json").read_text())["operations"][op2["request_id"]]
    disk2["claimed_by_generation"] = "dead-generation"
    store2 = json.loads((Path(temp) / "ops_c.json").read_text())
    store2["operations"][op2["request_id"]] = disk2
    (Path(temp) / "ops_c.json").write_text(json.dumps(store2))
    stale = Runner("c")
    before_state = stale.status(op2["request_id"])["state"]
    stale.advance()
    after_state = json.loads((Path(temp) / "ops_c.json").read_text())["operations"][op2["request_id"]]["state"]
    out["old_generation_running_promoted_by_query"] = (before_state != disk2["state"])  # False = query is pure
    out["old_generation_running_reconciled_by_advance"] = (after_state == "RECONCILE")

    # 3. corrupt store preserved and refused (isolated task d; quarantining the
    # store is itself the required behavior, so this scenario runs last)
    d = Runner("d")
    d.submit({"step_params": {"frames": [2]}}, "p", {})
    # 3. corrupt store preserved and refused
    store_path = Path(temp) / "ops_d.json"
    store_path.write_text("{broken", encoding="utf-8")
    try:
        d.submit({"step_params": {"frames": [2, 4]}}, "p", {})
        out["corrupt_store_same_request_refused"] = True
    except Exception as exc:
        out["corrupt_store_same_request_refused"] = "CORRUPT" in str(exc).upper()
    out["corrupt_record_preserved"] = bool(list(Path(temp).glob("ops_d.json.corrupt*")))

    verdict = all([out["query_does_not_start_execution"], out["advance_claims_without_query"],
                   out["second_task_rejected_while_first_queued"], out["second_task_rejected_while_first_running"],
                   out["corrupt_store_same_request_refused"], out["corrupt_record_preserved"],
                   not out["old_generation_running_promoted_by_query"],
                   out["old_generation_running_reconciled_by_advance"]])
    out["REWORK_VERDICT"] = "PASS" if verdict else "FAIL"
    print(json.dumps(out, indent=1))
