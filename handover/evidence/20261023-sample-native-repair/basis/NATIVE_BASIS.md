# 本机原生身份采集依据

日期：2026-10-23。范围：只读生产代码、测试、同机 Apple 手册、公开 SDK 声明，以及无目标 `-h` 帮助；未运行任何目标的 sample/vmmap，未启动 DCC。以下结论是方向依据，不能作为原生采集通过或正式链验收。

## 已核实环境与原始材料

- 本机 macOS 15.8.1，build 24H32，arm64。
- `/usr/share/man/man1/sample.1`：Apple，文档日期 2013-03-16；原字节副本 `sample.1.roff`。
- `/usr/share/man/man1/vmmap.1`：Apple，文档日期 2022-08-09；原字节副本 `vmmap.1.roff`。
- `/usr/bin/sample -h`：退出 255，原始 stdout/stderr 分别见 `sample.help.*.txt`，调用元数据见 `sample.help.json`。
- `/usr/bin/vmmap -h`：退出 0，原始 stdout/stderr 分别见 `vmmap.help.*.txt`，调用元数据见 `vmmap.help.json`。
- `metadata.json` 固定本机版本、二进制与已读源文件 SHA-256。这里没有用 strings 命中作为参数合法性或效果的证据。

## sample：没有获得公开的关闭符号化选项依据

同机手册与实际 `-h` 只公开 `-wait`、`-mayDie`、`-fullPaths`、`-e`、`-file`（帮助另写 `-f/-file`）。二者均没有公开 `-nodsyms`、`-noSymbolication` 或等价的抑制符号处理参数。

`-mayDie` 的合同是立即读取符号位置/信息，以便进程退出后仍能报告栈；它不能作为避免符号处理的选项。`-fullPaths` 控制调试源文件路径展示，也不是关闭符号处理。

因此，本次没有依据给出“合法且有效的无符号化 sample argv”，也没有依据证明未文档化 flag 会保留 Process、Parent Process、Load Address、Launch Time、Target Type 五个字段。`nodsyms` 字串只说明二进制中存在字串，不能建立调用合同、分支效果或性能结论。

现有固定 argv 为 `['/usr/bin/sample', str(pid), '1', '1000', '-file', '/dev/stdout']`。`sample(1)` 明确将 duration 定义为采样秒数，samplingInterval 定义为毫秒采样间隔；duration 不承诺包含报告分析和符号处理的总耗时。公开文档不能证明该 argv 会在 5 秒内完成。

## vmmap：唯一已有文档支持的最小候选

同机 `vmmap(1)` SYNOPSIS 和实际 `-h` 都允许最后一个可选 `<address>`。DESCRIPTION 明确说明：给定 address 时，只展示包含该地址的 VM region（若有）及其周围 region。`-w` 明确用于完整映射路径；`-interleaved` 明确按起始地址排序。输出定义明确给出 region 起止地址、当前/最大保护属性；二进制映射的最右列给出映射文件。

候选调用顺序如下，均使用被观察 PID 与原生返回值：

```python
header_argv = ['/usr/bin/vmmap', '-w', '-interleaved', str(pid), '0']
region_argv = ['/usr/bin/vmmap', '-w', '-interleaved', str(pid), observed_load_address]
```

这里的 `0` 只是数值地址候选，**不是文档中定义的 header-only 模式**。手册没有禁止零地址，也没有逐项定义地址输入格式或明确列出零地址；不能将“0 必然只取头”写成已证实合同。即使零地址附近出现 `__PAGEZERO` 或其他相邻行，这些行也不能充当实际主像。

手册仅限定展示范围，没有说明内部是否仍会遍历全域 VM、读取映像元数据或做其他工作。因此性能优势、符号处理是否被避开、零地址时五 header 是否全部保留、Launch Time 的精度，以及不同目标状态下是否有 stderr，都必须由执行者保存真实 stdout/stderr、返回码和分阶段时间进行验证。本报告未验证这些运行行为。

旧证据 `handover/evidence/20261023-coordination/native-basis/relocated-original-vmmap.txt` 是现存原生文件：开头确有上述五字段；它仅证明该历史完整报告的格式，不证明 `PID 0` 的行为。该文件还同时显示原 Load Address 处被重新映射为只读 mapped file，另处存在同路径可执行 mapped file。候选必须继续拒绝这种“原加载位置不再是唯一实际 r-x __TEXT”的情况；不能按同路径、任意 r-x 区域或 expected 路径补齐主像事实。

