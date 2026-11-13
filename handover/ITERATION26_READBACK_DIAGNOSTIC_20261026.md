# 只读渲染配置读回专项结果（2026-10-26，ITERATION26）

状态：**专项已执行成功并取得决定性事实：authorized-06 正式保存 HIP 中，karmarendersettings 节点参数为 manual/128×128/无驱动，但重开宿主组合出的 RenderSettings prim `resolution` 是 `Gf.Vec2i(2048, 1152)`（uniform int2、authored、非时变）——与节点参数脱钩，指向无头进程的显示默认值。** 组合语义的触发条件尚未钉死，需一次对照实验专项（见下一步）。

## 决定性事实（dump 原件已入 Git）

[evidence/20261026-render-readback/readback-dump.json](evidence/20261026-render-readback/readback-dump.json)（sha256 `8f211e2c...`）：

- 节点层（重开宿主实时读回）：`res_mode='manual'`、`resolutionx=128`、`resolutiony=128`，全部无表达式/无锁定/无关键帧；engine=cpu、denoiser=off、enablemblur=0、pixelAspectRatio=1.0。
- 组合层：settings prim `/World/Bridge_c3e1a30abf835f0b/settings`（经 render 节点 loppath→`usd_network/settings_binding`（Lop/rendersettings）→ stage@frame1）：
  - `resolution = Gf.Vec2i(2048, 1152)`，uniform int2，**authored=true**——不是默认未著写，是有人写入了显示分辨率。
  - `aspectRatioConformPolicy=expandAperture`、`dataWindowNDC=(0,0,1,1)`、`pixelAspectRatio=1.0`。
  - `husk:default_delegate=BRAY_HdKarma`、karma 全局/对象参数均在（samplesperpixel=9、convergence_mode=Variance 等，与初始化写入一致——**这些参数的组合都正确，唯独 resolution 脱钩**）。
- 关系：camera→/World/.../camera、products→/World/.../Products/renderproduct。
- capture（真实原生证据）确认：karmarendersettings 的分辨率参数是名为 `resolution` 的 intvector2 tuple（**default_tokens 为空，未捕获出厂默认**）；`resolutionx/y` 仅是分量名；res_mode 菜单由 `loputils.resolutionModeMenuItems()` 动态生成，'manual' 是合法值（菜单首项）。

## 含义

1. `CONTROLLED_OUTPUT_CONFIG_OUTSIDE_POLICY: composed USD resolution differs` 的直接原因即此：策略要求组合值 [128,128]，实际组合值 2048×1152。
2. 由于 husk 主渲染同样在加载 HIP 后自行组合，**渲染将真实产出 2048×1152 的图**——不是校验层可绕过的问题，必须在渲染前使组合正确。
3. 2048×1152 为 16:9 显示分辨率，与 128 无任何推导关系（autoheight/autowidth 都推不出），且 karma 其余参数组合全部正确——指向 karmarendersettings LOP 在该环境下对 resolution 的 authoring 走了"当前显示配置"路径而非 manual 参数值。

## 执行记录

| 范围/候选 | scope | 结果 |
|---|---|---|
| candidate（bad35035） | 未激活 | 冻结了旧版宿主脚本，废弃不用 |
| authorized（ff512fe4） | 1 次 hython 启动 | 宿主旧版单字段异常中断（真实 HOM 对无表达式参数 `expression()` 抛错），dump 未产出，STOP_UNKNOWN，`NATIVE_SCOPE_EXECUTION_FAILED` 封闭 |
| candidate-2（3c6e4bb9） | — | 含修正后源码，经第三轮独立复核 APPROVED 后激活 |
| **authorized-2（46277f44）** | **1 次 hython 启动，8.4 秒级** | **RENDER_READBACK_PASSED**：dump 落盘、HIP 字节未变、签名启停对完整；控制端最终预算核对我误用 `state['tickets']`（`check()` 不含该键）报 KeyError，scope 以 NATIVE_SCOPE_EXECUTION_FAILED 封闭——**结果证据完整有效，工具缺陷已修**（snapshot()['tickets']，与 HIP 运行器一致） |

PYTHONEXECUTABLE 事实（透明记录）：execute 以绑定 3.14.7 stub 为实际解释器启动，`PYTHONEXECUTABLE=<绑定路径>` 仅修正 sys.executable 的展示重定位（homebrew opt 链接 10-24 起指向 3.14.9）；实际解释器身份锚点是 hosts 字节绑定 + owned supervisor 从绑定路径 exec，不受该变量影响（独立复核评估：软一致性守卫，对抗边界在 HMAC 账本，接受）。

**治理发现（待用户决策）**：engineering 05/06 与本专项的 supervisor_python 绑定的是 launcher stub 文件哈希；实际解释器由 PATH/opt 链接决定。homebrew 升级 python@3.14（已发生：3.14.7→3.14.9）可静默替换实际解释器。05/06 实际运行解释器按时间线推定已是 3.14.9（opt 链接改动早于执行）。生产绑定层应改为绑定真实解释器文件或对 `sys.executable`/`sys.version` 做绑定校验。

## 独立复核

三轮：首轮发现 3 处修正（目录参数、settings env、计划措辞）后 APPROVED；执行失败后第三轮确认宿主逐字段容错修正、旧 scope 消耗、PYTHONEXECUTABLE 手段（附条件）、并指出控制脚本未提交修复（已提交 b789018）。聚焦测试 `test_render_readback_diagnostic.py` 6/6。

## 下一步（需用户新的执行授权）

**对照实验专项**（1 次 hython 启动、只读+内存内操作、不保存 HIP）：在重开宿主上
1. 记录 settings LOP 的 res_mode 求值与 `resolution` tuple 值；
2. 触发 `resolutionMenu` 按钮/重跑 `updateResolutionParameters` 回调；
3. 重新 `lop.stage()` 组合并记录 resolution 是否变为 128×128；
4. 对照"不做 2/3"的组合值。

由此钉死"组合何时采用参数值"，然后设计第 24 次修复（候选方向：重开后受控重设分辨率并证明组合，或受控输出策略按真实语义改写——以实验结果定）。04/05/06 与本专项证据原样保留，不拼接。
