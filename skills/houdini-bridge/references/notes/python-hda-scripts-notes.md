# Python / HDA / 脚本插件速查（学自用户笔记 VEX和VOP和脚本插件编写等.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\Houdini基础模块\VEX和VOP和脚本插件编写等.md` 第 1960-3747 行。
原始笔记保持只读；本文件是蒸馏版——Python API、python 节点与工具架脚本（实测代码
完整保留）、HDA 制作、环境变量、常用工具包。截图见原笔记。

## 1. Houdini 里写 Python 的四个地方

1. **节点上**（`file` / new operator type 里的 python 形式）
2. **python shell**（Windows 菜单，交互解释器）
3. **python source editor**（写 `hou.session` 模块的地方）
4. **工具栏**（右键工具栏建工具写 python）

查帮助：`help(函数名)`；官方 HOM 手册：sidefx.com/docs/houdini/hom/index.html

## 2. 基础 API（实测代码，完整保留）

### 2.1 节点与参数

```python
obj = hou.node("/obj") # 获取obj节点
geo = obj.createNode("geo") # 创建一个geo节点
box = geo.createNode('box')  # 创建一个box在第二个创建的geo中
box.move((2,3))  # 在network view(节点树面板上) 移动一个node到一个位置上
box.setName("Hallo")   # 重命名这个节点叫Hallo
box.setSelected(True)  # 选中这个节点
box.isSelected()  # 判断这个节点是否被选中(返回判断值)
box.type().name()   # 获得节点的类型的名字

# 获得节点参数的值:
box.parm('tx').eval()
box.evalParm('tx')
box.evalParmTuple('t')  #（获取这个参数的元组）

box.setParms({'tx':6, 'ty':1, 'tz':-4})  # 修改节点的参数
box.parms()  #获取这个节点的所有参数
box.setInput(0,hou.node('/obj/geo1/sphere1')) # 将 /obj/geo1/sphere1 的节点(上游) 连接到这个节点
boxparm = box.parm('ty') # 获取这个节点的ty参数给boxparm
boxparm.evalAtFrame(4) # 获取这个参数在第4帧的值

bx = hou.parmTuple('/obj/geo1/box1/t') # 获取box1这个节点的t参数(Center)给 bx
bx.deleteKeyframeAtFrame(1)  # 删除这个参数在第1帧的关键帧
bx.deleteAllKeyframes()  # 删除这个参数的所有关键帧

bx = hou.parmTuple('/obj/geo1/box1/t')[0] # 获取Center参数的 x值 给bx
by = hou.parmTuple('/obj/geo1/box1/t')[1] # 获取Center参数的 y值 给by
bz = hou.parmTuple('/obj/geo1/box1/t')[2] # 获取Center参数的 z值 给bz
bx.set(30)  # 修改center参数中x的值为30
bx.setExpression("$F*2") # 修改center参数中x的值为表达式 $F*2
str = bx.expression() # 获取center参数中x的表达式给str
frm = bx.keyframes() # 获取center参数中x的所有关键帧给frm
```

参数名速记：`t`=Center、`size`=Size、`r`=Rotate。参数真名：鼠标悬停在参数上看。
其它常用：`box.node('..')` 父节点；`n.children()`/`n.parent()` 子/父节点；
`hou.node('...').destroy()` 删节点；`hou.pwd()` 当前目录；`box.path()` 节点路径；
`hou.selectedNodes()` 选中节点；`hou.ui.displayMessage("...")` 弹窗。

### 2.2 创建节点并连接

```python
>>> obj = hou.node("obj")
>>> mygeo = obj.createNode('geo') #创建一个geo
>>> mygeo = obj.createNode('geo',run_init_scripts=False) #创建一个geo，不运行初始化脚本
>>> mybox = mygeo.createNode('box') #创建一个box在第二个创建的geo中
>>> mysur = mygeo.createNode('subdivide') #创建一个subdivide在第二个创建的geo中
>>> mysur.setFirstInput(mybox) #连接subdivide和box节点
>>> mygeo.layoutChildren()     #位置排列，相当按下L
>>> mysur.setDisplayFlag(True) #设置显示属性
>>> mysur.setRenderFlag(True)  #设置渲染属性
>>> mysur.isDisplayFlagSet()   #显示属性是否开启
```

### 2.3 函数

`def 函数名(变量):` + `return` 即可（greet/find_max 等入门示例见原笔记）。
修改模型上某个点位置的函数（含越界报错）：

