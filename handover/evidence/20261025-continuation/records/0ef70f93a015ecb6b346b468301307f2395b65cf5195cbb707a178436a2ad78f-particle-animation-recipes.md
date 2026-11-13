# 粒子动画配方集（学自用户笔记 小案例.md，2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\Houdini基础模块\小案例.md`（含截图的
完整原文在那，本文件是蒸馏版）。鸟群模板工程：
`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\一些能当成套模板使用的工程文件\Houdini\`
（bird_murmurations.v3.hip、TPOSEblendANI.hip）。

## 配方一：variant 播放动画（在点上播放逐帧动画）★核心模式

**问题**：大量粒子上各自播放一段帧动画（弹窗生长、翅膀扇动），每颗相位/大小不同。
**思路**：把动画的每一帧拆成独立 `variant` 值的 piece，粒子按 age/帧号映射到
variant，`copytopoints` 勾 **Piece Attribute** 按 variant 匹配复制。

1. **拆帧**（For-Each Number 循环，迭代数=动画总帧数）：
   - `foreach_begin`：Method=**Fetch Input**；`foreach_end`：Iteration Method=**By
     Count**、Gather Method=**Merge Each Iteration**；`foreach_count`：Fetch Metadata
     （产出 `iteration`/`numiterations`/`value`/`ivalue` 循环属性）
   - 循环内 `timeshift` 冻结当前帧 + `attribcreate` 把帧号写进 `variant`
   - 取循环值的表达式：`101+detail(-1,"iteration",0)`（-1 指向 Spare Input0，
     需在参数里把含循环值的节点拖成 Spare Input）或 `detail("../foreach_count1","iteration",0)`
   - `filecache` 缓存整段
2. **映射**（wrangle，粒子侧）：
   ```c
   float a = @age;
   if (a >= 1) { a = 28; }     // 钳到最后一帧
   else { a *= 30; abs(a); }
   if (a == 29) { a = 28; }
   i@variant = (int)a;          // 强转 int，帧号离散化
   ```
   （动画侧同款：`if(a>=28){a=28;} i@variant=(int)a;`）
3. **复制**：`copytopoints` 勾 **Piece Attribute** = variant，源与目标 variant 相同即复制。
4. **自检**：`check` wrangle 验证每帧都有内容：
   `if(@variant != chi("number")){ removepoint(0,@ptnum); }`

**配套技巧**：
- 抽稀发射点：`if(@id % chi("int") != 0){ removepoint(0,@ptnum); }`（滑块控每隔N个留一个）
- 边长边转（四元数朝向）：
  ```c
  float angle = rand(@ptnum) * chi("int") * $PI;
  float speed = chf("speed");
  vector euler = set(0, angle, 0);
  float a = speed * @Frame;
  @orient = quaternion(a, euler);
  ```
- VOP 版 variant（鸟群随机相位）：`variant = (rand(ptnum+偏移) fit 到 0..总帧数
  floor) + @Frame` 再 `% 总帧数`（modulo 节点）再 floattoint；`pscale = fit(rand(ptnum+1121),0,1,2,0.5)`
  再乘一个 Constant 做全局缩放。

## 配方二：carve + wrap 沿轨迹移动

两个 `grid` 异位放置 + `scatter` 同点数（种子不同）-> wrangle `@id=@ptnum` 配对
-> `add`（按 id 连线）-> `resample`（勾 **Curve U Attribute** 产出 `curveu` 0-1
参数）-> wrangle 用 `chramp` 控制连线中段弧度 -> `group` 选一组当快线 ->
`carve`（Divisions=Extract、Extract Type=Extract Point(s)）：
- 快组 `First U = wrap($F/24, 0, 1)`，慢组（`!group`）`First U = wrap($F/48, 0, 1)`
-> `trail` 加拖尾让更多点沿路径走 -> `sort`（Random 打乱编号）-> `blast` 删部分点
-> `copytopoints` 换成圆/模型。

`wrap(x, min, max)`：周期函数，超出上限回到 min 重新计（等效取余），用于周期运动。

## 配方三：鸟群远景（两法）

**方法一 VEX 点云**（无解算，超轻）：
```c
vector normal = chv("normal_axis");   // 朝向轴
v@WV = chv("wobble_axis");            // 摆动轴
@WA = ch("wobble_amount");  @WF = ch("wobble_freq");
@N = normal;
@N.x += @WA * (@WV.x * sin((@Time * @WF) + @ptnum));
@N.y += @WA * (@WV.y * sin((@Time * @WF) + @ptnum));
@N.z += @WA * (@WV.z * sin((@Time * @WF) + @ptnum));
@a = fit01(rand(@ptnum), ch("slowest"), ch("fastest"));  // 个体速度差
@c = @a * ch("speed_rate");
@P.x = @c * @Frame;
```
- 临时属性（a/b/c/WA/WF/WV）算完用 **Attribute Delete** 清掉省计算。
- **动画转移到任意模型**（通用技巧）：带动画模型 `retime`（Speed 调速）+
  `timeshift` 循环拍帧（翅膀 8 帧一段：`$F-8`、`$F-16` 关键帧循环加密扇翅频率）
  + `convert` 转多边形 -> `point deform` 把动画姿势包到目标静模上（冻结一帧
  姿势去匹配目标姿态）-> 多材质部位用 `delete`+`pack` 分组封装再 merge（**pack
  时保留 uv 和组**，极大减体积）-> 配方一拆 variant。

**方法二 POP murmuration**（群集感）：
- `POP Source`：Source=**All Points**（第一输入端全部点当发射器）、Birth
  `$FF==1`（只第一帧出生）、Attribute 里 Set initial velocity 增加混乱
- `POP vop`×2：先去掉 Y 轴（vector->float 拆 xyz 只接 x/z 再转回），再加
  `P + force` 且 force 用 `curl noise` 搅乱（否则只会向外扩散不乱）
- `POP attract(follow)`：Goal=**Points**（第二输入端的点引导）、Force Method=
  **Follow**（Force Scale 牵引强度 / Min Distance 内减速停 / Max Distance 外无力 /
  Ambient、Speed Scale）
- `POP attract2`：Goal=**Particles** + Number of Clusters=2~3（K-Means 聚簇，
  让粒子分团追逐而非聚成一点）
- `POP interact`：粒子互斥防穿插（Position Force 推开 / Velocity Force 速度对齐 /
  Core Radius 全强度内圈 / Falloff Radius 衰减到零）
- `POP drag`：`airresist = fit01(rand(@id*0.123),0,0.05);` 每颗阻力不同
- `POP lookat`：`mode=1; target=@v;`（定向到速度方向，头朝前飞）
- 收尾：Attribute Delete `* ^P ^N ^v`（`^`=保留语法）+ Attribute Randomize 随机大小

## 配方四：蚊虫飞舞（跟随主体）

- `grid` 当点云控数量 + `attribvop` 里 **Turbulent Noise** 控随机移动路径
  （Roughness 越小路径越流畅）+ `trail` 生成速度使蚊虫朝向飞行方向 +
  `copytopoints` 勾 **Pack and Instance** 实例化减运算
- **跟随运动**：Constraints 工具架的 **Lag** 工具（先选蚊虫 geo，再选跟随目标
  如猪头）
- **坑**：主体（猪头）的运动路径要在该层级下 K 关键帧，**不能在内部节点用
  Transform K 帧**（Lag 感知不到）

## 配方五：抛物线抛出（RBD）

`pointvelocity` 设初速度 -> `assemble`（生成 name 属性对应模板碎片）->
`Transform Pieces`（输入1=待变换几何，输入2=模板变换）-> `DOP Import`
（路径 `../rbdbulletsolver1/dopnet/`）。

## 散坑

- **烟花拉丝粒子在 Karma 不显示**：alpha 通道 Karma 不识别需**改名**，pscale
  要设好，默认材质做发光，导入新的 alpha 属性（参考教程《Houdini Karma如何渲染
  拉丝粒子？？？》）
- 报纸飘落、洞穴扫描、噪波分离合并线（魔法线条）：笔记中仅存图，
  见原文 `小案例.md` 对应小节
