# Native output observation discovery — 2026-10-14

Scope: focused static discovery only. Read AGENTS.md, handover/OUTPUT_PREFLIGHT_20261013.md and current README/STATUS/REMAINING/NEXT_AGENT pointers. No DCC, hython, husk, model, simulation, cache, tests or render executed. No production changes. Real phase: **NOT_RUN**. Static documentation availability is not software, installation, host, visual or production acceptance.

## Conclusion

Installed H21.0.631 and H22.0.429 document **husk child-process script hooks** exposing `husk_command`, `stage`, and, at frame hooks, `settings`. These support a future observer inside the existing usdrender-launched husk, without replacing rendering with PDG or reconstructing the command from parent parameters. They do not document the command variable's concrete type/tokenization, the settings dictionary's keys, a writer-instance accessor, resolved per-AOV OCIO processors, completed filter callbacks, or beauty alpha association. These gaps must remain explicit; no AVAILABLE writer metadata can be issued from this discovery.

All ZIP references below are exact existing archive paths plus member names. Line numbers are one-based in member text split on LF, read directly in memory without extracting files. Define installed roots:

- H21 = `C:/Program Files/Side Effects Software/Houdini 21.0.631`
- H22 = `C:/Program Files/Side Effects Software/Houdini 22.0.429`
- Bridge = `C:/Users/32200/Desktop/Agent/skill/Bridge`

## Existing capture and misleading alternatives

`Bridge/docs/native-basis/lop-render-hda-followup.json:3` explicitly records native execution NOT_RUN. H21 core-script entry begins at line 10683; H22 at 21433. Both contain `scripts/out/usdrender.cmd`, source lines 1–17, SHA256 `63a12109739a6a9d5cf99f635e3b25a4370af968f116012aec6ecd1df8973f72`. Original paths in that capture are macOS archive/source provenance, not paths executable on this Windows host. The matching installed files are:

- `C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/scripts/out/usdrender.cmd:13`
- `C:/Program Files/Side Effects Software/Houdini 22.0.429/houdini/scripts/out/usdrender.cmd:13`

Their lines 13–17 initialize the **parent node renderer parameter** from environment defaults. They do not launch husk or expose actual writer facts. The captured operators are Render Product/Settings/Var, Karma Render Products and Component Material interfaces, not a render-launch Python implementation. `Bridge/docs/native-basis/w1-sopimport-usdrender-static.json:87` and `:209` capture output override documentation, not execution observations.

`C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/python3.11libs/usdrenderers.py:10` describes scanning HOUDINI_PATH/UsdRenderers.json into a renderer metadata map. H22's corresponding file is `C:/Program Files/Side Effects Software/Houdini 22.0.429/houdini/python3.13libs/usdrenderers.py`. Neither is the ROP process-launch implementation.

The installed **PDG** source `C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/python3.11libs/pdgjob/usdrender.py:72` builds argv; lines 184–194 append the USD and record a joined command string; lines 196–200 call `subprocess.Popen(argv, ..., shell=False)`. This is a genuine process boundary for that PDG route, but it does not establish that the existing usdrender ROP passes through it. The joined string is not a lossless argv serialization. H22 also has `C:/Program Files/Side Effects Software/Houdini 22.0.429/houdini/python3.13libs/pdgjob/usdrender.py`; its line mapping was not separately established. Focused searches of installed Python/soho sources did not locate a Python launcher for the existing ROP. This is a bounded search result, not proof none exists.

## Supported hooks in the existing ROP/husk route

