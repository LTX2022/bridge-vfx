# Bounded AOV output collector repair — 2026-10-13

Scope: pure software collector repair and bottom USD API tests. No Houdini,
hython, husk, Nuke, native bindings, formal host tests, rendering, simulation,
cache, model or HY3 execution. Installed files were read only. Mirrors and
repository docs are left to the main implementer.

## Exact installed native basis

Verified both installed builds, `21.0.631` and `22.0.429`, under
`C:/Program Files/Side Effects Software/Houdini <version>`.
Full absolute paths, file/member SHA-256 and numbered declarations/excerpts
are in [collector-native-basis.json](collector-native-basis.json).

| RenderVar property | Native USD type | H21 schema / generated line | H22 schema / generated line |
|---|---|---|---|
| `driver:parameters:aov:karma:filter` | `string` | 841 / 739 | 827 / 824 |
| `driver:parameters:aov:husk:format` | `token` | 44 / 25 | 49 / 36 |
| `driver:parameters:aov:husk:channel_prefix` | `string` | 32 / 13 | 37 / 22 |
| `driver:parameters:aov:husk:channel_lower_rgb` | `bool` | 27 / 8 | 32 / 15 |

Schema paths relative to each installation:

- Karma: `houdini/dso/usd_plugins/usdKarma/resources/usdKarma/schema.usda`
  and `houdini/dso/usd_plugins/usdKarma/resources/generatedSchema.usda`.
- Husk: `houdini/dso/usd_plugins/usdHusk/resources/usdHusk/schema.usda`
  and `houdini/dso/usd_plugins/usdHusk/resources/generatedSchema.usda`.
- Help: `houdini/help/nodes.zip!lop/rendervar.txt`.

The help's `karma:plane:filter` at line 91 is a documentation anchor;
the actual schema property is `driver:parameters:aov:karma:filter`.
Neither build's examined Karma/Husk schemas or RenderVar help declares
`channel_layout`. Do not invent `driver:parameters:aov:husk:channel_layout`
or a native type for it. Channel naming observations use the verified,
existing `channel_prefix` and `channel_lower_rgb`, alongside the newly read
format. These configuration values do not prove final EXR channel layout.

Read existing `handover/evidence/20261010/closure/native-output/REPORT.md`
and `docs/native-basis/lop-render-hda-followup.json`,
`w1-sopimport-usdrender-static.json`, and
`usdrender-renderer-machine-field-audit.json`. Direct installed declarations
resolve the help-anchor ambiguity; no schema fallback was supplied by code.

## Changed implementation paths

- `packages/houdini-bridge/src/houdini_bridge/render_color_facts.py`:
  add the native token format and replace the unsupported help-anchor lookup
  with the native string filter lookup. Product source/output color collection
  is unchanged. Existing identity checks, authored state, `Get(frame)`, strict
  types, 8192-character bounds, shared 128-target budget and missing/None/empty
  gaps apply unchanged. Filter strings remain raw, including malformed JSON.
- `tests/unit/test_render_color_facts.py`: six new bottom API tests cover
  independent AOV/frame samples, authored/fallback state, absent/None/empty
  gaps, wrong native and payload types, 8192/8193-character boundaries,
  corrupt filter preservation and rejection of undocumented property aliases.
  All 26 original tests remain.

No other source, mirror or repository documentation file was changed by this
implementer. Other agents' worktree changes are outside this report's scope.

## Actual scoped verification

Interpreter: repository `.venv/Scripts/python.exe`, Python 3.11.9.
Command, captured by the existing `tools/run_logged.py` wrapper:

```text
.venv/Scripts/python.exe -B -m unittest discover -s tests/unit -p test_render_color_facts.py -v
```

- Before collector repair, with the new tests present: 32 methods,
  1 failure and 21 errors (including subtest errors), exit 1.
  [Before log](collector-before-20261013-122057.log).
  Missing real filter/format observations and their absent `Get(frame)` calls
  reproduced the collector omission.
- After repair: 32 methods, all passed, zero skips, exit 0; unittest 0.014s,
  wrapper wall time 0.423s.
  [After log](collector-after-20261013-122223.log).
- Scoped `git diff --check` passed. No broader suite or formal host test ran.

Final scoped SHA-256:

- Collector: `84754cd9d7d4119973d7f3cc40a6d66d008f8176e531b1e905124956c8e16bb2`.
- Tests: `09be747edc0a685dbb1a1ae634807cff8285834a5c5b515f16c86a9e19442a6a`.

Software observations/rejection tests passed only. Runtime alpha association,
effective OCIO and filter execution remain BLOCKED through the existing
missing-fact codes. No metadata PASS, completion status or defaults were added.
Installed/static declarations are verified; installation acceptance, real
host, HY3/model, visual and production acceptance are NOT_RUN.