```python
def set_point_position(node,point_num,position):

    geo = node.geometry()
    if point_num < 0 or point_num >= len(geo.points()):
       raise ValueError(f"点号{point_num}超出范围！")


    point = geo.iterPoints()[point_num]  # 获取指定点
    point.setPosition(hou.Vector3(position))  # 设置新位置


node = hou.pwd()
set_point_position(node, 5, (2,1,2))
```

按节点名后缀给参数赋值（wedge 场景常用）：

```python
# 获取当前节点
node = hou.pwd()

# 获取节点名字
node_name = node.name()

# 根据“_”分割名称
name_parts = node_name.split('_')

# 提取末尾的字符
last_part = name_parts[-1]

# 设置想要改变的参数
hou.parm('/obj/geo1/null1/wedge').set(last_part)
```

## 3. python 节点脚本（实测代码，完整保留）

**按 aid 属性自动拆 Blast**（检测点/prim 属性，为每个唯一值建节点，已存在则跳过）：

```python
import hou

# 获取当前 Python 节点
node = hou.pwd()

# 获取输入几何体
inputs = node.inputs()
if not inputs:
    raise hou.Error("Python 节点没有输入几何体，请连接上游几何体。")

input_geo = inputs[0].geometry()

# 检测 aid 是点属性还是基元属性
attr_name = 'aid'
attr_type = None

if input_geo.findPointAttrib(attr_name):
    attr_type = 'point'
    attribs = input_geo.points()
elif input_geo.findPrimAttrib(attr_name):
    attr_type = 'prim'
    attribs = input_geo.prims()
else:
    raise hou.Error(f"几何体中没有找到名为 '{attr_name}' 的属性。")

# 收集所有唯一的 aid 值
unique_aids = set()
for elem in attribs:
    val = elem.attribValue(attr_name)
    if val is not None:
        unique_aids.add(val)

if not unique_aids:
    raise hou.Error(f"没有找到任何有效的 '{attr_name}' 值。")

# 获取父级目录（通常为当前 Python 节点的父级）
parent = node.parent()
if not parent:
    parent = node

# 为每个唯一值创建 Blast 节点（如果已经存在则跳过）
created = []
skipped = []
for aid in sorted(unique_aids):
    node_name = f"blast_aid_{aid}"
    # 检查同名节点是否已存在
    existing = parent.node(node_name)
    if existing is not None:
        skipped.append(aid)
        continue

    blast = parent.createNode("blast", node_name)
    blast.setParms({
        "group": f"@aid={aid}",   # 选择 aid 等于该值的元素
        "negate": 1               # 1 = 保留组内元素（删除非选中）
    })
    blast.setInput(0, inputs[0])
    blast.setDisplayFlag(True)
    created.append(aid)

print(f"成功创建 {len(created)} 个 Blast 节点，对应 '{attr_name}' 值: {created}")
if skipped:
    print(f"以下 '{attr_name}' 值已有对应节点，已跳过: {skipped}")
```

**按 shop_materialpath / prim 组提取模型**：与上面 aid 脚本同一模式——
`geo.primStringAttribValues("shop_materialpath")` 取唯一值（或 `geo.pointGroups()/
geo.primGroups()` 取组名），循环 `node.createOutputNode("blast")`，
`group` 写 `'@shop_materialpath="路径"'` 或直接写组名，`grouptype`
设 0（Point Groups）或 4（Primitives），`negate` 设 1。完整两段代码见原笔记
"python节点"一节。

## 4. 工具架脚本（实测代码，完整保留）

工具架安装：新建工具架（`Documents/houdini20.0/toolbar` 下生成 `.shelf`）→
工具架上右键新建工具 → 粘贴代码。

### 4.1 Karma GPU/CPU 控制

Karma 节点设 Xpu 模式后用 rop 渲染（视图窗口的 XPU 不影响 rop）。平时只开 GPU
腾出 CPU，出成片全开。**Python Script 节点写有时失效，建议用工具架热修改**：

