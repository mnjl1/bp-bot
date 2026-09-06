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

## Runtime and database migration safety gate

- Any change to SCHEMA_VERSION, migration code, schema validation,
  DB_PATH, Dockerfile, docker-compose database volumes, or database
  startup compatibility activates MIGRATION-SENSITIVE MODE.

- In MIGRATION-SENSITIVE MODE, never run:
  - python bot.py
  - docker compose up
  - docker compose restart
  - any command that starts the application against a real bp.db

- Tests may use temporary SQLite databases only.

- Treat local bp.db as protected real data.
  Never inspect, initialize, migrate, replace, modify, copy, or delete it
  without explicit user approval.

- Before a local live test after a schema change:
  1. full tests must pass
  2. review git diff
  3. explicit user approval
  4. create timestamped DB backup
  5. run SQLite integrity_check
  6. verify current schema version
  7. run the migration explicitly
  8. run integrity_check again
  9. verify expected schema version
  10. only then start the application

- Production database migrations are always manual.
  Codex must never perform them.

- Never perform a blind production:
  docker compose up -d --build
  when application schema requirements changed.

- Production schema deployment must be staged:
  1. verify current commit and container status
  2. prepare/build the new image before modifying the DB
  3. create timestamped DB backup
  4. run integrity/schema checks
  5. stop only the bot container when ready
  6. explicitly migrate using the approved code
  7. verify integrity and schema
  8. start/recreate the new bot container
  9. verify logs and health

- If migration fails, STOP.
  Never automatically restore a backup or start an application whose
  expected schema does not match the database schema.

- Never use docker compose down as a routine production deployment step.

- Never run docker system prune, docker volume rm, or destructive Docker
  cleanup on production without explicit approval.

- Docker images must never be pushed or published unless explicitly approved.
- After a clean production image is deployed and verified, obsolete images that may
  contain historical .env or bp.db snapshots may be removed only by exact image ID,
  with explicit user approval. Never use broad prune commands for this cleanup.

- If unsure whether a command can mount, open, or modify a real database,
  treat it as unsafe and ask first.

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
