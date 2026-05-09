"""Prompt builders for configured Aethr workflow steps."""

from aethr.config import WorkflowStep


ROLE_INSTRUCTIONS = {
    "planner": (
        "Produce a compact implementation plan. Include ordered steps, key files or areas to inspect, "
        "risks, and a clear stopping point. Do not write code."
    ),
    "implementer": (
        "Produce the implementation content. Be concrete about code changes, edge cases, and tests. "
        "If exact patches are not possible from context, state the intended edits precisely."
    ),
    "reviewer": (
        "Review critically. Lead with findings, bugs, regressions, missing tests, and unclear assumptions. "
        "Keep summaries secondary and concise."
    ),
    "debugger": (
        "Diagnose the failure from the available context. Separate likely cause, evidence, and smallest fix. "
        "Avoid speculative rewrites."
    ),
    "writer": (
        "Write clear documentation-oriented output. Prefer accurate, concise text that matches the project tone. "
        "Call out any source-of-truth gaps."
    ),
    "test-planner": (
        "Plan focused test coverage. Identify behaviors, important edge cases, and the minimal test set needed."
    ),
    "test-writer": (
        "Draft tests in the existing project style. Prefer deterministic assertions and avoid brittle implementation details."
    ),
    "worker": "Complete the step directly and concisely using the prior workflow context.",
}


def step_prompt(
    task: str,
    step: WorkflowStep,
    previous_context: str,
    explicit_context: str,
    role_description: str = "",
) -> str:
    """Build a prompt for one configured workflow step."""

    role_instruction = ROLE_INSTRUCTIONS.get(step.role, ROLE_INSTRUCTIONS["worker"])
    role_context = f"\nWorkflow role guidance:\n{role_description}\n" if role_description else ""
    return f"""You are the {step.role} step in an Aethr coding workflow.
{role_context}
Role-specific instructions:
{role_instruction}

Task:
{task}

Step:
{step.id}

Previous step output:
{previous_context}

Explicit repo context:
{explicit_context}

Return only the content for this step."""
