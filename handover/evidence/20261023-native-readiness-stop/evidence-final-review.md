# READY13 最终独立证据评审

**结论：SOFTWARE PASS；candidate13 冻结审计 PASS。** ready 调度与采集失败立即停止的软件修复已有定向回归、真实普通进程、受控失败和正式软件八启动链证据。真实 H21/husk/hython/Nuke 的同 PID hook、实际生命周期、真实工程闭环及全 16 域 M1 仍未验证，本报告不授权真实 DCC 启动。

本角色只读检查源码、原始回执、完整工具流、账本、产物登记库和冻结文件；只在本目录写评审材料和审计脚本。没有运行或重试目标、原生采集、DCC、模型或渲染；没有修改生产源码、candidate13、成功工作区或旧原件；未复制 intent/env/receipt.key。

## 最终源码与回归

审查清单为 `implementation/ready-after-sha256.json`，18 个文件；manifest SHA-256 `70bbfe11a2d37fa057540e99e2718aabdabc336e5ca06d7d4a7a461d5c3d2564`，patch SHA-256 `48ce18c233a01ca42025c791dcd9db09b0afdfc6c29273503accc2f4be56ec67`。独立快照、before/after 和四对 authoritative/controller runtime 镜像全部一致。

Python 3.11.16 与 3.14 定向回归分别为 108 项：104 通过、4 Windows 跳过，0 failure/error，测试前后 18 项摘要完全匹配最终清单。Windows 的 Job tree、kill-on-close、未知 Job query 和 birth/Job/wait receipt 四项未在 macOS 执行；真实普通 writer 测试从 focused suite 明确排除，其后另有下面的实际普通进程验证。

事件只作 strict observe 调度：HMAC、identity、本次 runtime nonce、实际 PID 与精确 command 摘要均验证；caller/model verified 布尔、诊断文本和 ready 文件存在不产生身份 authority。首次 ps 后、首次 vmmap 前的 gate 消耗同一次 observe 16 秒，生产 Popen 前建立的 session/collection end 不重领；工具5/freeze5/observe16/capture60/collection22及业务8启动/120秒每项/600秒总量/512MiB/1heavy/0自动重试未增加。

collector/ready/started 写入失败在同轮 TERM dispatch 前进入失败状态；原 cause 保留，可信停止与执行失败分离。首次有效 binding 的 started 写失败重签交互已用固定 writer error 关闭，最小核心回归通过。alpha 只有认证 operation 的结构、identity、PID、argv、started hash 和 execution 协议通过后才传播原始采集原因，拒绝 alpha-output 和下一 Nuke dispatch。

取消边界准确保留：门前取消阻断新观察；已进入原 `_observe` 的工具沿原期限有界完成，晚结果丢弃、不签 binding，owned stop 不等待 collector。当前没有逐工具取消中断能力，不能声称 mid-observe 取消后绝无后续工具调用。Bugbot 对最终同一源码未发现 P1/P2。

## 实际普通进程与受控失败

详细逐项独验：`ordinary-final-independent-audit.json`。本角色本地读取私钥仅用于 HMAC，报告不输出或复制私钥。

| 原始案例 | 独立结果 | 证据层 |
| --- | --- | --- |
| ordinary-positive-02，PID 97981，2.552791 秒 | runtime-ready/started/stopped 三份 HMAC 有效，原始公开副本与私有原件逐字相同；identity/nonce/PID/argv/started hash 一致；原 strict 链实际执行 ps、vmmap summary/address、双 lsof、再次 vmmap summary/address、末次 ps，共8工具，全部 rc0/完整空stderr；host_anchor 映像与 expected 完整身份一致，当前实际文件 hash 相符；ready 认证早于首 vmmap，业务 marker 晚于签 started，结束成功且无 stop 请求 | 普通 Python/macOS 原始工具与合作式协议阳性；不是 DCC hook 阳性 |
| ordinary-collector-error-01，PID 98161，0.131208 秒 | runtime-ready/started/stopped HMAC及绑定一致；真实首 ps 后，在 `_vmmap` 边界显式注入 collector error；没有原生 vmmap 调用，没有 writer binding 或业务 marker；trace 的 signed error→TERM 请求相隔7209ns、同监督线程且无中间sleep；最终 owned wait 的 -15/failed/COLLECTION_FAILED 与原始整组缺席检查一致 | 正式监督器的受控软件采集失败关闭；不是原生 warning 复现 |

两案的 trace-events 原始内容与 result.events/tools 一致，所有工具 stdout/stderr 原字节已逐项读核并记录摘要；单次 observe deadline 全程相同，session30/collection22/tool5/observe16、1target/case、0自动重试均成立。签名 stopped 的认证与既有源码整组 absence 门共同支持停止结论；本角色没有另作 live PID/组查询。

首轮 ordinary-positive-01 独立保留：sandbox 内首 `/bin/ps` spawn EPERM，尚无 ready/vmmap，signed TOOL_UNAVAILABLE 和 -15/failed 停止有效；driver 对 ready=None 的 TypeError 单列，未创建 result.json，也未持久化 profile events。因此该次不证明原生阳性，不能独立重建其实际 TERM 时序。外部执行条件改为 root 指定的 require_escalated 后，才以 fresh positive-02 完成上述阳性；旧失败没有被覆盖、重命名或转为成功。封存11个公开文件全部匹配，见 `ordinary-positive-01-environment-review.md`。

## 正式软件八启动链与登记消费

