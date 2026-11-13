# 本地私有上下文 API

此组件对应 `handover/MASTER_PLAN_20261004.md` 的 F 阶段最小本地读取能力。它把偏好、项目规范与来源陈述作为有出处的数据返回，供执行核心/Plugin 调用方组合。已验证技术事实继续由现有 `KnowledgeStore.search()` 提供；没有新增数据库、知识卡、批准流程、自动学习或晋升接口。

## 冻结接口

```python
from dcc_task_runtime.private_context import (
    PrivateContextReader, PrivateContextError, encode_context,
)

reader = PrivateContextReader(
    root=config["private_context_root"],
    project_id=config["project_id"],
    documents=config["private_context_documents"],
)

result = reader.search(
    query="crowd motion",
    domain="crowd_agents_v1",
    version="21.0.631",
    limit=4,
    max_bytes=16384,
    read_budget=262144,
)
wire_bytes = encode_context(result)
```

`root`、`project_id`、`documents` 必须来自模型之外的本地启动授权配置。`documents` 是 `{相对JSON路径: 原文件小写SHA256}` 的显式白名单，最多 32 份。构造器复制白名单，后续配置字典修改不会扩大现有实例的读取范围；更新文件需由授权配置更新 pin 并新建 reader。不要从文档自身或模型输出计算新 pin 来绕过篡改检查。

不自动递归查找文档，不读取引用指向的文件/网址。使用本地目录；UNC/网络地址样式的 root 直接拒绝，映射盘/挂载点是否为本地存储由启动配置负责人保证。root 和已有祖先路径不允许符号链接或 Windows reparse point。调用方负责目录 ACL 和启动配置保护；此读取组件不会更改 ACL 或建立操作系统沙箱。

## 文档合同

每个文件是一份 UTF-8 JSON 文档，仅允许下列字段；`expires_at` 可省略。所有必需字符串非空，identity/domain/version/topic 最多 128 字符，reference 最多 1024 字符。schema、来源类型及字段类型严格检查，重复 JSON key、非有限 JSON 常量、未知字段或不可编码的 Unicode 拒绝。

```json
{
  "schema": "bridge.private-context/1",
  "document_id": "project-a-crowd-motion",
  "project_id": "project-a",
  "source_type": "project_specification",
  "domain": "crowd_agents_v1",
  "version": "21.0.631",
  "topic": "crowd-motion",
  "reference": "制作简报#人群运动",
  "content": "人群保持缓慢、柔和的运动。",
  "expires_at": "2027-01-01T00:00:00+08:00"
}
```

`source_type` 只允许 `preference`（偏好）、`project_specification`（项目规范）、`source_statement`（来源陈述）。它们均未经过技术事实验证。`reference` 是不透明引用标签；整档 SHA256 将引用、来源类型、项目和正文共同绑定，但不代表引用对象已经被读取或验真。

项目必须与构造器授权 project_id 精确相同，否则整个请求拒绝，不返回此前匹配的部分数据。domain/version 精确匹配，不自动跨版本、不推断兼容性、不支持通配回退。`version` 是调用方明确选择的版本标识；不能自动把 Houdini 原生版本当作已有 `KnowledgeStore.domain_version` 的领域合同版本。

`expires_at` 必须是带时区 ISO 时间，按实际当前 UTC 判断。已过期匹配只增加 `expired_count`，不返回正文；没有 expires_at 表示未声明期限，不表示其内容已验证或永不过时。

## 结果与预算

返回普通 dict，只包含 JSON 可序列化值，无文件句柄、Path、datetime 或知识合同对象：

```json
{
  "schema": "bridge.private-context-result/1",
  "content_role": "untrusted_data",
  "project_id": "project-a",
  "domain": "crowd_agents_v1",
  "version": "21.0.631",
  "status": "no_match",
  "matches": [],
  "conflict_count": 0,
  "expired_count": 0,
  "omitted_count": 0,
  "bytes_read": 0
}
```

此处展示无匹配的 envelope 字段。实际成功的每条 match 包含原文档字段及 `document_path`（root 内相对路径）、`document_sha256`（原始 UTF-8 文件字节 SHA256）、`conflict`（boolean）。不返回授权 root 的绝对路径。结果排序按白名单相对路径固定，不执行偏好或正文里的指令。

