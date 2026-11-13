# Bridge Protocol (HTTP)

Houdini runs `hwebserver` on `127.0.0.1:8100+` when the app launches. The
package ships idempotent `scripts/123.py` and `scripts/456.py` hooks so both
new empty scenes and opened hip files autostart the Bridge; this covers Houdini
22 launch paths that skip one of the two lifecycle callbacks. Bound port is written to
`%LOCALAPPDATA%/HoudiniBridge/bridge.port`.

Configured via Houdini **package** only (`packages/houdini_bridge.json`).
`houdini.env` is **not** required and is not modified by install.

## RPC

```
POST /api
Content-Type: application/x-www-form-urlencoded
Body: json=["mcp.health", [], {}]  # legacy-compatible RPC method name
Body: json=["mcp.execute", [], {"command":"scene.info","params":{},"request_id":"..."}]
```

Success: `{"status":"success","data":{...},"timing_ms":12.3}`
Error: `{"status":"error","error":{"code":"...","message":"...","hint":"..."}}`

## Clients (any agent)

```bash
python -m houdini_bridge              # health check
python -m houdini_bridge call scene.info
python -m houdini_bridge doctor
python -m houdini_bridge install
python -m houdini_bridge uninstall
```

This release is a local CLI/HTTP bridge, not a standalone MCP stdio server.

Old TCP JSON-lines on 9877 is **deprecated**.
