"""Prompt builders for configured Relay workflow steps."""

from relay.config import WorkflowStep


def step_prompt(task: str, step: WorkflowStep, context: str, role_description: str = "") -> str:
    """Build a prompt for one configured workflow step."""

    role_context = f"\nRole guidance:\n{role_description}\n" if role_description else ""
    return f"""You are the {step.role} step in a Relay coding workflow.
{role_context}

Task:
{task}

Step:
{step.id}

Previous step output:
{context}

Return only the content for this step."""
