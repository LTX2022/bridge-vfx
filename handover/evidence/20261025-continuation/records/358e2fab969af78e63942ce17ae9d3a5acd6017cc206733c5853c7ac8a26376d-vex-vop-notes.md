# VEX 与 VOP 速查（学自用户笔记 VEX和VOP和脚本插件编写等.md, 2026-08-25）

> **⚡ TL;DR 速答卡**（读完能解决就不用往下翻）
> - 表达式 ≠ VEX：参数里写 `$F`/`ch()`（表达式），wrangle 里写 `@P`/`@Time`（VEX）；写混不报错但不生效
> - 属性前缀：`f@`/`i@`/`v@`/`u@`(vector2)/`p@`(vector4)/`s@`/`2@ 3@ 4@`(矩阵)；不写前缀默认 float，要 int/vector 必须写 `i@`/`v@`
> - 常用属性：P/Cd/N/v、pscale/width、ptnum/primnum/numpt/numprim、Frame/Time/TimeInc、orient/up；第 2 输入用 `@opinput1_`（0 起算）；组引用 `@group_组名`
> - ch 家族：`ch("名")` 自动生成滑块、`chi` int、`chv` 向量、`chsop` 节点路径、`chramp("ramp",x)` 渐变
> - 高频函数：`rand(seed)` 返回 [0,1) 同 seed 同结果；`fit01(v,nmin,nmax)`；`clamp(x,a,b)`；精确 90° 用 `atan2` 不是 `atan`
> - 删点/删面：`removepoint(0,@ptnum)`、`removeprim(0,@primnum,1)`；第 3 参语义相反--removepoint 的 0=保留 prim 只删点，removeprim 的 0=保留点只删面
> - 邻域查找：`nearpoints(0,@P,半径,最大数量)` 返回点号数组，配 `point(0,"Cd",pt)` 读指定点属性
> - VOP 内部参数无时间依赖，动画不动先 Promote Parameter 到上层；连线颜色：绿=矢量、蓝=整数、蓝绿=浮点
> - VOP 输出节点与外部属性同名=直接修改外部属性，不想覆盖就换名字
> - `rest` 属性存置换前的 P：displacement 后用 rest 乘 noise 防噪波滑动
> - 相机剔除：`toNDC(chsop("cam"),@P)` 切相机外模型（`fromNDC` 反向）；相机路径用 `chsop()` 取，别写死字符串
> - 波纹一行流：`@P.y += sin(length(@P)*ch("freq") + ch("speed")*@Time) * ch("mult");`
> - 坑：`pcopen` 找不到点（num=0）时后续 distance 按 {0,0,0} 算，结果错但不报错；use vexpressions 里节点自带属性不加 `@`

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\Houdini基础模块\VEX和VOP和脚本插件编写等.md` 第 1-1560 行。
原始笔记保持只读；本文件是蒸馏版——常用属性表、VEX 语法、高频函数、VOP 对应关系、
表达式函数与实测代码小案例。笔记里指向图片的链接保留原样（截图见原笔记）。

## 0. 基本概念

- **expression 表达式 ≠ VEX script**：表达式写在参数里（`$F`、`ch()` 那套）；
  VEX 写在 wrangle 等 VEX 相关节点里。两种写法**不相等**，别混用。
- 四个属性级别：**Points / Vertices / Primitives / Detail**。
- 数据类型：`float` `int` `vector`（含 vector2 如 UV、vector4 如 RGBA）
  `string` `boolean` `matrix` `array`。
- VEX 区分大小写；性能接近编译的 C/C++。
- `mono` 节点：当做 float 用。虚线在 Houdini 一般代表 reference。
- VOP 是可视化节点式编写 VEX；在 VOP 节点上右键可查看生成的 VEX 代码
  （截图见原笔记 `./图片/Houdini/微信截图_20231230225121.png`）。
- 命令行调用 Houdini 工具：把 `C:\Program Files\Side Effects Software\Houdini 21.0.512\bin` 加入环境变量。

## 1. 属性前缀与常用属性

类型前缀（常用属性可不写前缀，默认 `f`）：

| 前缀 | 类型 |
|---|---|
| `f@name` | float |
| `i@name` | int |
| `v@name` | vector |
| `u@name` | vector2 |
| `p@name` | vector4 |
| `s@name` | string |
| `2@ 3@ 4@` | 2x2 / 3x3 / 4x4 矩阵 |

常用属性速查：

| 属性 | 含义 |
|---|---|
| `v@P` / `v@Cd` / `v@N` | 位置 / 颜色 / 法线 |
| `v@v` | 速度及方向 |
| `f@pscale` / `f@width` | 点大小 / 线宽 |
| `i@ptnum` / `i@id` / `i@numpt` | 点序号 / 点 id / 点总数 |
| `i@primnum` / `i@numprim` | 面序号 / 面总数 |
| `f@Frame` / `f@Time` / `f@TimeInc` | 当前帧 / 当前秒 / 时间步长 |
| `p@orient` / `v@up` / `v@side` | 方向 / 朝上 / 侧向向量 |
| `f@age` / `f@life` | 年龄 / 寿命（与 SOP 不兼容） |
| `v@force` / `u@uv` / `f@Alpha` | 力场 / UV / 透明度 |

- `@opinput1` 表示第 2 个输入（0 起算），`@opinput2` 是第 3 个输入。
- 引用组：组名前加 `@group_`，如 aaa 组 → `@group_aaa`；
  `f@group_x = @opinput1_group_x;` 把输入 2 的分组属性绑过来。
- 创建属性：`i@index = 2;` 即可（Attribute Wrangle）；
  `attribute creat` / `attribute expression` 节点也行，后者可一次建多个。
- `toNDC()` 能切除摄像机之外的模型；`fromNDC()` 反向（NDC → 相机空间）。

常见内置属性（按类型）：int 类 `id / gl_ / ptnum / primnum / vtxnum / numpt / numprim / numvtx`；
float 类 `age / life / Time / TimeInc / Frame / pscale / Alpha / width / lod / density / temperature`；
string 类 `name / instance`；vector 类 `P / N / Cd / scale / force / up / v / rest / uv / spritescale`；
vector4 类 `orient / rot`。（Copy 与 Instance 属性、几何体显示属性两张总结图见原笔记）

## 2. 常用局部变量（$ 变量，用于表达式）

| 变量 | 含义 |
|---|---|
| `$F` / `$FF` / `$T` | 整数帧 / 子帧（浮点）/ 秒 |
| `$PT` / `$NPT` | 点序号 / 点总数 |
| `$PR` / `$NPR` | 面序号 / 面总数 |
| `$VTX` / `$NVTX` | 顶点序号 / 总数 |
| `$TX $TY $TZ` | 输入点 1 位置（`$TX2...` 为输入点 2） |
| `$CEX $CEY $CEZ` | 几何体中心坐标 |
| `$BBX $BBY $BBZ` | 点在边框中的归一化位置 |
| `$SIZEX/Y/Z`、`$XMIN/$XMAX...` | 尺寸 / 最小最大坐标 |
| `$NX $NY $NZ` / `$VX $VY $VZ` | 法线 / 速度 |
| `$CR $CG $CB` / `$CA` | 颜色 / 透明度 |
| `$MAPU $MAPV` | 贴图坐标 |
| `$ID` / `$AGE` / `$LIFE` | 粒子编号 / 年龄 / 生命 |
| `PI` / `E` | 圆周率 / 自然对数底 |

通配：`*` 全选；`!*` 全不选；`* ^P ^N` 全选但排除 P、N。

## 3. 生成控制参数（ch 家族）

| 函数 | 用途 |
|---|---|
| `ch("tx")` | 取数值参数（自动生成滑块） |
| `chf` | 浮点滑块（0~1，可超） |
| `chi` | 整数参数 |
| `chs` | 字符串参数 |
| `chsop` | 节点路径参数（返回运算符路径） |
| `chv` | 向量参数 |
| `ch2 / ch3 / ch4` | 2x2 / 3x3 / 4x4 矩阵参数 |
| `chramp("ramp", x)` | ramp 渐变参数 |

在 wrangle 里写 `ch("freq")` 会自动在节点上生成同名滑块（各类型截图见原笔记）。

## 4. VEX 语法（实测代码，完整保留）

整数 / 浮点 / 数组：

```c
int x=1;
printf("%i",x);
//输出 1

