"""Context prefetching -- Stripe's Layer 2.

Before the agent starts, deterministic code scans the task description
and repo to pull in relevant context. No LLM involved. The agent wakes
up with rich context already loaded.

Prefetch steps:
  1. Extract file paths and patterns from the task description
  2. Grep the repo for relevant code (function names, class names, error messages)
  3. Load per-directory CLAUDE.md rules for the affected paths
  4. Pull in relevant docs (README, CONTRIBUTING, etc.)
  5. Return a structured context block to prepend to the agent prompt
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PrefetchedContext:
    """Context gathered before the agent starts."""
    relevant_files: list[str] = field(default_factory=list)
    code_snippets: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)
    stack_info: str = ""


def extract_paths(text: str) -> list[str]:
    """Extract file paths and directory references from task text."""
    patterns = [
        r'[\w./]+\.(?:ts|tsx|js|jsx|py|rb|go|rs|java|cpp|c|h|css|html|json|toml|yaml|yml|md)',
        r'(?:src|lib|app|agent|test|tests|spec|pkg|cmd|internal)/[\w./-]+',
    ]
    paths = []
    for pattern in patterns:
        paths.extend(re.findall(pattern, text))
    return list(dict.fromkeys(paths))  # dedupe, preserve order


def extract_identifiers(text: str) -> list[str]:
    """Extract likely function/class/variable names from task text."""
    # camelCase, PascalCase, snake_case identifiers that look like code
    candidates = re.findall(r'\b([a-z][a-zA-Z0-9]*(?:[A-Z][a-zA-Z0-9]*)+)\b', text)
    candidates += re.findall(r'\b([A-Z][a-zA-Z0-9]+(?:[A-Z][a-zA-Z0-9]*)+)\b', text)
    candidates += re.findall(r'\b([a-z_][a-z0-9_]{2,})\b', text)
    # Filter out common English words
    stopwords = {
        'the', 'and', 'for', 'not', 'this', 'that', 'with', 'from', 'are',
        'was', 'has', 'have', 'been', 'will', 'can', 'should', 'would',
        'into', 'when', 'then', 'than', 'also', 'just', 'about', 'after',
        'before', 'could', 'does', 'each', 'make', 'like', 'over', 'such',
        'take', 'them', 'these', 'only', 'other', 'some', 'very', 'line',
        'fix', 'bug', 'add', 'new', 'use', 'code', 'file', 'test', 'run',
        'error', 'issue', 'crash', 'fails', 'broken', 'wrong', 'missing',
    }
    return [c for c in dict.fromkeys(candidates) if c.lower() not in stopwords][:15]


def grep_repo(repo_path: str, patterns: list[str], max_results: int = 20) -> list[str]:
    """Search the repo for patterns, return matching file:line snippets."""
    results = []
    for pattern in patterns[:10]:  # cap to avoid slow searches
        try:
            proc = subprocess.run(
                ["grep", "-rn", "--include=*.ts", "--include=*.tsx",
                 "--include=*.js", "--include=*.jsx", "--include=*.py",
                 "--include=*.rb", "--include=*.go", "--include=*.rs",
                 "--exclude-dir=node_modules", "--exclude-dir=.git",
                 "--exclude-dir=dist", "--exclude-dir=.next",
                 "--exclude-dir=__pycache__", "--exclude-dir=.venv",
                 "-l", pattern, "."],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in proc.stdout.strip().splitlines()[:5]:
                if line and line not in results:
                    results.append(line)
        except (subprocess.TimeoutExpired, Exception):
            continue
        if len(results) >= max_results:
            break
    return results[:max_results]


def find_rules_files(repo_path: str, affected_paths: list[str]) -> list[str]:
    """Find CLAUDE.md files relevant to the affected paths.

    Stripe loads per-directory rules. Working on payments/ -> payments rules.
    We walk up from each affected path collecting CLAUDE.md files.
    """
    repo = Path(repo_path)
    rules = []
    seen = set()

    # Always check repo root
    root_rules = repo / "CLAUDE.md"
    if root_rules.exists() and str(root_rules) not in seen:
        seen.add(str(root_rules))
        content = root_rules.read_text(errors="replace")[:3000]
        rules.append(f"# Rules from {root_rules.relative_to(repo)}\n{content}")

    for path_str in affected_paths:
        current = repo / path_str
        # Walk up to repo root, collecting CLAUDE.md files
        if current.is_file():
            current = current.parent
        while current != repo.parent and str(current).startswith(str(repo)):
            rules_file = current / "CLAUDE.md"
            if rules_file.exists() and str(rules_file) not in seen:
                seen.add(str(rules_file))
                content = rules_file.read_text(errors="replace")[:2000]
                rules.append(
                    f"# Rules from {rules_file.relative_to(repo)}\n{content}"
                )
            current = current.parent

    return rules


def find_repo_docs(repo_path: str) -> list[str]:
    """Find high-value documentation files in the repo root."""
    repo = Path(repo_path)
    docs = []
    for name in ["README.md", "CONTRIBUTING.md", "ARCHITECTURE.md", "AGENTS.md"]:
        doc = repo / name
        if doc.exists():
            content = doc.read_text(errors="replace")[:2000]
            docs.append(f"# {name}\n{content}")
    return docs


def get_directory_structure(repo_path: str, max_depth: int = 3) -> str:
    """Get a quick directory tree for orientation."""
    try:
        proc = subprocess.run(
            ["find", ".", "-maxdepth", str(max_depth),
             "-type", "d",
             "-not", "-path", "*/node_modules/*",
             "-not", "-path", "*/.git/*",
             "-not", "-path", "*/__pycache__/*",
             "-not", "-path", "*/.next/*"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        dirs = proc.stdout.strip().splitlines()[:50]
        return "\n".join(dirs)
    except Exception:
        return ""


def prefetch_context(
    task_description: str,
    repo_path: str,
    command: str = "fix",
) -> PrefetchedContext:
    """Run all prefetch steps. Returns context to inject into agent prompt.

    This is deterministic -- no LLM calls. Runs in <5 seconds typically.
    """
    ctx = PrefetchedContext()

    # 1. Extract paths from the task description
    paths = extract_paths(task_description)
    ctx.relevant_files = paths

    # 2. Extract identifiers and search the repo
    identifiers = extract_identifiers(task_description)
    if identifiers:
        grep_results = grep_repo(repo_path, identifiers)
        ctx.relevant_files.extend(grep_results)
        ctx.relevant_files = list(dict.fromkeys(ctx.relevant_files))[:30]

    # 3. Load per-directory rules (CLAUDE.md files)
    affected_dirs = paths if paths else ["."]
    ctx.rules = find_rules_files(repo_path, affected_dirs)

    # 4. Pull repo docs (first run only, helps orientation)
    if command in ("build", "review"):
        ctx.docs = find_repo_docs(repo_path)

    # 5. Directory structure for orientation
    dir_tree = get_directory_structure(repo_path)
    if dir_tree:
        ctx.stack_info = f"Directory structure:\n```\n{dir_tree}\n```"

    return ctx


def format_context_block(ctx: PrefetchedContext) -> str:
    """Format prefetched context into a text block for the agent prompt."""
    sections = []

    if ctx.rules:
        sections.append(
            "## Project Rules (from CLAUDE.md files)\n\n"
            + "\n\n".join(ctx.rules)
        )

    if ctx.relevant_files:
        file_list = "\n".join(f"- {f}" for f in ctx.relevant_files[:20])
        sections.append(f"## Relevant Files\n\n{file_list}")

    if ctx.stack_info:
        sections.append(f"## Project Layout\n\n{ctx.stack_info}")

    if ctx.docs:
        sections.append(
            "## Project Documentation\n\n"
            + "\n\n---\n\n".join(ctx.docs)
        )

    if not sections:
        return ""

    return (
        "--- PREFETCHED CONTEXT (gathered before you started) ---\n\n"
        + "\n\n".join(sections)
        + "\n\n--- END PREFETCHED CONTEXT ---\n\n"
    )
