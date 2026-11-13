# 跟踪与稳定（学自用户笔记 Nuke.md, 2026-08-25）

> **⚡ TL;DR 速答卡**（读完能解决就不用往下翻）
> - Tracker 节点不要留在工程里（会持续计算拖慢预览）：导出带跟踪数据的 Transform 后禁用或删除
> - Roto 跟随跟踪点：右键 Roto → Link to → 选 Tracker 跟踪点 → Translate as offset
> - 平面跟踪：画 roto → 右键遮罩 → planar-track... → 导出边角定位；合格标准 = 跟踪面始终锁定在同一位置
> - 平面跟踪合成的 CornerPin 放置：交叉放到素材下方 + 取消勾选 invert（与 roto 导出的 CornerPin 顺序相反）
> - 手机单点跟踪：禁用 CornerPin 把 4 点摆到素材四角 → From 界面点 Copy 'to' → 启用 → 再复制一份到下方（第二个防偏移）→ 跟踪点右键 copy → copy Animation → 目标点最右按钮 Paste Absolute 粘贴
> - CameraTracker（仅 NukeX，Indie 不可用）流程：遮罩后 Mask 选 Mask Alpha（Inverted = 只用遮罩内）→ Track → Solve → AutoTracks 里 Delete Unsolved / Delete Rejected（调 Min Length / Max Track Error / Max Error）→ 勾 Focal Length + Position + Rotation → Refine Solve → extract user track 锁好点 → 框选地面点 set to selected → Export Scene+
> - Refine Solve 后绝不要再点 Solve / Update Solve——会让结果更糟
> - Delete Rejected 前先 extract user track 锁定确认正确的点，防止被参数误删
> - 相机稳定法：复制 Camera 只留首末帧关键帧 → 原相机接 Project3D 投到 Card（Card 要够大否则黑边）→ ScanlineRender 接稳定相机 → Transform 缩放消除黑边
> - Project3D 必须配 FrameHold 固定相机某一帧，否则图像随相机滑动、等于没跟踪
> - 稳定的代价：画面整体软 2-4 像素；优化 = 手动删掉相机曲线上不平滑的关键帧
> - nuke-bridge 关键调用：ct["mask"].setValue("Mask Alpha") → ct["track"].execute() → ct["solve"].execute() → ct["refine"].execute()（先 focal / position / rotation 置 True）
> - Scene 节点出口：白色端连 Scene 节点，不是素材

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Nuke.md` "跟踪" / "CameraTracker" 节。
原始笔记保持只读；本文件是 2D / 3D 跟踪与画面稳定的蒸馏版。

## 0. 总原则

- **Roto 负责平面跟踪**
- **`Tracker` 节点不要留在工程里**——会一直算跟踪，连预览都卡
  - 导出带跟踪数据等的 `Transform` 后禁用掉或者删掉
- 习惯用法：先画 roto，再加跟踪，再 Bake
- 工程内多用 `Bake tracker` 信息

## 1. tracker 节点（基础单点/多点跟踪）

### 让 Roto 跟随 Tracker 节点

1. 使用 `Tracker` 节点跟踪出轨迹
2. 使用 `Roto` 节点画出需要抠出来的区域
3. 右键 Roto 节点 → `Link to` → 选择 `Tracker1` 跟踪点 → `Translate as offset`
   - 这样 roto 节点就可以跟随跟踪节点的轨迹进行跟踪
   - 也可以任意摆放 roto 节点画的遮罩的位置

### 单点跟踪亮度变化场景

> Tracker 节点跟踪（跟踪前去 `Settings` 界面勾选 `adjust for luminance changes`，
> 启用后 Tracker 会进行一些额外的预过滤来补偿亮度的变化）

## 2. 多点平面跟踪技术（跟踪叠加，手机跟踪等）

**适用场景**：手机屏幕、招牌、贴图替换等只有一个可跟踪的平面

**注意**：Nuke 平面跟踪有 `Roto` 节点内置版本（`planar-track`）和独立
`Tracker` 节点两个工具。

### 正常平面跟踪流程（用户多步法）

1. （**跟踪位置**）让 `Roto 1` 节点做平面跟踪
   - 画一个 roto → 右键遮罩 → `planar-track...`
   - 导出为边角定位 → 反选 → 查看跟踪效果
   - **检查标准**：跟踪的面一直锁定在一个位置 = 准确
2. （**纠正数据**）如果发现有一个角有点点飘动
   - 那个位置附近是否有适合跟踪的地方
   - 用新的 `Roto 2` 节点做一次 `planar-track...` 再导出
   - 重复上面步骤
3. （**放置素材**）完成跟踪后
   - 把 `CornerPin` 节点**交叉**放到素材下方
   - 取消勾选 `invert`
   - 合并即可完成跟踪
   - **注意**：和 `roto` 跟踪导出的 `CornerPin` 放置顺序倒过来放置

### 单点跟踪（手机类型）特殊流程

只有一个点而没有一个平面适合跟踪的情况：

1. （**跟踪**）先画好 roto 做一下平面跟踪
   - 有一个角在抽动的话，使用 `Tracker` 节点跟踪
   - 去 `Settings` 界面勾选 `adjust for luminance changes`
2. （**设置边角定位初始位置**）跟踪好后
   - 手动放置一个 `CornerPin` 节点
   - **禁用**它后，把四个点放置在素材四个角落
   - 来到 `From` 界面，点击 `Copy 'to'` 按钮
   - 就可以将设置的四个点作为边角定位四个点初始来源的位置
   - 这时再启用该节点
   - 复制一次该节点到下方（**第二个边角定位是防止偏移矫正**）
3. （**放置跟踪点到正确位置**）
   - 右键跟踪好的跟踪点 → `copy` → `copy Animation`
   - 来到跟踪点对应的边角定位的点上
   - 点击该点最右边的按钮 → `Paste` → `Paste Absolute`
   - 即可将该点跟踪数据粘贴到对应的边角定位的点上
   - 通过第一个边角定位来矫正该点产生的位置偏移

> 第二个边角定位是防止将 Tracker 点的跟踪信息复制到边角定位上一个点时
> 发生偏移，还可以通过第一个边角定位负责放置准确位置来矫正偏移

## 3. CameraTracker 摄像机反求（仅 NukeX）

> `CameraTracker` 只有 NukeX 版本才可以使用

### 用户 6 步法

1. **第一步：画遮罩挡住不要跟踪的移动物体**
   - 用 `Roto` 或 `RotoPaint`
   - `bj` 连接线要链接素材以匹配画幅大小（如果工程设置的大小和素材一样则不用改）
   - 画好遮罩后，`CameraTrack` 节点 `Mask` 参数选 `Mask Alpha`（遮罩外跟踪）
   - 选 `Mask Inverted Alpha` = 只用遮罩内区域跟踪

2. **第二步：解算 + 手动删除跟踪不好的点**
   - 在 `CameraTracker` 选项卡中点 `Track`
   - 跟踪完后直接点 `Solve`
   - 手动删除跟踪不好的点

3. **第三步：优化跟踪结果（关键）**
   - 来到 `AutoTracks` 选项卡
   - `Delete Unsolved`（删除未使用的跟踪点）
   - `Delete Rejected`（删除不合适的跟踪点）
   - 通过调节 3 个参数再删除跟踪不好的点效果会更好：
     - `Min Length`（跟踪点最小长度要达到多少帧）
     - `Max Track Error`（最大跟踪误差）
     - `Max Error`（最大误差）
   - 勾选 `Focal Length`（焦距）`Position`（位置）`Rotation`（旋转）3 个选项
   - 点击 `Refine Solve` 解算 → 优化跟踪结果

   > **做完这些不需要再回到 `CameraTracker` 选项卡中勾选 `Update Solve`
   > 或者 `Solve` 来优化结果，会使得跟踪结果可能更糟糕**
   > 当扩展了帧范围或者使用 `Setting` 选项卡的一些参数细化结果时，
   > 尝试优化相机轨迹时可以使用 `Update Solve` 更新轨迹。

4. **第四步：锁定认为正确的点（重要）**
   - 使用右键：`trqxks → extract user track`
   - 可以强制将认为正确的点锁定住
   - 这样在调节 `AutoTracks` 选项卡中的参数时不会再误删掉这些点

5. **第五步：设置地面**
   - 框选在地面上的点（越多越好）
   - 右键 → `ground plane` → `set to selected`
   - 觉得有误差，再在 `Scene` 选项卡中调节正确的方向

6. **第六步：导出 Scene**
   - 使用 Export 导出 `Scene+`（用于 ModelBuilder）
   - 或直接用 `PointCloudGenerator` 节点

### 提高精度的方法（实战总结）

- 跟踪时在 `CameraTracker` 选项卡中点 `Track`，等跟踪完后直接点 `Solve`
- 手动删除跟踪不好的点
- 通过调节 `Min Length` / `Max Track Error` / `Max Error` 删除跟踪不好的点
- 勾选 `Focal Length` / `Position` / `Rotation` 3 个选项后点 `Refine Solve`

## 4. 利用相机反求稳定画面

1. 反求画面得到相机运动轨迹
2. 复制 `Camera` 节点，第二个 `Camera` 用来做稳定画面的相机
   - 保留第一帧和最后一帧关键帧
   - 替代原相机
   - 接入 `ScanlineRender` 节点的相机接口
3. 用 `Project3D` 节点，使用原动画的相机
   - 将原来视频图像投射到 `Card` 中
   - `Card` 节点要保证在第一个相机运动时，画面能全部投影到上面，否则会出现黑边
4. 用 `Transform` 节点缩放稳定好的视频（因为做稳定后会因为画面移动产生黑边）

## 5. 案例技巧：Project3D + FrameHold

> `Project3D` 节点的作用是将 2D 的图像通过摄影机的视角，投射到 3D 对象上，
> 而 `FrameHold` 的作用是固定住相机所在的任意一帧

**原理**：

- 不然相机和图像会同时移动，这样就会导致画面会一直在"画布"上的同一个位置
  就像没有跟踪效果一样
- 此时是认为相机是运动的，而手机是静止的
- 世界坐标中心就是手机的位置，投射上去固定的位置也就是手机目前所在的位置
- 如果没有 `FrameHold`，图像的位置就会随着摄像机的移动而在画布上到处移动，
  从而不会固定在手机的位置上

## 6. 稳定 vs 不稳定的权衡

**优势**（稳定）：

- 焦距不变，模型位置不变，正确的空间关系不变
- 相对平滑的相机曲线，为上游 CG 其他环节提供优质的制作环境
  （动画、特效、灯光）
- CG 渲染得到正确的运动模糊

**劣势**（稳定）：

- 破坏了原始画面的像素
- 整体画面会比稳定前虚 2-4 个像素

**手动优化相机曲线方法**：

- 修改相机曲线使用插件或者手动平滑
- 目的是得到顺滑的相机路径
- 操作：将一些不平滑的关键帧删除，即可得到一个稳定的画面（相机都是跟踪好了的）

## 7. nuke-bridge 自动化 CameraTracker 的最小工作流

```python
# nuke_run 中 nuke 已被注入
import nuke
# 1. 读素材
r = nuke.createNode("Read", inpanel=False)
r["file"].setValue("C:/footage/shot.%04d.exr")
r["first"].setValue(1001); r["last"].setValue(1250)

