"""Command-line entry point for the Bridge Skills 2.0 pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dcc_task_runtime.errors import RuntimeV2Error

from .service import ModelSafePipeline, PipelineExecutionError, TrustedApprovalControl, TrustedExecutionControl


def _json_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vfx-pipeline")
    parser.add_argument("--state-db", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)

    capabilities = commands.add_parser("capabilities")
    capabilities.add_argument("--refresh", action="store_true")

    domain = commands.add_parser("domain")
    domain_commands = domain.add_subparsers(dest="domain_command", required=True)
    domain_commands.add_parser("list")
    show = domain_commands.add_parser("show")
    show.add_argument("identifier")
    show.add_argument("--version", default="1.0.0")

    graph = commands.add_parser("graph")
    graph_commands = graph.add_subparsers(dest="graph_command", required=True)
    graph_commands.add_parser("catalog")
    graph_list = graph_commands.add_parser("list")
    graph_list.add_argument("task_id")
    graph_propose = graph_commands.add_parser("propose")
    graph_propose.add_argument("task_id")
    graph_propose.add_argument("--proposal", type=Path, required=True)
    graph_propose.add_argument("--request-id")
    graph_propose.add_argument("--run-id")
    graph_propose.add_argument("--session-id")

    execution = commands.add_parser("execution", help="trusted controller evidence plane")
    execution_commands = execution.add_subparsers(dest="execution_command", required=True)
    register_analysis = execution_commands.add_parser("register-reference-analysis")
    register_analysis.add_argument("task_id")
    register_analysis.add_argument("--run-id", required=True)
    register_analysis.add_argument("--session-id", required=True)
    register_analysis.add_argument("--analysis", type=Path, required=True)
    register_analysis.add_argument("--receipt", type=Path)
    register_analysis.add_argument("--capture-id")
    register_analysis.add_argument("--config", type=Path, required=True)

    model = commands.add_parser("model")
    model_commands = model.add_subparsers(dest="model_command", required=True)
    probe = model_commands.add_parser("probe")
    probe.add_argument("--config", type=Path, required=True)
    probe.add_argument("--task-id")
    # `model step` was an unregistered CLI bypass of the command contract; the
    # sanctioned entries are `model skill-step` (model-safe) and the trusted
    # control plane. The service method stays available to the controller.
    model_card = model_commands.add_parser("card")
    model_card.add_argument("task_id")
    skill_step = model_commands.add_parser("skill-step")
    skill_step.add_argument("task_id")
    skill_step.add_argument("--selection", type=Path, required=True)
    skill_step.add_argument("--idempotency-key", required=True)

    task = commands.add_parser("task")
    task_commands = task.add_subparsers(dest="task_command", required=True)
    for name in ("plan", "start"):
        item = task_commands.add_parser(name)
        item.add_argument("--spec", type=Path, required=True)
    for name in ("status", "resume", "result"):
        item = task_commands.add_parser(name)
        item.add_argument("task_id")
    events = task_commands.add_parser("events")
    events.add_argument("task_id")
    events.add_argument("--after-seq", type=int, default=0)

    feedback = commands.add_parser("feedback")
    feedback_commands = feedback.add_subparsers(dest="feedback_command", required=True)
    diagnose = feedback_commands.add_parser("diagnose")
    diagnose.add_argument("task_id")
    diagnose.add_argument("--feedback", required=True)
    diagnose.add_argument("--evidence", type=Path, required=True)
    diagnose.add_argument("--domain")

    candidate = commands.add_parser("candidate")
    candidate_commands = candidate.add_subparsers(dest="candidate_command", required=True)
    candidate_list = candidate_commands.add_parser("list")
    candidate_list.add_argument("task_id")
    candidate_select = candidate_commands.add_parser("select")
    candidate_select.add_argument("task_id")
    candidate_select.add_argument("candidate_id")

    verification = commands.add_parser("verification")
    verification_commands = verification.add_subparsers(dest="verification_command", required=True)
    verification_record = verification_commands.add_parser("record")
    verification_record.add_argument("task_id")
    verification_record.add_argument("--measurement", type=Path, required=True)

    approval = commands.add_parser("approval")
    approval_commands = approval.add_subparsers(dest="approval_command", required=True)
    request_cache = approval_commands.add_parser("request-cache")
    request_cache.add_argument("task_id")
    resources = approval_commands.add_parser("configure-cache-resources", help="trusted controller configuration; does not grant cache execution")
    resources.add_argument("task_id")
    resources.add_argument("--config", type=Path, required=True)
    request_experience = approval_commands.add_parser("request-experience")
    request_experience.add_argument("task_id")
    accept = approval_commands.add_parser("accept-result", help="trusted human control plane only")
    accept.add_argument("task_id")
    accept.add_argument("--actor", required=True)
    accept.add_argument("--trust-proof")
    accept.add_argument("--interactive", action="store_true")
    accept.add_argument("--verification-id", required=True)
    accept.add_argument("--verification-hash", required=True)
    accept.add_argument("--artist-notes", default="")
    for name in ("grant-cache", "grant-experience"):
        item = approval_commands.add_parser(name, help="trusted human control plane only")
        item.add_argument("request_id")
        item.add_argument("--actor", required=True)
        item.add_argument("--trust-proof")
        item.add_argument("--interactive", action="store_true")

    cache = commands.add_parser("cache")
    cache_commands = cache.add_subparsers(dest="cache_command", required=True)
    cache_run = cache_commands.add_parser("run")
    cache_run.add_argument("task_id")
    cache_run.add_argument("--grant-id", required=True)

    experience = commands.add_parser("experience")
    experience_commands = experience.add_subparsers(dest="experience_command", required=True)
    search = experience_commands.add_parser("search")
    search.add_argument("--domain", required=True)
    search.add_argument("--version", default="1.0.0")
    search.add_argument("--task-id")
    search.add_argument("--limit", type=int, default=5)
    return parser


def _trusted_proof(args: Any, actor: str, scope: str, subject_id: str) -> str:
    supplied = str(getattr(args, "trust_proof", None) or "").strip()
    interactive = bool(getattr(args, "interactive", False))
    if supplied and interactive:
        raise ValueError("choose either --trust-proof or --interactive")
    if supplied:
        return supplied
    if not interactive or not sys.stdin.isatty():
        raise RuntimeV2Error(
            "TRUSTED_HUMAN_REQUIRED",
            "trusted approval requires a signed --trust-proof from the UI or --interactive in a real TTY",
        )
    phrase = "APPROVE {} {}".format(scope, subject_id[-8:])
    entered = input("Type exactly '{}': ".format(phrase)).strip()
    if entered != phrase:
        raise RuntimeV2Error("TRUSTED_HUMAN_REQUIRED", "interactive approval phrase did not match")
    return TrustedApprovalControl.sign_proof(actor, scope, subject_id)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        pipeline = ModelSafePipeline(args.state_db)
        if args.command == "capabilities":
            result = pipeline.capabilities(args.refresh)
        elif args.command == "domain":
            result = pipeline.domain_list() if args.domain_command == "list" else pipeline.domain_show(args.identifier, args.version)
        elif args.command == "model":
            if args.model_command == "card":
                result = pipeline.model_card(args.task_id)
            elif args.model_command == "skill-step":
                result = pipeline.model_skill_step(args.task_id, _json_file(args.selection), args.idempotency_key)
            elif args.model_command == "probe":
                config = _json_file(args.config)
                result = pipeline.model_probe(config, args.task_id)
        elif args.command == "graph":
            if args.graph_command == "catalog":
                result = pipeline.graph_catalog()
            elif args.graph_command == "list":
                result = pipeline.graph_list(args.task_id)
            else:
                result = pipeline.graph_propose(
                    args.task_id, _json_file(args.proposal), request_id=args.request_id,
                    run_id=args.run_id, session_id=args.session_id,
                )
        elif args.command == "execution":
            trusted_execution = TrustedExecutionControl(pipeline)
            result = trusted_execution.register_reference_analysis_run(
                args.task_id, run_id=args.run_id, session_id=args.session_id,
                analysis=_json_file(args.analysis), tool_receipt=_json_file(args.receipt) if args.receipt else None,
                capture_id=args.capture_id, config=_json_file(args.config),
            )
        elif args.command == "task":
            if args.task_command in {"plan", "start"}:
                spec = _json_file(args.spec)
                result = pipeline.task_plan(spec) if args.task_command == "plan" else pipeline.task_start(spec)
            elif args.task_command == "status":
                result = pipeline.task_status(args.task_id)
            elif args.task_command == "events":
                result = pipeline.task_events(args.task_id, args.after_seq)
            elif args.task_command == "resume":
                result = pipeline.task_resume(args.task_id)
            else:
                result = pipeline.task_result(args.task_id)
        elif args.command == "feedback":
            result = pipeline.feedback_diagnose(args.task_id, args.feedback, _json_file(args.evidence), args.domain)
        elif args.command == "candidate":
            result = pipeline.candidate_list(args.task_id) if args.candidate_command == "list" else pipeline.candidate_select(args.task_id, args.candidate_id)
        elif args.command == "verification":
            result = pipeline.verification_record(args.task_id, _json_file(args.measurement))
        elif args.command == "approval":
            if args.approval_command == "configure-cache-resources":
                result = TrustedApprovalControl(pipeline).configure_cache_resources(args.task_id, **_json_file(args.config))
            elif args.approval_command == "request-cache":
                result = pipeline.approval_request_cache(args.task_id)
            elif args.approval_command == "request-experience":
                result = pipeline.approval_request_experience(args.task_id)
            else:
                trusted = TrustedApprovalControl(pipeline)
                if args.approval_command == "accept-result":
                    subject_id = "{}:{}".format(args.task_id, args.verification_id)
                    proof = _trusted_proof(args, args.actor, "final_result_acceptance", subject_id)
                    result = trusted.accept_result(
                        args.task_id,
                        args.actor,
                        proof,
                        args.verification_id,
                        args.verification_hash,
                        args.artist_notes,
                    )
                elif args.approval_command == "grant-cache":
                    proof = _trusted_proof(args, args.actor, "houdini_simulation_cache", args.request_id)
                    result = trusted.grant_cache(args.request_id, args.actor, proof)
                else:
                    proof = _trusted_proof(args, args.actor, "repair_experience_promotion", args.request_id)
                    result = trusted.grant_experience(args.request_id, args.actor, proof)
        elif args.command == "cache":
            result = pipeline.cache_run(args.task_id, args.grant_id)
        else:
            result = pipeline.experience_search(args.domain, args.version, args.task_id, args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (RuntimeV2Error, PipelineExecutionError, ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        code = getattr(exc, "code", "INVALID_ARGUMENT")
        rendered_code = getattr(code, "value", code)
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": str(rendered_code),
                    "message": str(exc),
                    "details": dict(getattr(exc, "details", {}) or {}),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
