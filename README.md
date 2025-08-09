### telegram-broker

Minimal scaffolding to manage Telegram dialog folders using Telethon.

### Requirements

- Python 3.12+
- Telegram API credentials from `https://my.telegram.org` (API ID and API Hash)

### Setup

1. Create and activate a virtual environment
   - macOS/Linux:
     - `python3.12 -m venv .venv && source .venv/bin/activate`
   - Windows (PowerShell):
     - `py -3.12 -m venv .venv; .venv\\Scripts\\Activate.ps1`

2. Install
   - `pip install -e .`

3. Configure environment
   - `cp .env.example .env`
   - Fill `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`
   - Adjust `ACCOUNT` if you use a different account directory under `data/accounts/<account>`

4. First run will ask you to log in
   - The session file is stored at `data/accounts/<account>/session.session`

### Run

- Via entrypoint: `telegram-broker`
- Or: `python -m app.main`

Desktop UI (PySide6):
- `telegram-broker --ui`

The app logs in (if needed) and ensures the following dialog folders exist with fixed IDs:
`{1: 'Manual', 2: 'Bot', 3: 'Timewaster', 4: 'Confirmation'}`.

### Project Layout

- `app/` – entrypoint
- `core/` – configuration, logging, folder management
- `telegram/` – Telegram client setup
- `ui/` – PySide6 desktop UI
- `data/accounts/acc1/` – sample templates and rules, plus session storage

### Notes

- `ensure_filters` is idempotent: it creates the folders if missing and preserves existing included peers when only titles are updated.
- Use `add_peer_to(client, folder_id, peer)` to add an entity (user/chat/channel) into a folder.