| Fact/hook | H21 exact archive/member and lines | H22 exact archive/member and lines | Supported boundary |
|---|---|---|---|
| Husk pre-render | `H21/houdini/help/ref.zip::utils/husk.txt:184–189` | `H22/houdini/help/ref.zip::utils/husk.txt:210–215` | `stage`, `husk_command`, first frame via `hou.frame()`; product partitioning follows pre-render. H22 describes selected settings before reading their values; H21 describes before reading settings. Preserve version distinction. |
| Husk pre-frame | `H21/houdini/help/ref.zip::utils/husk.txt:191–202` | `H22/houdini/help/ref.zip::utils/husk.txt:217–228` | `stage`, `settings` dictionary, `husk_command`, current `hou.frame()`. Hook may raise SkipFrame: invocation alone is not rendering completion. |
| Husk post-frame | `H21/houdini/help/ref.zip::utils/husk.txt:211–212` | `H22/houdini/help/ref.zip::utils/husk.txt:237–238` | Same three variables and completed frame number. |
| Post-frame save ordering | `H21/houdini/help/nodes.zip::out/usdrender.txt:328–329` | `H22/houdini/help/nodes.zip::out/usdrender.txt:327–328` | Runs after frame rendering and after all render products are saved. This is a completion location, not a report of internal processing details. |
| Post-load | Not found in inspected H21 husk reference | `H22/houdini/help/ref.zip::utils/husk.txt:207–208`; `H22/houdini/help/nodes.zip::out/usdrender.txt:312–313` | H22-only documented stage-loaded hook; do not backport its availability by assumption. |
| Printed command and child logs | `H21/houdini/help/nodes.zip::out/usdrender.txt:364–365`, `385–403` | `H22/houdini/help/nodes.zip::out/usdrender.txt:363–364`, `384–402` | Command display and stdout/error logs; reference identifies `husk_log`, `husk_logappend`. Printed command alone is insufficient because disabled Run Command still prints it. |
| Disabled execution | `H21/houdini/help/nodes.zip::out/usdrender.txt:459–461` | `H22/houdini/help/nodes.zip::out/usdrender.txt:504–506` | Render Command may be printed and USD saved while no external command executes. |
| Parent HOM events | `H21/houdini/help/hom.zip::hou/RopNode.txt:12–23` | `H22/houdini/help/hom.zip::hou/RopNode.txt:12–23` | `addRenderEventCallback(callback, run_before_script=False)`, callback receives node/event/time; session-local. This is the ROP script boundary, not a writer callback. |
| Parent post-frame limitation | `H21/houdini/help/nodes.zip::out/usdrender.txt:580–584` | `H22/houdini/help/nodes.zip::out/usdrender.txt:625–629` | USD generation complete does not necessarily mean husk image render finished. Parent PostFrame cannot replace husk PostFrame. |

The ROP hook sections are `H21/houdini/help/nodes.zip::out/usdrender.txt:294–332` and `H22/houdini/help/nodes.zip::out/usdrender.txt:290–331`. Their example `sys.argv` print is script context; the expressly documented husk command variable is `husk_command`. Exact ROP hook parameter machine names were not established from these label-only sections; do not fabricate them.

## Driver, output, color and filter facts versus actual execution

| Subject | Exact static support | What remains unobserved |
|---|---|---|
| Output override | `H21/houdini/help/nodes.zip::out/usdrender.txt:113–116`; `H22/houdini/help/nodes.zip::out/usdrender.txt:117–120`. `H21/houdini/help/ref.zip::utils/husk.txt:246–267`; H22 `:272–293`: `-o/--output`, frame substitutions and comma-separated filenames for multiple products. | Concrete post-expansion filenames and product-to-file mapping from the actual execution. Do not invent comma-list mapping order or expand paths using a homemade substitute. |
| EXR driver selection | `H21/houdini/help/ref.zip::utils/husk.txt:357–360`; H22 `:393–396`: `--exrmode -1` uses HOUDINI_OIIO_EXR, 0 classic, 1 improved. `H21/houdini/help/nodes.zip::lop/renderproduct.txt:150–154`; H22 `:156–160` documents modern-driver multipart behavior. | Actual writer instance/backend. An explicit executed flag can support a documented selection request; absent/-1 plus parent environment cannot certify the active writer. |
| Delegate | H21 husk reference `:317–318`: `-R/--renderer`. H22 ROP `H22/houdini/help/nodes.zip::out/usdrender.txt:81–86` documents CLI, `husk:default_delegate`, environment selection. | Actual instantiated delegate and fallback. H22 `H22/houdini/help/ref.zip::utils/husk.txt:346–351` instead spells property `husk:delegate` and environment `HOUDINI_HUSK_DEFATULT_DELEGATE`; this conflicts with the ROP documentation. Do not silently normalize or infer default precedence in implementation. |
| Writer metadata/color inputs | `H21/houdini/help/nodes.zip::lop/renderproduct.txt:115–121,138–148`; H22 `:121–127,144–154`: driver-prefixed properties pass to image device library, image format can be overridden, Product color defaults/per-AOV overrides are described. | Actual resolved image format and processor. The Output Color Space paragraphs describe source color space, so that paragraph cannot justify a guessed output precedence rule. |
| Per-AOV color | `H21/houdini/help/nodes.zip::lop/rendervar.txt:184–190`; H22 `:198–204`: source/output properties and output file_rules. `H21/houdini/help/ref.zip::utils/husk.txt:362–363`; H22 `:398–399`: `--ocio` enable/disable. | Internal writer processor, context and applied LUTs per AOV; reconstructing OCIO in either parent or child is not an internal processor observation. |
| Sequential slap comp | `H21/houdini/help/ref.zip::utils/husk.txt:346–355`; H22 `:382–391`: repeated `--slap-comp` operations run sequentially, mapinput/mapoutput and filterlist payload described. | Which operations actually finished, payload execution order relative to color conversion, actual per-AOV effects. |
| H22 USD filter lists | `H22/houdini/help/nodes.zip::lop/imagefilter.txt:13–17,23,42–57`; `H22/houdini/help/nodes.zip::lop/rendersettings.txt:1105–1108`; `H22/houdini/help/ref.zip::utils/husk.txt:379–380`: ordered lists, AOV selection and disable-slapcomp gate. | Applied per-AOV list and completion events. Do not assume H21 supports the H22 Image Filter LOP/schema path; H21's inspected nodes archive lacks that help member. |
| Beauty alpha association | No direct writer association fact/API found in inspected husk, Product/Var, Render Settings or targeted color/filter help. COP Color Correct premultiplication documentation concerns that COP operation only. | Premultiplied versus straight output and any unpremultiply/color-transform/premultiply ordering; channel A, pixel samples, format extension or COP docs cannot fill this fact. |

