from __future__ import annotations

import json
import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from dcc_task_runtime import RecipeRegistry, Step, TaskEngine, TaskSpec, TaskStore
from houdini_bridge import tasks as houdini_tasks
from houdini_bridge.recipes import ModelToKarmaRecipe, ReferenceEffectRecipe
from houdini_bridge.tasks import HoudiniCommandAdapter
from houdini_bridge.__main__ import _watch as watch_houdini
from nuke_bridge import tasks as nuke_tasks
from nuke_bridge.recipes import ReferenceCompositeRecipe, RenderDeliveryRecipe
from nuke_bridge.tasks import NukeCommandAdapter
from nuke_bridge.__main__ import _watch as watch_nuke


class _ResponseClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[str] = []

    def call(self, command, _params=None):
        self.calls.append(command)
        return dict(self.response)


def _houdini_spec() -> TaskSpec:
    return TaskSpec(
        task_type="houdini.reference_effect",
        intent="verify one effect step",
        target_application="houdini",
        constraints={"fx": {"domain_pack": "pyro_smoke_v1"}},
    )


def _nuke_spec() -> TaskSpec:
    return TaskSpec(
        task_type="nuke.reference_composite",
        intent="verify one composite step",
        target_application="nuke",
    )


class CrossLayerGateNegativeTests(unittest.TestCase):
    def test_strict_gate_cannot_omit_kind(self) -> None:
        adapter = NukeCommandAdapter(
            _ResponseClient({"gates": [{"name": "preview_artifact", "passed": True}]})
        )
        step = Step(
            "verify_preview",
            "TECH_VERIFY",
            "agent.nuke.verify_preview",
            gate_policy="strict",
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "gate_kind_unsupported"):
                adapter.execute(step, _nuke_spec(), Path(directory))

    def test_technical_verify_cannot_use_an_operation_action(self) -> None:
        client = _ResponseClient(
            {
                "gates": [
                    {
                        "name": "preview_rendered",
                        "passed": True,
                        "kind": "operation",
                    }
                ]
            }
        )
        adapter = NukeCommandAdapter(client)
        step = Step(
            "fake_verify",
            "TECH_VERIFY",
            "agent.nuke.render_preview",
            gate_policy="strict",
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "STEP_PHASE_NOT_ALLOWED"):
                adapter.execute(step, _nuke_spec(), Path(directory))
        self.assertEqual(client.calls, [])

    def test_houdini_carrier_progress_and_unknown_kind_cannot_verify(self) -> None:
        cases = (
            "evidence_carrier",
            "progress",
            "caller_invented_kind",
        )
        for step_policy in ("legacy_first_party", "strict"):
            for gate_kind in cases:
                with self.subTest(step_policy=step_policy, gate_kind=gate_kind):
                    client = _ResponseClient(
                        {
                            "gates": [
                                {
                                    "name": "houdini_fx_technical_evidence",
                                    "passed": True,
                                    "kind": gate_kind,
                                }
                            ]
                        }
                    )
                    adapter = HoudiniCommandAdapter(client)
                    step = Step(
                        "collect",
                        "TECH_VERIFY",
                        "agent.fx.collect_evidence",
                        gate_policy=step_policy,
                    )
                    with tempfile.TemporaryDirectory() as directory:
                        with self.assertRaisesRegex(RuntimeError, "gate_kind_unsupported"):
                            adapter.execute(step, _houdini_spec(), Path(directory))

    def test_cross_action_operation_cannot_satisfy_nuke_verification(self) -> None:
        adapter = NukeCommandAdapter(
            _ResponseClient(
                {
                    "gates": [
                        {
                            "name": "preview_rendered",
                            "passed": True,
                            "kind": "operation",
                        }
                    ]
                }
            )
        )
        step = Step("verify_preview", "TECH_VERIFY", "agent.nuke.verify_preview", gate_policy="strict")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "gate_not_allowed_for_action"):
                adapter.execute(step, _nuke_spec(), Path(directory))

    def test_composite_final_artifact_cannot_bypass_lineage_gate(self) -> None:
        adapter = NukeCommandAdapter(
            _ResponseClient(
                {
                    "gates": [
                        {
                            "name": "composite_final_artifacts",
                            "passed": True,
                            "kind": "verification",
                        }
                    ]
                }
            )
        )
        step = Step(
            "verify_composite_final",
            "ARTIFACT_VERIFY",
            "agent.nuke.composite.verify_final",
            gate_policy="strict",
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "required_gate_missing"):
                adapter.execute(step, _nuke_spec(), Path(directory))

    def test_action_phase_spoofing_is_rejected_before_any_dcc_call(self) -> None:
        cases = (
            (
                NukeCommandAdapter,
                _nuke_spec(),
                "agent.nuke.composite.build_graph",
                "DELIVER",
            ),
            (
                NukeCommandAdapter,
                _nuke_spec(),
                "agent.nuke.composite.audit_lineage",
                "DELIVER",
            ),
            (
                NukeCommandAdapter,
                _nuke_spec(),
                "agent.nuke.composite.render_preview",
                "TECH_VERIFY",
            ),
            (
                HoudiniCommandAdapter,
                _houdini_spec(),
                "agent.fx.build_preview",
                "DELIVER",
            ),
            (
                HoudiniCommandAdapter,
                _houdini_spec(),
                "agent.model.render_preview",
                "TECH_VERIFY",
            ),
        )
        for adapter_type, spec, action, phase in cases:
            with self.subTest(action=action, phase=phase):
                client = _ResponseClient({})
                adapter = adapter_type(client)
                step = Step("spoofed_phase", phase, action, gate_policy="strict")
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaisesRegex(RuntimeError, "STEP_PHASE_NOT_ALLOWED"):
                        adapter.execute(step, spec, Path(directory))
                self.assertEqual(client.calls, [])


