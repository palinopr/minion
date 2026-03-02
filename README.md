# Minion

Unattended coding agents on your Mac -- inspired by [Stripe's agent-infra approach](https://stripe.com/blog/how-we-built-the-infrastructure-behind-stripes-ai-powered-coding-agent).

Minion uses the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk) to run coding agents that can fix bugs, write tests, review code, and build features. Each agent runs in a git worktree for isolation (no VMs, no containers, no cloud sandboxes) and follows a blueprint -- a sequence of deterministic steps (lint, test, git) interleaved with agent reasoning steps.

## Quick start

```bash
# Clone
git clone https://github.com/palinopr/minion.git
cd minion

# Install
pip install -e .

# Authenticate (pick one)
#   Option A: API key
export ANTHROPIC_API_KEY=sk-ant-...
#   Option B: Claude CLI (recommended -- no env var needed)
claude login

# Fix a bug
python minion.py fix --repo ~/myapp "login crashes on empty email"

# Write tests
python minion.py test --repo ~/myapp "src/auth/"

# Review code (read-only, no changes)
python minion.py review --repo ~/myapp "src/payments/checkout.py"

# Build a feature
python minion.py build --repo ~/myapp "Add rate limiting to /api/search"

# Run multiple tasks in parallel
python minion.py batch --repo ~/myapp tasks.txt
```

## How it works

```
    You                      Minion                    Claude Agent SDK
     |                         |                              |
     |  minion fix --repo ...  |                              |
     |------------------------>|                              |
     |                         |  1. Create git worktree      |
     |                         |  2. Prefetch context          |
     |                         |     - grep for relevant files |
     |                         |     - load CLAUDE.md rules    |
     |                         |     - map directory structure  |
     |                         |  3. Agent: analyze + fix ---->|
     |                         |  4. Run lint (deterministic)  |
     |                         |  5. Run tests (deterministic) |
     |                         |     - fail? Agent fix, retry  |
     |                         |     - max 2 rounds            |
     |                         |  6. Commit + push + open PR   |
     |  PR url + cost          |                              |
     |<------------------------|                              |
```

Each command follows a **blueprint** -- a predefined sequence of steps. Some steps are deterministic (run a shell command, check output) and some are agentic (let Claude reason about code). The agent gets up to `max_rounds` attempts (default: 2) to make tests pass before giving up. Context is prefetched deterministically before the agent starts -- no LLM calls wasted on orientation.

## Context prefetching

Before the agent starts, minion runs a deterministic prefetch step (~2-5 seconds, no LLM):

1. **Extract paths** from the task description (`agent/src/events/message-handler.ts`)
2. **Extract identifiers** (function names, class names) and grep the repo for matches
3. **Load CLAUDE.md rules** from affected directories (walk up to repo root)
4. **Pull repo docs** (README, ARCHITECTURE.md) for build/review commands
5. **Map directory structure** for orientation

The agent wakes up with all this context already in its prompt. This is inspired by Stripe's approach: deterministic prefetching before the agent runs means fewer wasted tokens on exploration.

To add project-specific rules, create `CLAUDE.md` files in your repo directories:

```
myapp/
  CLAUDE.md              # root rules (always loaded)
  src/
    payments/
      CLAUDE.md          # loaded when task touches payments/
    auth/
      CLAUDE.md          # loaded when task touches auth/
```

## Commands

| Command     | What it does |
|-------------|-------------|
| `fix`       | Fix a bug described in natural language |
| `test`      | Add test coverage for a file or directory |
| `review`    | Read-only code review with findings printed to stdout |
| `build`     | Implement a feature from a spec |
| `batch`     | Run multiple tasks in parallel from a file |
| `resume`    | Continue a failed/incomplete run using its session ID |
| `status`    | Show recent run history |
| `tools`     | List registered MCP tools |
| `dashboard` | Launch local web dashboard (Flask, port 7777) |
| `clean`     | Remove leftover agent worktrees |

## Configuration

Edit `config.toml` to set defaults:

```toml
[general]
max_parallel = 3      # Max concurrent agents (each ~2-3GB RAM)
max_rounds = 4        # Max retry loops per agent
budget_usd = 2.00     # Spend cap per agent run

[repo]
path = ""             # Default repo (override with --repo)
base_branch = "main"
branch_prefix = "agent/"

[tools]
lint_cmd = ""         # Auto-detected from pyproject.toml / package.json
test_cmd = ""         # Auto-detected
format_cmd = ""       # Auto-detected

[github]
create_pr = true
reviewer = ""

[safety]
blocked_commands = ["rm -rf /", "git push --force", ...]
protected_files = [".env", "*.pem", "*.key", ...]
```

Stack detection is automatic: if the repo has `pyproject.toml`, lint/test/format default to `ruff`/`pytest`/`ruff format`. For `package.json`, they default to `npm run lint`/`npm test`/`npm run format`. Same for Go and Ruby.

## Batch file format

```
# tasks.txt -- one task per line
fix: login crashes on empty email
fix: divide by zero in calculate_average
test: src/auth/
review: src/payments/checkout.py
build: Add rate limiting to /api/search
```

## MCP tools

Register external MCP servers in `tools.toml`. The agent can call these during its reasoning steps:

```toml
[tools.postgres]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres"]
env = { DATABASE_URL = "$DATABASE_URL" }
description = "Query the PostgreSQL database"
```

## Project structure

```
minion.py                        # CLI entry point
config.toml                      # Runtime configuration
tools.toml                       # MCP tool registry
minion/
  config.py                      # Config loader + stack auto-detection
  worktree.py                    # Git worktree management
  quiet.py                       # Stderr noise filter
  history.py                     # Run history (JSON logs)
  parallel.py                    # Concurrent task runner
  prefetch.py                    # Context prefetching (Stripe Layer 2)
  toolshed.py                    # MCP tool loader
  hooks/
    safety.py                    # Block dangerous commands, protect files
    validation.py                # Auto-lint after agent writes
  agents/
    definitions.py               # Subagent definitions (researcher, fixer, tester, reviewer, builder)
  blueprints/
    base.py                      # Step types, shell runner, formatting
    fix.py                       # Bug fix blueprint
    test.py                      # Test coverage blueprint
    review.py                    # Code review blueprint
    build.py                     # Feature implementation blueprint
    resume.py                    # Resume from session ID
  dashboard/
    app.py                       # Flask web dashboard
templates/
  CLAUDE.md.example              # Context engineering template
```

## Requirements

- Python 3.12+
- Git
- Claude CLI authenticated (`claude login`) or `ANTHROPIC_API_KEY` set
- `gh` CLI authenticated (for PR creation)
- macOS, Linux, or WSL

## License

MIT
