# 坐标轴规则修复真实结果（2026-10-27）

axis-20261027-01经65项受控软件回归、独立边界复审、完整冻结核验和激活预检后，在用户持续执行授权下运行一次。

真实warm保存、cold加载/导出、USD语义比较以及official-husk参考渲染均完成。原始upAxis事实与哈希保留；冷导出回执记录显式policy及fallback-Y表示等价。最终封存观测失败：验证器将原生Menu[2]错误预期为String['UsdLuxDiskLight']。

三次原生进程已可信停止，合计94.67884111404419秒；范围ENGINEERING_DRIVER_FAILED关闭，零自动重试，余额不可复用。完整冷热观测相等，176冻结源不变，根目录123716647字节。官方累计21启动／539.3666749000549秒。

官方参考EXR96471字节已生成；离线真实解码验证为420×300 RGBA HALF、504000样本，自比较完全一致。这不是官方与Bridge对照通过；封存失败，alpha/Bridge/NK/Nuke尚未到达，人工视觉未验收。

静态原source HIP菜单显示lighttype为ordinal，Cylinder、Distant、Disk、Point、Rectangle、Sphere依次，序号2对应UsdLuxDiskLight/Disk。真实观测Menu[2]、唯一USD DiskLight一致。软件最小修复将关键字段合同改Menu[2]，保留同版本/源绑定和重建模板哈希检查。新增错误序号、String、浮点和模板漂移测试；66项软件回归通过，已有真实31节点观测经当前验证器离线通过。

[签名停止与产物认证](evidence/20261027-export-axis-live-01/result.json)。所有历史scope、原始观测、回执和签名不改写；新menu范围另行冻结执行。
