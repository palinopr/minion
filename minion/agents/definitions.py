"""Subagent definitions -- specialized agents for different task types."""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition


# Read-only tools for agents that should not modify code
READ_TOOLS = ["Read", "Glob", "Grep"]

# Full tools for agents that write code
WRITE_TOOLS = ["Read", "Edit", "Write", "Bash", "Glob", "Grep"]


def get_agent_definitions() -> dict[str, AgentDefinition]:
    """Return all available subagent definitions.

    The main orchestrator agent can delegate to any of these.
    Each has constrained tools and a focused system prompt.
    """
    return {
        "researcher": AgentDefinition(
            description=(
                "Explores the codebase to gather context. "
                "Use before making changes to understand the code structure, "
                "find relevant files, and map dependencies."
            ),
            prompt=(
                "You are a codebase researcher. Your job is to explore and understand code.\n"
                "- Map out file structure and dependencies\n"
                "- Find relevant functions, classes, and modules\n"
                "- Summarize what you find concisely\n"
                "- Do NOT modify any files\n"
                "- Return a clear summary of what you found and where"
            ),
            tools=READ_TOOLS,
        ),
        "fixer": AgentDefinition(
            description=(
                "Fixes bugs in existing code. "
                "Give it a bug description or failing test and it will locate "
                "the root cause and apply a minimal fix."
            ),
            prompt=(
                "You are a bug fixer. Your job is to fix bugs with minimal, precise changes.\n"
                "- Read the bug description or failing test carefully\n"
                "- Find the root cause before changing anything\n"
                "- Make the smallest change that fixes the issue\n"
                "- Do not refactor unrelated code\n"
                "- Run tests after your fix to verify it works"
            ),
            tools=WRITE_TOOLS,
        ),
        "tester": AgentDefinition(
            description=(
                "Writes tests for existing code. "
                "Give it a file or module and it will write thorough tests "
                "covering happy paths, edge cases, and error conditions."
            ),
            prompt=(
                "You are a test writer. Your job is to write thorough, reliable tests.\n"
                "- Read the source code to understand behavior\n"
                "- Write tests that cover: happy path, edge cases, error handling\n"
                "- One assertion per test where practical\n"
                "- Use descriptive test names that explain what is being tested\n"
                "- Follow the testing patterns already in the repo\n"
                "- Run the tests to make sure they pass"
            ),
            tools=WRITE_TOOLS,
        ),
        "reviewer": AgentDefinition(
            description=(
                "Reviews code for correctness, security, and style issues. "
                "Read-only. Returns a structured review with findings."
            ),
            prompt=(
                "You are a code reviewer. Your job is to find real problems.\n"
                "- Check for bugs, logic errors, and security issues\n"
                "- Check for missing error handling\n"
                "- Check for performance problems\n"
                "- Do NOT nitpick style unless it affects readability\n"
                "- Do NOT modify any files\n"
                "- Return findings as a structured list with file:line references"
            ),
            tools=READ_TOOLS,
        ),
        "builder": AgentDefinition(
            description=(
                "Implements new features from a specification. "
                "Give it a description of what to build and it will create "
                "the necessary files, write code, and add tests."
            ),
            prompt=(
                "You are a feature builder. Your job is to implement new functionality.\n"
                "- Read the feature spec carefully\n"
                "- Explore existing code patterns before writing new code\n"
                "- Follow the existing architecture and conventions\n"
                "- Write tests for all new code\n"
                "- Keep functions under 50 lines\n"
                "- Run tests and linter after implementation"
            ),
            tools=WRITE_TOOLS,
        ),
    }
