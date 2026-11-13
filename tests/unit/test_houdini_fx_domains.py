from __future__ import annotations

import importlib.util
import hashlib
import hmac
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dcc_task_runtime import TaskSpec, builtin_domain_registry
from dcc_task_runtime.canonical import canonical_sha256
from houdini_bridge.client import BridgeError
from houdini_bridge.domain_packs import all_domain_packs, get_domain_pack, validate_candidate_patch
from houdini_bridge.install import ensure_approval_secret
from houdini_bridge.recipes import ReferenceEffectRecipe
from houdini_bridge.registry import COMMANDS
from houdini_bridge.tasks import HoudiniCommandAdapter, task_service


ROOT = Path(__file__).resolve().parents[2]
ADDON_PATH = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"


def _load_addon():
    spec = importlib.util.spec_from_file_location("_houdini_fx_contract_addon", ADDON_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Houdini add-on contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call(self, command, params=None):
        self.calls.append((command, params or {}))
        if command == "capabilities.get":
            return {"houdini_version": "contract-only", "fx_domain_packs": []}
        return {"gates": [{"name": command, "passed": True}]}


class StructuredClient(Client):
    def call(self, command, params=None):
        if command == "agent.fx.probe":
            return {
                "gates": [{"name": "fx_node_contract_probe", "passed": True, "kind": "capability"}],
            }
        if command == "agent.fx.build_preview":
            return {
                "gates": [{"name": "editable_native_fx_topology", "passed": True, "kind": "operation"}],
                "outcome_state": "DIAGNOSIS_INCONCLUSIVE",
            }
        if command == "agent.fx.apply_candidate":
            return {
                "gates": [{"name": "candidate_patch_applied", "passed": True, "kind": "operation"}],
                "cache_subject_hash": "host-subject-hash",
                "cache_approval_subject": {"purpose": "houdini_simulation_cache"},
                "parameter_diff": [{"semantic_control": "voxel_size"}],
            }
        if command == "agent.fx.collect_evidence":
            return {
                "gates": [{"name": "houdini_fx_technical_evidence", "passed": True, "kind": "verification"}],
                "evidence": {"frames": [1, 5, 9]},
                "diagnosis_state": "DIAGNOSIS_INCONCLUSIVE",
            }
        if command == "agent.fx.verify":
            return {
                "gates": [{"name": "houdini_fx_technical_evidence", "passed": True, "kind": "verification"}],
                "scorecard": {"visual_verdict": "INCONCLUSIVE"},
                "diagnosis_state": "DIAGNOSIS_INCONCLUSIVE",
            }
        return super().call(command, params)


class _SceneClient:
    def __init__(self, scene: Path, sha256: str) -> None:
        self.scene = scene
        self.sha256 = sha256
        self.current = scene
        self.dirty = False
        self.task_digest = "1" * 64
        self.non_task_digest = "2" * 64
        self.global_digest = "3" * 64
        self.external_digest = "4" * 64
        self.complete = True
        self.calls: list[tuple[str, dict]] = []

    def info(self):
        return {
            "hip_path": str(self.current),
            "hip_sha256": self.sha256 if self.current == self.scene else None,
            "has_unsaved_changes": self.dirty,
            "bridge_task_fingerprint": {
                "sha256": self.task_digest,
                "identity_complete": True,
            },
            "non_task_scene_fingerprint": {
                "sha256": self.non_task_digest,
                "identity_complete": True,
            },
            "global_scene_fingerprint": {
                "sha256": self.global_digest,
                "identity_complete": True,
            },
            "external_reference_fingerprint": {
                "sha256": self.external_digest,
                "identity_complete": True,
            },
            "scene_graph_identity_complete": self.complete,
        }

    def call(self, command, params=None):
        payload = dict(params or {})
        self.calls.append((command, payload))
        if command == "scene.info":
            return self.info()
        if command == "scene.open_hip":
            self.current = Path(str(payload["path"])).resolve()
            self.dirty = False
            return {
                "path": str(self.current),
                "sha256": self.sha256,
                "has_unsaved_changes": False,
            }
        raise AssertionError(command)


class HoudiniFrozenSceneBindingTests(unittest.TestCase):
    @staticmethod
    def _spec(scene: Path, digest: str, inputs=()) -> TaskSpec:
        return TaskSpec(
            task_type="houdini.reference_effect",
            intent="bind one frozen Houdini scene",
            target_application="houdini",
            target_scene_path=str(scene),
            constraints={"frozen_scene_sha256": digest},
            inputs=tuple(inputs),
        )

    @staticmethod
    def _action_result(client: _SceneClient) -> dict:
        return {
            "bridge_scene_fingerprints": {
                "bridge_task_fingerprint": {
                    "sha256": client.task_digest,
                    "scope": "bridge_task_nodes_only",
                    "identity_complete": True,
                },
                "non_task_scene_fingerprint": {
                    "sha256": client.non_task_digest,
                    "scope": "all_scene_nodes_except_bridge_task",
                    "identity_complete": True,
                },
                "global_scene_fingerprint": {
                    "sha256": client.global_digest,
                    "scope": "fps_ranges_take_color_config",
                    "identity_complete": True,
                },
                "external_reference_fingerprint": {
                    "sha256": client.external_digest,
                    "scope": "houdini_file_references_bound_to_explicit_inputs",
                    "identity_complete": True,
                },
                "scene_graph_identity_complete": True,
                "full_scene_identity_verified": False,
            }
        }

    def test_first_same_path_dirty_scene_fails_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scene = Path(directory) / "shot.hip"
            scene.write_bytes(b"frozen")
            digest = hashlib.sha256(scene.read_bytes()).hexdigest()
            client = _SceneClient(scene, digest)
            client.dirty = True
            adapter = HoudiniCommandAdapter(client)
            with self.assertRaises(BridgeError) as caught:
                adapter._ensure_target_scene(
                    self._spec(scene, digest), "abc", Path(directory) / "task"
                )
            self.assertEqual(caught.exception.code, "SCENE_STATE_DRIFT")
            self.assertEqual([item[0] for item in client.calls], ["scene.info"])

    def test_unknown_or_failed_dirty_readback_never_opens_a_scene(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scene = Path(directory) / "shot.hip"
            other = Path(directory) / "other.hip"
            scene.write_bytes(b"frozen")
            other.write_bytes(b"other")
            digest = hashlib.sha256(scene.read_bytes()).hexdigest()
            client = _SceneClient(scene, digest)
            client.current = other
            client.dirty = None
            adapter = HoudiniCommandAdapter(client)
            with self.assertRaises(BridgeError) as caught:
                adapter._ensure_target_scene(
                    self._spec(scene, digest), "abc", Path(directory)
                )
            self.assertEqual(caught.exception.code, "SCENE_STATE_DRIFT")
            self.assertEqual([item[0] for item in client.calls], ["scene.info"])

            class FailedReadClient(_SceneClient):
                def call(self, command, params=None):
                    if command == "scene.info":
                        raise BridgeError("COMMAND_FAILED", "dirty readback failed")
                    return super().call(command, params)

            failed = FailedReadClient(scene, digest)
            failed.current = other
            with self.assertRaises(BridgeError) as failed_caught:
                HoudiniCommandAdapter(failed)._ensure_target_scene(
                    self._spec(scene, digest), "abc", Path(directory)
                )
            self.assertEqual(failed_caught.exception.code, "COMMAND_FAILED")

    def test_bridge_owned_dirty_continuation_and_restart_use_both_digests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scene = Path(directory) / "shot.hip"
            scene.write_bytes(b"frozen")
            digest = hashlib.sha256(scene.read_bytes()).hexdigest()
            task_dir = Path(directory) / "task"
            task_dir.mkdir()
            client = _SceneClient(scene, digest)
            spec = self._spec(scene, digest)
            adapter = HoudiniCommandAdapter(client)
            adapter._ensure_target_scene(spec, "abc", task_dir)
            adapter._record_target_scene_mutation(
                spec, "abc", task_dir, self._action_result(client)
            )
            client.dirty = True
            adapter._ensure_target_scene(spec, "abc", task_dir)

            restarted = HoudiniCommandAdapter(client)
            restarted._ensure_target_scene(spec, "abc", task_dir)
            self.assertTrue((task_dir / "houdini-scene-binding.json").is_file())

    def test_task_non_task_and_global_drift_each_fail_closed(self) -> None:
        for attribute, changed in (
            ("task_digest", "4" * 64),
            ("non_task_digest", "5" * 64),
            ("global_digest", "6" * 64),
        ):
            with self.subTest(attribute=attribute), tempfile.TemporaryDirectory(
                prefix="bridge-scene-binding-"
            ) as directory:
                scene = Path(directory) / "shot.hip"
                scene.write_bytes(b"frozen")
                digest = hashlib.sha256(scene.read_bytes()).hexdigest()
                task_dir = Path(directory) / "task"
                task_dir.mkdir()
                client = _SceneClient(scene, digest)
                spec = self._spec(scene, digest)
                adapter = HoudiniCommandAdapter(client)
                adapter._ensure_target_scene(spec, "abc", task_dir)
                adapter._record_target_scene_mutation(
                    spec, "abc", task_dir, self._action_result(client)
                )
                client.dirty = True
                setattr(client, attribute, changed)
                with self.assertRaises(BridgeError) as caught:
                    adapter._ensure_target_scene(spec, "abc", task_dir)
                self.assertEqual(caught.exception.code, "SCENE_STATE_DRIFT")

    def test_unfrozen_or_changed_explicit_input_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scene = Path(directory) / "shot.hip"
            source = Path(directory) / "source.vdb"
            scene.write_bytes(b"frozen")
            source.write_bytes(b"source")
            scene_digest = hashlib.sha256(scene.read_bytes()).hexdigest()
            source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
            client = _SceneClient(scene, scene_digest)
            adapter = HoudiniCommandAdapter(client)
            missing_hash = self._spec(
                scene, scene_digest, ({"role": "source", "path": str(source)},)
            )
            with self.assertRaises(BridgeError):
                adapter._ensure_target_scene(missing_hash, "abc", Path(directory))

            frozen = self._spec(
                scene,
                scene_digest,
                ({"role": "source", "path": str(source), "sha256": source_digest},),
            )
            adapter._ensure_target_scene(frozen, "abc", Path(directory))
            source.write_bytes(b"changed")
            with self.assertRaises(BridgeError) as caught:
                adapter._ensure_target_scene(frozen, "abc", Path(directory))
            self.assertEqual(caught.exception.code, "SCENE_STATE_DRIFT")

    def test_open_requires_independent_clean_path_and_hash_readback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scene = Path(directory) / "shot.hip"
            other = Path(directory) / "other.hip"
            scene.write_bytes(b"frozen")
            other.write_bytes(b"other")
            digest = hashlib.sha256(scene.read_bytes()).hexdigest()
            client = _SceneClient(scene, digest)
            client.current = other
            adapter = HoudiniCommandAdapter(client)
            adapter._ensure_target_scene(
                self._spec(scene, digest), "abc", Path(directory)
            )
            self.assertEqual(
                [item[0] for item in client.calls],
                ["scene.info", "scene.open_hip", "scene.info"],
            )

    def test_reopened_scene_requires_explicit_clean_readback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scene = Path(directory) / "shot.hip"
            other = Path(directory) / "other.hip"
            scene.write_bytes(b"frozen")
            other.write_bytes(b"other")
            digest = hashlib.sha256(scene.read_bytes()).hexdigest()

            class UnknownAfterOpen(_SceneClient):
                def call(self, command, params=None):
                    result = super().call(command, params)
                    if command == "scene.info" and self.current == self.scene:
                        result["has_unsaved_changes"] = None
                    return result

            client = UnknownAfterOpen(scene, digest)
            client.current = other
            with self.assertRaises(BridgeError) as caught:
                HoudiniCommandAdapter(client)._ensure_target_scene(
                    self._spec(scene, digest), "abc", Path(directory)
                )
            self.assertEqual(caught.exception.code, "SCENE_STATE_DRIFT")

    def test_v2_sequence_manifest_requires_exact_ordered_coverage_and_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene = root / "shot.hip"
            scene.write_bytes(b"frozen")
            scene_digest = hashlib.sha256(scene.read_bytes()).hexdigest()
            pattern = str(root / "source.%04d.vdb")
            paths = {frame: root / "source.{:04d}.vdb".format(frame) for frame in (1, 2, 3)}
            for frame, path in paths.items():
                path.write_bytes("frame-{}".format(frame).encode("ascii"))

            def frame_record(frame: int, *, path: Path | None = None) -> dict:
                source = path or paths[frame]
                return {
                    "frame": frame,
                    "path": str(source),
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "bytes": source.stat().st_size,
                }

            def sequence_item(frames: list[dict]) -> dict:
                normalized = [
                    {
                        "index": index,
                        "frame": int(frame["frame"]),
                        "uri": str(Path(frame["path"]).resolve()),
                        "sha256": frame["sha256"],
                        "bytes": frame["bytes"],
                    }
                    for index, frame in enumerate(frames)
                ]
                return {
                    "role": "source",
                    "path": pattern,
                    "frames": frames,
                    "sha256": canonical_sha256(normalized),
                }

            def spec(item: dict) -> TaskSpec:
                return TaskSpec(
                    task_type="houdini.reference_effect",
                    intent="frozen v2 sequence",
                    target_application="houdini",
                    target_scene="existing",
                    target_scene_path=str(scene),
                    constraints={"frozen_scene_sha256": scene_digest},
                    inputs=(item,),
                    render={"frame_range": {"start": 1, "end": 3, "step": 1}},
                    schema_version="2.0",
                )

            complete = [frame_record(frame) for frame in (1, 2, 3)]
            self.assertEqual(
                len(HoudiniCommandAdapter._frozen_inputs_sha256(spec(sequence_item(complete)))),
                64,
            )
            for invalid in (
                [frame_record(1), frame_record(3)],
                [frame_record(1), frame_record(1), frame_record(3)],
                [frame_record(3), frame_record(2), frame_record(1)],
            ):
                with self.subTest(frames=[item["frame"] for item in invalid]), self.assertRaises(
                    BridgeError
                ):
                    HoudiniCommandAdapter._frozen_inputs_sha256(spec(sequence_item(invalid)))

            wrong = root / "other.0002.vdb"
            wrong.write_bytes(b"wrong")
            wrong_frames = [frame_record(1), frame_record(2, path=wrong), frame_record(3)]
            with self.assertRaisesRegex(BridgeError, "sequence pattern"):
                HoudiniCommandAdapter._frozen_inputs_sha256(spec(sequence_item(wrong_frames)))

    def test_v2_video_binds_container_and_time_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.mp4"
            path.write_bytes(b"video-container")
            common = dict(
                task_type="houdini.reference_effect",
                intent="freeze video",
                target_application="houdini",
                inputs=(
                    {
                        "role": "reference",
                        "path": str(path),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    },
                ),
                schema_version="2.0",
            )
            with self.assertRaisesRegex(BridgeError, "time_range"):
                HoudiniCommandAdapter._frozen_inputs_sha256(TaskSpec(**common))
            item = dict(common["inputs"][0])
            item["time_range"] = {"start": 0.0, "end": 2.0}
            self.assertEqual(
                len(
                    HoudiniCommandAdapter._frozen_inputs_sha256(
                        TaskSpec(**{**common, "inputs": (item,)})
                    )
                ),
                64,
            )


class HoudiniSceneFingerprintTests(unittest.TestCase):
    class _Node:
        def __init__(self, *, parms_error=False, geometry=b"", node_type="Sop/null") -> None:
            self.parms_error = parms_error
            self.flags = {
                "isBypassed": False,
                "isDisplayFlagSet": False,
                "isRenderFlagSet": False,
                "isTemplateFlagSet": False,
                "isSelectableInViewport": True,
                "isLockedHDA": False,
                "isHardLocked": False,
                "isTimeDependent": False,
            }
            self.geometry_bytes = geometry
            self.node_type = node_type

        def parms(self):
            if self.parms_error:
                raise RuntimeError("parms unavailable")
            return []

        def inputs(self):
            return []

        def userDataDict(self):
            return {}

        def type(self):
            return SimpleNamespace(nameWithCategory=lambda: self.node_type)

        def geometry(self):
            return SimpleNamespace(data=lambda: self.geometry_bytes)

        def __getattr__(self, name):
            if name in self.flags:
                return lambda: self.flags[name]
            raise AttributeError(name)

    def test_cook_affecting_flags_and_stored_geometry_change_the_digest(self) -> None:
        addon = _load_addon()
        node = self._Node()
        baseline = addon._houdini_node_graph_fingerprint({"/obj/a": node}, scope="test")
        self.assertTrue(baseline["identity_complete"])
        for flag in ("isBypassed", "isDisplayFlagSet", "isRenderFlagSet"):
            with self.subTest(flag=flag):
                node.flags[flag] = True
                changed = addon._houdini_node_graph_fingerprint({"/obj/a": node}, scope="test")
                self.assertNotEqual(changed["sha256"], baseline["sha256"])
                node.flags[flag] = False

        node.flags["isHardLocked"] = True
        node.geometry_bytes = b"geometry-a"
        geometry_a = addon._houdini_node_graph_fingerprint({"/obj/a": node}, scope="test")
        node.geometry_bytes = b"geometry-b"
        geometry_b = addon._houdini_node_graph_fingerprint({"/obj/a": node}, scope="test")
        self.assertNotEqual(geometry_a["sha256"], geometry_b["sha256"])

    def test_unreadable_required_node_state_marks_identity_incomplete(self) -> None:
        addon = _load_addon()
        record = addon._houdini_node_graph_fingerprint(
            {"/obj/a": self._Node(parms_error=True)}, scope="test"
        )
        self.assertFalse(record["identity_complete"])
        self.assertTrue(any("parms unreadable" in item for item in record["errors"]))

    def test_external_reference_must_be_covered_by_explicit_input(self) -> None:
        addon = _load_addon()

        class Owner:
            def path(self):
                return "/obj/file1"

        class Parm:
            def node(self):
                return Owner()

            def path(self):
                return "/obj/file1/file"

            def unexpandedString(self):
                return "/show/source.vdb"

        fake_hou = SimpleNamespace(
            fileReferences=lambda: [(Parm(), "/show/source.vdb")],
            expandString=lambda value: value,
        )
        with mock.patch.dict(sys.modules, {"hou": fake_hou}):
            covered = addon._scene_external_reference_fingerprint(
                {"/obj/file1": object()}, [{"path": "/show/source.vdb"}]
            )
            missing = addon._scene_external_reference_fingerprint(
                {"/obj/file1": object()}, []
            )
        self.assertTrue(covered["identity_complete"])
        self.assertFalse(missing["identity_complete"])

    def test_dcc_action_boundary_rehash_rejects_same_path_byte_replacement(self) -> None:
        addon = _load_addon()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.vdb"
            path.write_bytes(b"before")
            spec = TaskSpec(
                task_type="houdini.reference_effect",
                intent="freeze source",
                target_application="houdini",
                inputs=(
                    {
                        "path": str(path),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    },
                ),
                schema_version="2.0",
            )
            manifest = HoudiniCommandAdapter._frozen_inputs_manifest(spec)
            self.assertEqual(
                addon._rehash_frozen_input_manifest(manifest),
                canonical_sha256(manifest),
            )
            path.write_bytes(b"after!")
            with self.assertRaises(addon.BridgeCommandError) as caught:
                addon._rehash_frozen_input_manifest(manifest)
            self.assertEqual(caught.exception.code, "SCENE_STATE_DRIFT")

    def test_save_copy_preserves_current_dirty_hip_and_recovers_after_failure(self) -> None:
        addon = _load_addon()
        with tempfile.TemporaryDirectory() as directory:
            root_path = Path(directory)
            original = root_path / "shot.hip"
            output = root_path / "copy.hip"
            original.write_bytes(b"saved-original")

            class HipFile:
                def __init__(self, fail=False):
                    self.current = str(original)
                    self.dirty = True
                    self.fail = fail

                def path(self):
                    return self.current

                def hasUnsavedChanges(self):
                    return self.dirty

                def save(self, path, save_to_recent_files=False):
                    Path(path).write_bytes(b"dirty-scene-copy")
                    self.current = str(Path(path).resolve())
                    self.dirty = False
                    if self.fail:
                        raise RuntimeError("save failed")

                def setName(self, path):
                    self.current = path

            class Root:
                def __init__(self, hip):
                    self.hip = hip

                def setUserData(self, _name, _value):
                    self.hip.dirty = True

                def destroyUserData(self, _name):
                    pass

            hip = HipFile()
            with mock.patch.dict(sys.modules, {"hou": SimpleNamespace(hipFile=hip)}):
                addon._save_hip_copy_preserving_current(output, Root(hip))
            self.assertEqual(hip.current, str(original))
            self.assertTrue(hip.dirty)
            self.assertEqual(output.read_bytes(), b"dirty-scene-copy")

            failing = HipFile(fail=True)
            with mock.patch.dict(sys.modules, {"hou": SimpleNamespace(hipFile=failing)}):
                with self.assertRaisesRegex(RuntimeError, "save failed"):
                    addon._save_hip_copy_preserving_current(
                        root_path / "failed.hip", Root(failing)
                    )
            self.assertEqual(failing.current, str(original))
            self.assertTrue(failing.dirty)

            with self.subTest(check="symlink_output"):
                victim = root_path / "victim.hip"
                victim.write_bytes(b"do-not-overwrite")
                linked_output = root_path / "linked-copy.hip"
                try:
                    linked_output.symlink_to(victim)
                except OSError as exc:
                    if getattr(exc, "winerror", None) == 1314:
                        self.skipTest("NOT_RUN: Windows symbolic-link privilege unavailable")
                    raise
                clean = HipFile()
                clean.dirty = False
                with mock.patch.dict(sys.modules, {"hou": SimpleNamespace(hipFile=clean)}):
                    with self.assertRaises(addon.BridgeCommandError) as caught:
                        addon._save_hip_copy_preserving_current(linked_output, Root(clean))
                self.assertEqual(caught.exception.code, "OUTPUT_NOT_WRITABLE")
                self.assertEqual(victim.read_bytes(), b"do-not-overwrite")


class HoudiniDomainPackTests(unittest.TestCase):
    def test_selected_build_controls_evidence_flags_without_promoting_support(self):
        addon = _load_addon()
        for build, expected, current in (("22.0.459", True, True),
                                         ("22.0.429", False, True),
                                         ("22.0.368", False, False)):
            with self.subTest(build=build), mock.patch.object(
                addon, "_fx_valid_evidence_entries", return_value=([
                    {"evidence_kind": "live_dcc", "application": "houdini",
                     "application_build": build, "renderer": "karma", "render_validated": True}
                ], [])), mock.patch.object(addon, "_fx_valid_doubao_route", return_value=(None, [])):
                state = addon._fx_validation_state("pyro_smoke_v1", addon._FX_PACKS["pyro_smoke_v1"], current_build=build)
                self.assertEqual(state["houdini_22_validated"], expected)
                self.assertEqual(state["current_build_validated"], current)
                self.assertFalse(state["supported"])
                self.assertFalse(state["live_validated"])
        with mock.patch.dict(sys.modules, {"hou": SimpleNamespace(
                applicationVersionString=lambda: "22.0.999")}), \
                mock.patch.object(addon, "_fx_houdini_supported", return_value=True), \
                mock.patch.object(addon, "autostart", side_effect=AssertionError("must not start")):
            with self.assertRaisesRegex(RuntimeError, "HOUDINI_VERSION_UNSUPPORTED"):
                addon.task_host_serve()

    def test_all_first_party_houdini_packs_are_declared_experimental(self) -> None:
        expected = {
            "pyro_smoke_v1",
            "pyro_fire_v1",
            "particles_v1",
            "water_ocean_v1",
            "water_flip_v1",
            "crowd_agents_v1",
            "swarm_flocking_v1",
            "vellum_cloth_v1",
            "vellum_softbody_grains_v1",
            "hair_fur_v1",
            "rbd_destruction_v1",
            "procedural_geometry_v1",
            "material_lookdev_v1",
            "lighting_camera_render_v1",
            "explosion_composite_v1",
        }
        packs = all_domain_packs()
        self.assertEqual({pack.identifier for pack in packs}, expected)
        self.assertTrue(all(pack.maturity == "experimental" for pack in packs))
        self.assertTrue(all(pack.validated_houdini_versions == () for pack in packs))
        self.assertTrue(all(pack.nodes and pack.controls and pack.evidence and pack.metrics for pack in packs))

    def test_addon_and_host_catalogs_have_identical_pack_ids(self) -> None:
        addon = _load_addon()
        self.assertEqual(set(addon._FX_PACKS), {pack.identifier for pack in all_domain_packs()})

    def test_addon_and_host_catalogs_have_identical_public_semantics(self) -> None:
        addon = _load_addon()
        from houdini_bridge.native_domain_registry import overlay_host_pack
        from houdini_bridge.native_render_domains import overlay_host_pack as overlay_render
        # Native role/port routing is version-specific. Compare both catalogs
        # after their production overlays; actual routing is exercised by the
        # native graph and render build/feedback/save/reopen tests.
        for version in ("21.0.631", "22.0.429"):
            for pack in all_domain_packs():
                branches = ("softbody", "grains") if pack.identifier == "vellum_softbody_grains_v1" else (None,)
                for branch in branches:
                    with self.subTest(pack=pack.identifier, version=version, branch=branch):
                        host = pack.to_dict(native_version=version, native_branch=branch)
                        live = addon._FX_PACKS[pack.identifier]
                        if pack.identifier in {"material_lookdev_v1", "lighting_camera_render_v1"}:
                            live = overlay_render(pack.identifier, live, version)
                        elif pack.identifier in {"pyro_smoke_v1", "pyro_fire_v1", "vellum_cloth_v1",
                            "vellum_softbody_grains_v1", "crowd_agents_v1", "hair_fur_v1", "water_flip_v1",
                            "rbd_destruction_v1", "particles_v1", "swarm_flocking_v1", "water_ocean_v1", "procedural_geometry_v1"}:
                            live = overlay_host_pack(pack.identifier, live, version, branch)
                        host["nodes"] = [{**n, "types": n["type_candidates"],
                            "required_parms": n["required_parameter_aliases"]} for n in host["nodes"]]
                        host["controls"] = {c["id"]: {**c, "role": c["node_role"],
                            "aliases": c["parameter_aliases"]} for c in host["controls"]}
                        self.assertEqual(addon._fx_pack_semantic_contract(live), addon._fx_pack_semantic_contract(host))
                        self.assertEqual(set(live["controls"]), {c.identifier for c in pack.controls})

    def test_required_first_release_control_coverage_is_explicit(self) -> None:
        required = {
            "particles_v1": {"force_strength", "collision_radius", "trail_length", "motion_blur_scale"},
            "material_lookdev_v1": {"normal_strength", "displacement_scale", "anisotropy", "emission_weight"},
            "lighting_camera_render_v1": {"depth_of_field", "filter_width", "motion_blur", "volume_step_rate", "denoise"},
            "water_flip_v1": {"collision_separation", "collision_passes", "droplet_scale", "meshing_detail"},
            "vellum_cloth_v1": {"collision_thickness", "constraint_iterations", "wrinkle_scale"},
            "explosion_composite_v1": {"shockwave_thickness", "debris_amount", "fire_scale", "smoke_scale"},
        }
        catalogs = {pack.identifier: {control.identifier for control in pack.controls} for pack in all_domain_packs()}
        for pack_id, controls in required.items():
            self.assertTrue(controls.issubset(catalogs[pack_id]), pack_id)

    def test_runtime_candidate_controls_are_accepted_by_host_and_addon_catalogs(self) -> None:
        addon = _load_addon()
        runtime = builtin_domain_registry()
        host = {pack.identifier: {control.identifier for control in pack.controls} for pack in all_domain_packs()}
        for reference in runtime.list():
            if reference.identifier == "nuke_composite_v1":
                continue
            canonical = set(runtime.get(reference.identifier, reference.version).control_map)
            self.assertTrue(canonical.issubset(host[reference.identifier]), reference.identifier)
            self.assertTrue(canonical.issubset(addon._FX_PACKS[reference.identifier]["controls"]), reference.identifier)

    def test_topology_and_missing_passes_never_claim_live_visual_validation(self) -> None:
        addon = _load_addon()
        for pack in addon._FX_PACKS.values():
            # Validation flags must be derived from the pack, not read from a
            # constant that can only ever be False.
            self.assertEqual(addon._fx_validation_flags(pack), {"houdini_21_validated": False, "houdini_22_validated": False, "karma_render_validated": False})
            self.assertEqual(pack["maturity"], "experimental")
            self.assertEqual(pack["validated_houdini_versions"], [])
            self.assertEqual(pack["preview_kind"], "topology_scaffold")
            requirements = addon._fx_evidence_requirements(pack)
            self.assertTrue(requirements)
            self.assertTrue(all(item["available"] is False for item in requirements))
            self.assertTrue(all("not attached" in item["reason"] for item in requirements))

    def test_static_validation_declarations_cannot_promote_support(self) -> None:
        addon = _load_addon()
        for declarations in (
            {"validated_houdini_versions": [], "karma_render_validated": False},
            {"validated_houdini_versions": ["21.0.631"], "karma_render_validated": True},
            {"validated_houdini_versions": ["21.0.631", "22.0.368"]},
        ):
            self.assertEqual(
                addon._fx_validation_flags(declarations),
                {"houdini_21_validated": False, "houdini_22_validated": False, "karma_render_validated": False},
            )

    def test_declared_validation_survives_instead_of_being_erased(self) -> None:
        # The previous loop overwrote every pack with [] on import, so real
        # evidence could never take effect.
        addon = _load_addon()
        for pack in addon._FX_PACKS.values():
            self.assertIn("validated_houdini_versions", pack)

    def test_the_live_validation_constant_is_gone(self) -> None:
        # A module-level constant that can only be False makes promotion
        # unreachable regardless of evidence.
        addon = _load_addon()
        self.assertFalse(hasattr(addon, "_FX_LIVE_VALIDATION"))
        flags = addon._fx_validation_flags({"validated_houdini_versions": ["22.0.368"]})
        self.assertEqual(flags, {"houdini_21_validated": False, "houdini_22_validated": False, "karma_render_validated": False})

    def test_explicit_frames_cannot_escape_the_frozen_render_stride(self) -> None:
        addon = _load_addon()
        params = {
            "render": {"frame_range": {"start": 1, "end": 9, "step": 4}},
            "step_params": {"frames": [1, 5, 9]},
        }
        self.assertEqual(addon._fx_frame_values(params), [1, 5, 9])
        params["step_params"]["frames"] = [2, 6]
        with self.assertRaises(addon.BridgeCommandError) as context:
            addon._fx_frame_values(params)
        self.assertEqual(context.exception.code, "APPROVAL_REVOKED")

    def test_candidate_patch_accepts_only_bounded_semantic_controls(self) -> None:
        pack = get_domain_pack("pyro_smoke_v1")
        self.assertEqual(validate_candidate_patch(pack, {"voxel_size": 0.05, "disturbance": 1.5}), {"voxel_size": 0.05, "disturbance": 1.5})
        with self.assertRaises(ValueError):
            validate_candidate_patch(pack, {"raw_hscript": "hou.node('/').destroy()"})
        with self.assertRaises(ValueError):
            validate_candidate_patch(pack, {"voxel_size": -1})
        with self.assertRaises(ValueError):
            validate_candidate_patch(pack, {str(index): index for index in range(6)})

    def test_direct_addon_call_rejects_control_owned_by_nuke(self) -> None:
        addon = _load_addon()
        with self.assertRaises(addon.BridgeCommandError) as context:
            addon._fx_apply_candidate(
                {"step_params": {"changes": {"denoise_mix": 0.5}}},
                "pyro_smoke_v1",
                addon._FX_PACKS["pyro_smoke_v1"],
            )
        self.assertEqual(context.exception.code, "DCC_OWNERSHIP_MISMATCH")

    def test_all_high_level_actions_are_registered(self) -> None:
        self.assertTrue(
            {
                "agent.fx.probe",
                "agent.fx.build_preview",
                "agent.fx.collect_evidence",
                "agent.fx.apply_candidate",
                "agent.fx.verify",
                "agent.fx.cache",
                "agent.fx.deliver",
            }.issubset(COMMANDS)
        )


class HoudiniReferenceRecipeTests(unittest.TestCase):
    @staticmethod
    def _spec(pack: str, **fx):
        return {
            "schema_version": "2.0",
            "task_type": "houdini.reference_effect",
            "intent": "rebuild an editable reference effect",
            "target": {"application": "houdini"},
            "constraints": {"fx": {"domain_pack": pack, **fx}},
            "render": {"frame_range": {"start": 1, "end": 9, "step": 4}},
        }

    def test_simulation_plan_uses_stride_and_requires_explicit_cache_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = task_service(Client(), Path(directory))
            plan = service.plan(self._spec("pyro_smoke_v1", candidate_patch={"voxel_size": 0.05}))
        actions = [step["action"] for step in plan["steps"]]
        self.assertNotIn("agent.fx.cache", actions)
        evidence = next(step for step in plan["steps"] if step["action"] == "agent.fx.collect_evidence")
        self.assertEqual(evidence["params"]["frames"], [1, 5, 9])

    def test_cache_request_without_assertion_is_rejected_at_plan_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = task_service(Client(), Path(directory))
            with self.assertRaisesRegex(ValueError, "signed cache approval"):
                service.plan(self._spec("pyro_smoke_v1", cache_requested=True))

    def test_simulation_cache_step_carries_assertion_but_non_sim_pack_never_caches(self) -> None:
        approval = {
            "purpose": "houdini_simulation_cache",
            "subject_hash": "abc",
            "grant_id": "human-1",
            "expires_at": "2999-01-01T00:00:00Z",
            "signature": "contract-signature",
        }
        recipe = ReferenceEffectRecipe("houdini.reference_effect")
        with tempfile.TemporaryDirectory() as directory:
            service = task_service(Client(), Path(directory))
            simulation = service.plan(self._spec("particles_v1", cache_requested=True, cache_approval=approval))
            non_simulation = service.plan(self._spec("material_lookdev_v1", cache_requested=True, cache_approval=approval))
        cache_step = next(step for step in simulation["steps"] if step["action"] == "agent.fx.cache")
        self.assertEqual(cache_step["params"]["approval"], approval)
        self.assertNotIn("agent.fx.cache", [step["action"] for step in non_simulation["steps"]])
        self.assertEqual(recipe.identifier, "houdini.reference_effect")

    def test_visual_pipeline_alias_is_registered_without_breaking_v1(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = task_service(Client(), Path(directory))
            visual = service.plan(
                {
                    "schema_version": "2.0",
                    "task_type": "visual.reference_rebuild",
                    "intent": "rebuild smoke from reference",
                    "target": {"application": "pipeline"},
                    "constraints": {"fx": {"domain_pack": "pyro_smoke_v1"}},
                }
            )
            legacy = service.plan(
                {
                    "task_type": "houdini.model_to_karma",
                    "intent": "make a crate",
                    "target": {"application": "houdini"},
                }
            )
        self.assertEqual(visual["steps"][0]["action"], "agent.fx.probe")
        self.assertEqual(legacy["steps"][0]["action"], "agent.model.probe")

    def test_cache_wait_requires_owned_stop_receipt_not_complete_frame_files(self) -> None:
        complete = {"cached": True, "cache": {"state": "COMPLETE", "stop_confirmed": True},
                    "artifacts": [{"kind": "simulation_cache"}]}
        class Client:
            calls = []
            def call(self, method, payload):
                self.calls.append((method, payload))
                return complete
        client = Client()
        initial = {"cached": False, "cache": {"state": "RUNNING", "frames": [1,5,9]}}
        payload = {"task_id": "cache-test", "fx": {"resource_contract": {"max_seconds": 1}}}
        self.assertEqual(HoudiniCommandAdapter(client)._wait_for_fx_cache(initial, payload), complete)
        self.assertEqual(client.calls, [("agent.fx.cache_status", payload)])
        with self.assertRaisesRegex(RuntimeError, "requires recovery"):
            HoudiniCommandAdapter(client)._wait_for_fx_cache({"cache":{"state":"RECONCILE"}}, payload)

    def test_structured_evidence_and_host_approval_subject_survive_task_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = task_service(StructuredClient(), Path(directory))
            started = service.start(
                self._spec("pyro_smoke_v1", candidate_patch={"voxel_size": 0.05}),
                background=False,
            )
            result = service.result(started["task_id"])
        outputs = result["step_outputs"]
        self.assertEqual(outputs["fx_collect_evidence"]["output"]["evidence"]["frames"], [1, 5, 9])
        self.assertEqual(outputs["fx_apply_candidate"]["output"]["cache_subject_hash"], "host-subject-hash")
        self.assertEqual(outputs["fx_verify"]["output"]["scorecard"]["visual_verdict"], "INCONCLUSIVE")
        self.assertFalse(any(gate.get("kind") == "evidence_carrier" for gate in result["gates"]))


class HoudiniApprovalContractTests(unittest.TestCase):
    def test_cache_approval_is_bound_to_purpose_and_subject(self) -> None:
        addon = _load_addon()
        secret = "test-only-control-plane-secret-32-bytes-minimum"
        expires_at = "2999-01-01T00:00:00Z"
        signed = "houdini_simulation_cache:subject-a:grant-a:{}".format(expires_at)
        approval = {
            "purpose": "houdini_simulation_cache",
            "subject_hash": "subject-a",
            "grant_id": "grant-a",
            "expires_at": expires_at,
            "signature": hmac.new(secret.encode("utf-8"), signed.encode("utf-8"), hashlib.sha256).hexdigest(),
        }
        previous = os.environ.get("HOUDINI_BRIDGE_APPROVAL_SECRET")
        os.environ["HOUDINI_BRIDGE_APPROVAL_SECRET"] = secret
        try:
            verified = addon._fx_validate_cache_approval(approval, "subject-a")
            self.assertEqual(verified["verified_by"], "signature")
            with self.assertRaises(addon.BridgeCommandError) as context:
                addon._fx_validate_cache_approval(approval, "subject-b")
            self.assertEqual(context.exception.code, "APPROVAL_REVOKED")
            wrong_purpose = {**approval, "purpose": "repair_case_promotion"}
            with self.assertRaises(addon.BridgeCommandError) as context:
                addon._fx_validate_cache_approval(wrong_purpose, "subject-a")
            self.assertEqual(context.exception.code, "APPROVAL_SCOPE_MISMATCH")
        finally:
            if previous is None:
                os.environ.pop("HOUDINI_BRIDGE_APPROVAL_SECRET", None)
            else:
                os.environ["HOUDINI_BRIDGE_APPROVAL_SECRET"] = previous

    def test_forgeable_trusted_boolean_is_rejected(self) -> None:
        addon = _load_addon()
        approval = {
            "purpose": "houdini_simulation_cache",
            "subject_hash": "subject-a",
            "grant_id": "grant-a",
            "trusted_control_plane": True,
        }
        with self.assertRaises(addon.BridgeCommandError) as context:
            addon._fx_validate_cache_approval(approval, "subject-a")
        self.assertEqual(context.exception.code, "APPROVAL_INVALID")

    def test_recipe_rejects_forgeable_trusted_boolean_before_execution(self) -> None:
        approval = {
            "purpose": "houdini_simulation_cache",
            "subject_hash": "subject-a",
            "grant_id": "grant-a",
            "trusted_control_plane": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            service = task_service(Client(), Path(directory))
            with self.assertRaisesRegex(ValueError, "missing: expires_at, signature"):
                service.plan(
                    HoudiniReferenceRecipeTests._spec(
                        "pyro_smoke_v1",
                        cache_requested=True,
                        cache_approval=approval,
                    )
                )

    def test_signed_approval_requires_a_verifiable_secret(self) -> None:
        addon = _load_addon()
        previous = os.environ.pop("HOUDINI_BRIDGE_APPROVAL_SECRET", None)
        previous_file = os.environ.get("BRIDGE_SKILLS_APPROVAL_SECRET_FILE")
        with tempfile.TemporaryDirectory() as directory:
            os.environ["BRIDGE_SKILLS_APPROVAL_SECRET_FILE"] = str(Path(directory) / "missing.key")
            try:
                approval = {
                    "purpose": "houdini_simulation_cache",
                    "subject_hash": "subject-a",
                    "grant_id": "grant-a",
                    "expires_at": "2999-01-01T00:00:00Z",
                    "signature": "not-verifiable",
                }
                with self.assertRaises(addon.BridgeCommandError) as context:
                    addon._fx_validate_cache_approval(approval, "subject-a")
                self.assertEqual(context.exception.code, "APPROVAL_INVALID")
            finally:
                if previous is not None:
                    os.environ["HOUDINI_BRIDGE_APPROVAL_SECRET"] = previous
                if previous_file is None:
                    os.environ.pop("BRIDGE_SKILLS_APPROVAL_SECRET_FILE", None)
                else:
                    os.environ["BRIDGE_SKILLS_APPROVAL_SECRET_FILE"] = previous_file

    def test_installer_secret_is_idempotent_private_and_shared_with_addon(self) -> None:
        addon = _load_addon()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "approval.key"
            first = ensure_approval_secret(path)
            value = first.read_text(encoding="ascii").strip()
            second = ensure_approval_secret(path)
            self.assertEqual(second.read_text(encoding="ascii").strip(), value)
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o077, 0)
            previous = os.environ.get("BRIDGE_SKILLS_APPROVAL_SECRET_FILE")
            os.environ["BRIDGE_SKILLS_APPROVAL_SECRET_FILE"] = str(path)
            try:
                self.assertEqual(addon._approval_secret_value(), value)
                if os.name != "nt":
                    path.chmod(0o644)
                    with self.assertRaises(addon.BridgeCommandError):
                        addon._approval_secret_value()
            finally:
                if previous is None:
                    os.environ.pop("BRIDGE_SKILLS_APPROVAL_SECRET_FILE", None)
                else:
                    os.environ["BRIDGE_SKILLS_APPROVAL_SECRET_FILE"] = previous

    def test_installer_rejects_preexisting_short_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "approval.key"
            path.write_text("short\n", encoding="ascii")
            with self.assertRaisesRegex(RuntimeError, "too short"):
                ensure_approval_secret(path)

    def test_non_simulation_cache_action_is_a_noop(self) -> None:
        addon = _load_addon()
        result = addon._fx_cache({}, "material_lookdev_v1", addon._FX_PACKS["material_lookdev_v1"])
        self.assertFalse(result["cached"])
        self.assertFalse(result["cache_required"])
        self.assertTrue(result["gates"][0]["skipped"])


if __name__ == "__main__":
    unittest.main()
