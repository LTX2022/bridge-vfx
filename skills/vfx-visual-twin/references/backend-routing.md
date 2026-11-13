# DCC backend routing

Route domain work through the capability-probed `DccBackend` selected by the
pipeline. Current backends are the authenticated Houdini HTTP Bridge and Nuke
Bridge. Backend identity and session provenance travel with every route leg.

Treat a future SideFX MCP as optional. It is usable only after the connector
proves `sidefx.mcp`, official-provider identity, session/source identity and
the required capabilities. An unavailable or incomplete negotiation is
`UNSUPPORTED`; never replace it with guessed tools or arbitrary code.
