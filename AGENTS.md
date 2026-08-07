# BP Bot — Codex Instructions

## Safety is the highest priority

This is a production project containing real user data.

Safety and production stability have priority over speed or convenience.

### Forbidden actions

- Never work directly on the `main` branch.
- Never run `git push`.
- Never merge branches.
- Never deploy.
- Never connect to or access the production VPS.
- Never use SSH.
- Never inspect, display, modify, copy, delete, or move `.env` files or secrets.
- Never inspect, modify, delete, replace, or migrate `bp.db`.
- Never change the database schema without explicit user approval.
- Never run destructive Git commands such as:
  - `git reset --hard`
  - `git clean`
  - force push
  - destructive checkout/restore operations
- Never bypass Codex sandbox or approval protections.
- Never use `danger-full-access`.
- Never modify deployment or Docker configuration unless explicitly requested.
- Never perform network or external-service actions unless explicitly requested.

If an action could affect production, user data, credentials, Git history,
deployment, or external services, STOP and request explicit user approval.

## Git workflow

- `main` is production-ready code only.
- Development happens only in a dedicated task branch.
- One task = one branch.
- Do not create, delete, merge, or push branches unless explicitly requested.
- Before changing files, check and report the current Git branch and working-tree status.
- Do not commit changes unless explicitly requested.
- Keep unrelated changes out of the current task.

## Development workflow

Before editing code:

1. Explain what you intend to change.
2. Identify which files need to change.
3. Explain why those files need to change.
4. Wait for approval when the requested task involves sensitive areas.

After editing code:

1. Explain exactly which files changed.
2. Explain the important implementation decisions.
3. Show how the change can be tested.
4. Do not deploy or push.

Prefer small, minimal changes over broad refactoring.

If requirements or consequences are unclear, STOP and ask instead of guessing.

## Project architecture

Technology:

- Python 3.11
- python-telegram-bot
- SQLite
- Docker

Existing responsibilities:

- `bot.py` — Telegram handlers and application setup
- `db.py` — SQLite database operations
- `utils.py` — helper functions and input processing
- `messages.py` — Ukrainian and English user-facing text
- `constants.py` — constants, validation limits, and patterns
- `admin.py` — administrator functionality

Preserve these responsibilities unless a change is explicitly discussed first.

Do not introduce new abstractions, dependencies, files, or architectural layers
unless they solve a clear requirement.

## Learning mode

The project owner is learning software development.

When proposing or implementing changes:

- Explain important Python concepts in plain language.
- Explain relevant Git, database, and architectural decisions.
- Prefer readable code over clever code.
- Do not assume generated code will be accepted without human review.
- Keep explanations focused on the changes being made.