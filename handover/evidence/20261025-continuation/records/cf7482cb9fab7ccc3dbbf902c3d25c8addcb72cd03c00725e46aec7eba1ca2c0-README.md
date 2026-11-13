# 模板库（references/templates/）

> 约定：存 **.hip / .nk 骨架文件**（已验证可 cook/可打开的标准起架），弱模型接到
> 高频任务时直接 `open_script`/加载模板改参数，比从零建图稳得多。
> 这是 fxhoudinimcp 的 Workflows 类目和官方 Roto_template.nk 的共同思路。
> **只收实测通过的模板**；生成模板优先用 scripts/quick_setup.py 等脚本产线，
> 生成命令写进本文件对应条目，保证可再生产。

## 现有模板

| 文件 | 内容 | 生成方式 | 验证 |
|---|---|---|---|
| `pyro_bonfire_skeleton.hip` | 篝火 Pyro 起架：torus 源 -> pyrosource -> volumerasterizeattributes -> DOP(smokeobject+volumesource+pyrosolver) -> dopimport -> OUT | `quick_setup.setup_pyro('/obj/SRC_torus', preset='bonfire')` 后 save | 末端 cook 无错误（2026-08-25，quick_setup self-test 同链路） |

## 回填规范（以后加模板照此）

1. 用脚本/工具链生成骨架（勿手工攒），cook 验证零错误
2. 文件名 `<效果>_<预设>_skeleton.<hip|nk>`，源节点命名 `SRC_*` 一眼可辨
3. 在上表登记：内容一句话 + 生成命令 + 验证日期
4. Nuke 侧模板（如标准抠绿链）放 `nuke-bridge/references/templates/`（同规范）

## 使用方式（agent 视角）

- Houdini：`hou.hipFile.load(模板路径)` 或 open 后改 `SRC_*` 节点与预设参数
- 模板改完先 cook 末端 OUT 节点确认，再接自己的上下游
