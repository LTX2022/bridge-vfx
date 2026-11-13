# macOS 主映像身份采集：原生依据与可行性

范围：只读核对本机工具、SDK 和 Apple 原始代码，并对普通自有 Python 子进程进行有界 API 探针；没有修改生产代码，没有启动 DCC。当前没有得到能够直接替换 vmmap、同时保留全部现有事实的已验证最小方案。公开 libproc 完整枚举可运行，但同文件唯一 RX 映射替代已被同一进程的正式对照反例否定。

## 已确认依据

本机为 macOS 15.8.1 / 24H32，Darwin 24.6.0、arm64；SDK 是本机 CommandLineTools 提供的 MacOSX.sdk，其版本早于运行系统，因此以下声明与运行结果分别记录。

| 必需事实 | 原生依据 | 本轮可确定的边界 |
|---|---|---|
| PID、PPID、精确出生 | `libproc.h` 的 `proc_pidinfo`；`sys/proc_info.h` 的 `PROC_PIDTBSDINFO`、`proc_bsdinfo.pbi_pid/pbi_ppid/pbi_start_tvsec/pbi_start_tvusec` | 内核结构支持，不必从进程命令行推断 |
| 可执行路径 | `libproc.h:102` 的 `proc_pidpath` | 普通 Python 探针成功；单独路径不证明实际主映像 load / vnode |
| 已知地址对应的区域、vnode | `PROC_PIDREGIONPATHINFO` / `proc_regionwithpathinfo`；区域包括 address / size / offset / protection，vnode 包括 stat 与 path | Apple XNU `proc_pidregionpathinfo` 调用 `fill_procregioninfo` 后读取该区域 vnode；不是主映像选择器 |
| 区域范围与路径 | `proc_regionfilename` 的 `PROC_PIDREGIONPATH` | 原始代码经过 `task_find_region_details` 返回范围和路径；不包含独立主映像选择标识 |
| dyld image load 与 MH_EXECUTE | `mach/task_info.h:260–272` 的 `TASK_DYLD_INFO`，`mach-o/dyld_images.h` 的 image array / imageLoadAddress；读取目标内存还需要 task read 权限 | 本轮跨进程 task read / inspect 均失败 EPERM，不能作为当前可用替代 |
| vmmap 精简选项 | 本机 `vmmap -help` 和 `man vmmap` | 有 `address` 参数，但说明只承诺过滤显示。没有找到关闭页统计的公开参数；不能猜 `-noResident` / `-noShared` 等选项 |

本机 SDK 位置：`/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/`。相关文件：`libproc.h`、`sys/proc_info.h`、`mach/task_info.h`、`mach/mach_traps.h`、`mach-o/dyld_images.h`。

## API 探针结果

每次仅启动一个最长 10 秒的普通 Python 目标和一个 5 秒硬限制的读取辅助进程；目标在读取后由父进程终止并 `wait`。没有调整系统权限或授权设置。

| 证据 | 结果 |
|---|---|
| `probe-result.json` | 沙箱内：pidpath 成功；task name / control 端口均返回 5 |
| `probe-unsandboxed-result.json` | 非沙箱：pidpath 成功；task name 端口返回 0，但 `TASK_DYLD_INFO` 返回 4；task control 端口返回 5 |
| `probe-read-port-unsandboxed-result.json` | 非沙箱：task read / inspect 返回 -1、端口为 0；首次脚本未记录 errno |
| `probe-read-port-errno-unsandboxed-result.json` | 补齐 errno：read / inspect 都为 -1、errno=1（EPERM）、端口为 0；0.038 秒完成 |

`TASK_DYLD_INFO_COUNT` 按 SDK 的 4 字节 packing 为 5。task name 端口成功不等于能读 dyld 信息；不存在成功读取后的“主映像已验证”证据。

## 准确的剩余缺口

Task read 权限失败只否定本轮探测的 TASK_DYLD_INFO / 远程 MH_EXECUTE 路线，不证明所有无额外权限方案都不存在。

公开 libproc 结构可以给出出生、父 PID、路径和指定区域的 vnode，但未找到可直接标记内核加载主映像地址的字段。以 `proc_pidpath` 对应文件的第一个 RX 区域作为 load，或只读磁盘 Mach-O 文件头看到 MH_EXECUTE，都不足以区分原始主映像与同文件额外映射。完整枚举后要求唯一候选是一条尚待证明的候选路线：它仍需处理重复映射、原主映像移除、架构切片、offset、前后变更和遍历上界，本轮没有把它作为已成立实现。

