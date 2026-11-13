"""Probe cover for Houdini parm-name resolution.

Houdini names a multi-component parm after the tuple (``rad``, ``size``,
``base_color``) but addresses it by component (``radx``, ``sizex``,
``base_colorr``) or through ``parmTuple``.  Probing aliases against raw parm
template names reported every tuple parm as missing, which marked eleven of
the fifteen domain packs unsupported for a reason that had nothing to do with
the packs.  These tests pin the expansion without needing a live Houdini.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
ADDON_PATH = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"


def _load_addon():
    spec = importlib.util.spec_from_file_location("_houdini_parm_probe_addon", ADDON_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Houdini add-on contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeTemplate:
    def __init__(self, name: str, num_components: int = 1, scheme: str = "parmNamingScheme.XYZW") -> None:
        self._name = name
        self._count = num_components
        self._scheme = scheme

    def name(self) -> str:
        return self._name

    def numComponents(self) -> int:  # noqa: N802 - mirrors the HOM name
        return self._count

    def namingScheme(self) -> str:  # noqa: N802 - mirrors the HOM name
        return self._scheme

    def parmTemplates(self):
        raise AttributeError("FloatParmTemplate object has no attribute 'parmTemplates'")


class _FakeFolder:
    def __init__(self, name: str, children) -> None:
        self._name = name
        self._children = list(children)

    def name(self) -> str:
        return self._name

    def numComponents(self) -> int:  # noqa: N802
        return 1

    def namingScheme(self) -> str:  # noqa: N802
        return "parmNamingScheme.Base1"

    def parmTemplates(self):
        return self._children


class _FakeGroup:
    def __init__(self, entries) -> None:
        self._entries = list(entries)

    def entries(self):
        return self._entries


class _FakeNodeType:
    def __init__(self, entries, name: str = "sphere") -> None:
        self._group = _FakeGroup(entries)
        self._name = name

    def name(self) -> str:
        return self._name

    def parmTemplateGroup(self) -> _FakeGroup:  # noqa: N802
        return self._group


class TupleExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.addon = _load_addon()

    def _names(self, template) -> set[str]:
        return self.addon._fx_template_parm_names(template)

    def test_three_component_float_expands_to_xyz(self) -> None:
        self.assertEqual(self._names(_FakeTemplate("rad", 3)), {"rad", "radx", "rady", "radz"})

    def test_two_component_float_expands_to_xy(self) -> None:
        self.assertEqual(self._names(_FakeTemplate("size", 2)), {"size", "sizex", "sizey"})

    def test_scalar_is_not_expanded(self) -> None:
        self.assertEqual(self._names(_FakeTemplate("scale", 1)), {"scale"})

    def test_rgba_scheme_expands_to_rgb(self) -> None:
        names = self._names(_FakeTemplate("base_color", 3, "parmNamingScheme.RGBA"))
        self.assertEqual(names, {"base_color", "base_colorr", "base_colorg", "base_colorb"})

    def test_base1_scheme_expands_to_indices(self) -> None:
        names = self._names(_FakeTemplate("size", 3, "parmNamingScheme.Base1"))
        self.assertEqual(names, {"size", "size1", "size2", "size3"})

    def test_unknown_scheme_falls_back_to_xyzw(self) -> None:
        names = self._names(_FakeTemplate("dim", 2, "parmNamingScheme.SomeFutureScheme"))
        self.assertEqual(names, {"dim", "dimx", "dimy"})

    def test_tuple_name_is_kept_because_parm_tuple_is_addressable(self) -> None:
        # node.parm("base_color") is None but node.parmTuple("base_color")
        # resolves, so the tuple name is a legitimate addressable target.
        self.assertIn("base_color", self._names(_FakeTemplate("base_color", 3, "parmNamingScheme.RGBA")))


class AddressableParmNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.addon = _load_addon()

    def test_sphere_style_tuple_exposes_component_names(self) -> None:
        node_type = _FakeNodeType([_FakeTemplate("rad", 3), _FakeTemplate("scale", 1)])
        names = self.addon._fx_addressable_parm_names(node_type)
        self.assertIn("radx", names)
        self.assertIn("rad", names)
        self.assertIn("scale", names)

    def test_nested_folder_templates_are_expanded(self) -> None:
        folder = _FakeFolder("Transform", [_FakeTemplate("t", 3), _FakeTemplate("r", 3)])
        names = self.addon._fx_addressable_parm_names(_FakeNodeType([folder]))
        self.assertIn("tx", names)
        self.assertIn("ry", names)

    def test_broken_node_type_yields_no_names(self) -> None:
        class Broken:
            def parmTemplateGroup(self):
                raise RuntimeError("no parm template group")

        self.assertEqual(self.addon._fx_addressable_parm_names(Broken()), set())

    def test_probe_marks_a_pack_available_when_its_tuple_alias_resolves(self) -> None:
        # The regression itself: eleven packs declared "radx"/"sizex", the
        # write path resolved them, but the probe compared against template
        # names and reported them missing.
        pack = {
            "nodes": [{"role": "source", "category": "sop", "types": ["sphere"], "required_parms": [["radx", "radius"]]}],
            "controls": {},
        }
        original = self.addon._fx_resolve_type
        self.addon._fx_resolve_type = lambda requirement: _FakeNodeType([_FakeTemplate("rad", 3)])
        try:
            probe = self.addon._fx_probe_pack("unit_probe", pack)
        finally:
            self.addon._fx_resolve_type = original
        self.assertTrue(probe["nodes"][0]["available"])
        self.assertEqual(probe["nodes"][0]["missing_parameter_aliases"], [])


class _FakeParm:
    def __init__(self, name: str, value, transform=None) -> None:
        self._name = name
        self._value = value
        self._transform = transform or (lambda value: value)

    def eval(self):
        return self._value

    def set(self, value, **_kwargs) -> None:
        self._value = self._transform(value)

    def isDisabled(self) -> bool:  # noqa: N802
        return False

    def isLocked(self) -> bool:  # noqa: N802
        return False

    def name(self) -> str:
        return self._name

    def path(self) -> str:
        return "/obj/test/" + self._name


class _FakeKeyframe:
    def __init__(self, code: str) -> None:
        self.code = code

    def asCode(self, brief=False, save_keys_in_frames=False):  # noqa: N802
        return "{}|brief={}|frames={}".format(self.code, brief, save_keys_in_frames)


class _DrivenParm(_FakeParm):
    def __init__(self, name: str, value, keyframes) -> None:
        super().__init__(name, value)
        self._keyframes = list(keyframes)
        self.set_calls = 0

    def keyframes(self):
        return tuple(self._keyframes)

    def deleteAllKeyframes(self):  # noqa: N802
        self._keyframes = []

    def setKeyframes(self, keyframes):  # noqa: N802
        self._keyframes = list(keyframes)

    def unexpandedString(self):  # noqa: N802
        raise RuntimeError("numeric channel")

    def set(self, value, **_kwargs) -> None:
        self.set_calls += 1
        self._value = value


class _ReferencedParm(_DrivenParm):
    def __init__(self, name: str, value, referenced: _FakeParm) -> None:
        super().__init__(name, value, [])
        self._referenced = referenced

    def expression(self):
        return "ch('../driver')"

    def getReferencedParm(self):  # noqa: N802
        return self._referenced

    def unexpandedString(self):  # noqa: N802
        return "ch('../driver')"

    def set(self, value, **_kwargs) -> None:
        self.set_calls += 1
        self._referenced.set(value)


class _ManifestRoot:
    def __init__(self, values=None) -> None:
        self.values = dict(values or {})

    def path(self):
        return "/obj/unit"

    def userData(self, key):  # noqa: N802
        return self.values.get(key)

    def setUserData(self, key, value):  # noqa: N802
        self.values[key] = value

    def destroyUserData(self, key):  # noqa: N802
        self.values.pop(key, None)


class _FakeParmTuple(_FakeParm):
    def __init__(self, name: str, value) -> None:
        super().__init__(name, tuple(value))
        self._component_parms = [_FakeParm("{}{}".format(name, suffix), item) for suffix, item in zip("rgb", value)]

    def __iter__(self):
        return iter(self._component_parms)

    def set(self, value, **_kwargs) -> None:
        self._value = tuple(value)


class _FakeNode:
    def __init__(self, path: str, parms=None, parm_tuples=None) -> None:
        self._path = path
        self._parms = dict(parms or {})
        self._parm_tuples = dict(parm_tuples or {})

    def parm(self, name):
        return self._parms.get(name)

    def parmTuple(self, name):  # noqa: N802
        return self._parm_tuples.get(name)

    def path(self) -> str:
        return self._path


class ParmReadbackAndAtomicityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.addon = _load_addon()

    def setUp(self) -> None:
        temporary=tempfile.TemporaryDirectory(prefix='parm-atomic-lease-')
        self.addCleanup(temporary.cleanup)
        environment=unittest.mock.patch.dict(os.environ,{'HOUDINI_BRIDGE_STATE_DIR':str(Path(temporary.name)/'host')})
        environment.start();self.addCleanup(environment.stop)
        self.root=_ManifestRoot()
        self.addon._root_lease_issue(self.root.path(),'unit',scope='sop')

    def test_bool_and_int_are_exact_while_floats_use_abs_and_relative_tolerance(self) -> None:
        self.assertFalse(self.addon._values_match(False, 0))
        self.assertFalse(self.addon._values_match(1, 1.0))
        self.assertTrue(self.addon._values_match(1, 1))
        self.assertTrue(self.addon._values_match(1.0, 1.0 + 1.0e-8))
        self.assertTrue(self.addon._values_match(1.0e8, 1.0e8 + 1.0))
        self.assertFalse(self.addon._values_match((1, False), (1, 0)))

    def test_unified_resolver_falls_back_to_parm_tuple(self) -> None:
        tuple_parm = _FakeParmTuple("base_color", (0.1, 0.2, 0.3))
        node = _FakeNode("/mat/test", parm_tuples={"base_color": tuple_parm})
        resolved = self.addon._resolve_parm_target(node, ["base_color"])
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.kind, "parm_tuple")
        result = self.addon._set_parm_verified(resolved, (0.2, 0.3, 0.4), restore=True)
        self.assertTrue(result["readback_verified"])
        self.assertTrue(result["restore_verified"])
        self.assertEqual(tuple_parm.eval(), (0.1, 0.2, 0.3))

    def test_readback_mismatch_restores_the_parameter(self) -> None:
        parm = _FakeParm("amount", 0.2, transform=lambda value: 0.7 if value == 0.8 else value)
        resolved = self.addon._ResolvedParm(parm, "amount", "parm")
        with self.assertRaises(self.addon.BridgeCommandError) as caught:
            self.addon._set_parm_verified(resolved, 0.8)
        self.assertEqual(caught.exception.code, "PARAMETER_READBACK_MISMATCH")
        self.assertEqual(parm.eval(), 0.2)

    def test_complete_channel_snapshot_restores_exact_keyframe_identity(self) -> None:
        keys = [_FakeKeyframe("key@1=0.2"), _FakeKeyframe("key@10=0.8")]
        parm = _DrivenParm("amount", 0.4, keys)
        resolved = self.addon._ResolvedParm(parm, "amount", "parm")
        snapshot = self.addon._snapshot_parm_state(resolved)

        parm.deleteAllKeyframes()
        parm.setKeyframes([_FakeKeyframe("key@5=9.0")])
        parm._value = 0.4
        restored = self.addon._restore_parm_snapshot(resolved, snapshot)

        self.assertEqual(restored, 0.4)
        self.assertEqual(
            [self.addon._keyframe_identity(item) for item in parm.keyframes()],
            [self.addon._keyframe_identity(item) for item in keys],
        )

    def test_shared_setter_rejects_driven_parameter_without_calling_set(self) -> None:
        parm = _DrivenParm("amount", 0.2, [_FakeKeyframe("expression=ch('../driver')")])
        resolved = self.addon._ResolvedParm(parm, "amount", "parm")
        with self.assertRaises(self.addon.BridgeCommandError) as caught:
            self.addon._set_parm_verified(resolved, 0.8, restore=True)
        self.assertEqual(caught.exception.code, "PARAMETER_STATE_UNSUPPORTED")
        self.assertEqual(parm.set_calls, 0)
        self.assertEqual(parm.eval(), 0.2)

    def test_shared_setter_never_follows_a_channel_reference(self) -> None:
        external = _FakeParm("driver", 0.2)
        parm = _ReferencedParm("amount", 0.2, external)
        resolved = self.addon._ResolvedParm(parm, "amount", "parm")
        with self.assertRaises(self.addon.BridgeCommandError) as caught:
            self.addon._set_parm_verified(resolved, 0.8)
        self.assertEqual(caught.exception.code, "PARAMETER_STATE_UNSUPPORTED")
        self.assertEqual(parm.set_calls, 0)
        self.assertEqual(external.eval(), 0.2)

    def test_multi_control_candidate_rolls_back_prior_success(self) -> None:
        first = _FakeParm("first", 0.2)
        second = _FakeParm("second", 0.2, transform=lambda value: 0.7 if value == 0.8 else value)
        nodes = {
            "/obj/first": _FakeNode("/obj/first", parms={"first": first}),
            "/obj/second": _FakeNode("/obj/second", parms={"second": second}),
        }
        fake_hou = SimpleNamespace(node=lambda path: nodes.get(path))
        manifest = {"nodes": {"first_role": "/obj/first", "second_role": "/obj/second"}}
        pack = {
            "controls": {
                "first_control": {"role": "first_role", "aliases": ["first"], "minimum": 0.0, "maximum": 1.0},
                "second_control": {"role": "second_role", "aliases": ["second"], "minimum": 0.0, "maximum": 1.0},
            }
        }
        original_manifest = self.addon._fx_manifest
        original_undo = self.addon._undo
        self.addon._fx_manifest = lambda _task_id: (self.root, manifest)
        self.addon._undo = lambda _label: nullcontext()
        try:
            with unittest.mock.patch.dict(sys.modules, {"hou": fake_hou}):
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon._fx_apply_candidate(
                        {"task_id": "unit", "step_params": {"changes": {"first_control": 0.8, "second_control": 0.8}}},
                        "unit_pack",
                        pack,
                    )
        finally:
            self.addon._fx_manifest = original_manifest
            self.addon._undo = original_undo
        self.assertEqual(caught.exception.code, "PARAMETER_READBACK_MISMATCH")
        self.assertEqual(first.eval(), 0.2)
        self.assertEqual(second.eval(), 0.2)

    def test_candidate_persists_confirmed_readback_and_direct_operation_gate(self) -> None:
        parm = _FakeParm("amount", 0.1, transform=lambda value: value + 1.0e-9)
        node = _FakeNode("/obj/value", parms={"amount": parm})
        fake_hou = SimpleNamespace(node=lambda path: node if path == "/obj/value" else None)
        manifest = {"nodes": {"role": "/obj/value"}, "revision": 0}
        stored = {}
        pack = {"controls": {"amount": {"role": "role", "aliases": ["amount"], "minimum": 0.0, "maximum": 1.0}}}
        originals = (self.addon._fx_manifest, self.addon._undo, self.addon._fx_store_manifest, self.addon._fx_cache_subject)
        self.addon._fx_manifest = lambda _task_id: (self.root, manifest)
        self.addon._undo = lambda _label: nullcontext()
        self.addon._fx_store_manifest = lambda _root, value: stored.update(value)
        self.addon._fx_cache_subject = lambda _params, _pack_id, value: ({"candidate_patch": value["candidate_patch"]}, "hash")
        try:
            with unittest.mock.patch.dict(sys.modules, {"hou": fake_hou}):
                result = self.addon._fx_apply_candidate(
                    {"task_id": "unit", "step_params": {"changes": {"amount": 0.3}}},
                    "unit_pack",
                    pack,
                )
        finally:
            self.addon._fx_manifest, self.addon._undo, self.addon._fx_store_manifest, self.addon._fx_cache_subject = originals
        self.assertEqual(stored["candidate_patch"]["amount"], 0.300000001)
        self.assertEqual(result["cache_approval_subject"]["candidate_patch"], stored["candidate_patch"])
        self.assertEqual(result["gates"][0]["name"], "candidate_patch_applied")
        self.assertEqual(result["gates"][0]["kind"], "operation")
        self.assertTrue(result["gates"][0]["passed"])

    def test_linked_write_set_and_numeric_stiffness_exponent_preserve_public_units(self):
        import types
        stiffness = _FakeParm("stretchstiffness", 2.0)
        exponent = _FakeParm("stretchstiffnessexp", 10)
        exponent.parmTemplate = lambda: types.SimpleNamespace(menuUseToken=lambda:True,menuItems=lambda:("10","0","-10"))
        source = _FakeParm("particlesep", .1)
        surface = _FakeParm("particlesep", .1)
        node = _FakeNode("/obj/constraints",parms={"stretchstiffness":stiffness,"stretchstiffnessexp":exponent})
        stiffness.node = lambda:node
        source_node = _FakeNode("/obj/source",parms={"particlesep":source})
        surface_node = _FakeNode("/obj/surface",parms={"particlesep":surface})
        source.path = lambda:source_node.path()+"/particlesep"
        surface.path = lambda:surface_node.path()+"/particlesep"
        nodes = {n.path():n for n in (node,source_node,surface_node)}
        manifest = {"nodes":{"constraints":node.path(),"source":source_node.path(),"surface":surface_node.path()},"revision":0}
        pack = {"controls":{
            "stiffness":{"role":"constraints","aliases":["stretchstiffness"],"native_multiplier_parm":"stretchstiffnessexp","minimum":0,"maximum":1e12},
            "separation":{"role":"source","aliases":["particlesep"],"minimum":.001,"maximum":10,"linked_targets":[{"role":"surface","aliases":["particlesep"],"policy":"same"}]}}}
        stored = {}
        with unittest.mock.patch.object(self.addon,"_fx_manifest",return_value=(self.root,manifest)), unittest.mock.patch.object(self.addon,"_undo",return_value=nullcontext()), unittest.mock.patch.object(self.addon,"_fx_store_manifest",side_effect=lambda root,value:stored.update(value)), unittest.mock.patch.object(self.addon,"_fx_cache_subject",return_value=({},"hash")), unittest.mock.patch.dict(sys.modules,{"hou":types.SimpleNamespace(node=lambda path:nodes.get(path))}):
            result = self.addon._fx_apply_candidate({"task_id":"unit","step_params":{"changes":{"stiffness":5e10,"separation":.2}}},"unit_pack",pack)
            self.assertEqual(stiffness.eval(),5.0)
            self.assertEqual(exponent.eval(),10)
            self.assertEqual(stored["candidate_patch"]["stiffness"],5e10)
            self.assertEqual((source.eval(),surface.eval()),(.2,.2))
            self.assertEqual(result["gates"][0]["change_count"],2)
            # A later linked native callback changing an earlier target must
            # roll back the whole vector, including the failed target.
            previous_set = surface.set
            def callback(value,*args,**kwargs):
                previous_set(value,*args,**kwargs)
                if value == .3: source._value = .9
            surface.set = callback
            with self.assertRaises(self.addon.BridgeCommandError):
                self.addon._fx_apply_candidate({"task_id":"unit","step_params":{"changes":{"separation":.3}}},"unit_pack",pack)
            self.assertEqual((source.eval(),surface.eval()),(.2,.2))

    def test_candidate_rejects_driven_target_before_any_write_or_persistence(self) -> None:
        parm = _DrivenParm("amount", 0.1, [_FakeKeyframe("expression=ch('../driver')")])
        node = _FakeNode("/obj/value", parms={"amount": parm})
        fake_hou = SimpleNamespace(node=lambda path: node if path == "/obj/value" else None)
        manifest = {"nodes": {"role": "/obj/value"}, "revision": 0}
        pack = {
            "controls": {
                "amount": {
                    "role": "role",
                    "aliases": ["amount"],
                    "minimum": 0.0,
                    "maximum": 1.0,
                }
            }
        }
        with unittest.mock.patch.object(
            self.addon, "_fx_manifest", return_value=(self.root, manifest)
        ), unittest.mock.patch.object(
            self.addon, "_fx_store_manifest"
        ) as store, unittest.mock.patch.dict(sys.modules, {"hou": fake_hou}):
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon._fx_apply_candidate(
                    {
                        "task_id": "unit",
                        "step_params": {"changes": {"amount": 0.3}},
                    },
                    "unit_pack",
                    pack,
                )
        self.assertEqual(caught.exception.code, "PARAMETER_STATE_UNSUPPORTED")
        self.assertEqual(parm.set_calls, 0)
        store.assert_not_called()

    def test_candidate_persistence_failure_rolls_back_parameter_and_old_manifest(self) -> None:
        parm = _FakeParm("amount", 0.1)
        node = _FakeNode("/obj/value", parms={"amount": parm})
        fake_hou = SimpleNamespace(node=lambda path: node if path == "/obj/value" else None)
        manifest = {
            "task_id": "unit",
            "domain_pack": "unit_pack",
            "nodes": {"role": "/obj/value"},
            "revision": 4,
            "candidate_patch": {"amount": 0.1},
        }
        old_embedded = json.dumps(manifest, sort_keys=True)
        root = _ManifestRoot(
            {
                "bridge_fx_manifest_v1": old_embedded,
                "bridge_fx_pack": "unit_pack",
            }
        )
        pack = {
            "controls": {
                "amount": {
                    "role": "role",
                    "aliases": ["amount"],
                    "minimum": 0.0,
                    "maximum": 1.0,
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "unit.json"
            state_path.write_text(old_embedded, encoding="utf-8")

            def fail_after_partial_store(target_root, updated):
                target_root.setUserData(
                    "bridge_fx_manifest_v1", json.dumps(updated, sort_keys=True)
                )
                target_root.setUserData("bridge_fx_pack", "corrupted")
                state_path.write_text("partially persisted", encoding="utf-8")
                raise RuntimeError("simulated userData/sidecar failure")

            with unittest.mock.patch.object(
                self.addon, "_fx_manifest", return_value=(root, manifest)
            ), unittest.mock.patch.object(
                self.addon, "_undo", side_effect=lambda _label: nullcontext()
            ), unittest.mock.patch.object(
                self.addon, "_fx_state_path", return_value=state_path
            ), unittest.mock.patch.object(
                self.addon, "_fx_store_manifest", side_effect=fail_after_partial_store
            ), unittest.mock.patch.object(
                self.addon,
                "_fx_cache_subject",
                return_value=({"candidate_patch": {"amount": 0.3}}, "hash"),
            ), unittest.mock.patch.dict(sys.modules, {"hou": fake_hou}):
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon._fx_apply_candidate(
                        {
                            "task_id": "unit",
                            "step_params": {"changes": {"amount": 0.3}},
                        },
                        "unit_pack",
                        pack,
                    )

            self.assertEqual(caught.exception.code, "CANDIDATE_PERSIST_FAILED")
            self.assertEqual(parm.eval(), 0.1)
            self.assertEqual(root.userData("bridge_fx_manifest_v1"), old_embedded)
            self.assertEqual(root.userData("bridge_fx_pack"), "unit_pack")
            self.assertEqual(state_path.read_text(encoding="utf-8"), old_embedded)
            self.assertEqual(manifest["revision"], 4)

    def test_build_preview_reuse_rejects_driven_target_before_scene_mutation(self) -> None:
        parm = _DrivenParm("amount", 0.1, [_FakeKeyframe("expression=ch('../driver')")])
        node = _FakeNode("/obj/value", parms={"amount": parm})
        root = _ManifestRoot({"bridge_fx_owned": "1"})
        root_path = "/obj/HOUDINI_AGENT_WORKING_abc"
        fake_hou = SimpleNamespace(
            node=lambda path: root if path == root_path else (node if path == "/obj/value" else None)
        )
        existing = {
            "domain_pack": "unit_pack",
            "nodes": {"role": "/obj/value"},
            "candidate_patch": {"amount": 0.2},
        }
        pack = {
            "nodes": [],
            "controls": {
                "amount": {
                    "role": "role",
                    "aliases": ["amount"],
                    "minimum": 0.0,
                    "maximum": 1.0,
                }
            },
        }
        with unittest.mock.patch.object(
            self.addon, "_fx_manifest", return_value=(root, existing)
        ), unittest.mock.patch.object(
            self.addon,
            "_fx_probe_pack",
            return_value={"node_contract_available": True, "nodes": []},
        ), unittest.mock.patch.object(
            self.addon, "_fx_store_manifest"
        ) as store, unittest.mock.patch.dict(sys.modules, {"hou": fake_hou}):
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon._fx_build_preview(
                    {"task_id": "abc", "step_params": {}}, "unit_pack", pack
                )
        self.assertEqual(caught.exception.code, "PARAMETER_STATE_UNSUPPORTED")
        self.assertEqual(parm.set_calls, 0)
        store.assert_not_called()

    def test_source_plan_is_consumed_by_fake_host_set_connect_create_and_cache_invalidation(self) -> None:
        from source_host_fixture import source_params
        from vfx_pipeline.workbuddy_assembly import software_host_client
        def load_boundary(name, filename):
            spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / filename)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        native = load_boundary("source_native_schema", "native_schema_test_boundary.py")
        api = load_boundary("source_native_api", "software_render_api_boundary.py")
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.dict(sys.modules), unittest.mock.patch.dict(os.environ, {
            "HOUDINI_BRIDGE_STATE_DIR": tmp + "/houdini", "BRIDGE_SKILLS_STATE_ROOT": tmp + "/state",
            "BRIDGE_SKILLS_SCHEDULER_ROOT": tmp + "/scheduler"}):
            client, addon = software_host_client(ADDON_PATH, Path(tmp) / "host")
            interfaces, states, ports = api.interface_profiles(ROOT, "21.0.631")
            native.constrain_hou(ROOT / "docs/native-basis/hda-interface-capture.json", "21.0.631",
                instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports)
            hou = sys.modules["hou"]
            api.install_stage_api(hou)
            node_class = type(hou.node("/obj"))
            original_create = node_class.createNode
            creations = []
            solver_noise_before = {}
            def create(node, *args, **kwargs):
                result = original_create(node, *args, **kwargs)
                creations.append(result.path())
                if result.type().name() == "pyrosolver":
                    solver_noise_before.update({name: result.parm(name).eval() for name in ("disturbance", "turbulence")})
                return result
            with unittest.mock.patch.object(node_class, "createNode", create):
                first = client.call("agent.fx.build_preview", source_params(spread_angle_deg=36.0))
                roles = first["scene_manifest"]["nodes"]
                role = lambda name: hou.node(roles[name])
                for left, right in zip(["source", "source_points", "source_control", "source_volume", "solver"],
                                       ["source_points", "source_control", "source_volume", "solver", "field_sharpen"]):
                    self.assertIs(role(right).inputs()[0], role(left))
                self.assertAlmostEqual(role("source").parm("radx").eval(), 0.51)
                self.assertAlmostEqual(role("source").parm("rady").eval(), 0.5)
                old_program = role("source_control").parm("snippet").eval()
                self.assertIn("v@v = active * 5 * velocity_direction;", old_program)
                for name, value in solver_noise_before.items():
                    self.assertEqual(role("solver").parm(name).eval(), value)
                root, manifest = addon._fx_manifest("abc123")
                manifest["cache"] = {"status": "synthetic_old_cache"}
                addon._fx_store_manifest(root, manifest)
                created_before = tuple(creations)
                second = client.call("agent.fx.build_preview", source_params(spread_angle_deg=72.0))
                self.assertEqual(tuple(creations), created_before)
                self.assertNotEqual(role("source_control").parm("snippet").eval(), old_program)
                self.assertNotIn("cache", second["scene_manifest"])
                self.assertTrue(second["scene_manifest"]["source_plan_cache_invalidated"])
                self.assertIn("generation_simulation", second["scene_manifest"]["source_plan_invalidates_from"])
                self.assertEqual(root.userData("bridge_fx_owned"), "1")
                sourcing = second["scene_manifest"]["solver_sourcing"]
                self.assertEqual(role("solver").parm("numsources").eval(), 2)
                self.assertEqual(sourcing["compiled_rows"]["instance_count"], 2)
                self.assertEqual([r["native_indices"] for r in sourcing["compiled_rows"]["rows"]], [[0], [1]])
                for index, expected in enumerate((("add", "scalar", "density", "density"), ("copy", "vector", "v", "vel")), 1):
                    self.assertEqual(tuple(role("solver").parm(field+str(index)).evalAsString() for field in
                        ("source_voperator", "source_rank", "source_volume", "source_vfield")), expected)
                    self.assertEqual([(int(k.frame()), int(k.value())) for k in role("solver").parm("source_activate"+str(index)).keyframes()],
                        [(1, 1), (21, 0), (41, 1), (61, 0), (181, 0)])
                # Use a different existing sibling selection and a legitimate
                # edited sampling base before both late failure points.
                role("source_control").setDisplayFlag(True)
                role("source_points").setRenderFlag(True)
                settings = role("render_settings")
                self.assertEqual(settings.parm("engine").evalAsString(), "cpu")
                self.assertEqual(settings.parm("convergence_mode").evalAsString(), "Variance")
                settings.parm("varianceaa_minsamples").set(3)
                settings.parm("varianceaa_maxsamples").set(11)
                def state():
                    return (addon._fx_state_path("abc123").read_bytes(), root.userData("bridge_fx_manifest_v1"),
                        {p.path():addon._fx_scene_parameter_readback(p) for name in ("source", "source_points", "source_control", "source_volume", "solver", "render_settings") for p in role(name).parms()},
                        {n.path():[n.isDisplayFlagSet(), n.isRenderFlagSet()] for n in role("source_volume").parent().children()})
                frozen = state()
                original_write = addon._fx_write_state
                def persist_then_fail(task, manifest):
                    original_write(task, manifest)
                    raise OSError("injected source manifest failure")
                with unittest.mock.patch.object(addon, "_fx_write_state", persist_then_fail), self.assertRaisesRegex(OSError, "source manifest failure"):
                    client.call("agent.fx.build_preview", source_params(spread_angle_deg=90.0))
                evidence = os.environ.get("BRIDGE_SOURCE_BOUNDARY_EVIDENCE_DIR")
                if evidence:
                    target = Path(evidence); target.mkdir(parents=True, exist_ok=True)
                    actual_failure = state()
                    (target / "late-failure-actual-readback.json").write_text(json.dumps({
                        "version": hou.applicationVersionString(), "before_parameters": frozen[2],
                        "after_parameters": actual_failure[2], "before_sibling_flags": frozen[3],
                        "after_sibling_flags": actual_failure[3],
                        "manifest_bytes_equal": actual_failure[:2] == frozen[:2],
                        "all_state_equal": actual_failure == frozen}, indent=2) + "\n")
                self.assertEqual(state(), frozen)
                original_set = type(role("source_control").parm("snippet")).set
                failed = []
                def late_failure(parm, value, **kwargs):
                    if parm.path() == role("source_control").parm("snippet").path() and not failed:
                        failed.append(True)
                        raise RuntimeError("injected source program failure")
                    return original_set(parm, value, **kwargs)
                with unittest.mock.patch.object(type(role("source_control").parm("snippet")), "set", late_failure), self.assertRaises(Exception):
                    client.call("agent.fx.build_preview", source_params(spread_angle_deg=90.0))
                self.assertTrue(failed)
                self.assertEqual(state(), frozen)
                # Unknown row counts and edits are rejected before any host write.
                role("solver").parm("numsources").set(3)
                foreign = state()
                with self.assertRaises(addon.BridgeCommandError):
                    client.call("agent.fx.build_preview", source_params(spread_angle_deg=90.0))
                self.assertEqual(state(), foreign)
                role("solver").parm("numsources").set(2)
                role("solver").parm("source_vfield2").set("foreign")
                foreign = state()
                with self.assertRaises(addon.BridgeCommandError):
                    client.call("agent.fx.build_preview", source_params(spread_angle_deg=90.0))
                self.assertEqual(state(), foreign)
                # A first failed build restores the empty owned root, including
                # absent embedded keys and sidecar bytes, via native userdata.
                fresh = source_params(); fresh["task_id"] = "first-source-failure"
                with unittest.mock.patch.object(addon, "_fx_write_state", persist_then_fail), self.assertRaisesRegex(OSError, "source manifest failure"):
                    client.call("agent.fx.build_preview", fresh)
                fresh_root = hou.node(addon._fx_task_paths(fresh["task_id"])[0])
                self.assertEqual(fresh_root.allSubChildren(), ())
                self.assertNotIn("bridge_fx_manifest_v1", fresh_root.userDataDict())
                self.assertNotIn("bridge_fx_pack", fresh_root.userDataDict())
                self.assertFalse(addon._fx_state_path(fresh["task_id"]).exists())
                evidence = os.environ.get("BRIDGE_SOURCE_BOUNDARY_EVIDENCE_DIR")
                if evidence:
                    target = Path(evidence); target.mkdir(parents=True, exist_ok=True)
                    (target / "source-native-transaction.json").write_text(json.dumps({
                        "version": hou.applicationVersionString(), "identity": addon._host_identity(),
                        "actual_lease": addon._root_lease_read(root.path()), "created_paths": list(created_before),
                        "before_program": old_program, "after_program": json.loads(frozen[1])["source_program_registration"]["program"],
                        "committed_manifest": json.loads(frozen[1]), "committed_parameter_readbacks": frozen[2],
                        "pre_failure_sibling_flags": frozen[3],
                        "preserved_existing_sampling": {n: settings.parm(n).eval() for n in ("engine", "convergence_mode", "varianceaa_minsamples", "varianceaa_maxsamples")},
                        "manifest_and_program_failures_restored_exact_state": True,
                        "unknown_rows_and_foreign_row_rejected_without_mutation": True,
                        "fresh_failure_children": [n.path() for n in fresh_root.allSubChildren()],
                        "fresh_failure_userdata": fresh_root.userDataDict(),
                        "fresh_failure_sidecar_exists": addon._fx_state_path(fresh["task_id"]).exists(),
                        "native_execution": False}, indent=2) + "\n")

    def test_source_plan_drift_is_rejected_before_fake_host_mutation(self) -> None:
        addon = self.addon
        raw = {"schema_version": "1.0", "ready": True, "controls": [], "defaults": [], "missing_semantics": []}
        params = {"task_id": "abc", "inputs": [], "step_params": {
            "source_plan": raw, "source_plan_sha256": "0" * 64, "source_controls": {},
            "source_input_binding_sha256": __import__("hashlib").sha256(b"[]").hexdigest(),
        }}
        created = []
        fake_obj = SimpleNamespace(createNode=lambda *args, **kwargs: created.append((args, kwargs)))
        fake_hou = SimpleNamespace(node=lambda path: fake_obj if path == "/obj" else None)
        with unittest.mock.patch.dict(sys.modules, {"hou": fake_hou}):
            with self.assertRaises(addon.BridgeCommandError) as caught:
                addon._fx_build_preview(params, "pyro_smoke_v1", {"nodes": [], "controls": {}})
        self.assertEqual(caught.exception.code, "SOURCE_PLAN_DRIFT")
        self.assertEqual(created, [])

    def test_preview_operation_is_successful_but_visual_outcome_is_inconclusive(self) -> None:
        result = self.addon._fx_preview_operation_result({}, {}, reused=False)
        self.assertEqual(result["gates"][0]["kind"], "operation")
        self.assertTrue(result["gates"][0]["passed"])
        self.assertEqual(result["outcome_state"], "DIAGNOSIS_INCONCLUSIVE")
        self.assertEqual(result["visual_validation"], "INCONCLUSIVE")


class _FakeNodeTypeWithCategory:
    def __init__(self, category: str) -> None:
        self._category = category

    def nameWithCategory(self) -> str:  # noqa: N802
        return self._category + "/test"

    def category(self):
        return SimpleNamespace(name=lambda: self._category)


class CookEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.addon = _load_addon()

    def test_sop_geometry_unreadable_is_not_a_successful_cook(self) -> None:
        node = SimpleNamespace(
            path=lambda: "/obj/test/sop",
            type=lambda: _FakeNodeTypeWithCategory("Sop"),
            cook=lambda force=True: None,
            errors=lambda: [],
            warnings=lambda: [],
            geometry=lambda: (_ for _ in ()).throw(RuntimeError("geometry unavailable")),
        )
        result = self.addon._fx_node_evidence(node)
        self.assertFalse(result["geometry_available"])
        self.assertFalse(result["cook_succeeded"])

    def test_lop_cook_does_not_require_sop_geometry(self) -> None:
        node = SimpleNamespace(
            path=lambda: "/stage/test",
            type=lambda: _FakeNodeTypeWithCategory("Lop"),
            cook=lambda force=True: None,
            errors=lambda: [],
            warnings=lambda: [],
        )
        result = self.addon._fx_node_evidence(node)
        self.assertIsNone(result["geometry_available"])
        self.assertTrue(result["cook_succeeded"])


if __name__ == "__main__":
    unittest.main()
