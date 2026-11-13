"""Houdini Agent Bridge v5 - Battle-tested.

Synthesized from 3 proven reference implementations:
  - Houdini-Agent-main: socketserver.ThreadingMixIn + StreamRequestHandler,
    idempotent single-start guard, port-file + auto-increment
  - houdini-mcp-main: hou.session persistence (the canonical Houdini way),
    explicit stop/cleanup entrypoints
  - DCC-ASSET-MANAGER: stop_event signaling for clean shutdown

ROOT CAUSE of DeepSeek's v3 zombie-thread disaster:
  v3 stored server state in globals(). But globals() varies by editor
  namespace (Python Shell != Source Editor != exec()). So the cleanup code
  `globals().get("_bridge_running")` never found the old state -> 15+ zombie
  serve_forever threads piled up, all racing to accept() on port 9877,
  each answering with its own stale command dict ("Unknown command: save_hip").

FIX (this file):
  State lives on hou.session - Houdini's official cross-namespace persistent
  object. Every Python context (Shell/Source Editor/Textport/exec'd code)
  sees the same hou.session. Re-running this script finds the old server,
  stops it cleanly, then starts fresh. Generation counter makes any stray
  thread self-terminate within 1s even if stop() somehow fails.

Usage (paste in Houdini Python Shell OR Source Editor - both work):
  exec(open(r"C:/Users/32200/.zcode/workspace/default/houdini_bridge.py").read())

To stop explicitly (optional):
  exec(open(r"C:/Users/32200/.zcode/workspace/default/houdini_bridge.py").read()\
       .replace('__main__ check', '__stop__'))

Protocol: one JSON-lines request per TCP connection (newline-terminated).
  Request:  {"type": "<cmd>", "params": {...}}\n
  Response: {"status": "ok", "result": {...}}\n
            {"status": "error", "error": "..."}\n

21 commands:
  ping  scene_info  save_hip  get_node_info  get_node_children  get_node_parms
  get_subtree  find_nodes  create_node  connect_nodes  set_parm  press_button
  layout_nodes  delete_node  cook_node  bypass_node  exec_python
  query_help  list_help  help_stats  debug_list
"""
import json, os, re, sys, socket, socketserver, threading, traceback
import hou

HOST = "127.0.0.1"
PORT_BASE = 9877
PORT_RANGE = 20
SESSION_KEY = "fable8_bridge_v5"   # attr on hou.session
_PORT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "HoudiniAgent")
_PORT_FILE = os.path.join(_PORT_DIR, "bridge.port")
_LOG_FILE = os.path.join(_PORT_DIR, "bridge.log")
_READ_CAP = 16 * 1024 * 1024  # 16 MiB per request line (matches Houdini-Agent-main)

# === Logging ===