class RegisteredRecipePhaseContractTests(unittest.TestCase):
    def test_every_registered_recipe_step_matches_its_exact_action_phase(self) -> None:
        houdini_specs = (
            (
                houdini_tasks.BridgeProbeRecipe(),
                TaskSpec(
                    task_type="houdini.bridge_probe",
                    intent="probe Houdini",
                    target_application="houdini",
                ),
            ),
            (
                ModelToKarmaRecipe(),
                TaskSpec(
                    task_type="houdini.model_to_karma",
                    intent="build a Karma scene",
                    target_application="houdini",
                ),
            ),
            (
                ReferenceEffectRecipe("houdini.reference_effect"),
                TaskSpec(
                    task_type="houdini.reference_effect",
                    intent="exercise every Houdini FX action",
                    target_application="houdini",
                    constraints={
                        "fx": {
                            "domain_pack": "pyro_smoke_v1",
                            "run_mode": "delivery",
                            "candidate_patch": {"disturbance": 1.0},
                            "cache_requested": True,
                            "cache_output": "/tmp/cache.$F4.vdb",
                            "cache_approval": {
                                "purpose": "houdini_simulation_cache",
                                "subject_hash": "subject",
                                "grant_id": "grant",
                                "expires_at": "2099-01-01T00:00:00Z",
                                "signature": "signature",
                            },
                        }
                    },
                ),
            ),
        )
        nuke_specs = (
            (
                nuke_tasks.BridgeProbeRecipe(),
                TaskSpec(
                    task_type="nuke.bridge_probe",
                    intent="probe Nuke",
                    target_application="nuke",
                ),
            ),
            (
                RenderDeliveryRecipe(),
                TaskSpec(
                    task_type="nuke.render_delivery",
                    intent="render in Nuke",
                    target_application="nuke",
                ),
            ),
            (
                ReferenceCompositeRecipe(),
                TaskSpec(
                    task_type="nuke.reference_composite",
                    intent="exercise every Nuke composite action",
                    target_application="nuke",
                    inputs=({"role": "effect_render", "path": "/tmp/effect.%04d.exr"},),
                    constraints={
                        "run_mode": "delivery",
                        "composite_candidate_patch": {"controls": {"blur_size": 1.0}},
                    },
                ),
            ),
        )

        seen_houdini: set[str] = set()
        for recipe, spec in houdini_specs:
            for step in recipe.steps(spec, {}):
                policy = houdini_tasks.houdini_gate_policy(step.action)
                policy.validate_phase(
                    step.phase,
                    allow_legacy=step.gate_policy == "legacy_first_party",
                )
                seen_houdini.add(step.action)
        seen_nuke: set[str] = set()
        for recipe, spec in nuke_specs:
            for step in recipe.steps(spec, {}):
                policy = nuke_tasks.nuke_gate_policy(step.action)
                policy.validate_phase(
                    step.phase,
                    allow_legacy=step.gate_policy == "legacy_first_party",
                )
                seen_nuke.add(step.action)

        self.assertEqual(seen_houdini, set(houdini_tasks._HOUDINI_STRICT_GATE_POLICIES))
        self.assertEqual(seen_nuke, set(nuke_tasks._NUKE_STRICT_GATE_POLICIES))