int x[]={10,20,30,40,50};
printf("%i\n",x);
printf("%i\n",x[2]);
//输出 {10, 20, 30, 40, 50}
//输出 30

float x=1;
printf("%f\n",x);
//输出 1.000000
```

向量 / 字符串 / 矩阵：

```c
vector x;
x = set{20,255,100};
printf("%f\n",x);
//输出 {20.000000, 255.000000, 100.000000}

string x="abcdefghijk";
printf("%s\n",x);
printf("%s\n",x[6]);
printf("%s\n",x[2:6]);
//输出 abcdefghijk
//输出 g
//输出 cdef

matrix x;
x = set(1,2,3,4,5,6,7,8,9,10,11,12,13,14,15);
printf("%f\n",x);
printf("%f\n",len(x));
//输出 {1...15}
//输出 16
```

创建属性：

```c
i@a
// 创建整数属性a;
// 等于 int @a;
f@b;
// 创建浮点属性b
// 等于 float @b;
v@c;
// 创建向量属性c;
// 等于 vector @c；
2@d;
// 创建2x2矩阵属性d;
// 等于 matrix2 @d;
3@e;
// 创建3x3矩阵属性e;
// 等于 matrix3 @e;
4@f;
// 创建标准矩阵属性f;
// 等于 matrix @f;
```

遍历（if / for / foreach / while / do-while）：

```c
//-----if_else-----//
float x;
x = @numpt; // 浮点x数值等于输入物体点数;
if (x>=12){
  printf("Yes\n");  // 输出“yes”，并换行;
}else{
  printf("No\n");   // 输出“No”,并换行;
}