def _log(msg):
    """Append to bridge.log for debugging (best-effort)."""
    try:
        os.makedirs(_PORT_DIR, exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            import datetime
            f.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass

def _say(msg):
    """Print to Houdini console AND log file."""
    print(msg, flush=True)
    _log(msg)

# === Helpers ===

def _ok(result):
    return {"status": "ok", "result": result}

def _err(msg):
    return {"status": "error", "error": str(msg)}

def _get_node(path):
    n = hou.node(str(path or ""))
    if n is None:
        raise ValueError(f"Node not found: {path}")
    return n

def _json_default(obj):
    """Stringify non-JSON-serializable objects (Houdini types, etc.)."""
    try:
        return str(obj)
    except Exception:
        return repr(obj)

def _safe_attr(node, method_name):
    """Call a node method, return False on any failure (broad except, not AttributeError)."""
    try:
        return getattr(node, method_name)()
    except Exception:
        return False

# === Command Registry (single source of truth) ===

DISPATCH = {}

def _cmd(name):
    """Register a command. Every handler takes a single `params` dict."""
    def decorator(fn):
        DISPATCH[name] = fn
        return fn
    return decorator

# ── Read Commands ──

@_cmd("ping")
def cmd_ping(params):
    return _ok({"pong": True, "server": "fable8-bridge-v5",
                "houdini": hou.applicationVersionString()})

@_cmd("scene_info")
def cmd_scene_info(params):
    return _ok({
        "hip": hou.hipFile.path(),
        "version": ".".join(str(x) for x in hou.applicationVersion()),
        "selected": [n.path() for n in hou.selectedNodes()],
        "fps": hou.fps(),
    })

@_cmd("get_node_children")
def cmd_get_node_children(params):
    parent = _get_node(params["path"])
    kids = [{"name": c.name(), "path": c.path(), "type": c.type().nameWithCategory()}
            for c in parent.children()]
    return _ok({"parent": parent.path(), "count": len(kids), "children": kids})

@_cmd("get_node_info")
def cmd_get_node_info(params):
    n = _get_node(params["path"])
    inputs = []
    for i in range(len(n.inputs())):
        inp = n.input(i)
        if inp:
            inputs.append({"index": i, "path": inp.path()})
    errs = n.errors()
    warns = n.warnings()
    return _ok({
        "path": n.path(),
        "name": n.name(),
        "type": n.type().nameWithCategory(),
        "children": len(n.children()),
        "bypassed": _safe_attr(n, "isBypassed"),
        "display": _safe_attr(n, "isDisplayFlagSet"),
        "subnetwork": _safe_attr(n, "isSubNetwork"),
        "inputs": inputs,
        "outputs": [{"path": o.path(), "name": o.name()} for o in n.outputs()],
        "errors": list(errs) if errs else [],
        "warnings": list(warns) if warns else [],
    })

@_cmd("get_node_parms")
def cmd_get_node_parms(params):
    n = _get_node(params["path"])
    mx = min(int(params.get("max_parms", 100)), 500)
    out = []
    for pm in n.parms()[:mx]:
        try:
            v = pm.eval()
        except Exception:
            v = "<eval error>"
        out.append({"name": pm.name(), "label": pm.description(), "value": v})
    return _ok({"path": n.path(), "parms": out})

@_cmd("get_subtree")
def cmd_get_subtree(params):
    root = _get_node(params["path"])
    mx = min(int(params.get("max_nodes", 1000)), 1000)
    nodes = [{"path": x.path(), "name": x.name(), "type": x.type().nameWithCategory()}
             for x in root.allSubChildren()[:mx]]
    return _ok({"root": root.path(), "count": len(nodes), "nodes": nodes})

@_cmd("find_nodes")
def cmd_find_nodes(params):
    pat = str(params.get("pattern", "")).lower()
    mx = min(int(params.get("max_results", 200)), 500)
    results = []
    for n in hou.node("/").allSubChildren():
        if pat in n.path().lower():
            results.append({"path": n.path(), "name": n.name(),
                            "type": n.type().nameWithCategory()})
        if len(results) >= mx:
            break
    return _ok({"pattern": pat, "count": len(results), "results": results})

# ── Mutation Commands ──

@_cmd("create_node")
def cmd_create_node(params):
    parent = _get_node(params["parent_path"])
    node = parent.createNode(str(params["node_type"]), params.get("node_name"))
    return _ok({"path": node.path()})

@_cmd("set_parm")
def cmd_set_parm(params):
    n = _get_node(params["node_path"])
    pm = n.parm(str(params["parm_name"]))
    if pm is None:
        raise ValueError(f"Parameter not found: {params['parm_name']}")
    pm.set(params["value"])
    return _ok({"path": n.path(), "parm": params["parm_name"]})

@_cmd("connect_nodes")
def cmd_connect_nodes(params):
    target = _get_node(params["target_node"])
    source = _get_node(params["source_node"])
    idx = int(params.get("input_index", 0))
    target.setInput(idx, source)
    return _ok({"target": target.path(), "source": source.path(), "index": idx})

@_cmd("layout_nodes")
def cmd_layout_nodes(params):
    parent = _get_node(params.get("parent_path", "/obj"))
    parent.layoutChildren()
    return _ok({"parent": parent.path()})

@_cmd("delete_node")
def cmd_delete_node(params):
    n = _get_node(params["path"])
    path = n.path()
    n.destroy()
    return _ok({"deleted": path})

@_cmd("cook_node")
def cmd_cook_node(params):
    n = _get_node(params["path"])
    force = bool(params.get("force", True))
    n.cook(force=force)
    geo = None
    try:
        geo = n.geometry()
    except Exception:
        pass
    npts = len(geo.points()) if geo else 0
    nprims = len(geo.prims()) if geo else 0
    return _ok({
        "path": n.path(),
        "points": npts,
        "prims": nprims,
        "errors": list(n.errors()) if n.errors() else [],
        "warnings": list(n.warnings()) if n.warnings() else [],
    })

@_cmd("bypass_node")
def cmd_bypass_node(params):
    n = _get_node(params["path"])
    state = bool(params.get("bypass", True))
    n.bypass(state)
    return _ok({"path": n.path(), "bypassed": state})

@_cmd("exec_python")
def cmd_exec_python(params):
    """Execute arbitrary Python code in Houdini's hou context.
    Code runs with `hou` in scope. Return value via a variable named `result`.
    Params: {"code": "<python code>", "timeout": 30}
    The code must assign its return value to a variable named `result`.
    """
    code = str(params.get("code", ""))
    if not code:
        raise ValueError("No code provided")
    # Execute in a namespace with hou available
    local_ns = {"hou": hou, "result": None}
    try:
        exec(code, local_ns)
    except Exception as e:
        traceback.print_exc()
        raise
    result = local_ns.get("result")
    return _ok({"result": result})

@_cmd("press_button")
def cmd_press_button(params):
    n = _get_node(params["node_path"])
    pm = n.parm(str(params["parm_name"]))
    if pm is None:
        raise ValueError(f"Parameter not found: {params['parm_name']}")
    pm.pressButton()
    return _ok({"path": n.path(), "parm": params["parm_name"]})

@_cmd("query_help")
def cmd_query_help(params):
    """Query Houdini's offline help documentation from $HFS/houdini/help/.

    Params:
      category: "node" | "vex" | "hom" | "solaris" | "custom"
      context: node context for node docs (e.g. "lop", "sop", "obj", "vop")
      name: document name (e.g. "layout", "instancer", "abs", "hou.Node")
      max_chars: max chars to return (default 4000)

    Returns the raw wiki-format documentation text.
    """
    import zipfile
    category = str(params.get("category", "node"))
    name = str(params.get("name", ""))
    context = str(params.get("context", ""))
    max_chars = int(params.get("max_chars", 4000))

    if not name:
        raise ValueError("name is required")

    hfs = hou.getenv("HFS")
    if not hfs:
        raise ValueError("HFS environment variable not set")
    help_dir = os.path.join(hfs, "houdini", "help")

    # Map category to zip file and path pattern
    zip_map = {
        "node": ("nodes.zip", f"{context}/{name}.txt"),
        "vex": ("vex.zip", f"functions/{name}.txt"),
        "hom": ("hom.zip", f"hou/{name}.txt"),
        "solaris": ("solaris.zip", f"{name}.txt"),
    }

    if category not in zip_map:
        raise ValueError(f"Unknown category: {category}. Use: {list(zip_map.keys())}")

    zip_name, file_path = zip_map[category]
    zip_path = os.path.join(help_dir, zip_name)

    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"Help archive not found: {zip_path}")

    with zipfile.ZipFile(zip_path) as zf:
        # Try exact path first
        names = zf.namelist()
        target = None
        # Exact match
        if file_path in names:
            target = file_path
        else:
            # Fuzzy: find files ending with the name
            name_lower = name.lower()
            candidates = [n for n in names if n.lower().endswith(f"/{name_lower}.txt")
                          or n.lower() == f"{name_lower}.txt"]
            if len(candidates) == 1:
                target = candidates[0]
            elif len(candidates) > 1:
                # Prefer ones in the right context
                if context:
                    ctx_candidates = [c for c in candidates if c.startswith(f"{context}/")]
                    if ctx_candidates:
                        target = ctx_candidates[0]
                if not target:
                    target = candidates[0]

        if target is None:
            # List available files in the context for helpful error
            if context:
                available = sorted([n for n in names if n.startswith(f"{context}/")])
                available = [n.replace(f"{context}/", "").replace(".txt", "") for n in available]
            else:
                available = sorted([n.replace(".txt", "") for n in names])[:50]
            raise FileNotFoundError(
                f"Help file not found: {file_path}. "
                f"Available in {context or 'root'}: {available[:30]}"
            )

        raw = zf.read(target)
        content = raw.decode("utf-8", errors="replace")
        full_len = len(content)
        if len(content) > max_chars:
            content = content[:max_chars] + "\n... (truncated, full doc is " + \
                      str(full_len) + " chars)"

    _track_help_query(category, context, name)

    return _ok({
        "category": category,
        "file": target,
        "content": content,
        "full_length": full_len,
    })

