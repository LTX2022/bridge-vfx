# 官方 Keying Mastery Roto_template.nk 解析（2026-08-25）

来源：`C:/Users/<USERNAME>/OneDrive/Node/Node/3D/一些能当成套模板使用的工程文件/Nuke/Roto_template.nk`（4728 行，Nuke 15.1v3 保存）。
原始工程只读未动；本文件是 Foundry 官方 Keying Mastery 课程模板的蒸馏版，供 nuke-bridge 复刻参考。

## 1. 工程全貌

- **节点总数**：顶层 120 个块（含 Root / 13 BackdropNode / 15 StickyNote）；
  含 Group 内部共 413 个节点。Group/Gizmo 5 个：`DasGrain1`（内含嵌套 `VoronoiScatter`，
  约 140 节点）、`D_QCTool` ×3（每个约 19 节点，第三方 QC gizmo，均 `disable=true`）。
- **Root 设置**：
  - `format "4096 2160 ... 4K_DCP"`，proxy `1024x778 1K_Super_35(full-ap)`（proxy_type scale）
  - `colorManagement Nuke`（**不是** OCIO config！），`workingSpaceLUT linear`，
    `monitorLut sRGB`，`monitorOutLUT rec709`
  - `lock_range true`，保存时 `last_frame 2`（素材实际 140–250）
- **输入素材**（3 个 Read）：
  | 节点 | 文件 | 帧 | 用途 |
  |---|---|---|---|
  | `Read2` | `Soldier_GS_Plate_v5_####.exr` | 140–250 | 原始绿幕 plate |
  | `Read3` | `Soldier_GS_Plate_MarkerRemoval_####.exr` | 140–250 | 已去跟踪标记 plate（主链路实际用它） |
  | `Read9` | `iStock-680409522.jpg`（沙漠背景，2121×1414） | 静帧 | 合成背景 |
- **输出**：`Write3` → `Soldier_Comp_####.exr`，exr / `ocioColorspace scene_linear` / `view sRGB`。
- **区域划分**（StickyNote 标注 + BackdropNode 围框，自上而下）：
  `PLATE` → `DENOISE` → `PREP / CLEANUP / TRACKING MARKER REMOVAL` → `SCREEN CLEAN`
  → `GARBAGE MATTE` / `CORE KEY` / `EDGE KEY`（三列并行）→ `DESPILL` / `DESPILL FIX`
  → `ADDITIVE KEYER` → `GRADING` → 背景合成 → `REGRAIN` → `QC CHECK` → `Write Node`。
- BackdropNode9 带课程链接（learn.foundry.com cleanup 教程）；StickyNote11/12 标注
  DasGrain 与 D_QCTool 的 Nukepedia 下载地址——**复刻时这两个 gizmo 需另行安装**。

## 2. 流水线结构图（主干）

