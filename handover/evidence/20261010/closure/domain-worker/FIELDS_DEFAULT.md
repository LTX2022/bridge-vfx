# Crowd 后续缺口：dopimportfield.fields

2026-10-09 的本机两版安装原件只读调查；未执行真实 DCC、模型、仿真、缓存或渲染。2026-10-10 补齐记录。

`after-fresh-queries/run.json`：双版本正常正式 Crowd 用例退出 1，15.687 秒。每版 journal 有六条 COMPLETE（包括 agent_definition 和 dop_network）、一条 UNKNOWN：创建 import_geometry 后，场景读回报 `native default is not captured: .../import_geometry/fields`。完整建图未成立；stash 创建与后续 children 查询早停已越过，不表示 Crowd 接收。

实际只读命令使用 `.venv/Scripts/python.exe -B -`，导入现有 `tools/capture_native_schema.py` 的 `index_sections` 与 `dialog_parameters`，读取 `C:/Program Files/Side Effects Software/Houdini <version>/houdini/otls/OPlibSop.hda`，依次解析 `Sop/dopimportfield` 与 `DialogScript`；没有调用安装目录中的程序。

| 版本 | 本机 HDA SHA-256 | DialogScript SHA-256 |
|---|---|---|
| 21.0.631 | c42f9d17b134de3d6d3b920ef26849975f9e8381fec23ce8e889ad79332d96c5 | 17ae72f9ef9833bd1631e69ed2675fc3da1b5bef0a6e6e3c9e2c7ba2640a8287 |
| 22.0.429 | 5cac9d862eecb4afe72ee83dc13a0b3861472079183002939b0b8cb23f24856c | 17ae72f9ef9833bd1631e69ed2675fc3da1b5bef0a6e6e3c9e2c7ba2640a8287 |

两版 section 与已有 selective capture 的 SHA 完全一致。`fields` 是 `multiparm`，size=1，子模板为 enable#/visible#/objname#/fieldname#，原件没有父 multiparm 的显式 default，解析为 default_tokens=[]。子模板默认值不能证明父 factory/current count；CreateScript 没有 count 赋值。未解析 Contents.gz 的运行时效果，也未观察实际 HOM count。

不能填 0/1，也不能当作无值 Folder 跳过；count 是实例绑定的必要事实。下一步补有原件依据的状态采集或合法新建初始化顺序，再复验同一正常正式入口。若必须真实 HOM 实例观察，按项目约束另行具体授权；当前保持 BLOCKED，正常 SUCCEEDED 断言和失败日志保留。
