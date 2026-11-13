# 实际 writer 采集接口核查

日期：2026-10-16。范围：Houdini 21.0.631／22.0.459 安装随附官方帮助、SDK头文件、C++样例、Python源码和配置；官方滚动HDK网页只作补充。未启动Houdini/hython/husk、Nuke、WorkBuddy/HY3或模型，未cook、仿真、缓存、渲染、编译或加载DSO。

**结论：找到公开的阶段性观察／扩展接点，但尚未找到可在当前正式链中绑定实际磁盘writer并完整取得所需最终事实的接点。AVAILABLE的实现前提仍未满足，工程闭环保持BLOCKED。** 本轮不改生产代码、登记门槛、真实索引或已有修复，不运行无关软件回归。

## 已确证的候选与适用范围

| 接点 | 同版源码依据 | 可获得的内容 | 尚不能证明的内容 |
|---|---|---|---|
| TIL图像滤镜 | `TIL_RasterFilter.h:37–55,174,200–203`；官方`TIL_NullFilter.C:72,128–140`及样例头说明 | 自定义滤镜在被调用时可观察`apply(PXL_Raster*)`的输入；输入raster、尺寸、格式、packing及辅助AOV。两版接口一致 | 自定义观察器是否已正确装入当前husk保存链、最终产品/帧绑定、其他滤镜完整执行顺序及其后writer变换。只有声明/样例，没有当前Bridge运行事实 |
| BRAY图像滤镜 | `BRAY_ImageFilter.h`两版及`BRAY_FilterBase.h` | `getAOVs`和`processImage`提供可用AOV与读写raster；阶段在pixel filtering后、display输出前，bucket先于whole-image | 没有writer路径/processor参数；`instancePlugin()`创建新实例，不是发现当前内建实例 |
| husk图像设备 | `TIL_HuskDevice.h:27–52,76–107` | 可注册默认display factory；create接收stat/parms，update另接收rasters | 明确是display接点，不是已证明的磁盘writer终态观察。H21的update没有save_rasters；H22增加该索引参数，不能跨版复用签名 |
| IMG tile/file设备 | `IMG_TileDevice.h:51–101`；`IMG_TileFile.h:78–103` | 已持有实际`IMG_TileFile`时，`files()`能取得`IMG_File`对象链，随后可读class/stat/metadata/部分file options | **关键前提未确证：当前husk如何把正在使用的tilefile/writer实例交给采集代码。** 注册creator是创建新设备，不是检索既有对象 |
| 格式writer工厂 | `IMG_Format.h`；官方`IMG_Sample.C:118–121,321–323` | `newIMGFormat/createFile`正式支持构建自己的writer，并在自己的create/write/close阶段观测 | 不提供既有默认OpenEXR writer的发现接口；采用它会新增组件并改变输出驱动路线，不能当作当前链已有观察器 |
| 统计与最终文件 | 精确`UsdRenderers.json`、`karma_stats.py`；`solaris.zip!stats.txt/tiles.txt` | verbose脚本解析verbosity、mode及JSON stats；Karma配置把frame/command/render_stats等映射到EXR。最终EXR可按官方iinfo途径读统计与intrinsic信息并绑定字节hash | stats/自定义metadata不等于writer processor/filter/alpha实效；原生工具本轮未执行。精确Python源码只解析mode，未给出writer终态语义，不能据此证明成功写盘/停止 |

已按两版`SYS/SYS_Version.h`中的MAJOR/MINOR/BUILD静态宏确认目标标记；HDK API兼容号单独记录，不把它当产品build，也未验证运行时版本。两版原件相对安装Resources目录，完整路径、SHA、字节数见 [来源索引](evidence/20261016-writer-interfaces/native-interfaces.json)。`IMG_File/PXL_OCIO`基础声明另见[前轮精确索引](evidence/20261016-writer-chain/native-basis.json)。这里核查的是公开声明、官方样例及随附Python源码；所查SDK未提供husk/Karma调用上述writer工厂的完整实现，不称为已读完渲染器源码。