```python
#禁用CPU，只用GPU
import hou
hou.unsetenv('KARMA_XPU_DISABLE_EMBREE_DEVICE')
hou.unsetenv('KARMA_XPU_DISABLE_OPTIX_DEVICE')
hou.putenv('KARMA_XPU_DISABLE_EMBREE_DEVICE', '1')

#禁用GPU，只用CPU
import hou
hou.unsetenv('KARMA_XPU_DISABLE_EMBREE_DEVICE')
hou.unsetenv('KARMA_XPU_DISABLE_OPTIX_DEVICE')
hou.putenv('KARMA_XPU_DISABLE_OPTIX_DEVICE', '1')

#CPU GPU都启用
import hou
hou.putenv('KARMA_XPU_DISABLE_EMBREE_DEVICE', '0')
hou.putenv('KARMA_XPU_DISABLE_OPTIX_DEVICE', '0')
hou.unsetenv('KARMA_XPU_DISABLE_EMBREE_DEVICE')
hou.unsetenv('KARMA_XPU_DISABLE_OPTIX_DEVICE')
```

`houdini.env` 写法：`KARMA_XPU_DISABLE_EMBREE_DEVICE = 1`（禁 CPU）、
`KARMA_XPU_DISABLE_OPTIX_DEVICE = 1`（禁 GPU）。

### 4.2 splitByAttr（按 path 属性拆分导入模型）

选中 File 节点，点工具架：

```python
import hou
# 属性名称
attrName = "path"

# 获取选择的节点
selected_nodes = hou.selectedNodes()
if not selected_nodes:
    raise Exception("No node selected")

node = selected_nodes[0]

# 获取geometry
geo = node.geometry()

# 获取class属性值
class_attr = geo.findPrimAttrib(attrName)
if not class_attr:
    raise Exception(attrName +" attribute not found")

# 找到所有唯一的class值
unique_class_values = set([prim.attribValue(class_attr) for prim in geo.prims()])

# 对于每个唯一的class值，创建一个blast节点
for class_value in unique_class_values:
    # 创建blast节点
    blast_node = node.createOutputNode("blast")

    # 设置blast节点的参数
    blast_node.parm("group").set("@"+attrName+"==" + str(class_value))
    blast_node.parm("negate").set(True)
    blast_node.setSelected(True)
```

### 4.3 merge_ref（给每个拆分模型做单独 Geo）

选中所有 Blast 节点，点工具架：

```python
for node in hou.selectedNodes():
    obj = hou.node('/obj')
    geo = obj.createNode("geo")
    geo.setName(node.name())
    merge = geo.createNode("object_merge")
    merge.parm("objpath1").set(node.path())

    nullNode = merge.createOutputNode("null")
    nullNode.setName("Render_"+node.name())
    nullNode.setDisplayFlag(True)
    nullNode.setRenderFlag(True)
```

### 4.4 create_rs_mat（创建 Redshift 材质）

选中所有 Blast 导出的 Geo 节点：

```python
for node in hou.selectedNodes():
    mat = hou.node("mat")

    rsmb = mat.createNode("redshift_vopnet","rs_mat_"+node.name())
    if(node.type().name() == "geo"):
         node.parm("shop_materialpath").set(rsmb.path())
    else:
        old_outputs = node.outputConnections()
        mate = node.createOutputNode("material")
        if len(old_outputs) > 0:
           for con in old_outputs:
            index = con.inputIndex()
            next_node = con.outputNode()
            next_node.setInput(index,mate)

        mate.parm("shop_materialpath1").set(rsmb.path())
        mate.setSelected(True)
        node.setSelected(False)
```

### 4.5 SuperMerge（按 M 自动创建 Merge）

```python
import hou

def create_merge_below_selected_nodes():
    selected_nodes = hou.selectedNodes()

    if selected_nodes and len(selected_nodes) >= 1:

        bbox_x_min = min([node.position()[0] for node in selected_nodes])
        bbox_x_max = max([node.position()[0] for node in selected_nodes])
        bbox_y_min = min([node.position()[1] for node in selected_nodes])
        bbox_y_max = max([node.position()[1] for node in selected_nodes])

        sop_nodes = [node for node in selected_nodes if node.type().category().name() == "Sop"]
        dop_nodes = [node for node in selected_nodes if node.type().category().name() == "Dop"]
        lop_nodes = [node for node in selected_nodes if node.type().category().name() == "Lop"]


        merge_x_pos = (bbox_x_min + bbox_x_max) / 2
        merge_y_pos = bbox_y_min - 2


        merge_node = selected_nodes[0].parent().createNode("merge")
        merge_node.setPosition((merge_x_pos, merge_y_pos))


        for node in selected_nodes:
            merge_node.setNextInput(node)

        if sop_nodes:
            merge_node.setSelected(True, True, False)
            merge_node.setDisplayFlag(True)
            merge_node.setRenderFlag(True)
        if dop_nodes:
            merge_node.setSelected(True, True, False)
        if lop_nodes:
            merge_node.setSelected(True, True, False)
            merge_node.setDisplayFlag(True)
    else:

        network_editor = None
        for pane in hou.ui.paneTabs():
            if isinstance(pane, hou.NetworkEditor) and pane.isCurrentTab():
                cursPos = pane.cursorPosition()
                currPwd = pane.pwd()
                n = currPwd.createNode("merge")
                n.setPosition(cursPos)

create_merge_below_selected_nodes()
```

