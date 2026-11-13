# 脚本与效率（学自用户笔记 Nuke.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Nuke.md` "脚本" / "表达式" 节。
原始笔记保持只读；本文件是 Python 脚本、表达式、批量工具的蒸馏版。

## 0. 官方 Python 文档

- 官方 Python API：https://learn.foundry.com/nuke/developers/70/pythonreference/
- Python 学习：https://www.runoob.com/python/python-tutorial.html

## 1. 在参数中使用表达式

- 右键 → `Add expression` 在参数中嵌入表达式
- 例如：`frame*10`、`height/2`、`random()`
- **`random()`** 生成随机数（做镜头震动很好用）
- **`frame*0.1`** 每帧偏移 0.1 帧
- `frame` 是当前帧数

### 参数关联（`Ctrl + 拖动` 链接）

> 按着 `Ctrl`（Mac 是 `Cmd`）键，从一个参数最右边的波浪线按钮点击拖住，
> 然后往想被关联的参数最右边的波浪线按钮放。
> 不按 `Ctrl` 的话，只会复制参数。

> **警告**：这在做一个 `.gizmo` 时是一个不必要的步骤，有时会导致问题。
> 你有没有在你的 Nuke 脚本周围复制/粘贴一个 gizmo，并发现它在所述副本之间
> 创建了表达式链接？这就是为什么……

**做 gizmo 时**：尽量用 disable/visibility 模式代替表达式链接。

## 2. 表达式速查

```text
frame              当前帧数
random()           随机数 [0, 1)
random(x)          seed = x 的伪随机
frame*0.1          每帧 0.1 偏移
height/2           项目高度的一半
width/2            项目宽度的一半
input1.width       第一输入端图像宽度
[value root.name]  当前 .nk 文件路径
[file dirname [value root.name]]  .nk 所在目录
```

## 3. 自动分层脚本（按 direct/indirect 配对）

**用户场景**：EXR 含 `direct_diffuse` / `indirect_diffuse` / `direct_specular` /
`indirect_specular` 等 AOV，要快速生成一个完整的合成图。

**操作步骤**：

1. 先创建一个脚本编辑器界面（`Window` → `Script Editor`）
2. 把下面代码复制到脚本编辑器内，**选中文件**，点击脚本编辑器上方的回车
3. 自动分好了