## 有界枚举原型和决定性对照

追加原型只写本证据目录。`regions-flavor-probe.c` 使用公开 `PROC_PIDREGIONPATHINFO=8`，固定最多 4096 区域，父进程对辅助进程限时 5 秒；递进要求 `address >= requested`、`size > 0`、加法不溢出，以 `address + size` 继续。三例分别 0.032、0.029、0.030 秒完成，观察到终止 `0 / errno=22`。这些计时只证明所测普通 Python，可执行原型没有做生产级完整 hash/双观察，不构成完整身份验证。

Apple `fill_procregioninfo` 在所查 XNU 家族里于最后区域后返回 0，也可能因 task map 不存在返回 0；`proc_pidregionpathinfo` 将该结果转成 EINVAL。不能把所有 EINVAL 一律当作已可靠完整遍历。公开 flavor8 内部仍统计区域页信息。私有 flavor22只枚举 vnode 映射并将页统计置零，普通 Python 也能运行，但不属于当前 SDK 的公开常量，不建议直接引入生产。

`regions-public-flavor-result.json` 保存正常、重复和搬移三例。正常例的唯一 RX / file offset 0 / vnode 匹配地址等于探针进程自身 dyld image0 地址。重复例出现两个候选，可保守拒绝。搬移例对同文件创建另一个 RX 映射，再成功解除原主 __TEXT；PID、出生、PPID、路径和 vnode 不变，剩下唯一候选是人为新映射。

为避免只依赖进程自报地址作结论，随后在同一个搬移进程调用了未修改的正式 `observe_process`。记录在 `existing-observe-comparison.json`，对应原始 vmmap 输出为 `relocated-original-vmmap.txt`：

- libproc 只剩地址 `4367564800`（RX、offset 0、原文件 dev/inode）的候选。
- 正式 vmmap 输出的 `Load Address` 为 `0x1041d4000`（十进制 `4363993088`）。探针进程通过 dyld image0 自报的 `self_main_address` 为 `0x1041d0000`（十进制 `4363976704`）；两者来自不同采集接口，不能写成同一个地址。
- 正式 `observe_process` 在 1.693 秒返回 `PROCESS_IMAGE_AMBIGUOUS_MAIN_IMAGE`，不是超时。
- 目标正常退出 0，未挂住或影响其他进程。

因此，完整枚举加唯一候选也不能等价于现有主映像 load 校验。增加文件 hash、BSDINFO 前后观察不会区分这个稳定反例。不能用该替代宣布修复，也不应通过放宽主映像含义解决。

另有已确认的格式约束：本机 `mach-o/fat.h` 的 `fat_arch.offset` / `fat_arch_64.offset` 定义 slice 在文件中的偏移，`loader.h` 的 segment `fileoff` 是切片内段偏移。通用实现不能一律只允许原文件 offset 0。本轮只测 thin arm64 Python，不假称 FAT / x86_64 兼容已完成；已有决定性反例，无须为这条方案扩写完整 Mach-O 解析系统。

当前结论：无需继续扩大该原型。若后续找到可信主 load 来源，可保留同一有界辅助进程内的 REGIONPATHINFO 定点复核 vnode、保护位及范围；否则明确保持阻断，不提升 task port 权限、不新增系统依赖、不延长 5 / 16 / 60 秒限制。

## 原始来源

- [Apple XNU proc_info.c，xnu-11417.140.69](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/bsd/kern/proc_info.c)：`proc_pidregionpathinfo`、`proc_pidregionpath`。
- [Apple XNU syscalls.master，同标签](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/bsd/kern/syscalls.master)：task inspect / read 的参数签名。
- [Apple XNU kern_proc.c，同标签](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/bsd/kern/kern_proc.c)：task read 路线包含 POSIX、MAC 和 taskgated 检查。
- [Apple XNU task.defs，同标签](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/osfmk/mach/task.defs)：task_info。
- [Apple XNU mach_vm.defs，同标签](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/osfmk/mach/mach_vm.defs)：mach_vm_read_overwrite 接受 vm_map_read_t。

该 Apple 标签属于本机内核版本家族，未把其视为本机 Apple 私有补丁版本的逐字一致源码。实际可用性以本轮本机探针为准。

- [Apple XNU bsd_vm.c，同标签](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/osfmk/vm/bsd_vm.c)：公开区域路径接口的递进、终止与页统计；onlymappedvnodes 分支跳过 submap。
- [Apple XNU proc_info_private.h，同标签](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/bsd/sys/proc_info_private.h)：私有 flavor22 和31的常量。
