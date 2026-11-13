# archive

已弃用文件存放处（仅存档参考，不要使用）。

- `houdini_bridge_v5_tcp9877.py` — v5 旧桥（TCP 9877 JSON-lines 协议）。
  原位于 `~/.zcode/workspace/default/houdini_bridge.py`。**它曾造成包遮蔽**：
  在 default workspace 为工作目录时 `import houdini_bridge` 会命中此文件并
  因 `import hou` 失败。2026-08-24 移入归档后遮蔽消除，现行包
  （`~/.zcode/houdini-bridge`，editable 安装）正常解析。
- `houdini_bridge_v5_duplicate.py` — 同一 v5 文件在 skill 目录里的第二份拷贝。

现行协议是 HTTP（hwebserver 8100+），见 `../bridge-protocol.md`。
