# 真人/图像粒子化（image -> particle dissolve）配方

学自工程 `真人粒子化讲话.hip`（Houdini 基础模块教程文件，2026-08-25 无头解析 +
实证 cook 验证；作者本人笔记 `小案例.md` 同节与此分析互相印证：delete=删中心留
边缘、mask 驱动一切、年龄 Alpha）。单张人像图 -> 带图像颜色的活粒子：人物区域内撒点、继承图片
颜色、靠近轮廓的地方抖动/漂移/发射粒子、拖尾随年龄淡出。全 stock 节点，无自定义 HDA。

**适用**：单图转粒子消散、logo 粒子化、照片溶解、任意"图片驱动粒子"效果。

## 节点链（已实证的完整流程）

```
图 ──> trace1 ──> scatter1 ──> attribtransfer1 ──> maskfromgeometry1 ──> transform1(×5)
       (填充多边形)  (撒满区域)    (从grid取Cd颜色)      (距轮廓距离->mask)      │
       │                                                        pointjitter1(mask驱动)
       ├──> resample1 ─> polypath1 ─> convertline1 ──┐              │
       │    (默认0.1抽稀成粗折线=参考轮廓)            └──输入2──┘     mountain1(动画噪声,mask混合)
       │                                                               │
       └──> grid1(600×600,rx=90) ─> uvtexture1(z) ─> attribfrommap1   ├──────────────┐
            (尺寸匹配图像纵横比)                        (图->Cd)        delete1        │
                                                                            (@mask<=0.1删远点) │
                                                                     trail1(算v,×5.13)      │ 全部点=静态身体
                                                            pointvelocity1(常速度+curl)│
                                                          attribwrangle1(v*=mask) │
                                                              popnet(popsource从点上发射)
                                                                  │
                                                        trail2(长10拖尾) ─> attribblur1(模糊v,32次)
                                                                  │
                                                        attribwrangle2(Alpha=年龄ramp)
                                                                  │
                                              merge1 <─────────────┘ + mountain1(身体)
```

## 关键参数（实测值，按此复刻）

| 环节 | 参数 |
|---|---|
| trace | thresh **0.116**（跟图走，需调）、channel=green、addtexture=on（产出 uv） |
| scatter | npts 36515 |
| attribtransfer | pointattribs=all（Cd 过去）、kernel elendt、kernelradius 10、thresholddist 10 |
| maskfromgeometry | radiusfrom=**maxdist**、ramp: (0→1, 0.072→0.163, 0.179→0) monotonecubic |
| pointjitter | maskattrib=**mask**、scale 0.27 |
| attribnoise(山) | blend by **mask**、amplitude 0.25/0.51、**animated、pulseduration 10**、hmfT/oct8/rough0.4、zcentered |
| delete | filter 表达式 **`@mask<=0.1`**（删远离轮廓的点；干净图形留~19%，细节丰富的人脸图大部分存活） |
| trail(算v) | velscale 5.13 |
| pointvelocity | 常速度 (4.7, 3.8, 0) + curl（scale 1.16、swirl size 10、animated） |
| wrangle | `v@v *= @mask;` |
| popsource | emittype=point、usecontextgeo=**first**（从输入点发射）、constantrate 87221、framepointlimit 25002、life 0.5±1、**jitterbirthtime=negative**（开场即在飞行中，防粒子集体出生条纹）、inheritvel 0.1、inheritattrib=\*（**原工程值，作者自评 POP 不好看--此部分勿学，用下方重设计替代**） |
| trail(拖尾) | length 10 |
| attribblur | 模糊 **v**（默认）、32 次迭代、proximity rad 2.37、42 邻居 |
| wrangle(Alpha) | `@Alpha = chramp('ramp', fit(@age/@life,0,1,0,1));` ramp: 1→0.173@0.435→0 (bspline) |

## 设计精髓（可迁移的模式）

1. **一个 `mask` 属性贯穿全场**：抖动、噪声混合、速度缩放全都吃同一个距轮廓衰减 mask
   --"效果集中在轮廓附近"的观感由一个属性统一驱动，改 ramp 一处生效。
2. **粗轮廓做距离场参考**：resample(0.1) 把稠密 trace 轮廓抽稀 60:1 当参考线，
   距离算得快且平滑（不是 bug 是设计）。
3. **图片颜色两路进粒子**：trace 路=位置（撒点区域），attribfrommap 路=颜色（grid
   采样再 attribtransfer），位置和颜色解耦，换图只改两个 file 参数。
4. **静态身体 + 动态拖尾 merge**：mountain 输出（全部点）直连 merge 当"身体"，
   POP 拖尾单独一路，一层图里同时有"在抖的人"和"在飘的粒子"。