```python
# 完整可执行版（来自 Nuke.md 笔记 3156-3350 行）
import nuke
import time

def shuffle_and_correct_exr_passes(read_node):
    """把 EXR 的所有 AOV 拆成 Shuffle → Grade → ColorCorrect 链"""
    # Get all channels available in the node
    all_channels = nuke.channels(read_node)
    # Deduce unique layers from channel names (split at the first dot)
    layers = list(set([channel.split('.')[0] for channel
                       in all_channels if 'rgba' not in channel]))

    # Sorting layers to group 'direct' and 'indirect' components together
    direct_layers = sorted([layer for layer in layers if 'direct' in layer.lower()])
    indirect_layers = sorted([layer for layer in layers if 'indirect' in layer.lower()])
    other_layers = sorted([layer for layer in layers
                           if 'direct' not in layer.lower()
                           and 'indirect' not in layer.lower()])

    # Combining sorted lists for proper ordering
    sorted_layers = []
    layer_nodes = {}
    x_positions = {}
    y_positions = {}
    # Match direct and indirect layers
    for direct in direct_layers:
        base_name = direct.replace("direct", "").strip()
        for indirect in indirect_layers:
            if base_name in indirect:
                sorted_layers.append(direct)
                sorted_layers.append(indirect)
                break

    # Add remaining other layers
    sorted_layers.extend(other_layers)

    # Coordinate positions for created nodes
    x, y = read_node.xpos(), read_node.ypos() + 100

    # Create nodes for each layer and store them for merging
    for layer in sorted_layers:
        # Create Shuffle node
        shuffle_node = nuke.nodes.Shuffle(name=f"Shuffle_{layer}",
                                          label=layer, inputs=[read_node])
        shuffle_node['in'].setValue(layer)
        shuffle_node['postage_stamp'].setValue(True)
        shuffle_node['out'].setValue('rgba')
        shuffle_node['label'].setValue(layer)
        shuffle_node.setXpos(x)
        shuffle_node.setYpos(y)

        # Create Grade node
        grade_node = nuke.nodes.Grade(name=f"Grade_{layer}", inputs=[shuffle_node])
        grade_node.setXpos(x)
        grade_node.setYpos(y + 100)

        # Create ColorCorrect node
        color_node = nuke.nodes.ColorCorrect(name=f"ColorCorrect_{layer}",
                                             inputs=[grade_node])
        color_node.setXpos(x)
        color_node.setYpos(y + 200)
        layer_nodes[layer] = color_node
        x_positions[layer] = x
        y_positions[layer] = y + 300

        x += 200  # Increment x position for the next set of nodes

    return layer_nodes, x_positions, y_positions


def merge_pairs(layer_nodes, x_positions, y_positions):
    """把配对的 direct/indirect 用 plus 模式 merge 起来"""
    pairs = [
        ("direct_coat", "indirect_coat"),
        ("direct_diffuse", "indirect_diffuse"),
        ("direct_reflect", "indirect_reflect"),
        ("direct_refract", "indirect_refract"),
        ("direct_sss", "indirect_sss"),
        ("direct_volume", "indirect_volume"),
    ]
    merge_nodes = []
    for direct, indirect in pairs:
        if direct in layer_nodes and indirect in layer_nodes:
            merge_name = f"Merge_{direct}_{indirect}"
            merge_node = nuke.nodes.Merge2(
                name=merge_name,
                inputs=[layer_nodes[direct], layer_nodes[indirect]],
                operation='plus')
            merge_node.setXpos((x_positions[direct] + x_positions[indirect]) // 2)
            merge_node.setYpos(max(y_positions[direct], y_positions[indirect]) + 50)
            merge_nodes.append(merge_node)
    return merge_nodes


# Usage:
read_node = nuke.toNode('Read1')  # 替换为实际 Read 节点名
layer_nodes, x_positions, y_positions = shuffle_and_correct_exr_passes(read_node)
merged_nodes = merge_pairs(layer_nodes, x_positions, y_positions)
```

**nuke-bridge 注意事项**：

- 这个脚本用了 `nuke.nodes.X` / `nuke.toNode` / `nuke.channels`，
  全部是 `nuke_run` AST allowlist 内的 API，可以直接搬到 `nuke_run` 调用
- **`nuke.channels(node)`** 返回通道列表，格式如 `['rgba.red', 'rgba.green', 'direct_diffuse.red', ...]`
- 脚本**未处理 alpha 通道**——你的 AOV 顺序若不是 direct_/indirect_ 配对，
  要修改 `pairs` 列表
- `time.sleep(0.1)` 在 nuke_run 中可删——不需要

## 4. 输出节点转绝对路径

**场景**：工程里用相对路径，部署到生产时全部转绝对路径

```python
import nuke
import os

def convert_to_absolute_path():
    # 获取当前选中的节点
    selected_nodes = nuke.selectedNodes()

    if not selected_nodes:
        nuke.message("请先选中一个节点。")
        return

    for node in selected_nodes:
        if "file" in node.knobs():
            file_path = node["file"].value()

            # 如果路径包含表达式（如 [value something]），使用 nuke.filename() 解析
            if '[' in file_path:
                absolute_path = nuke.filename(node)
            else:
                if not os.path.isabs(file_path):
                    script_dir = os.path.dirname(nuke.root().name())
                    absolute_path = os.path.normpath(
                        os.path.join(script_dir, file_path))
                else:
                    absolute_path = file_path

            node["file"].setValue(absolute_path)
            print(f"{node.name()} 的路径已更新为绝对路径: {absolute_path}")


convert_to_absolute_path()
```

**nuke-bridge 注意事项**：

- `nuke.selectedNodes()` 在 headless 模式会返回空——GUI 模式下用
- `nuke.filename(node)` 是解析路径的官方 API
- `os` 是脚本里 import 的——nuke_run AST 允许（nuke 进程内的 os，不影响沙箱）

## 5. 渲染后自动建立 Read 节点