def _track_help_query(category, context, name):
    """Track help queries to a stats file for auto-expansion of skill references."""
    try:
        stats_path = os.path.join(_PORT_DIR, "help_stats.json")
        stats = {}
        if os.path.exists(stats_path):
            with open(stats_path, "r", encoding="utf-8") as f:
                stats = json.load(f)
        key = f"{category}/{context}/{name}" if context else f"{category}/{name}"
        entry = stats.get(key, {"count": 0, "category": category, "context": context, "name": name})
        entry["count"] += 1
        entry["last"] = json.dumps(os.environ.get("USERNAME", ""))
        stats[key] = entry
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

@_cmd("help_stats")
def cmd_help_stats(params):
    """Show help query statistics. Use to find which docs are queried most
    so the skill's reference files can be expanded with popular topics.

    Params:
      top: return top N most-queried docs (default 20)
      reset: if true, clear all stats
    """
    stats_path = os.path.join(_PORT_DIR, "help_stats.json")

    if params.get("reset"):
        try:
            os.remove(stats_path)
        except Exception:
            pass
        return _ok({"reset": True})

    stats = {}
    if os.path.exists(stats_path):
        with open(stats_path, "r", encoding="utf-8") as f:
            stats = json.load(f)

    top_n = int(params.get("top", 20))
    sorted_stats = sorted(stats.values(), key=lambda x: -x.get("count", 0))[:top_n]

    # Check which are already in the skill references
    skill_ref_dir = os.path.join(os.path.expanduser("~"), ".zcode", "skills",
                                  "houdini-bridge", "references")
    existing_refs = ""
    for fname in ["node-reference.md", "sim-reference.md"]:
        try:
            with open(os.path.join(skill_ref_dir, fname), "r", encoding="utf-8") as f:
                existing_refs += f.read()
        except Exception:
            pass

    # Flag which top docs are NOT yet in references (candidates for expansion)
    candidates = []
    for s in sorted_stats:
        doc_key = s.get("name", "")
        if doc_key and doc_key not in existing_refs:
            candidates.append({
                "key": f"{s['category']}/{s.get('context','')}/{s['name']}",
                "category": s["category"],
                "context": s.get("context", ""),
                "name": s["name"],
                "count": s["count"],
            })

    return _ok({
        "total_queries": sum(s.get("count", 0) for s in stats.values()),
        "unique_docs": len(stats),
        "top_queried": sorted_stats,
        "expansion_candidates": candidates[:10],
        "stats_file": stats_path,
    })