> 注意：还要在热键设置里额外绑定快捷键 M（截图见原笔记）。

### 4.6 SuperNull（Shift + N 新建 Null 输出节点，需手动绑快捷键）

```python
createNodeSop = ['null', 'null1']
createNodeVop = ['null', 'null1']
createNodeLop = ['null', 'null1']
createNodeDop = ['null', 'null1']


sel = hou.selectedNodes()

if sel:
    for node in sel:

        if node.outputConnections():
            outputConnection = node.outputConnections()[0]
            connected_node = outputConnection.outputNode()

            inputConnections = connected_node.inputs()
            for i,connection in enumerate(inputConnections):
                if connection.name()==node.name():
                    connected_index = i

            #print(connected_node,connected_index)


        name = node.name()
        network_nodes = node.parent().children()
        while True:
            node_exists = any(['OUT_' + name == existing_node.name() for existing_node in network_nodes])
            if node_exists:
                name = 'OUT_' + name
            else:
                break


        if node.type().category() == hou.sopNodeTypeCategory():
            parent = node.parent()
            n = parent.createNode(createNodeSop[0],createNodeSop[1])
            n.setInput(0,node)

            node_position = node.position()
            n_pos = (node_position[0],node_position[1] - 1.5)
            n.setPosition(n_pos)
            n.setName('OUT_'+name)

            node_color = node.color()
            n.setColor(node_color)

            n.setSelected(True, True, False)
            n.setDisplayFlag(True)
            n.setRenderFlag(True)

        elif node.type().category() == hou.vopNodeTypeCategory():
            parent = node.parent()
            n = parent.createNode(createNodeVop[0],createNodeVop[1])
            node_position = node.position()
            n.setPosition((node_position[0] + 2, node_position[1]))
            n.setInput(0, node)
            n.setSelected(True, True, False)

        elif node.type().category() == hou.lopNodeTypeCategory():
            parent = node.parent()
            n = parent.createNode(createNodeLop[0],createNodeLop[1])
            n.setInput(0,node)

            node_position = node.position()
            n_pos = (node_position[0],node_position[1] - 1.5)
            n.setPosition(n_pos)
            n.setName('OUT_'+name)

            node_color = node.color()
            n.setColor(node_color)

            n.setSelected(True, True, False)
            n.setDisplayFlag(True)

        elif node.type().category() == hou.dopNodeTypeCategory():
            parent = node.parent()
            n = parent.createNode(createNodeDop[0],createNodeDop[1])
            n.setInput(0,node)

            node_position = node.position()
            n_pos = (node_position[0],node_position[1] - 1.5)
            n.setPosition(n_pos)
            n.setName('OUT_'+name)

            node_color = node.color()
            n.setColor(node_color)

            n.setSelected(True, True, False)


        output_connections = node.outputs()
        output_count = len(output_connections)
        if output_count > 1:
            connected_node.setInput(connected_index,n)

else:
    network_editor = None
    for pane in hou.ui.paneTabs():
        if isinstance(pane, hou.NetworkEditor) and pane.isCurrentTab():
            cursPos = pane.cursorPosition()

            if pane.pwd().childTypeCategory().name() == 'Sop':
                currPwd = pane.pwd()
                n = currPwd.createNode(createNodeSop[0],createNodeSop[1])
                n.setPosition(cursPos)

            elif pane.pwd().childTypeCategory().name() == 'Vop':
                currPwd = pane.pwd()
                n = currPwd.createNode(createNodeVop[0],createNodeVop[1])
                n.setPosition(cursPos)

            elif pane.pwd().childTypeCategory().name() == 'Lop':
                currPwd = pane.pwd()
                n = currPwd.createNode(createNodeLop[0],createNodeLop[1])
                n.setPosition(cursPos)

            elif pane.pwd().childTypeCategory().name() == 'Dop':
                currPwd = pane.pwd()
                n = currPwd.createNode(createNodeDop[0],createNodeDop[1])
                n.setPosition(cursPos)
```

