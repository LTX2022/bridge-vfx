from __future__ import annotations

import unittest

from dcc_task_runtime.errors import RuntimeV2Error
from dcc_task_runtime.models import ErrorCode
from dcc_task_runtime.skill_ir import (
    ModelActionSelection,
    SkillAction,
    SkillCompiler,
    SkillIR,
    SkillState,
)
from dcc_task_runtime.skill_vm import SkillExecutionVM


def example_skill() -> SkillIR:
    return SkillIR(
        skill_id="visual_causal_doctor",
        version="1.0",
        initial_state="diagnosing",
        states=(
            SkillState(
                state_id="diagnosing",
                instruction="Choose exactly one bounded diagnostic action.",
                actions=(
                    SkillAction("collect_evidence", "Collect evidence", success_state="choosing"),
                    SkillAction(
                        "adjust_control",
                        "Preview a semantic control",
                        control_ids=("detail_scale", "dissipation"),
                        candidate_ids=("candidate_a", "candidate_b"),
                        requires_control=True,
                        requires_candidate=True,
                        success_state="choosing",
                        recoverable_error_codes=(ErrorCode.COOK_FAILED.value,),
                    ),
                ),
            ),
            SkillState(
                state_id="choosing",
                instruction="Choose one candidate or request more evidence.",
                actions=(SkillAction("confirm_candidate", "Confirm candidate", candidate_ids=("candidate_a", "candidate_b"), requires_candidate=True),),
            ),
        ),
    )


class SkillIRTests(unittest.TestCase):
    def test_compiler_emits_only_explicit_bounded_actions(self) -> None:
        card = SkillCompiler(example_skill()).compile("diagnosing").to_dict()
        self.assertEqual(len(card["actions"]), 2)
        self.assertEqual(card["response_schema"]["required"], ["action_id"])
        self.assertFalse(card["response_schema"]["additional_properties"])
        action_keys = set().union(*(action.keys() for action in card["actions"]))
        self.assertTrue({"path", "script", "parameter_value", "parameters"}.isdisjoint(action_keys))

    def test_more_than_four_actions_is_rejected(self) -> None:
        with self.assertRaises(RuntimeV2Error) as caught:
            SkillState("state", "instruction", tuple(SkillAction(f"action_{index}", "label") for index in range(5)))
        self.assertEqual(caught.exception.code, ErrorCode.TOOL_BUDGET_EXCEEDED)

    def test_unknown_state_and_transition_are_rejected(self) -> None:
        skill = example_skill()
        with self.assertRaises(RuntimeV2Error):
            skill.state("missing")
        with self.assertRaises(RuntimeV2Error):
            SkillIR("bad", "1", "one", (SkillState("one", "i", (SkillAction("go", "go", success_state="missing"),)),))

    def test_model_selection_rejects_paths_values_scripts_and_multiple_actions(self) -> None:
        forbidden = (
            {"action_id": "collect_evidence", "path": "/tmp/out"},
            {"action_id": "collect_evidence", "parameter_value": 2.0},
            {"action_id": "collect_evidence", "script": "hou.exit()"},
            {"actions": [{"action_id": "a"}, {"action_id": "b"}]},
        )
        for payload in forbidden:
            with self.subTest(payload=payload), self.assertRaises(RuntimeV2Error):
                ModelActionSelection.from_mapping(payload)

    def test_model_selection_requires_identifier_strings(self) -> None:
        for payload in ({"action_id": ["one", "two"]}, {"action_id": "/unsafe/path"}, {"action_id": ""}):
            with self.subTest(payload=payload), self.assertRaises(RuntimeV2Error):
                ModelActionSelection.from_mapping(payload)