5. **Alpha 用年龄 ramp 在 wrangle 里算**（`fit(@age/@life,...)` + chramp），
   不用材质也能出淡入淡出。

## 坑（实证踩过）

- **外部图片依赖是绝对路径**：原工程指向 Desktop 截图，文件已删 -> 整条链
  cook 全失败但节点不报红（trace 静默空输出级联）。接手旧工程先查
  trace/attribfrommap 的 file 参数是否还在。
- **Distance-from-Geometry 的 remap ramp 横轴按 maxdist 归一化**，不是绝对距离
  （实测 dist=0.055 绝对值时 ramp 位置已是 0.179）。
- **Delete SOP 的 filter 表达式用 `parm.evalAsString()` 读出来是误导值**（把
  `@mask<=0.1` 算成了 "1"）；要读真实表达式用 **`parm.rawValue()`**。
- **Scatter 撒在 trace 的填充多边形上是撒满整个区域**，不是只撒轮廓线。
- 换图后 thresh 需要重调（0.116 是对原图调的）。

## 扩展与重设计（2026-08-25 作者反馈后更新）

作者反馈：①单图版可以扩展成**图像序列/视频播放**；②原工程 POP 链
（popnet/trail2/attribblur）自评**不好看，不学**，以下为替代重设计。

### 视频序列扩展（作者指出的方向 + 架构调整）

**换序列**：trace 与 attribfrommap 的 file 都填序列
`path/seq_$F4.png`（$F4=4 位帧号补零），播放时间线即逐帧取样。

**关键架构改变--固定点阵法**（解决"每帧重撒点会闪烁"）：

单图版用 trace+scatter 没问题（拓扑一次性）；视频每帧轮廓都在变，
scatter 每帧生成新点身份 -> 粒子闪烁。视频版改为：

1. `grid`（分辨率对齐视频、rx=90 + uvtexture 同原工程）--**点阵固定不动**
2. `attribfrommap` 每帧采样当前帧 Cd ->
   `@Alpha = chramp('a', luma(@Cd));`--暗背景透明、人像显形，
   画面本身就是"由粒子构成的视频"；pscale 也可乘 luma（亮处点大）
3. 保留原工程的动画噪声（mountain animated + mask 混合）让点阵"活着"；
   距轮廓 mask 机制可保留（trace 每帧跑代价高，可降采样或隔帧）
4. 消散粒子的出生概率挂在 `mask * animated_noise` 上：画面变化到哪、
   哪里冒消散粒子

### POP 优化重设计（替代原 popnet；属设计稿，未在本机实测）

原版诊断：constantrate 87221 恒量狂喷 + life 0.5s + 常速度 + curl =
"边缘冒烟/火箭感"，与"人物消散"叙事脱节。重设计：

- **birth**：impulse 而非 constant，出生概率 = `@mask * fit01(rand(@id)+noise)`
  --从"正在消散的区域"出生，不是全场均匀喷
- **inheritvel = 1**（完全继承主体点速度）--粒子像"从身上剥离"，
  而非凭空喷出
- **POP drag**：`airresist = fit01(rand(@id*0.123), 0, 0.05);`
  （鸟群笔记同款，消除速度失控的"火箭感"）
- **力**：轻微向上 `POP force (0, ch("up"), 0)`；要顺滑湍流用
  **POP Advect by Volumes** 接低频 curl vdb（比节点内 curl force 平滑，
  风洞笔记同款思路）
- **年龄双衰减**（比 alpha-only 淡出好看）：
  ```c
  @pscale = ch("size") * fit(@age/@life, 0, 1, 1, 0);  // 出生最大、死前缩没
  @Alpha  = chramp('a', fit(@age/@life, 0, 1, 1, 0));
  ```
- **渲染**：点 + motion blur 拉丝（Karma 拉丝粒子 alpha 要改名，坑见
  particle-animation-recipes.md）；想要"丝"感才建几何 trail（原 trail2
  length10 + attribblur 的思路降级为可选项）
- **高光火花层**（可选，增层次）：同一 popnet 用 **stream** 隔离第二类
  粒子：出生率约 5%、life 0.3s、pscale 减半、Cd 提亮

## 无头解析方法（学别的 .hip 时照抄）

`hython` 加载 + 递归 dump（节点类型/连线/非默认参数）+ 定向二次 dump
（关键节点全参数 + `rawValue()`）+ **换测试图实证 cook**（数点数、看属性、采样
坐标）。脚本见本次会话，要点：hip 复制到 ASCII 路径防中文路径问题；
`node.inputs()` 返回节点元组直接遍历；改参数只在内存改、不 save 回写。
