# 环境、依赖和软件验证

当前 macOS 软件验证使用 macOS 15.8.1 arm64 和 Python 3.11.16。当前命令、结果、跳过原因和源码绑定见 [本批验证记录](../outputs/m1-completion-20261015/RESULT.md)；历史 Windows 结果只证明当时平台和范围。[macOS 复验说明](MACOS_REVERIFY_20261004.md) 区分软件与原生验收。

标准入口为 `tests/run_tests.py`；从仓库根运行，状态目录必须隔离。macOS 可设置 `TMPDIR=/private/tmp`，避免 `/var` 系统别名被严格路径守卫拒绝；不通过放宽真实用户目录权限消除失败。需要查询自有进程身份的测试应在允许只读进程查询的执行环境运行，不能把 `unknown` 改成 `alive`。

四包离线 wheel 与三类 Skill 的结果分别记录。FFmpeg／ffprobe 外部运行库的完整离线迁移、当前 H21.0.631／H22.0.459 的完整原生接口与真实宿主依然是独立门槛，不能用 Python 安装成功替代。

当前兼容目标为H22.0.459，主版H21.0.631不变。459已独立静态保存55个HDA定义及支持原件，见 `docs/native-basis/hda-interface-22.0.459.json`、`supporting-sources-22.0.459.json` 和 `h22-459-originals/`；这些文件不提供compiled／运行时模板、实例行为或有效writer最终事实。旧429材料保留原版本。

## Python 与四包开发环境

四个包当前版本均为 `2.0.0rc1`，声明 Python >=3.9；本项目接收基准使用 **Python 3.11**。原机解释器是 `/opt/homebrew/opt/python@3.11/bin/python3.11`，新机器自行提供 Python3.11，不能依赖这个绝对路径。通用 `python3` 在原机可能是3.14。

```sh
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install 'setuptools>=61' wheel
python -m pip install --no-build-isolation --no-deps -e packages/dcc-task-runtime
python -m pip install --no-build-isolation --no-deps -e packages/houdini-bridge
python -m pip install --no-build-isolation --no-deps -e packages/nuke-bridge
python -m pip install --no-build-isolation --no-deps -e packages/vfx-pipeline
```

依赖真源为各包 `pyproject.toml`：Houdini/Nuke依赖同版dcc-task-runtime，vfx-pipeline依赖另三个同版包；构建需要 setuptools>=61。上述初次安装构建工具可能联网，严格离线环境应预先备齐对应平台 wheel。

离线准备可在有批准网络的构建机用四个本地目录制作 wheel，另备 pip/setuptools/wheel，复制 wheelhouse 到目标机后 `pip install --no-index --find-links wheelhouse ...`。本移交包不是完整第三方离线运行时发行版；不能仅因 Python 四包齐全宣称 FFmpeg、系统动态库或 DCC 已包含。具体收录和排除以包根清单为准。

## 软件验证命令

标准测试入口使用 unittest，不要求 pytest，并为状态目录设置临时根、退出恢复环境：

```sh
env -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 python tests/run_tests.py
```

发现范围是 `tests/unit`、`tests/contract`、`tests/integration`。不要开放真实用户状态目录权限使失败消失。先修当前失败再跑受影响组；全量留到阶段稳定，当前不声明全量数量或通过。

当前 RBD 最小复现：

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=packages/dcc-task-runtime/src:packages/houdini-bridge/src:packages/nuke-bridge/src:packages/vfx-pipeline/src:tests/unit \
python -m unittest -v test_native_domain_graphs.NativeDomainGraphTests.test_rbd_actual_owned_activation_channel_geometry_and_rollback
```

最新正式 readiness／feedback 局部组（会启动受控 Python/TCP 替身，不启动真实DCC）：

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=packages/dcc-task-runtime/src:packages/houdini-bridge/src:packages/nuke-bridge/src:packages/vfx-pipeline/src:tests/unit:tools \
python -m unittest -v test_domain_readiness_evidence test_feedback_versions
```

需要保留该集成的原始生成项目时，将 `BRIDGE_FORMAL_READINESS_EVIDENCE_DIR` 指到一个新的专用目录，不能复用历史 `outputs/m1-takeover/*` 冻结证据路径。TCP bind 被环境禁止时报告具体环境限制；不能把测试换成不经过真实边界的伪通过。

## 正式装配与宿主配置

配置生成器 `tools/configure_production_hosts.py` 只验证本地可执行文件并写配置，不启动宿主。必需参数：

- `--output`：新配置JSON；既有文件拒绝覆盖。
- `--task-root`：任务自有目录。
- `--houdini-executable`、`--nuke-executable`、`--python-executable`：可信操作者选定的实际可执行文件。
- `--houdini-version`：当前目标为21.0.631或22.0.459；22.0.429仍可显式配置以读取旧任务，Nuke固定17.0v1。
- 可选成对 `--husk-executable`、`--husk-sha256`：可信操作者明确选择的writer文件绝对无链接路径和预期SHA-256；版本使用明确的`--houdini-version`。只验证文件，不启动husk，也不自动发现。生产配置保存三键`{path,version,sha256}`，部署端冻结完整文件身份并接入原始签名启动链。当前OS image/祖先采集只支持macOS，真实husk可观察性未运行验证，其他原生缺项仍阻止AVAILABLE，详见[进程身份接口](PROCESS_IMAGE_IDENTITY_20261016.md)。
- `--max-bytes`：正磁盘预算；`--session-seconds`：大于0且不超过120。
- `--project-id`、`--project-colorspace`：成对填写人工按项目确认的标识与输出 colorspace token；`--project-color-revision` 为正整数，默认1。两宿主配置保存相同 `project_color`，来源固定为 `human_project_selection`。未填写时可准备配置和建图，正式 Houdini 渲染会拒绝并提示缺少项目选择。该选择声明输出解释，不自动转换场景；产物保留原版本，Nuke 按登记值设置并读回，alpha与写出校验独立保留。

