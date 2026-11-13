# Houdini 工程/资产格式转换

对齐 `Houdini_agent/app/backend/asset_tools/`（`runner.py` / `license.py`）及 force-hipnc 工具逆向。

## 关键：扩展名 ≠ 许可等级

Houdini 按**文件头许可标记**决定会话，不按后缀：

| 文件头 | 含义 | 打开后 |
|---|---|---|
| `HouLC\x1a...` | Limited Commercial（Indie） | `Entered limited commercial session mode.` |
| `HouNC...` 等 | Non-Commercial | Apprentice / NC 会话 |
| `07070700...` (CPIO) | Full Commercial | 正常 FX/Core 会话 |

## 两种转换方式对比

| 方法 | 脚本 | 结果文件头 | 打开提示 LC? |
|---|---|---|---|
| **旧：hython 另存** | `convert_hiplc_to_hip.py` | `HouLC` (保留) | **是** |
| **新：opscript+cmdread** | `convert_hiplc_to_hip_full.py` | `07070700` (CPIO) | **否** |

旧方法只改扩展名/压缩形态，不去 LC 标记。新方法通过 opscript 导出纯文本场景再重建，彻底去掉 LC 头。

## 决策树

1. 要**完美转换**（去 LC 头，打开不提示限商）-> `convert_hiplc_to_hip_full.py`
2. 只要「能打开、能学节点」-> 直接开 `.hiplc` 或旧方法另存的 `.hip`（都会进 LC）即可
3. 后缀是 `.hdalc` -> hython：`scripts/convert_hdalc_to_hda.py`（**不解除 LC**）
4. 后缀是 `.hipnc` / `.hdanc` -> `convert_hiplc_to_hip_full.py` 或 force-hipnc exe
5. 已是完整商业 `.hip` / `.hda`（头是 `07070700`，非 HouLC/HouNC）-> 无需转换

## 完美转换：hiplc -> hip（去 LC 头）

### 原理（逆向自 force-hipnc 工具）

force-hipnc 工具内部用两步 Python 脚本实现：

**test1.py**（导出）:
```python
hou.hipFile.load(source, ignore_load_warnings=True)
hou.hscript(f'opscript -G -r / > "{temp_dir}/{name}"')
hou.exit()
```

**test2.py**（重建+保存）:
```python
hou.hipFile.clear()
hou.hscript(f'cmdread "{temp_dir}/{name}"')
hou.hipFile.save(f'{output_dir}/{name}.hip')
hou.hipFile.clear()
```

关键：`opscript -G -r /` 把整个场景树导出为 HScript 文本命令；`cmdread` 从文本重建场景；保存后的 `.hip` 文件头为标准 CPIO 格式（`07070700`），不含 `HouLC` 或 `LIMITED_COMMERCIAL_FILE` 标记。

### 用法

```powershell
$hy = "C:\Program Files\Side Effects Software\Houdini 21.0.631\bin\hython.exe"
$skill = "$env:USERPROFILE\.zcode\skills\houdini-bridge\scripts"

# 单文件转换
& $hy "$skill\convert_hiplc_to_hip_full.py" "C:\path\scene.hiplc" "C:\path\scene.hip"

# 批量转换（整个目录的 .hiplc）
& $hy "$skill\convert_hiplc_to_hip_full.py" "C:\path\hiplc_dir"

# 也兼容 .hipnc 文件
& $hy "$skill\convert_hiplc_to_hip_full.py" "C:\path\scene.hipnc" "C:\path\scene.hip"
```

### 验证

```powershell
# 检查文件头：07070700 = 商业版，HouLC = 仍限商
Format-Hex "C:\path\scene.hip" -Count 8
```

- `07070700...` -> 转换成功，打开不会进 LC
- `HouLC...` -> 转换失败，检查 Houdini 版本是否匹配

### 注意事项