成功工作区：`/Users/user/Documents/Code_Project/Bridge/outputs/software-engineering-20261023-readiness-01/activated`。该次 Python3.11 原有正式链测试运行1项，55.185576秒，0失败/错误/跳过，最终 `SOFTWARE_CHAIN_COMPLETED`，`native_execution_status=NOT_RUN`。Houdini/Nuke API 使用明确的软件替身，process-image 使用真实 macOS 工具；image model 文件/审计不存在，image_adapter_installed 与 popen_bootstrap_installed 均为 false，模型调用0、自动重试0。

独立使用标准库按现有账本协议校验本地 HMAC、journal seq/previous链、anchor head 和 state 原始封套完全一致，随后认证每个源监督器 started/stopped 与 ledger 的绑定。没有把解开 payload 当作认证，也没有 import Bridge API 或创建锁文件。

- 8张票、7个独立 supervisor 目录、4份 writer runtime-ready。main-husk 票沿用所属 parent 的整树停止回执；没有把8票误称8份独立 supervisor 回执。
- alpha-husk1、alpha-nuke1、graph-worker1、houdini-host2、main-husk1、nuke-host1、nuke-render1；所有票均已可信停止、执行成功、closed_reason为空，签名账本序列15。
- 当前18项源码前后相同；成功 snapshot 的159文件和source_freeze的175项执行前/后及当前文件 hash 全相同，无pyc。
- registry 数据库以 `mode=ro&immutable=1` 只读，且该库无WAL。实际存在2项 artifact、2项version、0失效记录；13条 stage journal 均DONE，result摘要匹配，complete结果与最终原始result一致。
- `engineering_h21_main` 的COMPLETED登记回执与 Nuke prepare 的认证 input_artifact 一致；Nuke派生产物保留 `artifact:engineering_h21_main` 依赖。两项完成帧的实际字节/hash及最终NK字节/hash均与登记、版本和最终结果一致，来源保留 software_test/controlled_output_v1，内部 writer 状态仍为 NOT_OBSERVED。

这些证据支持正式软件链的实际登记和消费，不升级为真实 Nuke/H21 输出或视觉验收。

## candidate13 与历史原件

正式 candidate：`/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-13`。最终只读审计回执 `candidate13-audit-result.json` 为 passed=true、findings=[]。

| 对象 | 独立结果 |
| --- | --- |
| scope | SHA-256 `bb4c001a00ea38b92ccd57bb6cff9c128222fdf8c02e7a6fbcc2600995386276`；PREPARED_NOT_AUTHORIZED、execution_authorized=false、host_started=false |
| runtime bindings | SHA-256 `b43dff981e21f17aa9dfa55ff210e8e80ea608f76cebea8b2f91492670380e13`，与preparation及review绑定一致 |
| activation review | SHA-256 `72592c392e00a44747bcbe39c6dd13dc7bf35c6a5dca4f1091e6b1aa36f42535`；只审查后续目标，未创建或授权该目标 |
| prepared账本 | HMAC/链/anchor认证，0票、seq0、closed_reason为空，无supervisor目录，native NOT_RUN |
| 冻结数量 | snapshot manifest/实际均159，source_freeze175，immutable176，required源码17，pyc0；由实际清单派生，未沿用旧计数 |
| source/adapter | current、candidate13与成功软件snapshot逐文件一致；adapter为required/source_freeze项，alpha record/固定path/唯一prerender参数和plugin_build均一致 |
| 业务预算 | 精确8启动/每项120秒/总600秒/512MiB/1heavy/0自动重试 |
| future14 | 精确路径 `outputs/engineering-closure-20261023-h21-14-authorized` 不存在，亦不是symlink |
| 06–12原件 | baseline SHA-256 `f851f4df31c19349ad6f53fea956614f7b28a35b89e5bb561a1c69114adb5b0e`，1457文件逐项大小/hash匹配 |
| 首轮环境失败封存 | 11文件全部匹配，preservation manifest SHA-256 `411934b53a228b780f1a9e47f747bf447d64f871083619976744a096de5f3165`，私有intent/key不在公开复制清单 |

## 可重复只读审计

脚本：`audit_candidate13.py`，SHA-256 `8b9f58a7bd32f019cf47848b1a8e3eecf666fd054f79dcf8684cae67bb0a9349`。

实际回执：`candidate13-audit-result.json`，SHA-256 `e57a9ba9163c9f90581a47c2af16909038cc956767ef6448f8e0f34e89429b0d`。

脚本只用标准库读文件、算hash、认证本地HMAC及以immutable只读连接登记数据库；不导入执行Bridge、不spawn、不创建票据、不写状态、不运行native/DCC，不输出key或intent环境。调用stdout为派生审计结果：

```sh
/opt/homebrew/opt/python@3.11/bin/python3.11 -B /private/tmp/bridge-ready13-evidence-review/audit_candidate13.py \
  /Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-13 \
  /Users/user/Documents/Code_Project/Bridge/outputs/software-engineering-20261023-readiness-01 \
  --future14 /Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-14-authorized
```

最终验收状态止于 SOFTWARE PASS 与 candidate13 PREPARED_NOT_AUTHORIZED。真实 H21/Husk/Hython/Nuke 的同 PID hook、真实严格采集、许可/脚本实际时长、原生alpha及工程闭环、视觉和全16域M1保持未证；不能由本报告、完整软件产物或冻结review推定已获真实执行授权。