//-----for-----//
string x= "a1b2c3d4eb 5f6g 7h8";
for(
  int xi=0;   // 指令描述：初始化条件
  xi<len(x);  // 判断:xi小于字符位数
  xi++
){
  if(x[xi]==" ")continue; // 条件分歧:遇到空格字符就跳过
  if(x[xi]=="7")break;    // 条件分歧:遇到数字“7”终止循环
  printf("%s\n",x[xi]);   // 输出字符变量x中数位变量xi的字符
}
// 输出：a1b2c3d4eb5f6g

//-----for_each-----//
string xs="abcdefg";
foreach(string x; xs){  // 创建foreach循环字符变量x, 载入字符变量xs
  printf("%s\n",x);     // 输出xs中的每个字符
}
float xf[]={1,2,3,4,5,6,7,8,9};
foreach(float xx; xf){    // 创建foreach循环浮点变量xf, 载入浮点变量xx
  printf("%f\n",xx);      // 输出xf中的每个数值
}
// 输出：a b c d e f g 1.000000 2.000000 3.000000 4.000000 5.000000 6.000000 7.000000 8.000000 9.000000

//-----do_while-----//
int xa = 5;
while(xa>0){    // 判断 xa 不大于则0停止, xa大于0则运行
  xa--;
  printf("%i\n",xa);
}
printf("\n");

