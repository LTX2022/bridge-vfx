# H21 同版环境与启动依据核查

核查者 /root/native_startup_static。两driver共享GraphJobService worker环境；均清除外部Python/Houdini搜索变量，设置独立tmp/prefs，正式及HIP host warmup=False。不存在被新诊断遗漏的既有预热/缓存机制之证据；共同未设HFS/HH/HHP不能被判为单方漏项。

H21.0.631本机help、setup与ready脚本为来源，精确归档/member hash和行范围见h21-native-basis.json。启动自动import hou，存在脚本前初始化；缓存默认启用，未被driver关闭。没有证据证明许可、原厂扫描、冷prefs或路径造成此次83.85秒，更不能称其纯原生startup时间。

未使用H22网页代替H21依据；未跑native/许可证命令/采样或普通Python hou，未修改环境/系统配置。当前不建议source setup、关闭包扫描、强留cache或加warmup，因为缺因果依据。