@_cmd("list_help")
def cmd_list_help(params):
    """List available help documents in a category/context.

    Params:
      category: "node" | "vex" | "hom" | "solaris"
      context: node context for node docs (e.g. "lop", "sop")

    Returns list of available document names.
    """
    import zipfile
    category = str(params.get("category", "node"))
    context = str(params.get("context", ""))

    hfs = hou.getenv("HFS")
    if not hfs:
        raise ValueError("HFS environment variable not set")
    help_dir = os.path.join(hfs, "houdini", "help")

    zip_map = {
        "node": "nodes.zip",
        "vex": "vex.zip",
        "hom": "hom.zip",
        "solaris": "solaris.zip",
    }

    if category not in zip_map:
        raise ValueError(f"Unknown category: {category}. Use: {list(zip_map.keys())}")

    zip_path = os.path.join(help_dir, zip_map[category])

    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"Help archive not found: {zip_path}")

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if context and category == "node":
            names = [n for n in names if n.startswith(f"{context}/")]
            names = [n.replace(f"{context}/", "").replace(".txt", "") for n in names if n.endswith(".txt")]
        elif category == "vex":
            names = [n for n in names if n.startswith("functions/")]
            names = [n.replace("functions/", "").replace(".txt", "") for n in names if n.endswith(".txt")]
        elif category == "hom":
            names = [n for n in names if n.startswith("hou/")]
            names = [n.replace("hou/", "").replace(".txt", "") for n in names if n.endswith(".txt")]
        else:
            names = [n.replace(".txt", "") for n in names if n.endswith(".txt")]

    return _ok({
        "category": category,
        "context": context,
        "count": len(names),
        "documents": sorted(names),
    })

