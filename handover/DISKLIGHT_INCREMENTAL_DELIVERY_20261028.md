# DiskLight 增量真实使用交付（2026-10-28）

可直接使用和学习的文件已交付到 `outputs/Bridge-learning-20261028/`。入口为 [START_HERE](../START_HERE.md)和[交付说明](../outputs/Bridge-learning-20261028/README.md)。

## 当前最终文件

- `disklight-rebuilt.hip`：807825字节。SHA-256 `65df5466627ad21a3fecc1c04a94e08257b85d3be9cde565f8398b8db548d1de`。
- `disklight-rebuilt.usd`：17442字节。
- `disklight-rebuilt.0001.exr`：96218字节。
- `disklight-comparison-final.nk`：2572字节。SHA-256 `ff4720438131c81758fb3c5ac75f1411b02834cdb1e904fdd7d834b9a0365516`。
- `disklight-nuke-final.0001.exr`：96444字节。
- `disklight-preview.png`：29666字节，仅显示处理，原始EXR不改。

完整身份与来源见交付目录 `delivery-result.json`。旧NK、缺色彩元数据的早期EXR、检查点与失败记录保留；最终交付只以上述文件为准。

## 已实际完成

Houdini21.0.631、KarmaCPU、Nuke17.0v1，frame1、420×300、RGBA HALF、ACEScg。

从已有封存参数和官方HIP附加参数模板重建：读取模板后清空原场景，新建布局节点，继续检查点参数写入，1515项参数读回与stage语义比较通过。最终HIP由独立Houdini进程冷开，`load_warning=null`，有效stage比较PASS，文件字节未变。重建USD以husk实际渲染成功。

最终NK在独立Nuke进程冷开，实际执行Write_RGBA输出；Read/Write均ACEScg，Write保留all metadata，输出物理EXR带 `oiio:ColorSpace=lin_ap1`。官方参考→重建、重建→Nuke分别504000个RGBA样本逐一相同，RGB nRMSE、alphaMAE/P99均0。

预览使用已有H21 OCIO的ACES1.0 SDR/sRGB显示和+2.25EV，棋盘格背景。人工视觉与审美接收仍由用户直接观看判断，不代签。

## 增量执行与限制

用户2026-10-28明确取消每次修复的整组软件验证/冻结审查及从头重跑正式链，要求仅运行修改处。该约定已写入AGENTS.md顶部并保存共享记忆。此次复用官方参考、封存输入和原生alpha；失败处保存中间HIP后继续，仅重建、保存、冷开、渲染和Nuke消费相关步骤实际执行。

12次独立增量进程，累计112.710266秒，7项成功、5次调试步骤失败，均由父进程wait确认退出，无超时、无自动重试。没有新正式签名回执；本次不是旧正式GraphRun的签名登记验收。旧query2正式范围仍以34COMPLETE/1INTENT超时关闭保留，不改写成功；ArtifactRegistry未新增正式接收。当前交付实现的是用户要求的可实际打开、比较和学习的原生文件。

完整场景捕获限额读取优化只做了两处函数的AST定向检查：每次捕获前后各读一次限额、节点循环内不重复认证；未对该优化单独声明真实性能通过。没有重跑整组测试或新冻结审查，没有修改旧冻结源码。

本机依赖：参考目录 `outputs/official-karma-disklight-h21-query2-20261027-01`，已安装Houdini及其OCIO、Nuke；NK使用绝对路径，跨机迁移未验证。整个增量目录约3MiB，不重复复制官方素材。未提交或推送。