**hiplc→hip 转换工具**：完整脚本见原笔记"hiplc转换为hip文件工具"一节（来源
github.com/huiwentong/MyDailyWork 的 `hou_cvt_hdalc.py`：选节点 → 生成工具架
代码到剪贴板 → 新建工具架工具粘贴执行）。

## 5. HDA 资产制作

### 5.1 创建流程

1. 节点串打包 `subnet`（`Shift + C`）→ 改名 → 右键 `Create Digital Asset...`。
2. 弹面板改 `Asset Label`（节点名）和 `Tab Submenu`（放哪个菜单）→ `Create`。
3. `Edit Operator Type Properties` 里编辑参数属性，直接 `Accept`。

**修改资产必须从 `Type Properties...` 改参数！** 保存 HDA 时三个选项：

- `No Changes`：手动整理新旧参数
- `Revert Layout`：**保留旧参数**，丢弃新备用参数——99% 情况下解锁只是逛逛，选这个最安全
- `Destroy All Spare Parameters`：删旧迎新，大量开发迭代时用

陷阱：用参数面板上的 `Edit ...`（而非 Type Properties）改参数，保存时弹出的
`Type Properties` 里会**没有新改的参数**，导致保存出问题。

### 5.2 自定义参数面板（Edit Parameter Interface）

常用参数类型速查：`Float/Integer`（含 Vector 2/3/4）、`Toggle`、`Button(Strip)`、
`Color(and Alpha)`、`Ramp(Float/Color)`、`String`、`Operator Path/List`、
`File` 系列（目录/几何体/图片）、`Folder`、`Separator`、`Label`、
`Direction Vector`、`UV/UVW`、`Key-Value Dictionary`、`Logarithmic Float`、
`Min/max Float`、`RGBAMask`、`Icon Strip`。

- `Name`：参数名（代码引用用）；`Label`：面板显示名；`Type`：改类型；
  `Size`：参数数量；`Range`：范围（两把锁锁最高/最低值）。
- **引用已有参数**：打开 Null 的 `Edit Parameter Interface` → `Channels` 面板 →
  把 Transform 节点的 `Translate` 拖进来，自动识别三个通道——即可用 Null 控制
  Transform。曝光节点内部参数到上层：`From Nodes` 选项卡找到参数加进
  `Existing Parameters`（做 HDR 工具时把不想暴露的参数勾 `Invisible` 隐藏）。

### 5.3 Toggle 控制两种功能

- 拖入 `Toggle` 参数写好 Name（如 `enable`）/Label/Help。
- 需勾选才出现的参数：`Disable When`（当…成立时不启用）或 `Hide When`
  （当…成立时隐藏）里写 `{ enable == 0 }`。
- 内部 `Switch` 节点的 `Select Input` 写 `if (ch("../enable"), 1, 0)`：
  1=勾选（第 2 输入），0=未勾选（第 1 输入）。

### 5.4 用户自封装 HDA

`sop_sop.Point_Guidance.1.0`（点引导轨迹）、`gas_disturb`（pyro 内部扰动）、
`main.lookdev`（画板+参考球）、`lop_Solaris_Setup`（karma 节点树 Recipes）、
`Remesh_Polygons_by_VDB`（VDB 减面）、`juria_switchremovepoint`（删点工具）。

## 6. 环境变量

`houdini.env` 位置：`C:\Users\用户名\Documents\houdini版本号\houdini.env`
（macOS 在 `/Users/文档/houdini版本号/`）。实用项：

```
HOUDINI_DISABLE_OPENFX_DEFAULT_PATH = 1   # 关闭 openFX 插件加载（其报错拖慢启动）
HOUDINI_EXTERNAL_HELP_BROWSER = 1         # 帮助文档默认用系统浏览器打开
HOUDINI_VULKAN_VIEWER = 1                 # 视口用 Vulkan（默认 OpenGL|ES）
```

常用路径/时间变量：`$HIP` 工程路径、`$HIPNAME`/`$HIPFILE`、`$JOB`、`$HFS` 安装目录、
`$HH`（=$HFS/houdini）、`$OS` 当前节点名、`$HOME`、`$TEMP`、`$SIDEFXLABS`；
`$FPS`/`$FSTART`/`$FEND`/`$T`/`$F`/`$FF`。变量面板：`Shift + Alt + V`。
同一地址多写法：`$HFS/houdini/usd/assets/pig` = `$HH/usd/assets/pig`。