class SkillExecutionVMTests(unittest.TestCase):
    def test_executes_one_allowed_action_and_moves_to_declared_state(self) -> None:
        calls = []

        def executor(request):
            calls.append(request)
            return {"evidence_id": "evidence_1"}

        vm = SkillExecutionVM(example_skill(), executor)
        result = vm.execute("diagnosing", {"action_id": "collect_evidence"}, idempotency_key="request-1")
        self.assertTrue(result.succeeded)
        self.assertEqual(result.next_state, "choosing")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(vm.journal), 1)

    def test_replay_is_idempotent_and_does_not_call_executor_twice(self) -> None:
        calls = []
        vm = SkillExecutionVM(example_skill(), lambda request: calls.append(request) or {"ok": True})
        first = vm.execute("diagnosing", {"action_id": "collect_evidence"}, idempotency_key="same")
        replay = vm.execute("diagnosing", {"action_id": "collect_evidence"}, idempotency_key="same")
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first.created_at, replay.created_at)

    def test_idempotency_key_cannot_be_rebound(self) -> None:
        vm = SkillExecutionVM(example_skill(), lambda _request: {"ok": True})
        vm.execute("diagnosing", {"action_id": "collect_evidence"}, idempotency_key="same")
        with self.assertRaises(RuntimeV2Error):
            vm.execute(
                "diagnosing",
                {"action_id": "adjust_control", "control_id": "detail_scale", "candidate_id": "candidate_a"},
                idempotency_key="same",
            )

    def test_unknown_action_control_and_candidate_never_reach_executor(self) -> None:
        calls = []
        vm = SkillExecutionVM(example_skill(), lambda request: calls.append(request) or {})
        payloads = (
            {"action_id": "arbitrary_python"},
            {"action_id": "adjust_control", "control_id": "voxel_size", "candidate_id": "candidate_a"},
            {"action_id": "adjust_control", "control_id": "detail_scale", "candidate_id": "candidate_z"},
            {"action_id": "adjust_control", "control_id": "detail_scale"},
        )
        for index, payload in enumerate(payloads):
            with self.subTest(payload=payload), self.assertRaises(RuntimeV2Error):
                vm.execute("diagnosing", payload, idempotency_key=f"bad-{index}")
        self.assertEqual(calls, [])

    def test_empty_idempotency_key_is_rejected_before_execution(self) -> None:
        calls = []
        vm = SkillExecutionVM(example_skill(), lambda request: calls.append(request) or {})
        with self.assertRaises(RuntimeV2Error):
            vm.execute("diagnosing", {"action_id": "collect_evidence"}, idempotency_key="")
        self.assertEqual(calls, [])

    def test_declared_runtime_failure_is_recorded_as_recoverable(self) -> None:
        def executor(_request):
            raise RuntimeV2Error(ErrorCode.COOK_FAILED, "temporary cook failure", {"retry": "lower_preview_quality"})

        vm = SkillExecutionVM(example_skill(), executor)
        result = vm.execute(
            "diagnosing",
            {"action_id": "adjust_control", "control_id": "detail_scale", "candidate_id": "candidate_a"},
            idempotency_key="failure-1",
        )
        self.assertFalse(result.succeeded)
        self.assertTrue(result.recoverable)
        self.assertEqual(result.next_state, "diagnosing")
        self.assertEqual(result.error_code, ErrorCode.COOK_FAILED.value)
        self.assertEqual(len(vm.journal), 1)

    def test_undeclared_failure_is_recorded_but_not_recoverable(self) -> None:
        vm = SkillExecutionVM(
            example_skill(),
            lambda _request: (_ for _ in ()).throw(RuntimeV2Error(ErrorCode.POLICY_DENIED, "denied")),
        )
        result = vm.execute("diagnosing", {"action_id": "collect_evidence"}, idempotency_key="failure-2")
        self.assertFalse(result.succeeded)
        self.assertFalse(result.recoverable)
        self.assertEqual(result.error_code, ErrorCode.POLICY_DENIED.value)

    def test_untyped_executor_failure_is_safely_recorded(self) -> None:
        def executor(_request):
            raise OSError("secret host detail")

        vm = SkillExecutionVM(example_skill(), executor)
        result = vm.execute("diagnosing", {"action_id": "collect_evidence"}, idempotency_key="failure-3")
        self.assertFalse(result.succeeded)
        self.assertFalse(result.recoverable)
        self.assertEqual(result.error_code, ErrorCode.INTERNAL_ERROR.value)
        self.assertEqual(result.error_message, "executor failed: OSError")


if __name__ == "__main__":
    unittest.main()