- 优先用**独立 hython**，避免弄乱用户正在编辑的会话。
- 大文件可能 1-2 分钟；opscript 导出的文本中间文件在临时目录中，完成后自动清理。
- 转换后 `.hip` 可在任意商业版 Houdini 中打开，不再触发 LC 会话。
- 若场景含加密 HDA，opscript 可能无法完整导出，需先解锁 HDA。

## 旧方法：hiplc -> hip（仅改扩展名，保留 LC）

```python
import sys
import hou
source_path, output_path = sys.argv[1], sys.argv[2]
hou.hipFile.load(source_path, suppress_save_prompt=True)
hou.hipFile.save(file_name=output_path)
```

```powershell
& $hy "$skill\convert_hiplc_to_hip.py" "C:\path\scene.hiplc" "C:\path\scene.hip"
```

- 加载时 `Entered limited commercial session mode.` **正常**（源就是 LC）。
- 另存后的 `.hip` 再打开仍会进 LC -- **正常**。
- 适用于只需非压缩 `.hip` 扩展名的场景。

## hdalc -> hda

```python
import sys
import hou
source_path, output_path = sys.argv[1], sys.argv[2]
definitions = hou.hda.definitionsInFile(source_path)
if not definitions:
    raise RuntimeError("No HDA definitions found in source file")
definitions[0].save(file_name=output_path, template_node=None, options=hou.hdaSaveOptions())
```

```powershell
& $hy "$skill\convert_hdalc_to_hda.py" "C:\path\asset.hdalc" "C:\path\asset.hda"
```

多 definition 时默认保存第一个；若需全部，循环 `definitions` 并分文件写出。

## hipnc / hdanc 解锁

### 方法 1：convert_hiplc_to_hip_full.py（推荐，同原理）

```powershell
& $hy "$skill\convert_hiplc_to_hip_full.py" "C:\path\scene.hipnc" "C:\path\scene.hip"
```

### 方法 2：force-hipnc 解锁 exe

```text
C:\Users\<USERNAME>\Documents\WORK\Tools\force-hipnc转换工具-输入houdini版本号-输入hipnc文件夹路径-解锁.exe
```

用法（工具交互提示）：

1. 输入目标 **Houdini 版本号**（如 `21.0.631`）
2. 输入含 `.hipnc`（或对应 NC 文件）的**文件夹路径**
3. 等待解锁完成后再用对应版本 Houdini 打开

`.hdanc` 通常与 hipnc 同类 NC 资产流程；若工具只扫 hipnc，把 hdanc 放同目录或按工具说明操作。

## 许可证 class 表

| suffix | license_class | convertible_to | 完美去头? |
|---|---|---|---|
| `.hip` | hip_uncompressed | - | - |
| `.hiplc` | hiplc_compressed_hip | `.hip` | ✅ `convert_hiplc_to_hip_full.py` |
| `.hipnc` | hipnc_non_commercial | `.hip` | ✅ `convert_hiplc_to_hip_full.py` / force-hipnc |
| `.hda` | hda_uncompressed | - | - |
| `.hdalc` | hdalc_compressed_hda | `.hda` | ❌ 仅 hython 另存 |
| `.hdanc` | hdanc_non_commercial | `.hda` | force-hipnc |

## 失败排查

| 现象 | 处理 |
|---|---|
| 找不到 hython | 扫 `C:\Program Files\Side Effects Software\Houdini *\bin\hython.exe`，版本尽量对齐 |
| hiplc 打不开 | Apprentice/无 LC 许可；换商业或限商许可 |
| 转换后仍为 HouLC | 确认 hython 版本与文件版本匹配；检查场景是否含加密 HDA |
| opscript 导出不全 | 场景含加密/锁定 HDA，先解锁再转换 |
| force-hipnc 处理 hiplc | 改用 `convert_hiplc_to_hip_full.py`（同原理） |
| bridge 超时 | 转换用独立 hython，勿占用户会话 cook |
| 路径含中文 | force-hipnc 不支持中文路径；hython 脚本无此限制 |