int xb = 5;
do{           // 运行以下代码
  printf("%i\n",xb);
  xb--;
}
while(xb>0);  // 判断直至xb不大于0则停止, 大于0则运行do循环
// 输出：43210 54321
```

## 5. 高频函数详解

### 5.0 高频函数速查表（从"所有函数"节约 480 条中筛选真正常用的）

| 类别 | 函数 | 说明 |
|---|---|---|
| 数学 | `abs / pow / sqrt / exp / log / log10` | 基础运算 |
| 数学 | `sin / cos / tan / atan2` | 三角；`atan` 无法精确表示 90°，用 `atan2` |
| 数学 | `min / max / clamp(x,a,b)` | 取极值 / 限域 |
| 数学 | `floor / ceil / round(rint) / trunc / frac` | 向下 / 向上 / 四舍五入 / 截断取整 / 取小数 |
| 数学 | `rad / deg` | 角度↔弧度 |
| 向量 | `length / vlength / distance` | 向量长 / 两点距离 |
| 向量 | `normalize / cross / dot / vangle` | 归一化 / 叉乘 / 点乘 / 夹角 |
| 随机 | `rand(seed)` | 不连续随机 `[0,1)`，同 seed 同结果 |
| 随机 | `noise / snoise / turb / sturb` | 连续光滑随机 / 稀疏卷积 / 可设递归深度 |
| 映射 | `fit / fit01 / fit10 / efit` | 范围适配；efit 无范围限制 |
| 映射 | `smooth(value,min,max)` / `wrap(x,a,b)` | 光滑插值 / 周期循环（同求余） |
| 矩阵 | `ident / translate / rotate / rotaxis / scale` | 单位阵 / 平移 / 旋转 / 绕任意轴 / 缩放 |
| 矩阵 | `invert / transpose / dihedral` | 逆 / 转置 / 一个方向到另一个的旋转矩阵 |
| 矩阵 | `explodematrix` / `matrixtoquat / quattomatrix` | 拆 TRS / 矩阵↔四元数 |
| 几何计数 | `npoints / nprims / nvertices`（+`group` 变体） | 点/面/顶点总数 |
| 几何查询 | `nearpoint / nearpoints` / `centroid` / `bbox` | 最近点 / 重心 / 边框 |
| 属性读取 | `point / prim / vertex / detail` | 读数值型属性（字符串型加 `s`） |
| 属性列表 | `pointattriblist / detailattriblist...` / `haspointattrib...` | 列属性 / 判存在 |
| UV | `primuv / primduv / unituv / realuv` | 参数化 uv 取属性 / 偏导 / 单位uv转换 |
| 距离场 | `xyzdist / mindist / pointdist / primdist` | 到最近表面的距离+面号+uv |
| 体积 | `volumesample / volumeres / volumeindex` | 体素采样 / 分辨率 / 索引取值 |
| 邻居 | `pointneighbours / primneighbours` | 相邻点/面列表 |
| 去重 | `uniquevals / nuniquevals` | 属性去重取值 / 不同值数量 |
| 字符串 | `strlen / strcat / strcmp / strmatch` | 长度 / 连接 / 比较 / 模式匹配 |
| 字符串 | `strreplace / strsplit / substr / index(rindex)` | 替换 / 切割 / 取片段 / 查位置 |
| 字符串 | `tolower / toupper / trim(ltrim/rtrim)` | 大小写 / 截两端字符 |
| 通道 | `ch / chf / cht / chs / chsop / chramp` | 取参数（见第 3 节） |
| 通道 | `stamp` | 取 copy 的 stamp 变量（编译块内禁用） |
| 路径 | `opfullpath / opinputpath / oprelativepath / relpath / abspath` | 节点/文件路径转换 |
| 判断 | `opexist / if / ifs / isvariable` | 节点存在 / 条件（数值/字符串）/ 环境变量存在 |
| 插值 | `bezier / cubic / linear / spline / ease(in/out/p) / constant` | 动画曲线插值 |
| 循环 | `cycle / repeat / wrap` | 曲线循环取值 |
| 杂项 | `padzero / print / run / system` | 补零 / 打印 / 跑 HScript / 系统命令 |

> 完整 480+ 条函数表（含 COP/DOP/PDG/USD 专用）见原笔记"所有函数"一节。

**relbbox** —— 点相对几何体边界框的归一化位置：

```c
@Cd = relbbox(1,@P);
// 将颜色属性绑定到输入2物体的边界范围上
```

**getbbox 家族**：

- `getbbox(0, min, max)`：两个向量设为 bbox 最小/最大角
- `vector x = getbbox_size(0);`：边界尺寸
- 另有 `getbbox_center` / `getbbox_max` / `getbbox_min`
- `<geometry>` 参数在 SOP 上下文里就是输入端口号（0 起）

**remove 家族**：

```c
if( @N.y>0 ){ removepoint( 0, i@ptnum );};
// 如果点法线方向向下，则移除点（wrangle输入点 + 点序号）

if( @Cd.r< 0.4 ){ removepoint( 0, @ptnum );}

if( @Cd.r< 0.4 ){ removeprim( 0, @primnum, 1 );}
// wrangle输入点 + 面序号 + 是否删除孤立点(0:保留，1:删除)

removeprim(0， 1，0);
// 第二个参数：要删除的面序号
// 第三个参数：0 只删面保留点；1 删面及面上的点