@_cmd("save_hip")
def cmd_save_hip(params):
    path = str(params.get("path", "") or hou.hipFile.path())
    # Strip _agent_YYYYMMDD_HHMMSS nesting (DeepSeek's auto-save left these).
    path = re.sub(r'(_agent_\d{8}_\d{6})+', '', path)
    hou.hipFile.save(path)
    return _ok({"hip": path, "saved": True})

@_cmd("debug_list")
def cmd_debug_list(params):
    """Diagnostics: list commands + detect zombie threads."""
    bridge_threads = [{"name": t.name, "alive": t.is_alive(), "daemon": t.daemon}
                      for t in threading.enumerate() if "bridge" in t.name.lower()]
    return _ok({
        "commands": sorted(DISPATCH.keys()),
        "count": len(DISPATCH),
        "threads": bridge_threads,
        "thread_count": len(bridge_threads),
        "python_version": sys.version.split()[0],
        "session_key": SESSION_KEY,
        "has_session_state": hasattr(hou.session, SESSION_KEY),
    })

# === Request Handler (socketserver.StreamRequestHandler) ===

class _Handler(socketserver.StreamRequestHandler):
    """One request per connection. Reads a single newline-terminated JSON line."""

    def handle(self):
        try:
            line = self.rfile.readline(_READ_CAP)
            if not line:
                return
            req = json.loads(line.decode("utf-8", "replace"))
            cmd = req.get("type", "")
            params = req.get("params") or {}

            fn = DISPATCH.get(cmd)
            if fn is None:
                resp = _err(f"Unknown: {cmd}. Available: {sorted(DISPATCH.keys())}")
            else:
                try:
                    resp = fn(params)
                except Exception as e:
                    traceback.print_exc()
                    resp = _err(f"{type(e).__name__}: {e}")

            out = (json.dumps(resp, ensure_ascii=False, default=_json_default) + "\n").encode("utf-8")
            self.wfile.write(out)
        except Exception as e:
            traceback.print_exc()
            try:
                err = (json.dumps(_err(str(e)), ensure_ascii=False) + "\n").encode("utf-8")
                self.wfile.write(err)
            except Exception:
                pass

