# 原生几何输出采集器：本轮交付

本批仅新增采集器、controller 镜像及其定向测试。未修改 addon、Host、Registry、正式进程测试或共享状态说明；未提交、推送或启动真实 DCC。

## 接口

```python
from houdini_bridge import native_geometry_observation as observer
fact = observer.collect(already_acquired_geometry,
                        node_path='/obj/owned/actual_output', frame=1,
                        output_index=0)
```

采集器不取得 node.geometry、不 cook、不改帧、不生成期望 deformation、不签发 AVAILABLE/PASS。调用方认证 node_path/frame/output，控制取得 geometry 的授权及原生调用时间。

返回 JSON 对象：

- `schema='bridge.geometry-observation/1'`、`origin='runtime_hom'`、`node_path`、`frame`、`output`。
- `attribute_scope='public'`：枚举 HOM 四类公开属性。私有属性、分组和 packed/volume 内部内容不在覆盖范围，不能据此签发“全部几何保持”。
- `points/primitives/vertices`：实际数量；`point_numbers/primitive_numbers`：实际返回顺序的原生编号。
- `primitive_types/primitive_closed`：实际 primitive 类型与 closed 状态。
- `polygons`：连接映射到 `point_numbers` 数组索引，不把原生 point number 当作数组索引。
- `polygon_vertices`：每个 primitive 的 vertex 对应采集顺序索引；`vertex_numbers`：实际 detail-wide linearNumber。vertex 属性值按 primitive 遍历顺序排列。
- `attributes[point|primitive|vertex|detail][name]`：`owner/type/size/precision/is_array/qualifier/transformed_as_normal/default/options/values`。detail 的 `values` 为一项数组；数值 tuple 转成 JSON 数组。所有值从底层原生 API 读取。
- 不存在的 P/N/id 不添加，不以位置、公式或默认值补齐。

`CONTENT_FIELDS` 导出数据内容字段名。`geometry_sha256` 对这些字段的 canonical JSON（UTF-8、ensure_ascii=False、sort_keys=True、separators=(',', ':'), allow_nan=False）求 SHA256，不含 node_path/frame/output。`observation_sha256` 对完整包装（包含 geometry_sha256，但不含 observation_sha256 自身）求 SHA256。不同路径、帧或输出口的相同实际内容可以比较 geometry_sha256。内容摘要本身不证明身份、cook 成功或消费语义。

## 有界拒绝

`MAX_BYTES=524288` 是完整单次返回 JSON（含两种摘要）的 512 KiB 上限。点/primitive 各 8192，vertex 总计 65536；四类属性累计 256；数值 tuple 最多 64 项；原生值与元数据累计 1,048,576 标量；单字符串 4096 UTF-8 字节、累计字符串 1,048,576 字节；单属性 options 最多 64 项。累计值预算在值读取前预留，超限抛错后不继续读取本次其余数据。迭代器最多取得 cap+1 项后拒绝，不无限耗尽。

frame bundle 512 KiB、整体 2 MiB 预算和跨 collect 中止由主 addon 管理，本模块不缓存或跨请求重置任何全局预算。原生 API 内部的阻塞时间由现有宿主监督器控制。

支持文档明确的 Int8/UInt8/Int16/Int32/Int64/Float16/Float32/Float64 普通数值、普通 size=1 string。字符串不调用 numericDataType。数字 precision 读取实际 Attrib.numericDataType 并验证值类型与范围。除普通 Polygon 外的 packed/volume/VDB/曲线等 primitive、数组、dictionary、未知 storage、nonfinite、异常 tuple/owner/value、重复编号和悬空连接均明确拒绝。属性读取前后核对实际元数据，类型或元数据漂移拒绝。采集器不宣称并发原子几何快照；调用方仍需身份/帧/输入 fencing。

异常 `GeometryObservationError.code` 取自导出的 `ERROR_CODES`：