## 7. 安装路径总表（macOS 首选项在 `/Users/用户名/Library/Preferences/houdini/版本`）

| 内容 | 路径（Windows） |
|---|---|
| scripts 脚本 | `Documents/houdini20.x/scripts`（没有就新建） |
| otls 资产 | `Documents/houdini20.x/otls` |
| 工具架 | `Documents/houdini20.x/toolbar` |
| packages | `Documents/houdini20.x/packages` |
| Modeler/SoftBoolean | modeler 或 soft_boolean 和 packages 文件夹复制到用户首选项目录 |

## 8. 工具包速查

- **SoftBoolean**（融合 2 模型）/ **Modeler**（建模，含专用桌面）。
- **VFX Tricks Toolbox**：`Cacher`（读 `.usd/.bgeo .sc/.vdb`）、`Cacher Importer`
  （LOP 动态导入）、`Camera Frustum`、Multishot 工作流、Deadline 插件
  （USD 缓存/husk 渲染/Wedge 只交一次 hip）、UE Sequencer 导出器。
- **Blender→Houdini 资产库**：Blender 装 `super_batch_export_2.1.2`，导出后用
  `modify_usda.py` 修 Prim 层级，再用 `Layout Asset Gallery` 建库。
- **Scripts**：`externaldragdrop.py`（材质模型一键拖入）、
  `principledShader_to_MTLX.py`（材质一键转 Karma）。
- **WesLib**：个人项目管理。中英 UI 在 `wes_ProjBrowser.py` 改（**用中文 UI**）；
  `$JOB` 对不上时点"设JOB为Hip"。
- **渲染管理**：HoudiniRenderM（批量渲染，hython，Python 3.11）、
  Houdini Task Manage（简版 Deadline，hda 放 otls，exe 和 source 同目录）。
- **开源库**：Aelib（100+ 工具）、QLib、MOPs（动态图形）、Dolag 工具集（国人）。
  安装都是改 package json 里的路径放 packages，**路径用 `/` 不用 `\`**。
- **其它**：OD Houdini Shelf Tools、MasterExploder（可控爆炸）、Akshay Kumar
  脚本集、Natsura（植物）、郭超特效工具包（FluidSource/PyroCompress/RBD AutoUV 等）。

otls 常用资产（详见原笔记带图章节）：df_CameraCut（相机剔除，wrangle 等价代码
见 vex-vop-notes.md）、sop_frust_cam（相机体素）、cam_hud、EZ_CAM、CameraTrail、
DF_ViewAttr、DF_rope_bridge（程序化木桥）、cfx_wrap（wrap 变形）、
OpenCL Wrinkle Deformer（褶皱）、ping.modify_wave（海浪）、OpenCL Skin Slide、
sop_decay_spread、breakdown_fallout、tree_wind、Spark Trails、
Asset_USD_Builder（批量转 USD）、AX_Save_Assets（打包+路径相对化）、
HPT_FBXArrange（FBX 场景整理/封片/挤压/`model_error` 属性）、
HPT_AutoProject（资源搜集）、HPT_AutoMat、DF_CreateFolder。

## 9. 易错点

- **导入 FBX 时 `Import Directly Into /obj Network` 不要勾**：勾了模型散在 Object
  层级导致 HPT_FBXArrange 无法使用；不小心勾了自己做个 Subnetwork 也行。
- **packages json 里的路径必须用 `/`**（QLib、MOPs 同理），Windows 复制的 `\` 会失效。
- **Karma XPU 的 env 用 Python Script 节点设置有时失效**——用工具架脚本热修改。
- **改 HDA 参数必须走 `Type Properties...`**：用参数面板 `Edit ...` 改，保存时新参数
  会丢。解锁 HDA 逛一圈再保存：无脑选 `Revert Layout` 最安全。
- WesLib 英文 UI 是坏的，用中文 `Wes_ProjBrowser_ch.ui`；镜头文件夹基于 `$JOB`，
  Python 设 `$JOB` 有时出问题，路径对不上就按"设JOB为Hip"。
- `createNode('geo', run_init_scripts=False)` 可跳过初始化脚本，批量建 geo 更干净。
- 工具架脚本（SuperMerge/SuperNull）要**手动绑定快捷键**才生效。
- blast 批量拆分先确认属性是 point 还是 prim 级，`grouptype` 0=Point Groups、
  4=Primitives，设错拆出来是空的。
