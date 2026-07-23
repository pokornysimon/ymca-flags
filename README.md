# YMCA Capture the Flag — instructor app

A small FastAPI web app that lets a few camp instructors track a single capture-the-flag game in real time. See [rules.md](rules.md) for the game rules this implements.

## Stack

- Python 3.11+ / FastAPI / Uvicorn
- Server-rendered Jinja2 templates + HTMX for actions
- Server-Sent Events (SSE) push state to every connected screen
- In-memory state (one game per process). No database, no auth.

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open http://localhost:8000. Open the same URL in a second browser to see live sync.

## Using it during a game

1. **Setup screen** — enter team names (one per line, 2+ teams), duration, and point values. Click **Save setup**, then **Start game**.
2. **Running screen**:
   - Each flag has its own panel showing where it is.
   - When someone grabs a flag, tap the grabbing team's chip.
   - When they arrive at their base, tap **Captured by <team>**. If the flag was instead returned to its owner, tap **Returned to owner**.
   - Use the per-team **+1 ball delivered** for younger-kid scoring and **+1 hit thrown** for the honor-system hit stat.
   - Adjust point values any time — all scores recalculate.
   - **Undo last** rolls back the most recent event if you tapped the wrong thing.
   - The game ends automatically when the timer hits zero, or manually via **End game**.
3. **Ended screen** — final scoreboard with the winner. Point values can still be adjusted (recalculates). **Start new game** clears everything.

## Deploy to Azure App Service (Linux, Python)

The smallest tier (B1) is plenty for a handful of concurrent instructors.

**Startup command** (set in the App Service configuration):

```
bash startup.sh
```

**Required app settings:**

- `SCM_DO_BUILD_DURING_DEPLOYMENT=true` — installs requirements on deploy
- `WEBSITES_PORT=8000` — matches the gunicorn bind port in `startup.sh`

**Deploy** with the tool of your choice — VS Code Azure extension, `az webapp up`, GitHub Actions, or a zip deploy. Only one worker runs because SSE and in-memory state need every request to hit the same process.

## Files

- [game.py](game.py) — game state, actions, scoring
- [main.py](main.py) — FastAPI endpoints + SSE broadcaster
- [templates/](templates/) — Jinja2 HTML (setup / running / ended)
- [static/style.css](static/style.css) — dark UI
- [static/app.js](static/app.js) — client-side timer ticker
- [rules.md](rules.md) — game rules (source of truth)

## Known trade-offs

- **One game per process.** Restarting the app service resets the game. If you need to survive restarts, switch to a SQLite file inside `/home` (persistent on Azure Linux).
- **No auth.** Anyone with the URL can use it. Restrict via App Service access controls (IP allowlist / Easy Auth) if needed.
- **Single worker.** Fine for a few instructors; SSE + in-memory state make horizontal scaling non-trivial.
- **Best-effort undo.** Undo rewinds the last logged event and replays; it's for typo recovery, not full time-travel.