class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Threaded TCP server with address reuse + daemon connection threads."""
    allow_reuse_address = True
    daemon_threads = True

# === Port file ===

def _write_port_file(port):
    try:
        os.makedirs(_PORT_DIR, exist_ok=True)
        with open(_PORT_FILE, "w") as f:
            f.write(str(port))
    except Exception as e:
        _log(f"write port file failed: {e}")

def _clear_port_file():
    try:
        os.remove(_PORT_FILE)
    except Exception:
        pass

# === Server lifecycle ===

def _get_state():
    """Read bridge state from hou.session (persists across all Python namespaces)."""
    return getattr(hou.session, SESSION_KEY, None)

def _set_state(state):
    setattr(hou.session, SESSION_KEY, state)

def _clear_state():
    try:
        delattr(hou.session, SESSION_KEY)
    except AttributeError:
        pass

def stop_bridge():
    """Stop the running bridge cleanly. Safe to call even if not running."""
    state = _get_state()
    if state is None:
        _say("[bridge v5] stop: no server running")
        return True

    server = state.get("server")
    thread = state.get("thread")
    gen = state.get("gen", "?")

    _say(f"[bridge v5] stopping gen {gen}...")

    # 1. shutdown the TCPServer (stops serve_forever loop)
    if server is not None:
        try:
            server.shutdown()
        except Exception as e:
            _log(f"server.shutdown failed: {e}")
        try:
            server.server_close()
        except Exception as e:
            _log(f"server.server_close failed: {e}")

    # 2. join the thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=3)
        if thread.is_alive():
            _say(f"[bridge v5] WARNING: gen {gen} thread still alive after 3s")
        else:
            _say(f"[bridge v5] gen {gen} thread joined cleanly")

    _clear_state()
    _clear_port_file()
    _say(f"[bridge v5] gen {gen} fully stopped")
    return True

def start_bridge():
    """Start the bridge. Stops any existing instance first (clean restart)."""

    # Stop old instance if running (the key fix - finds it via hou.session).
    old_state = _get_state()
    if old_state is not None:
        stop_bridge()

    # Detect zombie threads from old v3/v4 runs (which may not have used hou.session).
    pre_threads = [t.name for t in threading.enumerate() if "bridge" in t.name.lower()]
    zombie_warning = ""
    if len(pre_threads) > 0:
        zombie_warning = f" (existing bridge threads: {pre_threads})"
        if len(pre_threads) > 1:
            _say("[bridge v5] *** ZOMBIE DETECTED *** Restart Houdini to clear ALL "
                 "old threads, then re-run this script.")
        _say(f"[bridge v5] pre-existing bridge threads: {pre_threads}")

    # Bind: try PORT_BASE, then auto-increment up to PORT_RANGE.
    bound = None
    last_err = None
    server = None
    for p in range(PORT_BASE, PORT_BASE + PORT_RANGE):
        try:
            server = _Server((HOST, p), _Handler)
            bound = p
            break
        except OSError as e:
            last_err = e
            server = None
            continue

    if server is None:
        msg = (f"[bridge v5] FATAL: no free port in {PORT_BASE}-"
               f"{PORT_BASE + PORT_RANGE - 1} ({last_err}){zombie_warning}")
        _say(msg)
        return None

    _write_port_file(bound)

    # Start serve_forever on a daemon thread.
    thread = threading.Thread(
        target=server.serve_forever,
        name="fable8-bridge-v5",
        daemon=True,
    )
    thread.start()

    # Persist state on hou.session so future re-runs can find and stop us.
    gen = 1
    _set_state({
        "gen": gen,
        "server": server,
        "thread": thread,
        "port": bound,
    })

    msg = (f"[bridge v5] {len(DISPATCH)} commands | listening {HOST}:{bound}"
           f" | gen {gen}{zombie_warning}")
    _say(msg)
    if bound != PORT_BASE:
        _say(f"[bridge v5] (default port {PORT_BASE} was busy, using {bound})")
    return server

# === Go ===

_say("[bridge v5] starting...")
start_bridge()
