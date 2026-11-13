# ready13 合作式就绪门：唯一实现合同

**裁决：该最小合作式方案的软件实现 GO；真实 H21／Nuke 同 PID 时序与工程闭环仍 PENDING，真实启动 NO_GO。** 不再运行原生目标；本轮两个普通 Mach-O 目标额度已用完。唯一实现者负责源码及其镜像，方向和证据审查者只读。

## 选型依据与边界

本轮 B1 明确建立早期状态与 main／malloc READY 的因果对照：挂起前态 vmmap exit 0、stderr 450 字节，被严格拒绝；独立 main／malloc READY 后两次 vmmap stderr 为 0。其完整后态 observe 又在 `/tmp` 与 `/private/tmp` 的原路径门被拒绝，故完整身份不是 PASS，也不修改该路径门。

B2 的 task_read_for_pid 在前后态都为 -1、EPERM、port 0，未继续 task_info/read。准确含义是本次 Python 祖先→C helper 所生目标的读权不可用；不泛化成 direct parent 或所有 DCC 必然不可用。该 generic 读位门不作为本轮实施路线，不再补 probe。

H21.0.631 精确安装文档支持 `--prerender-script`，在加载 USD 后、读取 settings／渲染／products partition 前运行 Python；本轮未取得真实 H21 同 PID 事实。合作式门只调度何时开始完整严格身份观察，不产生身份 authority，不修改 observation／proof schema，不采纳 supplied verified／success 布尔。

## 现有通道复用与有限接口

在现有 `owned_process.py` 中实现一份 child 端 `runtime_ready_and_wait` 辅助函数，复用 `_signed_write`、`read_receipt`、现有新建私有 supervisor 目录与每次新 receipt.key。不得另建 launcher、第二监督器、第二票据账本或原生 runtime 模块。

所有带 `writer_executable` 的现有监督分支统一要求 runtime-ready；不带 writer 的分支维持原行为。两个生产调用入口是 alpha runner 和 Hython task host；不得给正式 writer 增加“没有事件就直接采样”的 fallback。

由可信 launch／supervise 在本次新私有目录和 identity 确定后覆盖注入子环境：

- `BRIDGE_OWNED_SUPERVISOR_DIR`：本次目录；
- `BRIDGE_OWNED_SUPERVISOR_IDENTITY`：本次 canonical identity，包含现有唯一 launch nonce；
- 有限等待所需的本次共享 deadline：由 supervisor 计算一次，仅用于调度，不作为身份字段。

禁止沿用调用者环境中的旧 supervisor 目录、identity 或 deadline。Hython 当前自行设置前两项，可保留兼容写入，但可信 launcher 必须核一致或覆盖为本次值。alpha 真实 environment 当前没有它们，统一注入可补齐两个 alpha 子进程。

runtime-ready payload 最小字段：沿用 `SCHEMA`，`event='runtime-ready'`、完整本次 `identity`、严格整数 `pid=os.getpid()`、`argv_sha256`、`observed_at`。`argv_sha256` 用该目录 intent 的确切 command 规范字节计算，不使用 husk 内 Python 的 `sys.argv` 冒充原生 argv。可保留固定代码点标签作诊断，但它不自证身份或替代真正代码点。

child helper 在写一次事件前核环境 identity 与本目录 intent identity 一致，且本 intent 确实是 writer 模式；事件不得带 key、环境或整段 intent。collector 只接受 `read_receipt` 验证 HMAC 后、identity／nonce／actual Popen PID／预期 command hash 完全匹配的本次事件。目录是新建且拒绝复用；只消费一次事件，不以多个事件或重复观察求绿。未知、错 PID、错 nonce、错 hash、错 HMAC、格式错、symlink、陈旧目录均失败关闭。

脚本本身的可信来源是冻结源码 SHA、固定路径、精确 argv 与 source_freeze admission；HMAC 只认证本次回执。不得把 Python 脚本称为已获得 macOS 原生代码签名，也不得把 child 可写的 ready 声明当作 OS 身份证明。

## 三个原生接点与反循环

### H21 alpha husk

新增一个必要且很小的固定 prerender adapter，位于现有 dcc_task_runtime 源树／镜像中。adapter 顶层调用同一个 helper，只依赖标准库及现有 owned_process／platform_support；不 import hou、不调用 Houdini 库，不创建场景、节点或新渲染逻辑，不依赖 husk 是否设置 `__name__=='__main__'`。

adapter 必须从自身冻结位置定位／导入同一冻结 runtime，不能依靠外部安装或 ambient PYTHONPATH。它读到的 helper 正是 frozen supervisor 源树中的一份。真实 helper `os.getpid()` 必须等于监督器 Popen child PID；若 hook 在副解释器／子进程执行，立即失败，不能拿子进程 event 放行父 husk。

`prepare_native_alpha_scene.py` 在精确 command 中加入唯一 `--prerender-script <固定 adapter 路径>`，仍保留既有 renderer/settings/frame/output/scene 参数；准备结果记录 adapter 的源码文件身份。真实 argv 不使用 `--postload-script`，该选项不是 H21 合同。

### Hython task host

最小落点为 `plugins/houdini/_impl/houdini_bridge_addon.py::task_host_serve` 中的 `import hou` 成功之后，且在版本查询、warmup、bridge autostart 和 `_task_writer_process_identity` 之前，仅 writer 模式调用 helper。这样无需给 RUNNER_TEMPLATE 增加重复启动协议。

现有顺序由此成为：import hou → runtime-ready → 等本次 signed started 完整 binding → 原 task host／writer identity 验证 → 原 host.ready。不得直接用当前 host.ready 作为 collector 门；它本来先等待 signed started 再 observe self，直接复用会构成循环。

