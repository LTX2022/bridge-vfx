# USD / LOP 渲染缓存实战（Fire_shot1/2 血泪经验）

> **⚡ TL;DR 速答卡**（读完能解决就不用往下翻）
> - 渲染链照抄：sopimport(savepath 驱动落盘) → LOP filecache(Save to Disk) → pxr 合并 → loadlayer 指向 fire_merged_full.usd → Karma XPU ROP；VDB(`.usd.volumes/`)必须和 .usd 一起打包
> - sopimport 的 savepath 只是元数据、点了不写文件；真正落盘靠 LOP filecache(savestyle=flattenimplicitlayers) 执行 Save to Disk
> - 多段缓存共用同一 savepath = 760 字节空壳（后段覆盖前段 time samples）；必须每段独立 savepath(fire_usd_N.usd)，再 pxr 合并
> - pxr 合并必须复制 volume_0 的 relationships(field:density/flame/temperature)，只复制 prim+extent 视口/渲染全空
> - 火铁律：火 pass alpha 只能有火。两盏 domelight(domelight+sky_hdri)各加 Render Geometry Settings 关 Camera Visibility，树/地面开 Matte/Holdout——一盏都不能漏
> - 农场前预检：本地渲 1 帧查火层天空区 alpha 必须≈0（均值 0.1~0.3 正常，≥0.5=背景糊进去了）
> - 已渲坏帧首选救法：rgb = combinedemission + combinedvolume（本身就是黑底火/烟），alpha = clamp(luma × gain, 0, 1)
> - 次选减法（需无火同机同灯的 scen pass）：fire = E + T·scen，T = clamp(f_lum/max(s_lum,1e-4),0,1)，s_lum≤0.003 回退 T=1；节点链 Expression→Merge2(multiply)→Merge2(minus)→Expression 写回 alpha=1−T
> - ZibraVDB 渲染必卡死（每帧 GPU 解压），只当存档压缩；渲染改原生 VDB 稳定 ~2min/帧
> - Karma XPU：pathtracedsamples 32 够用（64=双倍成本）、volumequality 1.0、volumesteprate 0.25；1080p 是 4K 的 1/4 成本，先 1080p 验证再上 4K
> - 成功判断：savepath 文件 760 字节=空壳；EXR 空帧几 KB，正常 fire≈28MB / scen≈20MB / heathaze≈4MB(1080p)
> - 多 shot ROP 对齐 5 参数：分辨率 / pathtracedsamples / volumequality / volumesteprate / engine(XPU)
> - Axiom 调参后立即 hou.hipFile.save()，否则重启后参数丢失、工程与记录脱节

> 场景：Pyro 或 Axiom 烟火 → 渲染农场。目标：**不绕弯路**，一步到位。
> 关键教训：sopimport 的 savepath 不会写文件；filecache 分段必须独立 savepath 再 pxr 合并；
> ZibraVDB 渲染慢；合并必须带 relationships；**火 pass 的 alpha 只能有火——HDRI/几何糊进 alpha 就白烧农场费**。

## 1. 渲染链标准架构（照抄即可）

```
/obj/RENDER/Fire (sopimport, savepath 元数据 —— 真正驱动数据落盘!)
        ↓ 落盘靠 LOP filecache 的 Save to Disk
/obj/RENDER/fire_cache_N (LOP filecache, 每段独立 savepath)
        ↓ 保存时产生两个文件：
        │  ├─ file 参数路径 (fire_cache_N/v1/fire_cache_N_v1.usd) = 壳，内部 subLayers 引用 ↓
        │  └─ savepath 路径 (fire_usd_N.usd) = 真实数据 (filePath→VDB)
        ↓
usd/fire_usd_1~9.usd + fire_usd_N.usd.volumes/ (VDB 文件)
        ↓ 合并
usd/fire_merged_full.usd (250帧×3 field, 渲染入口)
        ↓
/obj/RENDER/fire_loaded (loadlayer → fire_merged_full.usd)
        ↓
render_scen / render_fire (Karma XPU ROP)
```

