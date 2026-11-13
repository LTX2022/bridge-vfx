# HDA 创作/封装全流程（官方手册为准，2026-08-25 实测核对）

> 依据：H21.0.631 hom.zip（hou.OpNode/HDADefinition/hda/OpNode.txt 原文）+ 本机
> hython 实证（hda_toolkit.py self-test 六项全 PASS 的链路）。
> 用户笔记（python-hda-scripts-notes.md 的 GUI 流程）只是入门视角的一种，
> 本文以官方 API 为准。工具脚本：`scripts/hda_toolkit.py`（11 函数+self-test）。

> **⚡ TL;DR 速答卡**（读完能解决就不用往下翻）
> - 一句话封装：subnet 节点上 `node.createDigitalAsset(name="作者::资产名::1.0",
>   hda_file_name=..., save_as_embedded=...)`，返回后**按路径重取节点**再拿定义
> - 官方版本工作流四步：实例 `allowEditingOfContents()` 解锁 -> 改内部 ->
>   `definition.updateFromNode(实例)` 回存 -> `definition.setVersion("2.0")`
> - 实例默认锁定：不解锁直接改内部 = `hou.PermissionError`
> - 命名 `作者::名字::版本`：namespace 防撞名，多版本可共存于一个 .hda
> - 参数面板程序化：`definition.parmTemplateGroup()` 改完
>   `setParmTemplateGroup(group)`
> - 内嵌文件/脚本 = Sections：`definition.addSection("OnCreated", code)`，
>   实例里用 `opdef:` 协议引用
> - 装卸：`hou.hda.installFile(path)` / `uninstallFile(path)`；开机自动装走
>   OPlibraries（installFile 的 oplibraries_file 参数可代写）

## 1. 创建：hou.OpNode.createDigitalAsset（H21 签名，原文核对）

```
createDigitalAsset(name, hda_file_name=None, description=None,
    min_num_inputs=0, max_num_inputs=0, compress_contents=False,
    comment=None, version=None, save_as_embedded=False,
    ignore_external_references=False, change_node_type=True,
    create_backup=True, install_path=None) -> Node
```

- `name`：新节点类型名，推荐三段式 `作者::资产名::版本`（如 `me::tool::1.0`）--
  namespace 防止与第三方撞名，版本段允许多版本共存
- `hda_file_name`：存到哪个 .hda；None 则默认 `$HOME/houdiniX.Y/hda/OPcustom.hda`
- `save_as_embedded`：True = 存进当前 hip（Embedded，随场景走）；False = 存文件
- `min/max_num_inputs`：输入口数（subnet 想接上游就设 max>=1）
- `compress_contents`：内容压缩
- `change_node_type=True`：subnet 直接变成 HDA 实例（**旧 Python 节点引用立刻
  失效**--`hou.ObjectWasDeleted`，必须 `hou.node(path)` 重取，实测坑）

## 2. 参数面板（Type Properties 程序化）

```python
group = definition.parmTemplateGroup()
tmpl = hou.FloatParmTemplate("strength", "Strength", 1, (1.5,), min_value=0)
# 放进已有/新建 folder：
group.appendToFolder(folder_template, tmpl)   # 或 group.append(tmpl) 放根
definition.setParmTemplateGroup(group)
```
模板类型：`FloatParmTemplate / IntParmTemplate / StringParmTemplate /
ToggleParmTemplate / MenuParmTemplate / FolderParmTemplate`。

## 3. Sections（内嵌脚本与文件）

- `definition.addSection("OnCreated", code)` -- 实例创建时执行
- `"PythonModule"` -- 实例内部可 `hou.node('.').hdaModule()` 调用的模块
- `"DialogScript"` -- 自定义 UI
- `definition.sections()` / `hasSection(name)` 查询
- 实例内引用内嵌文件用 **`opdef:` 协议**（如贴图路径
  `opdef:/obj/inst?sectionname=image.pic`）；`oplib:` 按类型引用

## 4. 安装管理（hou.hda 模块）

- `hou.hda.installFile(path)` / `uninstallFile(path)`（会话级）
- 开机自动加载：OPlibraries 文件（installFile 的 `oplibraries_file=` 参数可代写）
- `hou.hda.definitionsInFile(path)` 列出文件里的全部定义；
  `hou.hda.loadedFiles()` 列出已加载文件（含 "Embedded"）
- `hou.hda.safeguardHDAs()` 全局保护开关（True = 会话内定义一律不可改）；
  实例级解锁见下节，两者是不同层级

## 5. 版本工作流（官方四步，hom.zip 原文语义）

> HDADefinition.txt 原文："To edit those nodes you create an instance of the
> digital asset, **unlock it, modify the contents, and save the definition**."

```python
inst.allowEditingOfContents()            # 解锁（官方 API，菜单同名）
inst.node("geo_in/torus").parm("rows").set(10)   # 改内部
definition.updateFromNode(inst)          # 回存进定义
definition.setVersion("2.0")             # 版本号（bump 用 setVersion，无专用 API）
inst.matchCurrentDefinition()            # （可选）改完锁回去
```

- 实例默认锁定（read-only、随定义自动更新）；解锁后可编辑、不随定义更新
- `node.isEditable()` / `node.matchesCurrentDefinition()` 查锁定状态
- `definition.copyToHDAFile(new_path)` 可把定义拷进另一个 .hda

## 6. 文本化 / 逆向

- **opscript + cmdread 原理**（同 hip-convert）：`hou.hscript("opscript -G -r /obj/x")`
  导出纯文本，`cmdread` 重建 -- HDA 实例节点同样适用
- **`hou.hda.expandToDirectory(dir, definition)`**：定义展开成目录镜像
  （Contents/、sections/ 一目了然，审 HDA 神器）

## 7. 实测坑（2026-08-25 hda_toolkit self-test 抓到的）

1. **`change_node_type=True` 后旧节点引用失效**（ObjectWasDeleted）--重取：
   `node = hou.node(subnet_path)`
2. **OBJ 级 subnet 只能放 OBJ 节点**--SOP（torus 等）要套一层 `geo` 容器
3. **锁定实例改内部 = PermissionError**--先 `allowEditingOfContents()`
4. `hou.expandString()` 已弃用--用 `hou.text.expandString()`（H21）
5. `argparse` 参数别叫 `--def`（`args.def` 撞 Python 关键字）
6. 裸名查定义（`hda_tool_test`）与全名（`selftest::hda_tool_test::1.0`）都要支持--
   `nodeTypeName()` 带全名，按 `::` 拆段匹配

## 8. 工具脚本：scripts/hda_toolkit.py

| 函数 | 对应官方 API |
|---|---|
| `create_hda_from_subnet(subnet, name, hda_file, ...)` | createDigitalAsset |
| `add_parm(def_name, dict)` | parmTemplateGroup/setParmTemplateGroup |
| `set_type_properties(def_name, description/icon/comment)` | setDescription/setIcon/setComment |
| `add_section(def_name, section, contents)` | addSection |
| `install_hda / uninstall_hda / list_installed` | hou.hda.installFile 等 |
| `bump_version(def_name, major=True)` | setVersion（'1.0'->'2.0'/'1.1'） |
| `update_from_node(node_path)` | definition.updateFromNode |
| `export_text(target, out_dir)` | opscript / expandToDirectory |
| `self_test()` | 全链路验收（create->加参->OnCreated->实例化 cook->update->bump->export->卸载） |

自检：`hython hda_toolkit.py --self-test`（六项 PASS 基线 2026-08-25）。