# 2. 画遮罩（roto 需要 GUI，用 nuke_run 也可以但要传 2D 点）
roto = nuke.createNode("Roto", inpanel=False)
roto.setInput(0, r)

# 3. CameraTracker
ct = nuke.createNode("CameraTracker", inpanel=False)
ct.setInput(0, roto)
ct["mask"].setValue("Mask Alpha")          # 关键：只在遮罩外跟踪
# 跟踪
ct["track"].execute()                       # nuke 14+ 改成 nuke.execute(ct) 也行
# 解算
ct["solve"].execute()
# 优化（建议手工在 GUI 调节 3 个参数 + Refine Solve）
# 自动版
ct["focal"].setValue(True)
ct["position"].setValue(True)
ct["rotation"].setValue(True)
ct["refine"].execute()
# 导出 scene（生成 Scene+ 节点）
scene = nuke.createNode("Scene", inpanel=False)
scene.setInput(0, ct)
```

## 8. 易错点

- **`Mask Alpha` 方向**：填了 Mask 后想换方向 → 选 `Mask Inverted Alpha`
- **`Refine Solve` 后不要回到主 solve 按钮再解**——会破坏前面 refine 的成果
- **手机类跟踪**：3D 平面跟踪不稳时用单点 tracker + 2 个 CornerPin
- **设置地面后**：`Scene` 选项卡的方向一定要检查
- **Delete Rejected 之前**：先 `extract user track` 锁定已知好点
- **`CameraTracker` 必须 NukeX**：Indie 不可用
- **`Scene` 节点出口**：白色端连 `Scene` 节点（不是素材）