## 最小实现必须保持的解析和身份强度

当前 `_vmmap` 的五字段与 region 解析、`_observe` 两次采集和 `capture_ancestry` 正反双链定义仍是基准；替换工具不授权降低它们。

1. 每轮从独立原生输出取得五个字段，各出现一次；缺失、重复、未知 Target Type、PID 不符、无效出生时间、零或畸形 Load Address 均拒绝。路径/Identifier/显示名不能替代这些事实。
2. 第二条 argv 的地址只能来自第一条原生输出。实际 region 必须是唯一 `__TEXT`，起始地址等于原始 Load Address，结束地址大于起始地址，当前权限严格 `r-x`，并有可接受的绝对文件路径。允许 addressed 输出原有 `--->` 前缀；不可将邻接 region、同路径其他映射或只读旧位置认作主像。
3. 定点 vmmap 如也包含身份头，应核对其 PID/PPID/Launch Time/Load Address 与首份头一致，不能靠第一份头替第二份输出填字段。是否有头须先由真实证据确定。
4. 前后 `ps` 继续实测 PID、PPID、秒级 lstart 和非僵尸状态；两份 lsof 继续实测同一 PID/PPID 的唯一匹配 txt vnode。不能从 expected 身份构造任一观察。
5. 两次 lsof 与实际打开文件的 device/inode 对应；保留无符号链接/硬链接拒绝、stat、打开 fd、完整 hash、重新打开路径及 fd 状态回读。
6. 第一轮与第二轮原生头/主像事实完整复测，保留进程出生/PPID/Load Address/路径/vnode/stat/hash 漂移拒绝。祖先锚仍是可信宿主独立观察，保留严格祖先、正向与逆向完整双链、出生先后与所有失败即拒绝逻辑。
7. 工具 5 秒、单次观察 16 秒、完整链 60 秒限额不变；不采用 `-forkCorpse` 新路径、部分 stdout 成功、杀工具即接收头、放宽未知 stderr、重试求绿或删除第二次观察。现有原始 producer 签名与可信 binding 仍由原链处理。

UUID 边界：当前生产 `process_image.py` 与对应 unit tests 没有 UUID 字段、解析或比较。现存 `normal-sample.txt` 的 Binary Images 列表含主像 UUID，但五个头字段本身不含 UUID；`vmmap(1)` 文档也没有承诺 UUID 输出。按本轮已澄清范围，不新增 runtime UUID gate 或 schema；工具原始输出中已有 UUID 可以随原字节保留作证据，不能称为生产身份协议原本已有或本轮已验证的运行中 UUID。强度对照以上述现有字段及 defenses 为准。

## 公开系统 API 备选的已知边界

本机 SDK `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/libproc.h` 声明 `proc_pidinfo`、`proc_regionfilename`、`proc_pidpath`。`sys/proc_info.h` 的 `PROC_PIDTBSDINFO` / `proc_bsdinfo` 提供 pid、ppid、状态和 `pbi_start_tvsec` / `pbi_start_tvusec`；`PROC_PIDREGIONPATHINFO` / `proc_regionwithpathinfo` 提供 region 与 vnode 路径结构。这些声明说明可取得部分原生事实，但 `proc_pidpath` 仅有路径，不能单独证明原 Load Address 的唯一实际主像。

同机公开 `mach-o/dyld_images.h` 声明 `dyld_image_info.imageLoadAddress`、`imageFilePath` 与 `dyld_uuid_info.imageUUID` / `imageLoadAddress`。其注释明确指出 `infoArray == NULL` 表示正在修改，需要稍后读取；UUID 数组仅覆盖不在 shared cache 的映像。对任意目标跨进程读取涉及权限、远程指针、结构版本、一致性及原生 region/vnode 独立核对，本次没有执行或证明。这不是可以直接替换五 header 的已验收一条 API。

因此 API 路线目前比“公开 address 过滤 + 原 Load Address 定点”更大，缺少同强度原生验证，不应作为已经可用的生产修复。最小候选若不能满足现有头、实际主像及限额，结论应保持未解决。

## 交付判定

- sample 无符号化 flag：**未获本机公开依据，不能采用**。
- vmmap address 过滤：**公开支持展示过滤语法；`0` 取头与性能未验证，候选待原生对照**。
- 公共 API 完整替换：**仅有部分事实和结构声明，尚未证明同强度**。
- 本报告：**依据报告完成；原生采集、生产修复及正式链验收均未在本任务执行**。