```
Read2 (plate v5) ── FrameRange1(140-250) ── Shuffle4 ──┬── Denoise3 ──┐
   │(Read3 = MarkerRemoval plate)                       │              ▼
   └────────────────────────────── Read3 ──────────────► Switch1 (which=1 → Read3!) ── Dot19 (主分发)
                                                           input0=Denoise3(备用)
Dot19 ──┬─► [SCREEN CLEAN] IBKColourV3_3→_4→_5→_7 ──► Merge7(divide: plate÷screen) ── Grade7 ── Dot30
        │       (Size=1, erode=5, multi=1/10/30/60)        = "归一化绿幕" plate
        │
Dot30 ──┬─► [CORE KEY] Primatte1 ── FilterErode4(+5) ── Blur8(5) ──────────────┐
        │                                                                      ▼ over(A=edge,B=core)
        └─► [EDGE KEY] OCIOColorSpace4(lin→log) ── Keylight9 ── OCIOColorSpace5(log→lin)
                       ── Grade13(alpha, blackpoint 0.05 / whitepoint 0.66, mask=Roto5) ──► Merge10
[GARBAGE MATTE] Roto3 ── FilterErode1(+3.6) ── FilterErode2(-16) ── Blur2(20) ──► Merge6(mask=Roto3)
Merge6 + Merge10 ──► Merge5(in) = 最终 matte ──► Dot35 ─┐
                                                        │ copy alpha
Dot19 ──► Dot36 ──┬─► Keylight7 (despill A) ── Merge4(from: KL7 - plate) ── Shuffle2(取green)
        │         │    ── Grade10(white 0.22) ── Merge11(plus 回 plate) ──► Dot7
        │         └─► Keylight10 (despill B, balanceSet) ──┬─► Merge17(from: plate-KL10)=spill
        │                                                  │    ── Shuffle6(green) ── Grade6(white 2.95,
        │                                                  │      mask=Roto8) ── Grade5(white 0.08)
        │                                                  └─► Merge18(plus 8% spill 回补) ──► Keymix1(A)
        └─► Keymix1: A=Merge18, B=Dot7, mask=Roto2 → 两种 despill 按 roto 分区混合
Keymix1 ──► Grade8 (GRADING: white 1.4, multiply {1.225 1.240 1.141}, black ≈ -0.005)
        ──► Copy1(alpha from Dot35) ──► Premult3 ──┐
[ADDITIVE KEYER] Merge7 ── Saturation1(0) ── Grade4 ── Grade3(black=1, mask=Invert2←Blur4(23.5)←Roto7)
Read9(背景) ── Reformat6 ── Defocus1(10) ──► Merge19(multiply: 背景×纹理层) ──► Merge20(over: fg 上)
Merge20 ──► DasGrain1 (REGRAIN: COMP/PLATE/DEGRAINED_PLATE/mask 四输入) ── Crop1 ── Dot28 ── Write3
QC 支线: Merge20→PostageStamp4→D_QCTool1; Dot28→PostageStamp1→D_QCTool2;
        Shuffle4→PostageStamp3→Transform2(scale 2.5)→D_QCTool  (三个 QC gizmo 均 disable)
```

## 3. 各分区节点与关键参数（只记非默认值）

### 3.1 PLATE / DENOISE

- `FrameRange1`: `first_frame 140`, `last_frame 250` —— 模板级限帧。
- `Shuffle4`: mappings 把 alpha 也保留（`rgba.alpha 0 3`），喂给 Denoise。
- `Denoise3`（Denoise2 型）: `analysisFrame 159`, `analysisRegion {73 1965 365 2149}`，
  `needsAnalyzing false`（已分析完并序列化 profileCurve）。
- `Switch1`: `which 1`，input0=`Denoise3`、input1=`Read3`。
  **注意**：which=1 选中的是 **Read3（去标记 plate）**，Denoise 支路是备选；
  Denoise3 真正的固定用途是 DasGrain 的 `DEGRAINED_PLATE` 输入。

### 3.2 SCREEN CLEAN（IBKColour 四级堆栈）

四个 `IBKColourV3` 串联（_3→_4→_5→_7），共同参数：

- `Size 1`
- `off {-0.006 -0.009 -0.067}`（屏幕色偏置）
- `mult {0.636 0 1.03}`
- `erode 5`
- `multi`：_3=默认(1)，_4=10，_5=30，_7=60 —— **逐级放大采样半径做屏幕均化**

之后：

- `Merge7`: `operation divide`, `bbox B` —— plate ÷ IBK 屏幕色 = 归一化（screen clean 核心）
- `Grade7`: `multiply {0.1127097905 0.3580080867 0.1698716432 0}` —— 把绿幕亮度压到统一水平

### 3.3 GARBAGE MATTE

- `Roto3`（`output alpha`, `lifetime_start/end 140`）手绘外轮廓。
- `FilterErode1 size 3.6`（先扩）→ `FilterErode2 size -16`（再缩 16px）→ `Blur2 size 20`
  —— 造一条 20px 的内收过渡带。