removepoint(0, @ptnum);
// 第三个参数不写则 prim 还存在：
// 0 只删点但保留面上的 prim；1 删点及面（常用于少于三个顶点的模型）
```

删属性（`Attribute Wrangle` 的 `run over` 改为 `Detail`）：

```c
removeattrib(0, "point", "Cd"); //删点属性
removeattrib(0, "primgroup", "group1"); //删组
```

**wrap** 周期函数：`wrap(变量, 周期最小值, 周期最大值)`，
`wrap($F,0,20)` 取值空间 0-20，超出进下一周期，与求余效果一样。

**nearpoints / point**（见 Solver 生长案例）：`nearpoints(0,@P,半径,最大数量)`
返回搜索距离内的点号数组；`point(0,"Cd",pt)` 读指定点属性。

**pcopen 点云**：

```c
int pc = pcopen(1,'P',@P,chf('radius'),chi('numpt')); //以当前点的点位置 根据搜索半径和数量来查找点
int num =pcnumfound(pc); //找到的点云的点数量
vector pos = pcfilter(pc,'P'); //获取找到点云的点的点位置
float dis = distance(pos,@P);//当前点的点位置和点云的点位置计算距离

if (num>0)@Cd = dis;//如果点云的点数量大于0那么颜色就等于距离
//如果没找到点那么点云的点数量就等于0
//如果点云的点数量等于0, 那么0和当前的点位置 distance 的结果就是 {0,0,0} 和当前点位置的点计算的结果

