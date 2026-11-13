# 项目级固定视频解码配置

可信控制端通过项目 JSON 指定本地 ffmpeg，再交给 `tools/prepare_workbuddy_graph.py --media-config`。生成的 `control/run.json` 将该对象保存为 `controller_media`；正式 `build_graph_facade` 从它创建 `FixedVideoDecoder` 和 `ControllerMediaService`。生成的 `control/server.py` 默认 diagnostic stdio 入口及 export/handoff 命令均使用该组装，媒体操作不创建或派发 DCC 客户端。显式 production 入口仍要求完整生产配置。配置不会改写全局 WorkBuddy 设置。

最小配置见 `docs/examples/controller-media.json`。将示例绝对路径替换成已经安装、可信且具有执行权限的本地 ffmpeg 文件。允许指向该文件的本地符号链接；解码器使用解析后的绝对路径。生成工具不会搜索 PATH、下载依赖或执行 ffmpeg。

```sh
python3.11 tools/prepare_workbuddy_graph.py \
  --output /absolute/path/to/new-project \
  --media-config /absolute/path/to/controller-media.json
```

提供配置时，`ffmpeg_executable` 必须是非空本地绝对路径，目标必须存在且可执行。空对象、相对路径、不存在或不可执行的文件，以及未知字段会在创建项目前被拒绝。未提供配置的图像项目继续使用既有图像服务；视频抽帧工具会因缺少固定解码器而拒绝执行。

配置只接受以下字段：

| 字段 | 规则与消费入口 |
| --- | --- |
| `ffmpeg_executable` | 必填；本地绝对可执行文件；由正式组装交给固定解码器。 |
| `attachment_limits` | 可选对象；只接受 `max_attachments`、`max_attachment_bytes`、`max_total_bytes`、`max_dimension`，值必须是正整数；直接交给现有媒体服务。 |
| `sequence_diagnostics` | 可选对象；只接受 `expected_frames`、`active_frames`、`max_temporal_delta`。前两项必填，均为 1–12 个按升序排列、互不重复的非负整数；活动帧必须属于预期帧。可选阈值必须是有限非负数。 |

帧号采用零起始的已解码帧索引。预期帧和活动帧由控制端按实际案例冻结，模型不能覆盖。省略可选字段时保留现有服务行为。模型工具仅接受已登记的素材 ID、帧号和附件 ID，不能传入执行路径、命令、文件路径或来源分类。

控制端在新 run 第一次打开前，将授权的本地合成视频按 `assets` 既有登记结构写入 manifest，记录真实文件位置、SHA256、素材 ID 和来源分类。正式抽帧工具验证源文件摘要，成功解码后登记派生 ID、源 ID、源 SHA256、帧号、图像摘要和尺寸；附件工具重新核验这些登记信息后返回实际 PNG 内容。源文件变化或未登记素材会被拒绝。

持久 reference 的 kind 和目录 MIME 来自可信 manifest 的 `mime_type`：PNG 为 image，已支持的视频 MIME 为 video。视频目录给出抽帧与附件工具的入口；派生目录项保留帧 ID、摘要、版本、帧号、尺寸和父源关系。模型先调用 `media_video_frames`，再通过 `media_attachments` 或 `media` 读取派生图像，然后以原始视频源 ID 调用 `submit_observation`，只描述所提供帧的内容及不确定性。未抽帧、帧来源不匹配或字节变化会拒绝。派生 ID 本身可读取图片；观察提交使用目录中的 `observation_asset_id`，保持冻结的视频源身份。

视频观察回执绑定真实已登记帧的完整来源依据。控制端 handoff 会重新验证原始视频和该依据，保留原有图片校验；它不会把视频当成 PNG，也不会补造视频内容、运动结论或模型身份。抽样帧不足以证明完整运动正确性。

只读真实验收预检可使用同一配置文件：

```sh
python3.11 tools/preflight_real_acceptance.py \
  --config /absolute/path/to/host-config.json \
  --card /absolute/path/to/case-card.json \
  --scope /absolute/path/to/confirmed-scope.json \
  --media-config /absolute/path/to/controller-media.json \
  --output /absolute/path/to/preflight.json
```

也可在预检的宿主配置中提供 `controller_media` 对象；显式 `--media-config` 优先。案例卡或 scope 的 `references` 中出现 `{"kind":"video"}` 时必须提供媒体配置；非视频案例的依赖状态为 `NOT_REQUIRED`，已有但失效的可选视频配置不会阻断它。原有资源确认和 request 绑定的前后 operation 快照检查仍然执行。

预检输出 `media_dependency`，含 `READY`、`BLOCKED` 或 `NOT_REQUIRED`、具体缺项、配置路径、解析路径、文件/执行权限状态及可读取时的实际 SHA256。该摘要是只读观测，未在整个解码期间锁定或持续校验 executable。预检不执行 ffmpeg、宿主或模型；`READY` 只表示静态依赖检查通过，不授予启动权限。

软件验证使用本地 ffmpeg 创建微型合成视频，经实际生成的 `control/server.py` 默认 diagnostic stdio 服务完成抽帧、派生登记、真实附件、源视频观察及控制端 handoff。测试仅在底层 DCC transport 注入拒绝边界，不替换正式媒体服务或组装；记录实际解码 argv，确认无 DCC transport、网络调用和 operation 创建。该结果证明软件媒体链路和项目配置消费；原生 Houdini/Nuke、WorkBuddy/HY3、模型视觉与最终安装包验收须各自取得同一最终 build 的实际证据。

离线交付须另行具备可信本地 ffmpeg 及其本机运行依赖；本项目没有打包或安装它。最终源码/安装包确定后，需要重新检查安装端绝对路径、执行权限、解析目标和摘要，再在最终生成快照重复媒体正向。版本、原生能力与视觉效果不能由静态预检推断。
