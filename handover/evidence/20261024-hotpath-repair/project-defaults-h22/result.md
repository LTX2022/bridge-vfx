# Installed H22.0.459 factory fields (static only)

Inspected the actual installed Houdini22.0.459 resource tree, using read-only nested INDX extraction. No host execution, HOM import, or reuse of H21 metadata with a changed version. sources-and-fields.json records exact library and member SHA256 plus parsed templates; excerpt files retain installed member line numbers.

| Native type/field | H22 factory raw | Template type | Disable condition / controlling factory default | Evidence |
|---|---|---|---|---|
| Lop/karmarendersettings.dcmfilename | `$HIP/render/$HIPNAME.$OS.dcm.$F4.exr` | file, write chooser | `{ dcm == 0 }`; dcm=0 | DialogScript 3616-3626 |
| Lop/karmarendersettings.productName | `$HIP/render/$HIPNAME.$OS.$F4.checkpoint` | string, USD token | `{ outputcheckpoint == 0 }`; outputcheckpoint=0 | DialogScript 3905-3910 |
| Sop/pyrosolver.checkpoint_basename | `$HIPNAME.$OS` | string | `{ savecheckpoints == 0 }`; savecheckpoints=off | DialogScript 4527-4531 |
| Sop/pyrosolver.checkpoint_basedir | `$HIP/geo` | directory | `{ savecheckpoints == 0 }`; savecheckpoints=off | DialogScript 4543-4548 |
| Object/lopnet.rendergallerysource (Obj lookup context) | `$HIP/galleries/$HIPNAME.$OS/rendergallery.db` | Exact HOM template type UNKNOWN from inspected static sources | Template disable condition UNKNOWN; documented use only when gallery opened for that network | H22 ref.zip panes/rendergallery.txt:451-469; nodes.zip manager/lopnet.txt:77-80 |

The four HDA field values/types/conditions match the separately inspected H21 definitions, but are proven here from distinct H22 members: Lop/karmarendersettings/DialogScript SHA256 cc263cb8a2e6e1f964363999322d8395f7c52d7160ea723173a24b23568783fe; Sop/pyrosolver/DialogScript SHA256 950bb643b3b71d69d83d334bfa1ad3621ab6590fbd03105abbea2e6e8d4c702d.

Gallery's default is independently documented in the H22 help member, SHA256 cf655dc0def5408937f87754b00371c5e1106f6d0df17189c9a4dbe4308116d9. The installed config/Dialogs/OBJ/lopnet is a binary UI description, not a decoded parameter template; file chooser labels do not prove exact HOM parameter type or absence of a gate. Those facts must remain unknown until independently obtained from valid H22 template evidence. Do not fill them from H21 or mark an inferred type as captured.

All gates here are factory metadata, not evidence of any live instance's state or inactive behavior. No actual H22 save/cook/cache/compatibility acceptance is claimed. Basename remains a naming stem rather than an absolute path, and gallery remains conditional snapshot storage rather than a universal harmless field.