- **渲染入口永远是 loadlayer 指向合并后的单个 .usd**，不是 sopimport、不是 9 段文件。
  ⚠️ 工程中还有 `fire_merged`（sublayer 节点，指向 9 个 fire_cache_N/v1/*.usd 壳文件）--这是**旧路径，未在用**；渲染走 `fire_loaded`->`fire_merged_full.usd`。
- VDB 文件（`.usd.volumes/*.vdb`）被 filePath 引用，**必须和 .usd 一起打包**。
- 一个 `.vdb` 文件内含多 grid（density/flame/temperature 共用），文件名 0.vdb、2.vdb、4.vdb…（每帧一个 .vdb，编号=帧偏移×2，由 Houdini 命名，不要纠结）。
- **落盘机制（实测确认）**：filecache Save to Disk 时，数据写到 **sopimport 的 savepath**（如 `fire_usd_1.usd`），而 filecache 自己的 `file` 参数路径（`fire_cache_N/v1/fire_cache_N_v1.usd`）只写一个**引用壳**（内容仅 `subLayers=[@../../fire_usd_N.usd@]`，几百字节）。所以改 savepath 就改实际输出；壳文件可忽略/不打包。

## 2. 四大坑（都踩过，先看这个）

### 坑 A：sopimport savepath 不写文件
SOP Import 的 `savepath` 只是元数据（方便渲染器解析），**点它不会生成 .usd 文件**。
必须由 **LOP filecache**（savestyle=`flattenimplicitlayers`）执行 Save to Disk 才落盘。

### 坑 B：多段缓存共用同一 savepath → 760 字节空壳
9 个 fire_cache 若都写同一个 savepath（如 `fire.usd`）：数据落盘由 **sopimport 的 savepath** 驱动，
后执行的段会**覆盖**前段的 time samples（sublayer 语义是覆盖重复 prim，不是追加采样）。
结果文件只有几 KB 壳，渲染空。
✅ 正解：**每段独立 savepath**（`fire_usd_N.usd`），再用 pxr 脚本合并。
注意：改的是 **Fire（sopimport）的 savepath** 参数——filecache 节点自己没有 savepath 参数，
它只有 `file`（写壳）+ 遵循输入 sopimport 的 savepath（写数据）。

> ⚠️ **工程实例（SHOT_2）**：`/obj/RENDER/Fire` 和 `/obj/RENDER/Heathaze` 的 savepath
> 都指向 `$HIP\usd\fire.usd`（疑似复制节点时遗留）。若两个 filecache 都 Save to Disk，
> 后写者覆盖先写者。交付前务必核对每个 sopimport 的 savepath 互不冲突。

### 坑 C：合并脚本漏 relationships → 视口/渲染空
只复制 OpenVDBAsset prim 和 extent 不够，`volume_0` 上的
`field:density / field:flame / field:temperature` 是 **relationships**，必须单独复制，
否则 Houdini 视口看不到体积。见下方合并脚本（已含）。

### 坑 D：HDRI/背景糊进 fire pass 的 alpha（烧了 ¥1000 农场费的坑）

> **铁律：火渲染 pass 的 alpha 只能有火/烟，不能有 HDRI 背景和场景几何。**

**症状**：fire pass 的 beauty 里能看到 HDRI 天空和树；alpha 天空区域≈1、全图均值 0.6，
37% 像素半透明——合成 over 任何背景都会把 HDRI 蓝天"印"进去（双重曝光感）。
SHOT_1 和 SHOT_2 的 pass 都中招（**两 shot 都有两盏环境灯，只修一盏没用**）。

**根因（hython 实测）**：
1. 工程里有 **两盏 domelight**（`/obj/RENDER/domelight` + `/obj/RENDER/sky_hdri`），
   都没关相机可见性 → Karma `use_background=Auto`（默认）把环境贴图当背景渲进 RGB，alpha=1。
2. 场景几何（树/地面）没有设 matte/holdout → 几何 alpha 也糊进 pass。
3. 已有 `rendergeometrysettings4/5` 节点正对着树/地面 prim，只是没开 holdout。

**修复（Houdini 侧，重渲前必做）**：
- 两盏 domelight 各加一个 **Render Geometry Settings**，**Camera Visibility 关**
  （rendervisibility 不含 camera）→ HDRI 只照明、不进画面，天空 alpha=0。
  ⚠️ 一盏都不能漏（`domelight` 和 `sky_hdri` 是两盏！LPE 也证实了两个光名）。
- 要"纯火层"：给树/地面 prims 开 **Matte/Holdout**（打在已有 rendergeometrysettings4/5 上即可），
  几何挡火但不留 RGB/alpha。
- Karma rendersettings 的 `use_background` 也可直接关掉背景（二选一，别依赖记默认）。

**农场前 30 秒预检（防再烧钱）**：
1. 本地渲 1 帧 1080p（别整段上农场）。
2. 抽**除背景外的层（火层）**的 alpha 看图：**该层的天空/背景区 alpha 必须≈0**
   （背景层本身的 alpha 不算数，查的是去掉背景后的火/烟层）；
   alpha 均值应接近火的屏幕占比（0.1~0.3），若 ≥0.5 就是背景糊进去了。
3. 顺便确认 EXR 含 `combinedemission`+`combinedvolume` AOV（救赎主要靠这两层）；若只有 `combinedvolume*` 细分层，需组合/分级处理。

**已渲坏帧的 Nuke 救赎**：

1. **优先：AOV 直接组合（不依赖 scen）**  
   如果 fire EXR 有 Karma 体积 AOV，直接拿 `combinedemission`（火焰自发光）+ `combinedvolume`（被照亮的烟雾）相加，即得到**黑底干净火/烟层**。alpha 可由这层亮度推导：`alpha = clamp(luma × gain, 0, 1)`，天空区自然归零，HDRI 不可能进 alpha。  
   这是 SHOT_2 的实际救法：scen 是不透明 beauty，减法救不了，但 fire 自己的 AOV 救回了 250 帧，无需重渲。详见 nuke-bridge 坑 D Option C。

2. **次选：fire − T·scen 减法（仅当 fire/scen 是严格匹配的一对 pass 时才可行）**  

前提（缺一不可，否则必须重渲）：
- 有同帧的 `render_scen` pass，**无火、同相机同灯光、同分辨率**。
- `scen` 不能是不透明 beauty（alpha≈1 全帧）。如果 scen 是 opaque beauty，或
  fire/scen 的曝光/灯光/几何不一致，减法会把树、岩石、地面也抠成残影。
- 先抽一帧对比背景区：`fire.rgb` 必须和 `scen.rgb` 在天空/无火区基本一致。

满足前提时，模型：`fire = E + T·scen`（E=火焰自发光，T=烟透射率），解出干净预乘火层
**(E, alpha=1−T)**。正确 Nuke 节点链（注意 T 是**亮度比**，不是每通道除法）：

```
Read(fire) + Read(scen) [同分辨率]
  Expression      T = clamp(f_lum/max(s_lum,1e-4), 0, 1), s_lum<=0.003 回退 1
  Merge2(multiply) scen × T          → T·scen
  Merge2(minus)   fire − T·scen      → E
  Expression      E = max(E,0), alpha = 1 − T   # 写回 A
最终：Merge2(over)  E层 over 你的背景板
```

其中 `f_lum=(r+g+b)/3`（fire），`s_lum=(r1+g1+b1)/3`（scen）。

- 旧写法 `T = clamp((r+g+b)/3,0,1)` 作用在 `fire/scen` 上是**错的**，会反转亮火。
- scen pass 极暗区域（夜空 <0.003）比率不稳，必须给分母加 epsilon 并回退 T=1。
- 若最终背景**就是** scen pass 且不调色：fire beauty 本身已是成品，直接用、不用叠。
- 只减掉 `combinedvolume_domelight`/`combinedvolume_sky_hdri` 只能去掉 HDRI 对烟的
  照明（本例占 16%），**去不掉背景天空像素**；真正的 AOV 救赎是用
  `combinedemission + combinedvolume`（这两层本身就是黑底火/烟，无背景）。
- 脚本版（批量 250 帧）：`fire_scen_subtract_salvage.py` 在 houdini-bridge/scripts/。
  先在单帧上跑，确认天空区 alpha≈0、无场景残影，再上批量。

## 3. 可复用脚本（skill scripts/ 目录）

| 脚本 | 用途 |
|---|---|
| `usd_segmented_cache.py` | 9 段重烘焙：每段独立 savepath + 帧范围 + Save to Disk |
| `usd_merge_segments.py` | pxr 合并 9 段 → 单文件（含 relationships、全部 time samples） |
| `usd_verify_merged.py` | 校验：帧覆盖无缺口 / filePath 引用全部存在 / 3 field 齐全 |
| `fire_scen_subtract_salvage.py` | 坑 D 救赎：fire−T·scen 批量生成干净火层 EXR（需 `pip install OpenEXR numpy`） |

用法（Houdini Python Shell 或 hython）：
```python
exec(open(r"C:/Users/<USERNAME>/.zcode/skills/houdini-bridge/scripts/usd_segmented_cache.py").read())
```
合并脚本是独立 hython 跑的（不占用户会话）：
```powershell
& "C:\Program Files\Side Effects Software\Houdini 21.0.631\bin\hython.exe" "C:\Users\<USERNAME>\.zcode\skills\houdini-bridge\scripts\usd_merge_segments.py" "C:\path\SHOT_1\usd"
```

> ⚠️ **务必显式传 usd 目录路径**。不传参数时脚本回退到 `HIP/usd`，而独立 hython 的
> HIP 通常是启动目录而非项目目录——脚本会打印警告并在 `fire_usd_1.usd` 不存在时报错退出。
> 缺段时会逐段警告并在结尾汇总（旧版静默跳过，合并文件缺帧很难发现）。

合并要点（pxr）：
- 复制 volume_0 的**静态属性**（跳过 timeSamples）+
- **relationships**（`rel.GetTargets()` → `CreateRelationship().AddTarget()`）
- 每段每个 field：`dst_attr.Set(src_attr.Get(t), t)` 收集全部 time samples
- 3 个 field（density/flame/temperature）各 250 帧 = 750 条 filePath 引用、250 个唯一文件

## 4. 校验合并文件（渲染前必查，30 秒）

```powershell
usdcat.exe usd\fire_merged_full.usd > dump.txt   # bin 在 Houdini bin 目录
```
用 python 检查（见 `usd_verify_merged.py`）：
- 每个 field 帧数 = 期望（1001~1250 无缺口）
- `filePath.timeSamples` 引用的 `./fire_usd_N.usd.volumes/X.vdb` **全部存在**
- `field:density/flame/temperature` relationships 在

快速手查：
```
grep -c "filePath" dump.txt        # 应 = 3（每 field 一块）
grep "OpenVDBAsset" dump.txt       # 应 3 个 prim
```

## 5. 渲染农场交付包清单

```
SHOT_N/
├── usd/
│   ├── fire_merged_full.usd        ← 渲染入口（唯一必需，250帧×3 field）
│   └── fire_usd_1~9.usd.volumes/   ← 250 个 VDB（被引用，必须一起打包）
├── render/
│   ├── render_fire/   250 EXR
│   ├── render_scen/   250 EXR
│   └── render_heathaze/  (SHOT_1 旧渲染 360 帧到 1360，帧范围可超；SHOT_2 为 250 帧)
├── *.hip
└── (可选存档) ZibraVDB 压缩包 2.7GB
```

## 5.5 两 shot 渲染配置对照（实测，勿混用）

| | SHOT_1 (Pyro) | SHOT_2 (Axiom) |
|---|---|---|
| render_scen | 1080p / 32s | **4K** / 24s |
| render_fire | 1080p / 64s | 1080p / 64s（res_mode=autoheight） |
| render_heathaze | 1080p / 32s | 1080p / 32s（res_mode=autoheight） |
| 渲染帧范围 | 1001-1250（heathaze 实出 360 帧到 1360） | **1001-1250**（三 pass 均 250 帧） |
| Axiom startFrame | N/A | **950**（仿真起始帧，非渲染帧范围） |
| 输出路径 | C盘（`$HIP/render/`） | ROP picture 表达式 `D:/render/$OS/`，但实际 EXR 在 SHOT_2/render/（D 盘不存在，可能已移回） |
| cache 机制 | fire_cache_1~9 分段 + pxr 合并 | fire_cache 单个 |
| fire_loaded/merged | 有 | **无** |

**教训**：写 skill/文档时不能拿一个 shot 的参数当通用，必须逐 shot 核查。

## 6. 渲染速度 / 农场成本控制

- **ZibraVDB 慢**：渲染链走 zibravdb 节点时每帧 GPU 解压，慢到 1% 都不出；
  ✅ 改用原生 VDB（fire_loaded 直接读 .vdb）稳定 ~2min/帧。
- ZibraVDB 只当**存档/传输压缩**用，不当渲染源。本例 SHOT_1 有两份 zibravdb 缓存（vol3=7GB 全序列、vol4=2.7GB），保留一份即可。
- Karma XPU 关键参数：
  - `pathtracedsamples`：32 够用（64 是 double 成本）。**工程实际**：scen/heathaze=32，但两 shot 的 render_fire 都用了 64（追求火质量）
  - `volumequality` 1.0、`volumesteprate` 0.25
  - `res_mode=manual` + 分辨率：**1080p 是 4K 的 1/4 成本**；先 1080p 确认效果再决定 4K
- 渲染完成后检查（`usd_verify_merged.py` 模式 B）：
  - 每 pass 帧数一致（SHOT_1: fire/scen 250 vs heathaze 360 → 合成截短，别重渲染浪费钱；SHOT_2: 三 pass 均 250 帧）
  - EXR 非空：fire 约 28MB/帧、scen 约 20MB/帧、heathaze 约 4MB/帧（1080p），空帧只有几 KB
  - 分辨率确认：EXR header 解析 dataWindow（multipart 格式标志 0x1000 时先跳过 8 字节 offset 表）

### ROP 对齐检查（多 shot 一致）

对比各 shot 的 ROP（如 rop1 vs rop2）5 项参数必须一致：
**分辨率 / pathtracedsamples / volumequality / volumesteprate / engine(XPU)**。
`hython` 离线快速查（不占用户会话，比开 Houdini 快）：

```
"C:\Program Files\Side Effects Software\Houdini 21.0.631\bin\hython.exe" -c "
import hou; hou.hipFile.load(r'C:\path\shot.hip')
for p in ['/obj/RENDER/render_scen','/obj/RENDER/render_fire']:
    n = hou.node(p)
    print(p, n.parm('resolutionx').eval(), 'x', n.parm('resolutiony').eval(),
          '| samples:', n.parm('pathtracedsamples').eval())
"
```

**4K vs 1080p 决策**：先 1080p 渲染确认画面 OK → 决定是否重渲染 4K（费用 ×4）。
改分辨率：ROP 上 `res_mode=manual` + `resolutionx/resolutiony`。

## 7. filecache 路径表达式（防"文件不存在"渲染空）

sim_fire / sim_heathaze 的 filecache 节点用表达式而不是写死路径：
- `file` 参数 = `chs("sopoutput")`（引用 sopoutput 的值）
- `sopoutput` = 根据 `filemethod` 自动构造路径（`chs('file')` 或 `cachedir/cachename`）

否则磁盘路径对不上 -> 渲染器找不到缓存 -> 输出空/黑。

> ⚠️ **工程实例（SHOT_1）**：`fire_cache_2` 的 `file` 被手动改成了绝对路径
> `C:/.../SHOT_1/usd/fire_cache_2.usd`，其余 8 段都是 `chs("lopoutput")`。
> 不影响分段缓存（改的是 sopimport savepath，不是 filecache file），
> 但交付/迁移工程时应统一回表达式，避免换机器后路径失效。

## 8. Axiom vs Pyro 对齐速查（Fire_shot2）

> ⚠️ **已验证 vs 对话记录**：下表"已验证"= 工程 hip 里查到的真实值；
> "对话记录"= 当时对话中讨论/执行的值，**但 SHOT_2 的 .002 hip 保存于 8月8日，
> 后续修复未再次保存，工程文件中查不到这些值**。改完参数务必保存 hip！

| 症状 | 修法 | 状态 |
|---|---|---|
| 碰撞烟"方块感/被阻断" | collision_sdf `voxelsize→0.03` | ✅ 已验证（工程=0.03） |
| 同上 | leafSize `32→16` | ✅ 已验证（v7 等=16） |
| 同上 | divisionSize `0.01→0.02` | ✅ 已验证（V3_v9=0.02；v7=0.03） |
| 同上 | emitPressure `1→0.5` | ⚠️ 仅对话记录，工程无此值（各版均=1.0） |
| 同上 | emitDensity `4→2` | ⚠️ 仅对话记录（工程 v7=0.0、v4=4.0） |
| 同上 | marginIterations `1→2` | ⚠️ 仅对话记录（工程各版均=1） |
| `No suitable device found (solverCore)` | CUDA 不可用（改参数用 CPU/换机器），不是节点坏了 | ✅ |
| `density` 的 diffusion | 扩散系数，控制密度向周围扩散速度 | ✅ |
| dissipation | 消散，密度随时间消失 | ✅ |

**工程真实值参考**（SHOT_2 .002 hip，axiom_solver 有 v1~v10 十个版本，都是旁路实验节点，主链是 pyrobakevolume1）：
- `axiom_solver_v7`：divisionSize=0.03、leafSize=16、emitDensity=0.0、emitPressure=1.0、marginIterations=1、voxelLimitBehavior=1（Auto Increase，**非** Maintain）、timeScale=2.0、subSteps=3、buoyancy=0.27、wind=1.99、densityDissipation=0.25、sourceFieldDensityScale=1.0、sourceFieldTemperatureScale=1.6、sourceFieldFuelScale=1.3、fuelBurn=1.0、simulationFuel=0、disturbance1BlockSize=0.108、enableDisturbance2=1、enableTurbulence2=1、enableDisturbance3=0、enableTurbulence3=0、voxels=48000000、startFrame=950
- `axiom_solver_V3_v9`：divisionSize=0.02、leafSize=16、emitDensity=0.0、emitPressure=1.0、timeScale=1.5、subSteps=3、densityDissipation=0.2、sourceFieldDensityScale=1.0、sourceFieldTemperatureScale=1.6、sourceFieldFuelScale=1.3、fuelBurn=1.0、simulationFuel=1、disturbance1BlockSize=0.08、enableDisturbance2=1、enableTurbulence2=1、enableTurbulence3=1、enableDisturbance3=1、marginIterations=1、voxelLimitBehavior=1、voxels=48000000、startFrame=950（最接近"最终"，但参数与 set_axiom1_parms.py 差异很大）
- `collision_sdf`（vdbfrompolygons）：voxelsize=**0.03**
- `axiom_solver1`（set_axiom1_parms.py 目标节点）：**工程中不存在此节点**（hip 里只有 v1~v10）
- 旧脚本 `SHOT_2/set_axiom1_parms.py`（8月4日，目标 axiom_solver1）：emitDensity=0、divisionSize=0.02、leafSize=32、collision voxelsize=0.1、voxelLimitBehavior=0(Maintain)、Device Only
- `axiom_solver_V3_v10`：divisionSize=**0.3**（极端低分辨率实验节点，leafSize=16、voxelLimitBehavior=1）。
  翻 hip 看到 0.3 不要困惑，它不是调参参考值；参考值只看 v7 / V3_v9。

**经验**：Axiom 调参后**立即保存 hip**（`hou.hipFile.save()`），否则重启/交付后参数丢失，工程与记录脱节。

## 9. 缓存/渲染结果判断（省得反复确认"成功了吗"）

| 问"成功了吗" | 怎么查 |
|---|---|
| filecache 缓存好了没 | 看 `savepath` 文件大小：**760 字节=空壳(坑B)**，正常几 KB~几十 KB 且旁边有 `.volumes/` 目录(含 VDB) |
| 合并文件完整吗 | `usd_verify_merged.py`：250 帧×3 field 无缺口 + filePath 全存在 |
| 渲染出的是不是空 | EXR 大小：空帧几 KB，正常 fire≈28MB / scen≈20MB / heathaze≈4MB（1080p） |
| 农场跑的是哪版 hip | 对比 EXR 的 mtime 和 hip 的 mtime：EXR 早于 hip 保存=用了旧设置 |

## 10. 调试技巧

- **hython 读 hip 不需要 GUI**：`hython.exe -c "import hou; hou.hipFile.load(r'...hip'); print(...)"`
  可离线查 ROP 参数（分辨率/samples/帧范围），比开 Houdini 快。见第 6 节完整命令。
- **usdcat 转文本**：检查合并文件结构、引用、time samples。
  `"C:\Program Files\Side Effects Software\Houdini 21.0.631\bin\usdcat.exe" file.usd > dump.txt`
- **EXR header 直接读二进制**：magic `76 2f 31 01` → version → 属性表 → dataWindow 得分辨率。
- 帧范围用 `seq 1001 1250 | grep -vxF -f <(ls ...)` 查缺帧。
- 时间戳判断"这轮渲染用了哪版 hip"：EXR mtime vs hip mtime。

## 11. 一句话记忆

> sopimport 的 savepath 驱动落盘（filecache file 只写壳）；pxr 合并带 relationships + stage metadata；
> 渲染入口 loadlayer→单 usd；VDB 文件随包走；ZibraVDB 只存档不渲染；
> **火 pass alpha 只留火：两盏 domelight 关相机可见性 + 几何 matte，农场前先渲 1 帧查除背景外层的 alpha**；
> 1080p 先验证再上 4K；ROP 多 shot 对齐 5 参数；渲染完先查帧数/分辨率/非空。