class NukeSceneBindingTests(unittest.TestCase):
    def test_render_request_survives_adapter_restart_and_freezes_content_and_scene(self) -> None:
        from unittest import mock
        class Client:
            def __init__(self): self.calls = []
            def call(self, command, params):
                self.calls.append((command, dict(params)))
                return {'gates': [{'name':'composite_preview_rendered', 'kind':'operation', 'passed':True}],
                        'pre_scene_state': {'scene_fingerprint':params.get('expected_pre_scene_fingerprint'),
                                            'fingerprint_complete':True}}
        step = Step('preview-1', 'PREVIEW_RENDER', 'agent.nuke.composite.render_preview',
                    params={'frame':1}, gate_policy='strict')
        client = Client()
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/"effect.exr"
            from dcc_task_runtime.exr_codec import encode_tiny_exr
            from dataclasses import replace
            source.write_bytes(encode_tiny_exr(1.0))
            spec = replace(_nuke_spec(),inputs=({"role":"effect_render","path":str(source),"sha256":hashlib.sha256(source.read_bytes()).hexdigest()},))
            directory = Path(temp)/'task-1'
            scene = {'scene_fingerprint':'a'*64, 'fingerprint_complete':True}
            with mock.patch.object(NukeCommandAdapter, '_ensure_target_scene', return_value=scene):
                NukeCommandAdapter(client).execute(step, spec, directory)
                NukeCommandAdapter(client).execute(step, spec, directory)
                self.assertEqual(client.calls[0][1]['request_id'], client.calls[1][1]['request_id'])
                NukeCommandAdapter(client).execute(step, spec, Path(temp)/'task-2')
                self.assertNotEqual(client.calls[0][1]['request_id'], client.calls[2][1]['request_id'])
                changed = Step(step.identifier, step.phase, step.action, params={'frame':3}, gate_policy='strict')
                with self.assertRaisesRegex(RuntimeError, 'CONTENT_CHANGED'):
                    NukeCommandAdapter(client).execute(changed, spec, directory)
            with mock.patch.object(NukeCommandAdapter, '_ensure_target_scene', return_value={
                    'scene_fingerprint':'b'*64, 'fingerprint_complete':True}):
                with self.assertRaisesRegex(RuntimeError, 'frozen scene changed'):
                    NukeCommandAdapter(client).execute(step, spec, directory)
            self.assertEqual(len([call for call in client.calls if call[0] == step.action]), 3)
            self.assertEqual(client.calls[-1][0], "render_status")
            store = json.loads((directory/'nuke_render_requests.json').read_text())
            self.assertEqual(store['requests']['preview-1']['scene_fingerprint'], 'a'*64)

    def test_each_ensure_reopens_after_an_intermediate_script_switch(self) -> None:
        class SwitchingClient:
            def __init__(self, current: str) -> None:
                self.current = current
                self.calls: list[tuple[str, dict]] = []

            def call(self, command, params=None):
                payload = dict(params or {})
                self.calls.append((command, payload))
                if command == "script.info":
                    return {
                        "script": self.current,
                        "modified": False,
                        "scene_fingerprint": "1" * 64,
                        "fingerprint_complete": True,
                    }
                if command == "open_script":
                    self.current = str(payload["path"])
                    return {"path": str(payload["path"])}
                raise AssertionError(command)

        with tempfile.TemporaryDirectory() as directory:
            expected = str((Path(directory) / "expected.nk").resolve())
            switched = str((Path(directory) / "switched.nk").resolve())
            client = SwitchingClient(expected)
            adapter = NukeCommandAdapter(client)
            spec = TaskSpec(
                task_type="nuke.reference_composite",
                intent="bind every step to one NK",
                target_application="nuke",
                target_scene_path=expected,
            )

            adapter._ensure_target_scene(spec)
            client.current = switched
            adapter._ensure_target_scene(spec)

        self.assertEqual(
            [command for command, _payload in client.calls],
            ["script.info", "script.info", "open_script", "script.info"],
        )
        open_calls = [payload for command, payload in client.calls if command == "open_script"]
        self.assertEqual(open_calls, [{"path": expected, "sha256": ""}])

    def test_open_echo_cannot_replace_independent_script_info_readback(self) -> None:
        class LyingOpenClient:
            def __init__(self, current: str) -> None:
                self.current = current
                self.calls: list[str] = []

            def call(self, command, params=None):
                self.calls.append(command)
                if command == "script.info":
                    return {
                        "script": self.current,
                        "modified": False,
                        "scene_fingerprint": "2" * 64,
                        "fingerprint_complete": True,
                    }
                if command == "open_script":
                    return {"path": str((params or {})["path"])}
                raise AssertionError(command)

        with tempfile.TemporaryDirectory() as directory:
            expected = str((Path(directory) / "expected.nk").resolve())
            client = LyingOpenClient(str((Path(directory) / "other.nk").resolve()))
            adapter = NukeCommandAdapter(client)
            spec = TaskSpec(
                task_type="nuke.reference_composite",
                intent="reject a false open echo",
                target_application="nuke",
                target_scene_path=expected,
            )
            with self.assertRaisesRegex(RuntimeError, "exact target.scene_path"):
                adapter._ensure_target_scene(spec)

        self.assertEqual(client.calls, ["script.info", "open_script", "script.info"])

    def test_unknown_modified_state_never_opens_over_another_script(self) -> None:
        class UnknownClient:
            def __init__(self, current: str) -> None:
                self.current = current
                self.calls: list[str] = []

            def call(self, command, _params=None):
                self.calls.append(command)
                if command == "script.info":
                    return {"script": self.current, "modified": None}
                if command == "open_script":
                    raise AssertionError("open_script must not be called")
                raise AssertionError(command)

        with tempfile.TemporaryDirectory() as directory:
            expected = str((Path(directory) / "expected.nk").resolve())
            other = str((Path(directory) / "other.nk").resolve())
            client = UnknownClient(other)
            adapter = NukeCommandAdapter(client)
            spec = TaskSpec(
                task_type="nuke.reference_composite",
                intent="do not overwrite unknown dirty state",
                target_application="nuke",
                target_scene_path=expected,
            )
            with self.assertRaisesRegex(RuntimeError, "SCENE_STATE_DRIFT"):
                adapter._ensure_target_scene(spec)

        self.assertEqual(client.calls, ["script.info"])

    def test_same_path_unowned_modified_scene_fails_closed(self) -> None:
        class DirtyClient:
            def __init__(self, current: str) -> None:
                self.current = current
                self.calls: list[str] = []

            def call(self, command, _params=None):
                self.calls.append(command)
                if command == "script.info":
                    return {
                        "script": self.current,
                        "modified": True,
                        "scene_fingerprint": "3" * 64,
                        "fingerprint_complete": True,
                    }
                raise AssertionError(command)

        with tempfile.TemporaryDirectory() as directory:
            expected_path = Path(directory) / "expected.nk"
            expected_path.write_text("Root {}", encoding="utf-8")
            client = DirtyClient(str(expected_path.resolve()))
            adapter = NukeCommandAdapter(client)
            spec = TaskSpec(
                task_type="nuke.reference_composite",
                intent="reject unowned dirty state",
                target_application="nuke",
                target_scene_path=str(expected_path),
                constraints={
                    "frozen_scene_sha256": hashlib.sha256(expected_path.read_bytes()).hexdigest()
                },
            )

            with self.assertRaisesRegex(RuntimeError, "SCENE_STATE_DRIFT"):
                adapter._ensure_target_scene(spec)

        self.assertEqual(client.calls, ["script.info"])

    def test_same_path_frozen_scene_byte_replacement_fails_before_dcc_call(self) -> None:
        class NoCallClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def call(self, command, _params=None):
                self.calls.append(command)
                raise AssertionError(command)

        with tempfile.TemporaryDirectory() as directory:
            expected_path = Path(directory) / "expected.nk"
            expected_path.write_bytes(b"scene-a")
            frozen = hashlib.sha256(expected_path.read_bytes()).hexdigest()
            expected_path.write_bytes(b"scene-b")
            client = NoCallClient()
            adapter = NukeCommandAdapter(client)
            spec = TaskSpec(
                task_type="nuke.reference_composite",
                intent="reject replaced scene bytes",
                target_application="nuke",
                target_scene_path=str(expected_path),
                constraints={"frozen_scene_sha256": frozen},
            )

            with self.assertRaisesRegex(RuntimeError, "SCENE_STATE_DRIFT"):
                adapter._ensure_target_scene(spec)

        self.assertEqual(client.calls, [])

    def test_owned_bridge_fingerprint_allows_expected_modified_state(self) -> None:
        class OwnedClient:
            def __init__(self, current: str) -> None:
                self.current = current
                self.calls: list[str] = []

            def call(self, command, _params=None):
                self.calls.append(command)
                if command == "script.info":
                    return {
                        "script": self.current,
                        "modified": True,
                        "scene_fingerprint": "4" * 64,
                        "fingerprint_complete": True,
                    }
                raise AssertionError(command)

        with tempfile.TemporaryDirectory() as directory:
            expected_path = Path(directory) / "expected.nk"
            expected_path.write_bytes(b"scene")
            client = OwnedClient(str(expected_path.resolve()))
            adapter = NukeCommandAdapter(client)
            adapter._owned_scene_fingerprints[str(expected_path.resolve())] = "4" * 64
            spec = TaskSpec(
                task_type="nuke.reference_composite",
                intent="continue bridge-owned dirty state",
                target_application="nuke",
                target_scene_path=str(expected_path),
            )

            adapter._ensure_target_scene(spec)

        self.assertEqual(client.calls, ["script.info"])

    def test_scene_ownership_survives_adapter_restart_and_rejects_tamper(self) -> None:
        class PersistentClient:
            def __init__(self, current: str) -> None:
                self.current = current
                self.fingerprint = "5" * 64
                self.calls: list[str] = []

            def call(self, command, _params=None):
                self.calls.append(command)
                if command == "script.info":
                    return {
                        "script": self.current,
                        "modified": True,
                        "scene_fingerprint": self.fingerprint,
                        "fingerprint_complete": True,
                    }
                if command == "capabilities.get":
                    return {
                        "loaded_addon_path": "/trusted/nuke_bridge_addon.py",
                        "loaded_addon_sha256": "a" * 64,
                    }
                raise AssertionError(command)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene = root / "expected.nk"
            scene.write_bytes(b"scene")
            task_dir = root / "task-restart"
            client = PersistentClient(str(scene.resolve()))
            spec = TaskSpec(
                task_type="nuke.reference_composite",
                intent="resume bridge-owned scene",
                target_application="nuke",
                target_scene_path=str(scene),
            )

            first = NukeCommandAdapter(client)
            atomic_state = {
                "script": str(scene.resolve()),
                "modified": True,
                "scene_fingerprint": "5" * 64,
                "fingerprint_complete": True,
            }
            first._record_target_scene_state(spec, task_dir, atomic_state)
            second = NukeCommandAdapter(client)
            second._ensure_target_scene(spec, task_dir)

            binding_path = task_dir / "nuke_scene_binding.json"
            payload = json.loads(binding_path.read_text(encoding="utf-8"))
            payload["scene_fingerprint"] = "6" * 64
            binding_path.write_text(json.dumps(payload), encoding="utf-8")
            third = NukeCommandAdapter(client)
            with self.assertRaisesRegex(RuntimeError, "binding identity changed"):
                third._ensure_target_scene(spec, task_dir)

            # Restore a valid binding, then prove that a changed live scene is
            # not accepted merely because the task-side ownership exists.
            first._record_target_scene_state(spec, task_dir, atomic_state)
            client.fingerprint = "7" * 64
            fourth = NukeCommandAdapter(client)
            with self.assertRaisesRegex(RuntimeError, "unowned unsaved changes"):
                fourth._ensure_target_scene(spec, task_dir)

    def test_persisted_scene_binding_requires_exact_schema_and_digest_fields(self) -> None:
        class PersistentClient:
            def __init__(self, scene: str) -> None:
                self.scene = scene

            def call(self, command, _params=None):
                if command == "script.info":
                    return {
                        "script": self.scene,
                        "modified": True,
                        "scene_fingerprint": "b" * 64,
                        "fingerprint_complete": True,
                    }
                if command == "capabilities.get":
                    return {
                        "loaded_addon_path": "/trusted/nuke_bridge_addon.py",
                        "loaded_addon_sha256": "c" * 64,
                    }
                raise AssertionError(command)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene = root / "expected.nk"
            scene.write_bytes(b"scene")
            task_dir = root / "binding-schema-task"
            client = PersistentClient(str(scene.resolve()))
            spec = TaskSpec(
                task_type="nuke.reference_composite",
                intent="reject unknown binding formats",
                target_application="nuke",
                target_scene_path=str(scene),
            )
            first = NukeCommandAdapter(client)
            first._record_target_scene_state(
                spec,
                task_dir,
                {
                    "script": str(scene.resolve()),
                    "modified": True,
                    "scene_fingerprint": "b" * 64,
                    "fingerprint_complete": True,
                },
            )
            binding_path = task_dir / "nuke_scene_binding.json"
            original = json.loads(binding_path.read_text(encoding="utf-8"))

            def write_self_consistent(payload):
                unsigned = {key: value for key, value in payload.items() if key != "binding_identity"}
                payload["binding_identity"] = first._binding_identity(unsigned)
                binding_path.write_text(json.dumps(payload), encoding="utf-8")

            wrong_schema = dict(original)
            wrong_schema["schema"] = "bridge-skills.nuke-scene-binding/0.9"
            write_self_consistent(wrong_schema)
            with self.assertRaisesRegex(RuntimeError, "schema is unsupported"):
                NukeCommandAdapter(client)._ensure_target_scene(spec, task_dir)

            extra_field = dict(original)
            extra_field["untrusted_extension"] = True
            write_self_consistent(extra_field)
            with self.assertRaisesRegex(RuntimeError, "schema is unsupported"):
                NukeCommandAdapter(client)._ensure_target_scene(spec, task_dir)

            plain_fingerprint = dict(original)
            plain_fingerprint["scene_fingerprint"] = "self-consistent-but-not-a-digest"
            write_self_consistent(plain_fingerprint)
            with self.assertRaisesRegex(RuntimeError, "digest is invalid"):
                NukeCommandAdapter(client)._ensure_target_scene(spec, task_dir)

    def test_strict_v2_existing_or_current_scene_requires_frozen_identity(self) -> None:
        class NoCallClient:
            def call(self, command, _params=None):
                raise AssertionError(command)

        adapter = NukeCommandAdapter(NoCallClient())
        with tempfile.TemporaryDirectory() as directory:
            scene = Path(directory) / "expected.nk"
            scene.write_bytes(b"scene")
            for spec in (
                TaskSpec(
                    task_type="nuke.reference_composite",
                    intent="strict existing scene",
                    target_application="nuke",
                    target_scene="existing",
                    target_scene_path=str(scene),
                    schema_version="2.0",
                ),
                TaskSpec(
                    task_type="nuke.reference_composite",
                    intent="strict current scene",
                    target_application="nuke",
                    target_scene="current",
                    schema_version="2.0",
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "SCENE_IDENTITY_REQUIRED"):
                    adapter._ensure_target_scene(spec)

        adapter._ensure_target_scene(
            TaskSpec(
                task_type="nuke.reference_composite",
                intent="explicit new scene",
                target_application="nuke",
                target_scene="new",
                schema_version="2.0",
            )
        )

    def test_action_atomic_fingerprint_cannot_absorb_later_callback_edit(self) -> None:
        class AtomicClient:
            def __init__(self, scene: str) -> None:
                self.scene = scene
                self.after_action = False
                self.calls: list[str] = []

            def call(self, command, _params=None):
                self.calls.append(command)
                if command == "script.info":
                    return {
                        "script": self.scene,
                        "modified": self.after_action,
                        "scene_fingerprint": "8" * 64 if self.after_action else "9" * 64,
                        "fingerprint_complete": True,
                    }
                if command == "agent.nuke.composite.probe":
                    self.assert_expected = dict(_params or {}).get(
                        "expected_pre_scene_fingerprint"
                    )
                    self.after_action = True
                    return {
                        "gates": [
                            {
                                "name": "nuke_composite_available",
                                "passed": True,
                                "kind": "capability",
                            }
                        ],
                        "pre_scene_state": {
                            "script": self.scene,
                            "modified": False,
                            "scene_fingerprint": "9" * 64,
                            "fingerprint_complete": True,
                        },
                        "post_scene_state": {
                            "script": self.scene,
                            "modified": True,
                            "scene_fingerprint": "a" * 64,
                            "fingerprint_complete": True,
                        },
                    }
                if command == "capabilities.get":
                    return {
                        "loaded_addon_path": "/trusted/nuke_bridge_addon.py",
                        "loaded_addon_sha256": "b" * 64,
                    }
                raise AssertionError(command)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene = root / "expected.nk"
            scene.write_bytes(b"scene")
            task_dir = root / "atomic-task"
            spec = TaskSpec(
                task_type="nuke.reference_composite",
                intent="bind ownership to the action callback",
                target_application="nuke",
                target_scene_path=str(scene),
                inputs=({"role": "effect_render", "path": "/show/effect.exr"},),
            )
            client = AtomicClient(str(scene.resolve()))
            adapter = NukeCommandAdapter(client)
            result = adapter.execute(
                Step(
                    "probe",
                    "PROBE",
                    "agent.nuke.composite.probe",
                    gate_policy="strict",
                ),
                spec,
                task_dir,
            )
            self.assertTrue(result["gates"][0]["passed"])
            binding = json.loads(
                (task_dir / "nuke_scene_binding.json").read_text(encoding="utf-8")
            )
            self.assertEqual(binding["scene_fingerprint"], "a" * 64)
            self.assertEqual(client.assert_expected, "9" * 64)
            self.assertEqual(client.calls.count("script.info"), 1)

            resumed = NukeCommandAdapter(client)
            with self.assertRaisesRegex(RuntimeError, "unowned unsaved changes"):
                resumed._ensure_target_scene(spec, task_dir)

    def test_action_precondition_response_cannot_replace_host_scene_fingerprint(self) -> None:
        class DriftClient:
            def __init__(self, scene: str) -> None:
                self.scene = scene

            def call(self, command, params=None):
                if command == "script.info":
                    return {
                        "script": self.scene,
                        "modified": False,
                        "scene_fingerprint": "c" * 64,
                        "fingerprint_complete": True,
                    }
                if command == "agent.nuke.composite.probe":
                    self.expected = dict(params or {}).get(
                        "expected_pre_scene_fingerprint"
                    )
                    return {
                        "gates": [
                            {
                                "name": "nuke_composite_available",
                                "passed": True,
                                "kind": "capability",
                            }
                        ],
                        "pre_scene_state": {
                            "script": self.scene,
                            "modified": True,
                            "scene_fingerprint": "d" * 64,
                            "fingerprint_complete": True,
                        },
                        "post_scene_state": {
                            "script": self.scene,
                            "modified": True,
                            "scene_fingerprint": "d" * 64,
                            "fingerprint_complete": True,
                        },
                    }
                raise AssertionError(command)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene = root / "expected.nk"
            scene.write_bytes(b"scene")
            task_dir = root / "precondition-task"
            client = DriftClient(str(scene.resolve()))
            adapter = NukeCommandAdapter(client)
            spec = TaskSpec(
                task_type="nuke.reference_composite",
                intent="reject ensure-to-action drift",
                target_application="nuke",
                target_scene_path=str(scene),
            )
            with self.assertRaisesRegex(RuntimeError, "frozen pre-scene fingerprint"):
                adapter.execute(
                    Step(
                        "probe",
                        "PROBE",
                        "agent.nuke.composite.probe",
                        gate_policy="strict",
                    ),
                    spec,
                    task_dir,
                )
            self.assertEqual(client.expected, "c" * 64)
            self.assertFalse((task_dir / "nuke_scene_binding.json").exists())


class LegacyCheckpointCompatibilityTests(unittest.TestCase):
    def test_resume_accepts_checkpoint_written_before_step_outputs(self) -> None:
        class Recipe:
            identifier = "houdini.legacy_checkpoint"

            def steps(self, _spec, _capabilities):
                return [
                    Step("first", "AUTHOR", "first"),
                    Step("second", "AUTHOR", "second"),
                ]

        class Adapter:
            fail_second = True

            def probe(self, _spec):
                return {"ok": True}

            def execute(self, step, _spec, _task_dir):
                if step.identifier == "second" and self.fail_second:
                    raise RuntimeError("stop after the legacy checkpoint")
                return {
                    "artifacts": [{"path": f"/{step.identifier}.artifact"}],
                    "gates": [{"name": step.identifier, "passed": True, "kind": "operation"}],
                    "step_output": {"value": step.identifier},
                }

            def repair(self, _step, _spec, _task_dir, _failure):
                return False

        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory))
            registry = RecipeRegistry()
            registry.register(Recipe())
            adapter = Adapter()
            engine = TaskEngine(store, adapter, registry)
            started = engine.start(
                {
                    "task_type": "houdini.legacy_checkpoint",
                    "intent": "resume an old task",
                    "target": {"application": "houdini"},
                },
                background=False,
            )
            task_id = started["task_id"]
            self.assertEqual(engine.result(task_id)["state"], "PARTIAL")

            checkpoint_path = store.task_dir(task_id) / "checkpoints.json"
            legacy = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            legacy.pop("step_outputs")
            checkpoint_path.write_text(json.dumps(legacy), encoding="utf-8")

            adapter.fail_second = False
            engine.resume(task_id, background=False)
            result = engine.result(task_id)
            self.assertEqual(result["state"], "SUCCEEDED")
            self.assertEqual([item["name"] for item in result["gates"]], ["first", "second"])
            self.assertNotIn("first", result["step_outputs"])
            self.assertEqual(result["step_outputs"]["second"]["output"], {"value": "second"})