不要复制原机私有凭据、会话签名密钥或旧任务操作身份；为新任务用正式入口生成。production配置标识真实宿主源，缺配置报错；模型不能提供可执行路径或伪造身份。

项目生成入口是 `tools/prepare_workbuddy_graph.py --output <新项目目录>`，可显式附 `--production-config <配置JSON>`、`--media-config <配置JSON>` 和批准的profile。只做生成时不启动真实宿主；生成项目的 `control/server.py` 启动模式及后续工具可能进入执行，应先看配置与运行授权。

当前 `tools/run_full_readiness_cases.py` 默认 `--backend diagnostic`，不证明正式验收。正式模式必需 `--backend production --prepared-projects <映射JSON>`；软件验证必须再显式 `--software-processes`。映射是 `{exact_houdini_version: {case_id: absolute_prepared_project_path}}`，每case需要正式生成的 `control/run.json` 和 `snapshot-manifest.json`。不要手造成功manifest或用真实可执行文件试跑这个入口；其 production CLI整体仍待验证。当前可复验的底层替身建项目方式见 `tests/unit/test_domain_readiness_evidence.py`。

WorkBuddy使用桌面HY3和用户选择的完全访问权限，只提供项目级MCP配置/操作说明，不改全局配置或沙箱。材料限登记合成媒体及许可派生物。历史豆包/API脚本不属于当前必需路线。真实模型身份未取得证据时写unknown。

## 只读预检与真实运行分界

`tools/preflight_real_acceptance.py` 读取配置、操作卡和已确认资源scope，检查后输出回执，代码路径不启动宿主或FFmpeg：

```sh
python tools/preflight_real_acceptance.py \
  --config <控制端配置.json> --card <真实验收操作卡.json> \
  --scope <具体作业确认.json> --output <新的预检结果.json>
```

尖括号是待提供路径，占位符不可原样运行。scope要求具体case/domain、1–12个不同整数帧、0–120秒内预算、正磁盘预算、task_root、content_version、request_id、操作者确认及前后操作快照；缓存还需路径/估算/失效范围/帧/版本。不能替用户伪造confirmed或操作快照。预检通过本身不授予真实运行权限。

M2前需要独立接收M1，并具体确认版本、案例、帧段、路径、预算和缓存范围。本阶段不要运行 `validate_*live`、原生采集、hython/husk/idenoise/Nuke或WorkBuddy/HY3调用。

## 外部工具与可移植性

视频需可信固定 FFmpeg/ffprobe；本地合成媒体解码属于软件验证。原生接口静态依据在 `docs/native-basis/` 和完整档案W/integration；其中某些安装路径已离开原机，须根据记录版本/hash核对新环境，不能靠文件名判断版本。

Houdini、Nuke、WorkBuddy及许可证不包含在Python包内。OpenEXR命令行验证结果只是相应图像格式兼容证据。FFmpeg的动态库/rpath/动态加载资源/许可证，以及迁移后的真正解码仍需最终离线闭包验证。

三类发布入口和验证：

```sh
python tools/build_release.py <新的构建版本> --output <新发布目录>
python tools/verify_skill_lifecycle.py --release-dir <新发布目录> --output <新生命周期结果.json>
```

这些工具会创建测试安装或发布内容；仅在临时用户目录范围执行。当前未验证此移交build的三类生命周期，不先同步/清理覆盖历史证据。发布后还需清空开发PYTHONPATH检查真实导入和入口、升级/回退内容切换、保留其他插件设置。

准备矩阵源为 `tools/readiness_evidence.py`，报告入口 `tools/build_readiness_report.py` 要求 `--contract-evidence`、`--domain-cases`、`--media`、`--skill-lifecycle`、`--audit` 和 `--output-dir`。每项必须是实际当前build证据。包清单、Git记录或空案例不能代替这些输入。

## 本次离线包验证

`vendor/wheels/` 提供上述四个本地包的 wheel。新建 Python 3.11 虚拟环境，清空开发 PYTHONPATH，在仓库外通过 `--no-index` 安装；四包导入、三个 CLI `--help` 和 `pip check` 已验证。此项仅证明 Python 包安装与 help 入口，不证明正式宿主链或已知失败已修复。构建工具、Python 解释器和 FFmpeg/DCC 仍是外部前置依赖。

本地维护仓库位于 `/Users/user/Documents/Code_Project/Bridge/`。

## Git 中的运行证据边界

包含完整进程环境的历史原件仅保留在本地，相关路径由 `.gitignore` 排除；临时账本、编译探针和调试符号同样不上传。Git 中保留代码、复现脚本、非敏感审查记录及当前冻结证据；原始交付 ZIP 继续保存在本地 `outputs/` 与桌面交付目录。历史记录中对被排除原件的引用仅供本地核验，远端不构成完整原始证据归档。