| status | 含义 |
|---|---|
| matched | 有匹配正文；同时检查 omitted_count 和 expired_count |
| no_match | 当前项目/domain/version/query 没有匹配；不补造经验 |
| expired | 匹配仅包含过期文档，没有返回正文 |
| conflict | 匹配涉及同来源类型、同 topic 的不同有效正文；调用方决定取舍 |
| budget_exhausted | 有有效匹配，但响应预算无法容纳任意完整条目 |

query 最多 512 字符，按空白分词、casefold 后要求每词出现在 topic/reference/content 中；空 query 只按指定范围取用。冲突在当前 domain/version 的全部有效白名单文档中检测，再关联查询结果；查询词、limit 或响应字节预算不会把另一份不同正文藏成无冲突。不会判定自然语言逻辑矛盾：同 topic 的不同正文保守标记为待裁决，等价正文不标冲突。某个冲突伙伴可能不在当前文字查询结果中；按 topic 查询可取得更多引用，模块不代替调用方的要求优先级。

- 单份输入文件最多 65,536 bytes；每次调用总读取最多 262,144 bytes，可用 `read_budget` 下调。读取全部白名单文件并重新验 hash，包含本次未匹配/过期文档的 bytes。超预算在该文件 open 前拒绝，整个请求不返回部分数据。
- 返回最多 4 条完整条目，可用 `limit` 下调；不截断原文冒充完整引用。因数量/字节预算未返回的有效查询匹配计入 `omitted_count`。
- `max_bytes` 硬上限 16,384 bytes，约束整个 `encode_context(result)` UTF-8 envelope，包含字段、引用、正文及状态。调用方应使用该函数或相同 JSON 编码；更宽松/缩进/转义后的编码大小不属于此预算。envelope 本身也放不下时明确拒绝。
- 读取前后检查 root 身份、普通单链接文件、文件描述符与路径 stat 快照；整档 pin hash 校验当前实际读取字节。路径/链接/内容变化不能靠旧缓存 PASS。授权 root 应保持受控，不允许不可信进程并发重写其祖先目录；stat 校验不是跨操作系统的目录隔离原语。

## 薄 MCP 接入及知识组合

Plugin 可在启动时构造 reader，MCP 参数只允许 query/domain/version/limit；root/project/documents 以及预算均不接受模型参数。使用固定工具路由和命名的数据 payload，不把正文接到系统指令，不依据它创建执行批准或知识晋升。这里只给接入方法，本任务没有修改 MCP/server 或共享 export 文件。

```python
def read_private_context(params):
    allowed = {"query", "domain", "version", "limit"}
    if set(params) - allowed:
        return {"status": "rejected", "code": "unsupported_context_parameter",
                "matches": [], "bytes_read": None}
    try:
        return reader.search(
            query=params.get("query", ""),
            domain=params.get("domain", ""),
            version=params.get("version", ""),
            limit=params.get("limit", 4),
            max_bytes=16384,
            read_budget=262144,
        )
    except PrivateContextError as error:
        return {"status": "rejected", "code": error.code,
                "matches": [], "bytes_read": None}
```

异常 `.code` 是固定类别，不包含正文、外部项目 ID 或绝对路径。拒绝时 bytes_read 未作为部分结果暴露，调用方用 null 表示未知，不捏造为零。主要代码：`project_scope_mismatch`、`invalid_document_path`、`linked_path`、`non_private_file`、`root_changed`、`document_changed`、`document_hash_mismatch`、`document_unavailable`、`invalid_document_schema`、`duplicate_json_key`、`invalid_expiry`、`document_too_large`、`read_budget_exceeded`、`result_budget_too_small`；另有严格输入/manifest 参数错误。

既有技术事实组合保持独立：

```python
private_data = reader.search(
    request.query, domain=request.domain, version=request.context_version,
)
technical_cards = knowledge_store.search(
    request.query, limit=4, domain=request.domain,
    version=request.knowledge_domain_version,
)
```

不要把 private_data 内容转成已验证 card，也不要自动触发 `request_human_approval`、`put_human_approval` 或 `promote`。KnowledgeStore 的已验证卡、来源撤回、签名批准与晋升条件仍由现有接口维护。调用方分别保留两类引用，并为组合后的整个 MCP/模型上下文另设总输出预算；单组件的 16 KiB 不覆盖技术卡和外层协议的额外 bytes。