官方在线补充：[TIL滤镜接口](https://www.sidefx.com/docs/hdk/class_t_i_l___raster_filter.html)、[husk设备接口](https://www.sidefx.com/docs/hdk/class_t_i_l___husk_device.html)、[USD/Hydra集成](https://www.sidefx.com/docs/hdk/_h_d_k__u_s_d_hydra.html)、[图像格式扩展](https://www.sidefx.com/docs/hdk/_h_d_k__image__extend.html)。网页为滚动文档，不能代替精确build的原件或运行事实。

## 不能用于解除登记阻断的接口

- `IMG_FormatPassThru`保存调用方提供的父writer，并不寻找当前writer。其构造不加入format列表，`createFile()`返回nullptr；不能把它当作透明截获OpenEXR的现成方案。
- `IMG_File::setFileCreateCB`仅传文件名，不传writer对象；文件读取hooks围绕`UT_IStream`。通用`UT_DSO`的void*参数也不能推定为writer。
- `IMG_FileFilterLUT`的实际ocioHandle、processor handles和scope为private；公开声明未给出能报告这些执行信息的dump。旁建OCIO processor或读取父进程配置不能证明它被该writer使用。
- `PXL_Raster`颜色标记、hasAlpha和premultiply/unpremultiply动作，不提供最终图像当前关联alpha状态的已证实getter；alpha值类别不等于关联语义。
- `formatNeedsPremultiplied()`只在本机H22的IMG_File声明中存在；即使取得实际对象，它也表示格式需求，不是最终beauty实际状态。
- 自填metadata可做关联标记；USD trace可报告函数耗时；IMAGE_DEBUG可辅助错误诊断。它们均不自动提供完整processor/filter/alpha执行事实。

## 版本及调用边界

H21随附Python源码位于`python3.11libs`，H22位于`python3.13libs`，这是静态文件布局，不是本轮运行时版本验证。两版`karma_stats.State.parseArguments`均读取argv[1]、argv[2]及json.loads(argv[3])；`runprocedurals.py`把husk提供的settings继续传给procedural，没有定义其完整writer状态schema；`husktrace.py`只启停和导出USD Trace。

H22精确`inside_husk.txt`区分raster由husk保存、其他产品由delegate处理；两版Karma配置将deep/checkpoint列为delegate-owned。现有最小普通EXR链不能自动外推为所有输出类型的采集证据。

## 实施前仍须确认的四项

1. **实例绑定：**当前husk的实际`IMG_TileFile/IMG_File`交接点，包含产品/帧/输出路径/生命周期；必须区分创建另一对象和观察正在使用的对象。
2. **处理器：**实际writer消费的processor及其配置/LUT/context/file-rule、输出覆盖和逐AOV范围的合法观测接口；仅有创建参数或配置重建不足。
3. **执行次序：**本次输出所有适用滤镜实际执行、次序及完成的证据，并覆盖后续writer转换；仅看到自定义滤镜一次apply不足。
4. **alpha与终态：**该输出beauty实际关联语义、保存成功/可信停止及最终字节绑定，不能从通道存在、alpha像素类别或统计end推导。

本轮确认的public接点只覆盖其中部分阶段，因此没有增加未接通的AVAILABLE归约器或可由模型提交“可信事实”的入口。待这些接口及传播关系有同版依据后，再在既有producer／终态签名／ArtifactRegistry／Nuke链实现和验证。若采用自定义writer或设备，需要明确其接口、依赖和输出语义，并作为新组件单独设计验证；不悄悄替换当前路线。

## 复核与状态

本轮产物仅为本报告、静态来源与核验记录。可重复的[静态校验脚本](evidence/20261016-writer-interfaces/verify-static-sources.py)只读指定文本/ZIP成员并比对SHA，不导入厂商模块、不执行原生程序。它验证来源字节，不验证接口可用、安装加载或效果。

未参与本轮研究的审查者独立读取并核对60项来源，关键接口和边界结论一致；两处回调措辞已按声明修正。本结论仅为静态资料复核。

独立限定复核与最终保留检查见 [复核](evidence/20261016-writer-interfaces/review.md)、[文件保留记录](evidence/20261016-writer-interfaces/preservation.json)。本轮没有新的软件测试通过数；此前38项属于前轮软件改动，不充作本轮原生接口通过。AVAILABLE生产路径、真实Karma产物登记及真实Nuke消费仍未完成。未提交／推送Git，未改Desktop主工程，原全域铺开方案继续冻结。