H22 installed C++ declarations provide more precise **static** names, but are not demonstrated Python hooks into the active husk engine:

- `C:/Program Files/Side Effects Software/Houdini 22.0.429/toolkit/include/HUSD/HUSD_RenderSettings.h:390–400`: `updateFrame(...)` updates its husk-engine settings context and expands product filenames; `:304` product `outputName()`, `:420–421` grouped outputName. `C:/Program Files/Side Effects Software/Houdini 22.0.429/toolkit/include/HUSD/XUSD_RenderSettings.h:231–232` describes outputName as expanded. No exposed live engine object or Python binding into this object was found. Calling updateFrame would also be mutation, outside this discovery.
- `C:/Program Files/Side Effects Software/Houdini 22.0.429/toolkit/include/HUSD/UsdHoudini/houdiniImageFilterList.h:138–150`: `AOVs`, allowed tokens color/all/none/list and `GetAOVsAttr()`. `:163–172`: `AOVlist`, used only for list, `GetAOVlistAttr()`. `:248–250`: orderedFilters relationship and `GetOrderedFiltersRel()`. These support reading authored/resolved stage declarations while preserving sequence; schema fallback declarations are not observed instance values or execution evidence.

## Safe next software work, not performed here

1. Add a bounded observation-only husk pre/post-frame script contract using documented globals, recording their actual types and only representable values, frame, child identity and launch binding. Keep `husk_command` in its observed representation; do not label it exact tokenized OS argv until the representation is established. Preserve existing script hooks; hook composition behavior is still a fact to establish. Restrict any future substitutes to globals/native API/transport/process boundaries.
2. Keep parent raw settings, child command/settings/stage, child completion and writer execution as distinct evidence classes. Parent command print and child logs may corroborate; neither is a launch/completion proof alone. Bind child events to the current task/frame/process and actual outputs before consumption; fail closed on missing/empty/stale/unbound events.
3. Collect raw child-stage Product/Var/filter declarations with exact property names and order. Record explicit executed command switches such as exrmode/ocio/output/slap-comp, without resolving absent defaults or interpreting unspecified settings dictionary fields. Authoring a receipt into EXR metadata does not turn those declarations into writer truth.
4. Keep actual backend, final product mapping, resolved per-AOV processor, applied ordered filters and alpha association blocked pending a same-build supported live writer interface, documented log/metadata schema or native execution evidence. The current software-only authorization does not permit running these hooks in a real husk.

## Source binding

SHA256 computed read-only on the installed files (no copied installation/source payloads):

| Absolute path | SHA256 |
|---|---|
| `C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/help/ref.zip` | `5b2b6ff757fd72a74f1525ce43d852d4861790d26e1508b301574b397cf9914c` |
| `C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/help/nodes.zip` | `665f77cd1462339e621140501226edf07acaa63f8f73c5e6475a5fcdb18d6ce0` |
| `C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/help/hom.zip` | `baa3ee69f5c27a7bf5cd9062e9e06bad6167786ee3e8cdf871b9dd7d00befce7` |
| `C:/Program Files/Side Effects Software/Houdini 22.0.429/houdini/help/ref.zip` | `9ee926dcca5f141bf8de1a6926647c7ddfdc282976fc05dde27d47ec92c892c9` |
| `C:/Program Files/Side Effects Software/Houdini 22.0.429/houdini/help/nodes.zip` | `5e29284eca300d990113e559eabbc38c7e9d2c1a95493fc34556f80dc9121c19` |
| `C:/Program Files/Side Effects Software/Houdini 22.0.429/houdini/help/hom.zip` | `d242c5d2e25e118d03862df83a2cccfc109e94f52d17a1e8d797f796b51d2289` |
| `C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/python3.11libs/pdgjob/usdrender.py` | `d8b50b9a977b10021fe5185409687f39a59d9c57cd65f788e4eedea2c9214ffa` |
| `C:/Program Files/Side Effects Software/Houdini 22.0.429/houdini/python3.13libs/pdgjob/usdrender.py` | `4d024f866334f72ab1badf10be0476d31fde154ee9593e8e0719b6652b3ae45e` |

Only this discovery note was written. No failure reproduction, tests or runtime acceptance was requested or performed.
