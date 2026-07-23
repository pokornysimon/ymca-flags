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

**Runtime:** Python 3.13, Linux.

**One-time Startup Command setup (required).** FastAPI is ASGI; Azure's
default autodetected startup runs it as WSGI, which crashes silently and
shows the "Your App Service app is up and running" placeholder page.

The `azure/webapps-deploy` GitHub Action can't set the startup command when
using publish-profile auth (only OIDC/service-principal auth supports it), so
set it once in the portal:

1. Portal → App Service (**ymca-flags**) → **Configuration** → **General settings**
2. **Startup Command**, paste one of:
   - `bash startup.sh`  *(recommended — startup.sh is version-controlled)*
   - or the full command:
     `gunicorn --bind=0.0.0.0 --workers=1 --worker-class=uvicorn.workers.UvicornWorker --timeout=600 --keep-alive=75 main:app`
3. **Save** (button at the top), then hit **Restart** on the App Service overview.

You only need to do this once — it persists across deploys.

**App settings** — `SCM_DO_BUILD_DURING_DEPLOYMENT=true` (installs
`requirements.txt` on deploy). Nothing else needed; the app binds to the
`$PORT` Azure sets in the container.

Only one worker runs because SSE and in-memory state need every request to hit the same process.

### Troubleshooting: default Azure page after deploy

If the deploy job succeeds but you still see the Azure placeholder page:

1. Confirm the **Startup Command** is set — either via the workflow's
   `startup-command:` field, or in the portal at Configuration → General
   Settings.
2. Portal → App Service → **Log stream** shows the container output. Look for
   a Python traceback or a gunicorn worker crash.
3. Portal → App Service → Diagnose and solve problems → **Container Crash**
   often surfaces the root cause in one click.
4. If you switch the startup command in the portal, hit **Restart** on the
   App Service — App Service doesn't always pick up config changes on the
   next request.

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
