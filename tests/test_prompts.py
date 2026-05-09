from aethr.config import WorkflowStep
from aethr.prompts import step_prompt


def test_step_prompt_includes_role_specific_instructions() -> None:
    prompt = step_prompt(
        task="fix a failing test",
        step=WorkflowStep(id="diagnose", role="debugger"),
        previous_context="previous output",
        explicit_context="repo context",
        role_description="Find the root cause.",
    )

    assert "Role-specific instructions:" in prompt
    assert "Diagnose the failure" in prompt
    assert "Workflow role guidance:" in prompt
    assert "Find the root cause." in prompt
    assert "Explicit repo context:" in prompt
    assert "repo context" in prompt