```
GEOMETRY_OBSERVATION_NATIVE_READ_FAILED
GEOMETRY_OBSERVATION_BUDGET_EXCEEDED
GEOMETRY_OBSERVATION_UNSUPPORTED_TYPE
GEOMETRY_OBSERVATION_INVALID_TOPOLOGY
GEOMETRY_OBSERVATION_INVALID_VALUE
GEOMETRY_OBSERVATION_NONFINITE_VALUE
GEOMETRY_OBSERVATION_ATTRIBUTE_TYPE_CHANGED
GEOMETRY_OBSERVATION_INVALID_METADATA
GEOMETRY_OBSERVATION_UNSUPPORTED_ATTRIBUTE
GEOMETRY_OBSERVATION_UNSUPPORTED_ARRAY
GEOMETRY_OBSERVATION_UNSUPPORTED_STORAGE
GEOMETRY_OBSERVATION_UNSUPPORTED_METADATA
GEOMETRY_OBSERVATION_INVALID_CONTEXT
GEOMETRY_OBSERVATION_UNSUPPORTED_PRIMITIVE
```

异常文本固定为 `<code>: native geometry observation refused`；不拼接 native exception、路径、属性名称或值，异常链抑制原始 native 内容。

## 静态夹具

主测试可导入 `test_native_geometry_observation.NativeGeometry(version='21.0.631')` 或 `'22.0.429'`。版本标记仅用于底层软件夹具，不构成真实 native version 证据。三点三角形 P/N/id/label、primitive 整数 pair、vertex uv、detail title 都是显式静态值，不按 deformation 公式计算。point 原生编号是 `[10,30,20]`，连接为 `[1,2,0]`，vertex linear 编号为 `[2,0,1]`。可通过 `point_elements[*].values`、`primitive_elements[*].vertex_elements/closed/kind`、`attributes[owner]` 和 `detail_values` 构造反例。

## 验证

实际命令：

```powershell
.venv/Scripts/python.exe -B outputs/geometry-observation-20261013/agent-collector/validate-collector-20261013.py
```

最终原始日志：`unit-final-20261013T105457135896Z/unittest.log`；报告：同目录 `summary.json`。27 methods、0 failures、0 errors、0 skips，0.172 秒，退出码 0。解释器 Python 3.11.9，Windows-10-10.0.26300-SP0。三份所属源码测试前后 SHA 不变；两个生产镜像字节相同。历史 `unit-v1-*` 24 项测试保留，仅最终报告绑定当前源码。

最终生产镜像 SHA256：`787fe82c90487ecc57024ef5cf3a8f2057be744d0bcf8c65a7b58424ff5c8e9c`。
最终测试 SHA256：`3c308c25fbccaac319bb1a3c6ed8e6f594cad611a41b21d78958be1522ddccfe`。

覆盖四类属性、实际 metadata、非序号连接映射、缺 N/id、拓扑/N/extras 修改可见、保留属性可比较、数据/包装摘要分离、完整 JSON 字节边界、全 numericData 枚举、unsupported 类型与存储、nonfinite、所有无穷迭代器、累计预算、读值前拒绝与 native 异常不泄露。所有正常值都是明确底层 API fixture；实际 VEX、跨帧 cook、宿主输出、下游消费、视觉验收和真实 DCC 保持 NOT_RUN/BLOCKED。

接口依据：本地 `docs/native-basis/hom-attribute-numeric-storage-static.json` 的两版同 build 静态 HOM 文档；另外核对 [Attrib](https://www.sidefx.com/docs/houdini/hom/hou/Attrib.html)、[Geometry](https://www.sidefx.com/docs/houdini/hom/hou/Geometry.html)、[Vertex](https://www.sidefx.com/docs/houdini/hom/hou/Vertex.html) 和 [Polygon](https://www.sidefx.com/docs/houdini/hom/hou/Polygon.html) 官方公开接口。