- `Merge6`: `operation mask`, A=Blur2 流、mask=`Roto3` —— 过渡带裁回 roto 内。

### 3.4 CORE KEY

- `Primatte1`（Primatte3 型）：全部调参存在 `data`/`primEdgedata`/`primBodydata` blob 里
  （Smart Select 采样数据），无可读标量参数；`crop {0 0 4096 2160}`。
- `FilterErode4 size 5`（core 收缩）→ `Blur8 size 5`（core 边缘柔化）。

### 3.5 EDGE KEY（log 域 Keylight）

- `OCIOColorSpace4`: `scene_linear → compositing_log`（**在 Nuke 色彩管理下仍用 OCIO 节点做 log 转换**）
- `Keylight9`（`OFXuk.co.thefoundry.keylight.keylight_v201`）:
  - `screenColour {0.4210449457 0.5483123064 0.4716479182}`（log 域里吸取的屏幕色，数值偏灰白）
  - 其余 matte 参数全默认（clip 0/1、无 grow/softness）——官方只在 log 域取 alpha，不做 matte 修整
- `OCIOColorSpace5`: `compositing_log → scene_linear`
- `Grade13`: `channels alpha`, `blackpoint 0.05`, `whitepoint 0.66`，mask 输入 = `Roto5`
  —— **edge matte 的对比度全靠 Grade 在 alpha 上拉黑/白点**，限定在 Roto5 画的边缘带内。
- `Merge10`: over，A=edge(Grade13)、B=core(Blur8) —— edge 盖在 core 上。
- `Merge5`: `operation in`, A=Merge10、B=Merge6 —— 总 matte 受 garbage matte 约束。

### 3.6 DESPILL / DESPILL FIX（双 Keylight + Keymix）

主 plate（Dot36←Dot19）分两路做 despill，再用 `Keymix1` 按 `Roto2`（lifetime 200 的 roto）分区混合：

**支路 A（Keylight7，y≈3404 右列）**

- `Keylight7`: `screenColour {0.1148220971 0.3647842109 0.1733604372}`，
  `alphaBias {0.1689453125 0.106628418 0.08178710938}`（bias 往屏幕色方向偏，despill 更强）
- 溢出补偿：`Merge4 from`（KL7 − 原 plate = 被减掉的 spill）→ `Shuffle2`（green→rgb）
  → `Grade10 white 0.22` → `Merge11 plus` 回原图 —— **加回 22% 的 spill 亮度保发梢细节**。

**支路 B（Keylight10，y≈3346 中列）**

- `Keylight10`: `screenColour {0.07171999663 0.4509890079 0.1302579939}`（更深更纯的绿），
  `alphaBias {1.096874952 1.170254111 1.306332111}`（bias>1，往前景偏，保 alpha），
  `balanceSet true`（**screenBalance 已由自动平衡设置**——三个 Keylight 里唯一一个）
- 溢出补偿：`Merge17 from`（plate − KL10 = spill）→ `Shuffle6`（green→rgb）
  → `Grade6 white 2.95`（mask=`Roto8` 限定区域）→ `Grade5 white 0.08`
  → `Merge18 plus` 回 KL10 —— 2.95×0.08 ≈ **加回 23.6% 的 spill**，且只在 Roto8 区域内。

- `Keymix1`: A=Merge18（支路 B 结果）、B=Dot7（支路 A 结果）、mask=`Roto2`。

### 3.7 ADDITIVE KEYER（屏幕纹理转移到背景）

- `Roto7` → `Blur4 size 23.5` → `Invert2` = 主体外部的柔边 mask。
- `Merge7`（screen-clean 后的 plate）→ `Saturation1 saturation 0` → `Grade4`（全默认，占位）
  → `Grade3 black 1`（黑场抬到 1，mask=Invert2）—— 得到一张 ≈1 的"屏幕明度纹理"。
