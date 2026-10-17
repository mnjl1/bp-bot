# BP Bot — Project conventions

Python 3.11 Telegram bot using python-telegram-bot, SQLite, and Docker.

## File responsibilities

- `bot.py`: Telegram handlers and application setup.
- `db.py`: SQLite database operations.
- `utils.py`: helper functions and input processing.
- `messages.py`: Ukrainian and English user-facing text.
- `constants.py`: constants, validation limits, and patterns.
- `admin.py`: administrator functionality.
- `Dockerfile` and `docker-compose.yml`: container configuration.

## Development

- Develop on a feature branch; keep each change focused on its task.
- Preserve file responsibilities and backward compatibility.
- Prefer minimal, readable changes; add abstractions or dependencies only when needed.
- Run project tests from the repository root using the project virtual environment:
  `venv/bin/python -B -m unittest discover -s tests -q`.
- Never commit secrets, credentials, `.env` files, or real database files.
- Explain changes step by step, including relevant Python and design decisions,
  so the project owner can understand and learn from them.