```python
# 渲染完后直接将渲染好的作为一个 Read 节点建立出来
nuke.nodes.Read(file=nuke.thisNode()['file'].value())
```

**用法**：在 Write 节点的 `afterRender` 回调里调用，渲染完自动建一个 Read
回放节点。

## 6. 视频元数据修改

- `ModifyMetaDate` 节点可以修改视频元素
- `AddTimeCode` 节点可以将时间码添加到元数据中

## 7. PFtrack 相机导入（nuke 内部 Run Script）

> 与 **PFtrack**：
> PFtrack 导出的相机数据是 `py` 格式，可以直接使用 `Run Script` 导入到 Nuke 中使用

操作：
1. PFtrack 导出相机为 `py` 文件
2. Nuke 中 `Run Script` 节点 → 选择 `py` 文件
3. 自动建立 `Camera` 节点

## 8. 批量渲染

- `F5` 弹出批量渲染界面
- 有 `Write` 节点会加入进来渲染
- 建议用 deadline 配一个本地的，直接跑满，方便管理渲染追查

## 9. 批量替换丢失的文件

- 全选 `Shift +` 加选所有报错文件
- `Ctrl + Shift + /` 弹出替换框
- 上方旧路径，下方新路径
- **下划线用 `/`**，不能用 `\`（Windows 习惯）

## 10. 自动创建相对路径

> Nuke 想要开启相对路径功能，需要按 `S` 打开项目设置（Project Settings），
> 然后按下 `Script Directory` 按钮，`Read` 节点便可以直接使用相对路径的方法
> 来链接素材。

或者在素材路径那写：`[ file dirname [value root.name] ]` 即可直接写为相对路径。

## 11. nuke_run / 表达式 / 脚本 的常见坑

- **`nuke_run` AST allowlist**：只允许 `nuke` / `nukescripts` / `math` / `re` /
  `json` / `random` / `colorsys` / `struct`
  - 用户脚本里如果 import `os` / `time` / `sys` / `subprocess` 会被桥接器拒绝
  - `os.path` 在脚本里很常用，但**只能 nuke_run 之外先 import 再传**，
    或者用 nuke 自己的 `nuke.paths` 替代
- **`random` 模块被 nuke_run 注入**：用户脚本里 `import random` 会与注入的
  `random` 冲突；建议不用 `random` 库名
- **`nuke.thisNode()` 只在回调里有效**：比如 Write 的 afterRender、Read 的
  beforeRender
- **`nuke.selectedNodes()` headless 模式返回空**：要先在 GUI 选中
- **`nuke.Root().knob('first_frame')` 拿工程第一帧**——比 `nuke.frame()`
  更快（不依赖当前帧）
- **`nuke.paths` 是 nuke 自己的路径工具**：包含 Nuke 插件路径、脚本路径
  - 比 `os.path.expanduser` 在 nuke 环境下更稳
- **gizmo 副本间表达式链接**：把 `[expr ...]` 关联换为 `[disable ...]`
  模式，避免 link

## 12. 实用 snippet 速查

```python
# 拿到所有 viewer
for v in nuke.allNodes('Viewer'):
    print(v.name(), v['viewer_process'].value())

# 拿到所有 write 节点
writes = nuke.allNodes('Write')
for w in writes:
    print(w.name(), w['file'].value())

# 拿当前选中节点的名字
sel = nuke.selectedNodes()
if sel:
    print(sel[0].name())

# 拿工程所有 knob
root = nuke.root()
for k in root.knobs():
    print(k, root[k].value())

# 拷贝一个 Read 节点（带所有 knob）
src = nuke.toNode('Read1')
nuke.nodeCopy('%TEMP%/copy.nk')
nuke.nodePaste('%TEMP%/copy.nk')
```

## 13. 把脚本挂到菜单

在 `.nuke/menu.py` 里加：

```python
import myNukeScripts
toolbar = nuke.menu('Nuke')
toolbar.addCommand('My Scripts/Convert to Absolute',
                   'myNukeScripts.convert_to_absolute_path()')
```

这样在 Nuke 菜单 `Nuke` → `My Scripts` → `Convert to Absolute` 就能用。