- `Merge19`: `operation multiply`，A=背景散焦流、B=Grade3 —— 把屏幕纹理乘到背景上。
- `Read9 → Reformat6 → Defocus1 defocus 10`：背景图重定格式 + 10px 散焦模拟景深。
- `Merge20`: over，A=Premult3 前景、B=Merge19 背景 —— 最终合成点。

### 3.8 GRADING / alpha 合并

- `Grade8`: `white 1.4`, `multiply {1.225052476 1.24000001 1.140537262 1}`,
  `black {-0.004375 -0.005 -0.005 -0.008}` —— 前景提亮并轻微压黑匹配背景。
- `Copy1`: `from0 rgba.alpha → to0 rgba.alpha`，A=Grade8（调色后 fg）、B=Dot35（最终 matte）
  —— **先调色再贴 alpha，避免 despill 残留污染 matte**。
- `Premult3` 预乘。

### 3.9 REGRAIN（DasGrain gizmo）

- `DasGrain1` 四输入：0=COMP（Merge20）、1=PLATE（PostageStamp5←Shuffle4 原 plate）、
  2=DEGRAINED_PLATE（PostageStamp6←Denoise3）、3=mask（Difference2，`gain 999999` 的
  comp-vs-denoised 放大差，实际 `concealer 0` 未生效）。
- 关键参数：`luminance 1`, `number_of_frames 10`, `sample_count 20`, `scatter true`,
  `box {162 1942 562 2142}`, `sample_frame 1`, `cell_size 40`, `frequency 15`, `concealer 0`。
- 内部嵌套 `VoronoiScatter`（BlinkScript `VoroNoise` 做颗粒散布）；输出后经
  `Crop1`（`crop false`，仅重置 bbox 到 format）→ `Dot28`（label "Write Node"）→ `Write3`。

### 3.10 QC