## 本批验证与冻结

冻结记录时间：2026-10-04 07:34 UTC（北京时间 15:34）。本任务只新增 `packages/dcc-task-runtime/src/dcc_task_runtime/private_context.py`、`tests/unit/test_private_context.py`、本文件；没有修改共享 KnowledgeStore、MCP、包 exports 或其它 agent 的改动，没有 commit/branch。

最终实际运行（既有 runner，仅新模块）：

```powershell
$privateContextGuard = @'
import multiprocessing.process,os,runpy,subprocess,sys
from unittest.mock import patch
sys.argv=["outputs/windows-followup-20261004/run_selected_tests.py","test_private_context"]
with patch.object(subprocess,"Popen",side_effect=AssertionError("PROCESS_START_FORBIDDEN")),patch.object(multiprocessing.process.BaseProcess,"start",side_effect=AssertionError("PROCESS_START_FORBIDDEN")),patch.object(os,"system",side_effect=AssertionError("PROCESS_START_FORBIDDEN")),patch("socket.socket",side_effect=AssertionError("NETWORK_FORBIDDEN")):
    runpy.run_path(sys.argv[0],run_name="__main__")
'@
& .venv/Scripts/python.exe -B -X utf8 -c $privateContextGuard
```

Windows 原生 Python 3.11.9 下原始终端摘要：

```text
Ran 21 tests in 0.217s
OK (skipped=1)
{"tests_run": 21, "failures": 0, "errors": 0, "skipped": 1}
exit_code: 0
```

实际 20 PASS、1 SKIP。跳过为 `test_real_symlink_file_parent_and_root_are_rejected`：创建真实链接收到 WinError 1314，当前账户缺符号链接权限，故该真实链接检查未验证，不能记为 PASS。真实硬链接拒绝、中文路径和 UTF-8 字节、文件/root 替换、跨项目及 hash 篡改等其余 20 项已实际执行；符号链接父路径与 Windows reparse 拒绝另用明确的底层 lstat 替身检查，未因真实权限 SKIP 而删掉。进程及 socket 启动在外层显式阻断。

兼容性附加运行：此前将同一 guard 的模块列表扩展为 `test_private_context`、`test_knowledge_retrieval`、`test_knowledge_plane`，实际 34 项、29 PASS、1 SKIP、4 ERROR，退出码 1。四项 ERROR 均为旧测试退出临时目录时 SQLite 文件仍被占用的 WinError 32：

- `test_knowledge_retrieval.KnowledgeRetrievalTests.test_revocation_is_explicit_idempotent_and_excludes_future_and_existing_cards`
- `test_knowledge_retrieval.KnowledgeRetrievalTests.test_tampered_revocation_ledger_fails_closed`
- `test_knowledge_plane.KnowledgePlaneTests.test_database_payload_tampering_fails_closed`
- `test_knowledge_plane.KnowledgePlaneTests.test_knowledge_schema_is_separate_from_repair_experience`

这些旧测试的直接 sqlite3 连接及清理问题不在本任务独占文件范围，未修改，也不将附加组报告为通过。新模块的组合单元通过实际 KnowledgeStore 创建/检索未验证 candidate，证明私有陈述没有自动晋升、产生批准或改写既有 candidate；本组件自身不持有 KnowledgeStore，也不新建持久知识库。

源码与测试最终原字节 SHA256：

| 文件 | SHA256 |
|---|---|
| packages/dcc-task-runtime/src/dcc_task_runtime/private_context.py | `489617e2cacf5ff18706c64dff8a2514c60a2762c304bd7287ffc3663b41df28` |
| tests/unit/test_private_context.py | `2d49af46fafafb2a128f8e9ba06ace967ece91e3804e4066a0db7bff30e8ffa1` |

以上结果来自本轮实际终端，不沿用历史 PASS。原始输出保留在本次会话工具记录；仅在本授权文档写验证摘要，没有建立额外日志文件。源码/API 冻结后不继续修改这两个文件。实际 DCC/模型、外部连接器、安装发布、Plugin/MCP 路由和 macOS/目标机验收均未执行，仍须主线实际接入与独立验证。