class DiagnosticResumeTests(unittest.TestCase):
    def test_inconclusive_evidence_blocks_delivery_and_resume_rechecks_it(self) -> None:
        class Recipe:
            identifier = "houdini.diagnostic_resume"

            def steps(self, _spec, _capabilities):
                return [
                    Step("build", "AUTHOR", "build"),
                    Step("evidence", "TECH_VERIFY", "evidence"),
                    Step("deliver", "DELIVER", "deliver"),
                ]

        class Adapter:
            evidence_ready = False

            def __init__(self):
                self.calls = []

            def probe(self, _spec):
                return {"ok": True}

            def execute(self, step, _spec, _task_dir):
                self.calls.append(step.identifier)
                if step.identifier == "build":
                    return {
                        "gates": [{"name": "build", "passed": True, "kind": "operation"}],
                        "outcome_state": "DIAGNOSIS_INCONCLUSIVE",
                    }
                if step.identifier == "evidence":
                    return {
                        "gates": [{"name": "evidence", "passed": True, "kind": "verification"}],
                        "outcome_state": "SUCCEEDED" if self.evidence_ready else "DIAGNOSIS_INCONCLUSIVE",
                    }
                return {"gates": [{"name": "deliver", "passed": True, "kind": "verification"}]}

            def repair(self, _step, _spec, _task_dir, _failure):
                return False

        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory))
            registry = RecipeRegistry()
            registry.register(Recipe())
            adapter = Adapter()
            engine = TaskEngine(store, adapter, registry)
            started = engine.start(
                {
                    "task_type": "houdini.diagnostic_resume",
                    "intent": "collect evidence before delivery",
                    "target": {"application": "houdini"},
                },
                background=False,
            )
            task_id = started["task_id"]
            self.assertEqual(engine.result(task_id)["state"], "DIAGNOSIS_INCONCLUSIVE")
            self.assertEqual(adapter.calls, ["build", "evidence"])

            adapter.evidence_ready = True
            engine.resume(task_id, background=False)
            self.assertEqual(engine.result(task_id)["state"], "SUCCEEDED")
            self.assertEqual(adapter.calls, ["build", "evidence", "evidence", "deliver"])


class CliTerminalStateTests(unittest.TestCase):
    def test_watch_stops_on_diagnostic_and_unsupported_states(self) -> None:
        class Service:
            def __init__(self, state):
                self.state = state
                self.status_calls = 0

            def events(self, _task_id, _sequence):
                return {"events": []}

            def status(self, _task_id):
                self.status_calls += 1
                return {"state": self.state}

            def result(self, _task_id):
                return {"state": self.state}

        for watcher, state in (
            (watch_houdini, "DIAGNOSIS_INCONCLUSIVE"),
            (watch_nuke, "UNSUPPORTED"),
        ):
            with self.subTest(watcher=watcher.__module__, state=state):
                service = Service(state)
                with redirect_stdout(io.StringIO()):
                    code = watcher(service, "task", json_events=False, poll_interval=0.01)
                self.assertEqual(code, 1)
                self.assertEqual(service.status_calls, 1)


if __name__ == "__main__":
    unittest.main()