- `D_QCTool1/2/`D_QCTool` 三个实例全部 `disable=true`，分别挂在 Merge20、Write 前、
  原 plate（经 `Transform2 scale 2.5 center {1463 594}` 放大局部）——
  用时手动 enable，模式含 LUMINANCE / SATURATION / CLIPPING / GRAIN 四格 ContactSheet。
- `Viewer1` 输入 0/1 分别接 Copy1 与 PostageStamp5（plate 对照）。

## 4. 与已有 references 的对照

对照 `edge-blend-correct-workflow.md`（下称 E）与 `production-best-practices.md`（下称 P）：

**印证**

- E 的"方法 3：Primatte 核心 + IBK 边缘 + 收缩"与本模板结构一致：core/edge 分离、
  `FilterErode` 正值收缩 core、`Blur` 柔化、matte 合并后再 `in` garbage matte。
- P 的 Merge `divide` 用于"屏幕清洁"与 Merge7 完全同款（plate ÷ IBKColour）。
- E 的"Blur 只在 alpha 上"原则：本模板 Blur8/Blur2 作用在 alpha-only 流上（Primatte/Roto 输出），成立。

**差异 / 补充（官方模板更新的信息）**

1. **edge key 不在 linear 域做**：官方把 edge 支路整体转 `compositing_log` 再进 Keylight，
   出来转回 linear。log 域 Keylight 的 `screenColour` 会是灰白色调（≈0.42/0.55/0.47），
   不要拿 linear 域的绿幕值去填。
2. **edge matte 对比用 Grade blackpoint/whitepoint（0.05/0.66）+ Roto 限区**，
   而不是 Keylight 自带的 clipMin/clipMax/grow/softness（全默认）。E 未提这一手法。
3. **despill 不是 HueCorrect**：官方用两个 Keylight（不同 screenColour/alphaBias/balanceSet）
   出两版 despill，`from` 取 spill→按 ~22-24% `plus` 回补保细节，再 `Keymix` 按 roto 分区混合。
4. **core key 用 Primatte，edge key 用 Keylight，IBKColour 只做 screen clean**——
   与 E"方法 2：IBK Gizmo 抠像"不同，本模板完全没有 IBKGizmo。
5. **色彩管理是 `Nuke` 而非 OCIO**，但局部用 `OCIOColorSpace` 节点做 lin↔log；
   两者可混用，重建时不必改 Root。

## 5. 可直接复刻的 nuke_run 构建代码

重建主干链路（不含 Roto 曲线、Primatte blob、DasGrain/D_QCTool gizmo——这些需手工或装包）。
参数均按上文解析的真实值填写；节点名与模板一致，方便对照。

```python
# nuke_run(code=...) 一次跑完；路径按需替换
CODE = r'''
import nuke

PLATE  = "D:/nuke/Keying tutorial/Keying Mastery Course Files/Soldier_GS_Plate/Soldier_GS_Plate_v5_####.exr"
CLEAN  = "D:/nuke/Keying tutorial/Soldier_GS_Plate/Soldier_GS_Plate_MarkerRemoval_####.exr"
BG     = "C:/path/to/background.jpg"
OUT    = "D:/nuke/Keying tutorial/Soldier_GS_Plate/Soldier_Comp_####.exr"

def n(cls, name, knobs=None, inputs=None):
    node = nuke.createNode(cls, "name %s" % name, inpanel=False)
    node.setName(name)
    for k, v in (knobs or {}).items():
        node[k].setValue(v)
    for i, src in enumerate(inputs or []):
        node.setInput(i, src)
    return node

# --- PLATE / DENOISE ---
read2 = n("Read", "Read2", {"file": PLATE, "first": 140, "last": 250,
                            "origfirst": 140, "origlast": 250, "origset": True})
fr    = n("FrameRange", "FrameRange1", {"first_frame": 140, "last_frame": 250}, [read2])
sh4   = n("Shuffle2", "Shuffle4", inputs=[fr])
dn    = n("Denoise2", "Denoise3", {"analysisFrame": 159}, [sh4])
read3 = n("Read", "Read3", {"file": CLEAN, "first": 140, "last": 250,
                            "origfirst": 140, "origlast": 250, "origset": True})
sw    = n("Switch", "Switch1", {"which": 1}, [dn, read3])   # which=1 -> Read3

# --- SCREEN CLEAN: 4x IBKColour ---
prev = sw
ibk_common = {"Size": 1, "off": [-0.006, -0.009, -0.067],
              "mult": [0.636, 0, 1.03], "erode": 5}
for nm, multi in [("IBKColourV3_3", 1), ("IBKColourV3_4", 10),
                  ("IBKColourV3_5", 30), ("IBKColourV3_7", 60)]:
    knobs = dict(ibk_common)
    if multi != 1:
        knobs["multi"] = multi
    prev = n("IBKColourV3", nm, knobs, [prev])
merge7 = n("Merge2", "Merge7", {"operation": "divide", "bbox": "B"}, [sw, prev])
grade7 = n("Grade", "Grade7",
           {"multiply": [0.1127097905, 0.3580080867, 0.1698716432, 0]}, [merge7])

# --- GARBAGE MATTE（Roto3 曲线需手绘，此处只建处理链） ---
roto3 = n("Roto", "Roto3", {"output": "alpha"})
fe1   = n("FilterErode", "FilterErode1", {"size": 3.6}, [roto3])
fe2   = n("FilterErode", "FilterErode2", {"size": -16}, [fe1])
blur2 = n("Blur", "Blur2", {"size": 20}, [fe2])
m6    = n("Merge2", "Merge6", {"operation": "mask", "bbox": "B"}, [blur2, roto3])

# --- CORE KEY（Primatte 需在 GUI 里 Smart Select，此处占位） ---
prim  = n("Primatte3", "Primatte1", inputs=[grade7])
fe4   = n("FilterErode", "FilterErode4", {"size": 5}, [prim])
blur8 = n("Blur", "Blur8", {"size": 5}, [fe4])

# --- EDGE KEY（log 域 Keylight + Grade 调 alpha） ---
ocio4 = n("OCIOColorSpace", "OCIOColorSpace4",
          {"in_colorspace": "scene_linear", "out_colorspace": "compositing_log"}, [grade7])
kl9   = n("OFXuk.co.thefoundry.keylight.keylight_v201", "Keylight9",
          {"screenColour": [0.4210449457, 0.5483123064, 0.4716479182]}, [ocio4])
ocio5 = n("OCIOColorSpace", "OCIOColorSpace5",
          {"in_colorspace": "compositing_log", "out_colorspace": "scene_linear"}, [kl9])
roto5 = n("Roto", "Roto5", {"output": "alpha"})   # edge 区域 roto，需手绘
g13   = n("Grade", "Grade13", {"channels": "alpha", "blackpoint": 0.05,
                               "whitepoint": 0.66}, [ocio5, roto5])   # input1=mask
m10   = n("Merge2", "Merge10", {"bbox": "B"}, [g13, blur8])           # edge over core
m5    = n("Merge2", "Merge5", {"operation": "in", "bbox": "B"}, [m10, m6])  # 最终 matte

# --- DESPILL 支路 A ---
kl7  = n("OFXuk.co.thefoundry.keylight.keylight_v201", "Keylight7",
         {"screenColour": [0.1148220971, 0.3647842109, 0.1733604372],
          "alphaBias": [0.1689453125, 0.106628418, 0.08178710938]}, [sw])
m4   = n("Merge2", "Merge4", {"operation": "from"}, [kl7, sw])        # KL7 - plate = spill
sh2  = n("Shuffle2", "Shuffle2", inputs=[m4])   # GUI 中设 green->rgb 三通道
g10  = n("Grade", "Grade10", {"white": 0.22}, [sh2])
m11  = n("Merge2", "Merge11", {"operation": "plus", "bbox": "B"}, [g10, sw])

# --- DESPILL 支路 B ---
kl10 = n("OFXuk.co.thefoundry.keylight.keylight_v201", "Keylight10",
         {"screenColour": [0.07171999663, 0.4509890079, 0.1302579939],
          "alphaBias": [1.096874952, 1.170254111, 1.306332111],
          "balanceSet": True}, [sw])
m17  = n("Merge2", "Merge17", {"operation": "from"}, [sw, kl10])      # plate - KL10
sh6  = n("Shuffle2", "Shuffle6", inputs=[m17])
roto8 = n("Roto", "Roto8", {"output": "alpha"})
g6   = n("Grade", "Grade6", {"white": 2.95}, [sh6, roto8])            # mask=Roto8
g5   = n("Grade", "Grade5", {"white": 0.08}, [g6])
m18  = n("Merge2", "Merge18", {"operation": "plus", "bbox": "B"}, [kl10, g5])

# --- Keymix 混合两种 despill ---
roto2 = n("Roto", "Roto2", {"output": "alpha"})
km    = n("Keymix", "Keymix1", inputs=[m18, m11, roto2])              # A, B, mask

# --- GRADING + alpha 合并 ---
g8   = n("Grade", "Grade8", {"white": 1.4,
         "multiply": [1.225052476, 1.24000001, 1.140537262, 1],
         "black": [-0.004375000019, -0.004999999888, -0.004999999888, -0.00800000038]}, [km])
cp1  = n("Copy", "Copy1", {"from0": "rgba.alpha", "to0": "rgba.alpha"}, [g8, m5])
pm   = n("Premult", "Premult3", inputs=[cp1])

# --- ADDITIVE KEYER + 背景 ---
roto7 = n("Roto", "Roto7", {"output": "alpha"})
b4   = n("Blur", "Blur4", {"size": 23.5}, [roto7])
inv  = n("Invert", "Invert2", inputs=[b4])
sat  = n("Saturation", "Saturation1", {"saturation": 0}, [merge7])
g4   = n("Grade", "Grade4", inputs=[sat])
g3   = n("Grade", "Grade3", {"black": 1}, [g4, inv])                  # mask=Invert2
bg   = n("Read", "Read9", {"file": BG})
rf   = n("Reformat", "Reformat6", inputs=[bg])
df   = n("Defocus", "Defocus1", {"defocus": 10}, [rf])
m19  = n("Merge2", "Merge19", {"operation": "multiply", "bbox": "B"}, [df, g3])
m20  = n("Merge2", "Merge20", {"bbox": "B"}, [pm, m19])               # fg over bg

# --- 输出（REGRAIN gizmo 装好后插入在 m20 与 crop 之间） ---
crop = n("Crop", "Crop1", {"crop": False}, [m20])
wr   = n("Write", "Write3", {"file": OUT, "file_type": "exr",
         "ocioColorspace": "scene_linear", "view": "sRGB"}, [crop])
'''
```

注意：`Shuffle2`/`Shuffle6` 的"green→rgb 三通道"映射在 Nuke15 是 `mappings` knob
（字符串表），用 `nuke_run` 时可简化为 `Shuffle`（旧版）设 `red green; blue green`，
或按模板原值写 `mappings "4 rgba.green 0 1 rgba.red 0 0 rgba.green 0 1 rgba.green 0 1 rgba.blue 0 2 rgba.green 0 1 rgba.alpha 0 3"`。

## 易错点

1. **栈式连线方向**：.nk 里 `push $Nxxx` 后进节点的**栈顶 = input0**（A 输入），
   深处才是 input1/mask。解析脚本搞反会把 Keymix 的 A/mask 颠倒——本文已全部按正确方向修正。
2. **Keylight 的节点类名不是 `Keylight`**：保存为 `OFXuk.co.thefoundry.keylight.keylight_v201`。
   用 `create_node("Keylight")` 能建出来（Nuke 别名），但按行数/grep 解析 .nk 时搜 "Keylight {" 会漏。
3. **Switch1 which=1 选的是 input1（Read3）**：直觉以为主链路走 Denoise，实际模板默认走
   MarkerRemoval plate；Denoise 是 0 号备胎 + DasGrain 的 degrained 参考。
4. **log 域 screenColour 不可移植**：Keylight9 的 `{0.421 0.548 0.472}` 是 compositing_log
   域采样值，直接填给 linear 域 Keylight 会抠不出来；换素材必须重新吸色。
5. **Grade 的 mask 是 input1 且要 `inputs 1+1`**：`create_node` / `setInput(1, roto)` 才会出现；
   Grade13/Grade6/Grade3 三处 matte 处理都依赖 roto mask，漏接等于全画面生效。
6. **Primatte 的调参全在 `data` blob**（Smart Select 采样点），无法靠 set_knob 复刻，
   重建后必须在 Viewer 里重新拾取屏幕色；Roto 曲线同理（curves blob 占全文约 60% 行数）。
7. **DasGrain / D_QCTool 是第三方 gizmo**（Nukepedia），模板里带了完整内部节点，
   但未安装时打开会缺类；复刻时用 `nuke.createNode("DasGrain")` 前先确认 gizmo 已装入路径。
8. **`inputs` 行省略 = 类默认值**（过滤器默认 1，源节点显式写 `inputs 0`），
   且存在 `inputs 1+1` 这种表达式写法（=2），写解析器时两种都要处理。
9. **Root 是 `colorManagement Nuke`**：混用 `OCIOColorSpace` 节点做局部 lin↔log 是刻意的，
   不要"顺手"把工程切成 OCIO 管理，否则 ocioColorspace/view 语义会变。
10. **DasGrain mask 输入接的是 `Difference2 gain=999999`**（QC 放大差），看着像误接；
    因 `concealer 0` 实际不影响结果，复刻时 mask 输入留空即可。