v@Cd = chramp('ramp',v@Cd);//对颜色Ramp
```

**四元数（Quaternion）**：物体方向一般靠 `N` + `up` 就够；四元数是另一套系统，
用 4 个数定义空间中的一个轴及绕轴角度，`vector4 q = {0,0,0,1}`（(x,y,z),w）。
计算方法：默认 N 作为 Z 轴（法线必须是 Z 正方向），N 与 {0,1,0} 叉乘得 X 轴，
Z×X 得 Y 轴，再用 vector to matrix3 变成矩阵。

## 6. VOP

- **VOP 内部参数不含时间依赖**，必须 `Promote Parameter` 提升到上层才有时间依赖。
- 连线颜色：**绿**=矢量、**蓝**=整数、**蓝绿**=浮点、**浅棕**=几何体相关。
- 全局变量（Global Variables 节点）：`P / v / Force / Age / Life / id / Cd / Uv / N /
  Time / Timeinc / Frame / Ptnum / primnum / Vtxnum / Numpt / Numprim / Numvtx /
  OpInput1-4`。注意 VOP SOP 中 `N` 若输入端不存在不会自动计算。
- 数据类型转换：`Vector to Float` 拆三个浮点；`Float to Vector` 合并。
  对三维属性的单个分量调整：`v to f` 拆出 xyz，只改 y，再 `f to v` 合回。
- 常用运算节点：`Add / Subtract / Multiply / Divide / Constant / Add Constant /
  Multiply Add Constant` 等；`cross` 叉乘结果是向量不是标量。
- 常用节点：`turbulent noise` 噪波；`Anti-Aliased Noise`（Signature 选
  `3D Input, 1D Noise` 或 `3D Input, 3D Noise`）；`clamp` 限域；`fit` 范围映射；
  `Parameter` 参数节点（改 Type 为 vector 可做速度场）；`two way` 模拟
  if-then-else（配 `remove point` 做删点）。
- **参数暴露**：未绑定的参数用 input 节点加参数控制；右键节点 →
  `VEX/VOP Options` → `Create Input Parameters` 一键全部曝光。
- 输出节点不能与外面已创建的属性同名（同名=修改外部属性，不同名=新属性）；
  `Override Type with Input` 在输入节点下不起作用，输出节点下勾选后由 Type 参数决定类型。
- **rest 属性**：存 `P`。VOP 对模型做随时间 displacement 后各点都在变，
  拿时刻变化的坐标乘 noise 不合适，`rest` 记录置换前的位置且不受置换影响，
  用来避免噪波滑动。pyro 位置变化大会记两个 rest 做融合；新版 pyro 不算这个场了。

## 7. 表达式函数（写在参数里）

- `if(a,b,c)`：a 成立返回 b，否则 c。如 `if($F<=20,$F,20)`。
- `set`：`@Cd = set(chramp('color',@P.x), chramp('color',@P.y), chramp('color',@P.z));`
- `fit(value, omin, omax, nmin, nmax)`：`fit(.3, 0, 1, 10, 20) == 13`；
  `fit01(value, nmin, nmax)` 默认源范围 0-1。
- `rand(seed)`：返回 `[0,1)`；同 seed 同结果，`rand(@id*0.123)`。
- `centroid("../each1", D_x)` 求中心点；`noise/snoise` 连续随机；
  `smooth(value,min,max)`。
- 隔点取点（点序号分组）：
  `` 0-`npoints(opinputpath(".", 0))`:2 `` —— 从 0 号点每两个取一个（0,2,4...），
  改成 `1-...` 则从 1,3,5... 开始（截图见原笔记）。
- `npoints("/obj/sphere1")` 返回点数；`opinputpath` 返回输入节点完整路径；
  带节点路径参数的函数可用整数引用输入，如 `npoints(-1)`（需 Spare Input）。

## 8. 实测小案例（VEX 代码完整保留）

**波纹**：

```c
float s = sin(length(@P)*ch("freq") + (ch("speed") * @Time));
@P.y += s * ch("mult");
```

`length(@P)` 取每个点自身位置的值；`ch("freq")` 拉大差异；
`@Time` 当前秒数让波形随时间偏移；`@P.y +=` 抬升 y。

**淡淡的雾气漂浮**：

```c
f@density = noise(v@P/ch('size')+chv('offset'));
f@density = fit(@density,ch('min'),ch('max'),0,1);
vector nearP = minpos(1,@P);
float dist = distance(@P,nearP);
dist = fit01(dist,ch('min_den'),0);
@density *= dist*ch('density');
```

**物体基于相机透视缩放**（物体可一直保持在镜头前）：

```c
string cam = chs("cam_path"); // 获取相机路径
@P = fromNDC(cam,@P); // 将点从NDC空间转换到相机空间
@Alpha = ch("A"); // 调节模型透明度
```

**相机剔除物体**（等价于 df_CameraCut.hda 的 pointwrangle 写法）：

```shell
vector c = toNDC(chsop("cam"),@P);
if(c.x>ch("width_1")||c.x<ch("width_2")||c.y>ch("height_1")||c.y<ch("height_2"))
removepoint(0,@ptnum);
if(c.z<-chf("depath")||c.z>-chf("depath_2"))
removepoint(0,@ptnum);
```

**矩阵变换**（3x3 矩阵是两个空间向量的旋转变换信息，4x4 多了位移）：

```c
matrix ident = ident();
translate(ident,chv('translate'));
@p *= ident;
```

```c
matrix ident = ident();
scale(ident,chv('scale'));
@p *= ident;
```

`ident` 单位矩阵 / `translate` 平移 / `scale` 缩放 / `rotate` 旋转 /
`lookat` 指向（输入 1 是自己 bbox 中心，输入 2 是目标点，两个输入换一下朝向就反）。

## 9. 易错点

- **expression 和 VEX 是两套东西**：`$F`/`ch()` 是表达式（参数里用），
  `@P`/`@Time` 是 VEX（wrangle 里用），写混了不报错但不生效。
- **`use vexpressions` 里节点自带的属性不要加 `@`**；想知道参数在 VEX 里的
  名称，鼠标悬停在参数上看（尾巴带 XYZ 的写作 `wind.x` 等）。
- 自定义属性不写前缀默认是 float：需要 int/vector 时必须写 `i@`/`v@`。
- **VOP 内部参数没有时间依赖**——动画不动时先检查参数是否 Promote 到上层。
- `removepoint`/`removeprim` 的第 3 个参数语义相反易混：
  removepoint 第 3 参 0=保留 prim 只删点；removeprim 第 3 参 0=保留点只删面。
- VOP 输出节点与外部属性**同名会直接修改外部属性**，不想覆盖就换个名字。
- `pcopen` 找不到点（num=0）时，后续 `distance` 拿 {0,0,0} 计算，结果错但不报错。
- `atan` 无法精确表示 90 度，要精确用 `atan2`。
- 用 `toNDC`/`fromNDC` 时相机路径要用 `chsop()` 取，别写死字符串。