### Nuke alpha

`alpha_calibration.main` 在 `import nuke` 成功之后、`observe_native_nuke` 之前调用 helper。其顶层已有从自身 `__file__` 定位同一 runtime 的导入路径，不增加外部 Python 依赖。原 nuke task_host_worker 的较晚 server ready 不是本 alpha 路线的替代事件，也无需把本次门扩展到不带 writer 的 Nuke control/render launch。

## child hold 与停止

发布 ready 后，三个接点都必须等待本目录认证 `started`：PID 等于 `os.getpid()`、identity 完全一致、没有 writer error、包含完整 writer_process_binding，且 host_anchor PID 与本进程一致，才可继续原生业务。该等待不重新观察身份，不额外调用 vmmap。

started 中已签 writer error、认证 stopped、有效取消、共享期限到达或读取错误均立即终止 hook／helper，不返回业务。已签 writer 原因保留。监督器同时必须把 ready／采集失败接入已经修复的立即整组停止路径；不靠 child 自愿退出替代拥有者的 TERM／KILL／整组 absence／wait 认证。

## 唯一时钟与原严格观察

1. `supervise` 在业务 Popen 前计算一次 `session_end=now+budget_seconds` 和 `collection_end=min(session_end, now+22)`；将同值传 `_supervise_owned`／collector，并给 child helper 有限 hold。时钟只会收紧，不在 spawn、ready 或继续业务时重置。直接调用 `_supervise_owned` 的软件测试可以在入口生成等价默认值，但实际生产不得各取一套。
2. collector 的 refreeze 仍受原 5 秒上限及上述外层总限；之后建立一次 `observe_end=min(collection_end, session_end, now+16)`。
3. 按 root 最终指定，在 `process_image._observe` 的第一次 `_ps` 之后、第一次 `_vmmap` 之前等待 runtime-ready。可给此私有函数增加默认 None 的 ready callback；collector 用共享 `observe_end` 调它。callback 得到原 deadline、检查 cancelled、等待本次认证事件；返回后检查剩余时间，再逐字保留原 vmmap／双 lsof／stat/hash／后 ps 流。
4. gate 等待消耗该同一次 16 秒 observe 期限；收到事件后不得调用一个重新从 now+16 开始的 public observe_process。公开 observe_process／capture_ancestry 默认行为及 proof schema 不变。回调只允许可信 supervisor 内部提供，不是生产客户端的身份声明接口。
5. cancelled 在 ready 轮询和开始后续原生工具前生效，取消后不启动后续观察；晚结果不签入。缺事件、deadline、权限／格式等不可读情况走已有 fail-stop。工具 5／freeze 5／observe 16／capture 60／collection 22 均不增加，TERM 后现有 2 秒宽限不变。业务 8／120／600／512 MiB／1 heavy／0 retry 不变。

## 冻结与部署必须同步的最小面

- 原 authoritative runtime 与 `controller-entry/client/dcc_task_runtime` 镜像（含必要 adapter）；仍用现有 sync 工具，不创建第二模块树。
- `prepare_native_alpha_scene.py` 的 adapter source record 和精确 argv；`run_alpha_calibration.py::required_source_paths` 加入必要 adapter，并在 preflight 对其固定 snapshot 路径、hash 与唯一 prerender 参数作精确核对。
- snapshot 由现有准备链复制源树；其 project／alpha preparation immutable 和 source_freeze 扫描收纳新 adapter。不改旧冻结范围，不往 06–12 内写回。
- Hython addon 改动自然改变 plugin_build，沿用现有 preparation／deployment／source_freeze admission 重新冻结；不得手改旧 plugin_build 或 bindings 使其匹配。
- alpha output 继续签原精确 command、expected executable、started／stopped hash。ready 是本次 supervisor 原始事件，不赋予 alpha-output 权威或绕过任何既有执行／binding 门。
- 普通 Python 软件 hosts 显式执行相同 helper／协议，标明软件 API 边界；不得靠 Popen bootstrap、vmmap image 模型或伪造原生成功跳过门。

## 有限软件验收门

实现验收须显示：真实独立 ready 事实在完整原生校验之前；正式合作式协议的测试中 ready 前首次 vmmap 调用数 0、ready 后严格完整链恰当执行，且总 end 未重领。

必要负例限于本次风险：缺事件、错 HMAC／nonce／PID／argv／目录、ready deadline、已取消、hook 子 PID、ready 后 child exit、collector 错误、晚结果和 started writer error。每个失败都拒绝继续业务、保留原因、立即进入 owned stop，alpha-output 和下一 Nuke launch 均未发生。正常同 PID ready+完整 binding 要能解除 hold；Hython 要证明 runtime-ready→started→原 host.ready 的顺序无循环。

保留已有 cancel／session／disk／native-scope、慢 freeze／observe、信号拒绝、后代未停和正常成功覆盖，不重复本轮两个原生目标，不顺手修实验路径别名。软件检查与普通原生对照、后续真实 H21／Nuke 的同 PID／时长／脚本生命周期验收分别报告。

现阶段只给**方案和软件实现 GO**；源码改动后仍需独立代码审查及证据审查，不能由本设计文档宣布完整软件 PASS、live-readiness PASS 或新真实范围已授权。

## 已核来源

- 当前源码：`owned_process.py`、`process_image.py`、`alpha_calibration.py`、`task_host.py`、Houdini addon、alpha preparation／runner、production_hosts 与正式 preparation 的现有部署／snapshot 链。
- `/private/tmp/bridge-ready13-native-basis/native-readiness-basis.md`、`h21-husk.txt:184–187` 与原文 capture hashes。
- `/private/tmp/bridge-ready13-repro/state-machine/result.json`、B1／B2 独立结果；未重复运行。
