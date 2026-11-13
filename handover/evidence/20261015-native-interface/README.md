# H21只读接口观察

用户于2026-10-15明确批准一次最多20秒的hython只读参数采集。实际约5.46秒生成140项Driver/usdrender定义，未建节点、cook、仿真、缓存或渲染。捕获原件及脚本hash见index.json。

已观察到husk pre/post-frame的机器参数名与模板类型；没有执行hook，不声称知道实际husk_command具体类型、settings键、writer、OCIO/filter或alpha事实。H22.0.459未用于替代22.0.429。

监督器缺少签名停止回执；28秒等待超时，之后OS只读观察表明原PID和进程组不存在。此观察不能补签原始child wait，也不作为任何任务恢复/产物登记成功。另已用纯Python父子进程验证并修复POSIX监督窗口；尚未证明该窗口就是本次停止回执缺失的原因，旧回执保持缺失。采集启动警告HOUDINI_USER_PREF_DIR需要__HVER__，后续如需新的原生采集，应另获具体授权并修正该路径；不删除或覆盖既有用户偏好。
