"""Public command boundaries for model and trusted-human callers."""

from __future__ import annotations


MODEL_SAFE_COMMANDS = frozenset(
    {
        "capabilities",
        "domain.list",
        "domain.show",
        "graph.catalog",
        "graph.propose",
        "graph.list",
        "model.probe",
        "model.card",
        "model.skill-step",
        "task.plan",
        "task.start",
        "task.status",
        "task.events",
        "task.resume",
        "task.result",
        "feedback.diagnose",
        "candidate.list",
        "candidate.select",
        "approval.request-cache",
        "approval.request-experience",
        "cache.run",
        "verification.record",
        "experience.search",
    }
)

TRUSTED_CONTROL_COMMANDS = frozenset(
    {
        "execution.register-reference-analysis",
        "approval.accept-result",
        "approval.grant-cache",
        "approval.configure-cache-resources",
        "approval.grant-experience",
    }
)


def is_model_safe(command: str) -> bool:
    return command in MODEL_SAFE_COMMANDS


def is_trusted_control(command: str) -> bool:
    return command in TRUSTED_CONTROL_COMMANDS
