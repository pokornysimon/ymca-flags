"""FastAPI app for the capture-the-flag instructor tool.

Single-process, in-memory. Server-rendered HTML with HTMX for actions and
Server-Sent Events for pushing updates to every connected instructor.

The SSE stream fires a single "changed" event on every state change; each
view (admin panel, team panel, lobby) refetches its own partial via HTMX
when it hears that event.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from game import Game, GameError, PointValues, now

log = logging.getLogger("ymca_flags")
logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

game = Game()


class Broadcaster:
    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue[str]] = set()

    async def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        self.subscribers.discard(q)

    async def publish(self, event: str, data: str = "") -> None:
        payload = _sse_format(event, data)
        stale = []
        for q in list(self.subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                stale.append(q)
        for q in stale:
            self.unsubscribe(q)


def _sse_format(event: str, data: str) -> str:
    lines = [f"event: {event}"]
    for line in (data.splitlines() or [""]):
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


broadcaster = Broadcaster()
_bg_task: Optional[asyncio.Task] = None


def _panel_context(request: Request) -> dict:
    return {
        "request": request,
        "game": game,
        "scores": sorted(
            game.compute_scores().values(), key=lambda s: -s["total"]
        )
        if game.teams
        else [],
        "flags": game.flag_status_snapshot(),
        "points": game.points,
        "server_now": now().isoformat(),
    }


async def broadcast_change() -> None:
    await broadcaster.publish("changed", "")


async def _run_countdown() -> None:
    """Wait out the pre-game countdown then transition to running.

    When it finishes we also chain into the auto-end wait — a single background
    task shepherds the game through countdown → running → end.
    """
    if not game.countdown_ends_at:
        return
    delay = (game.countdown_ends_at - now()).total_seconds()
    if delay > 0:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
    if game.status == "countdown":
        game.begin_running()
        await broadcast_change()
        await _auto_end_wait()


async def _auto_end_wait() -> None:
    """Sleep until game.ends_at and end the game if it's still running."""
    while game.status == "running" and game.ends_at:
        delay = (game.ends_at - now()).total_seconds()
        if delay <= 0:
            break
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        # Loop: ends_at may have been extended while we slept.
    if game.status == "running":
        game.end()
        await broadcast_change()


def _cancel_bg_task() -> None:
    global _bg_task
    if _bg_task and not _bg_task.done():
        _bg_task.cancel()
    _bg_task = None


def _start_bg_task(coro) -> None:
    global _bg_task
    _cancel_bg_task()
    _bg_task = asyncio.create_task(coro)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    _cancel_bg_task()


app = FastAPI(lifespan=lifespan)

static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "panel_html": templates.get_template("_main.html").render(_panel_context(request))},
    )


@app.get("/join", response_class=HTMLResponse)
async def join_lobby(request: Request):
    return templates.TemplateResponse(
        "join.html",
        {"request": request, "panel_html": templates.get_template("_lobby.html").render(_panel_context(request))},
    )


@app.get("/team/{team_id}", response_class=HTMLResponse)
async def team_page(request: Request, team_id: str):
    if team_id not in game.teams:
        # Team doesn't exist yet (or reset). Send them to the lobby.
        return templates.TemplateResponse(
            "team.html",
            {
                "request": request,
                "team": None,
                "team_id": team_id,
                "panel_html": '<section class="card"><p>Tento tým již neexistuje. '
                              '<a href="/join">Zpět do vestibulu</a>.</p></section>',
            },
        )
    ctx = _panel_context(request)
    ctx["team"] = game.teams[team_id]
    return templates.TemplateResponse(
        "team.html",
        {
            "request": request,
            "team": game.teams[team_id],
            "team_id": team_id,
            "panel_html": templates.get_template("_team_main.html").render(ctx),
        },
    )


# ---------------------------------------------------------------------------
# Panel fragment routes (fetched by HTMX on SSE "changed")
# ---------------------------------------------------------------------------


@app.get("/panel/main", response_class=HTMLResponse)
async def panel_main(request: Request):
    return templates.TemplateResponse("_main.html", _panel_context(request))


@app.get("/panel/lobby", response_class=HTMLResponse)
async def panel_lobby(request: Request):
    return templates.TemplateResponse("_lobby.html", _panel_context(request))


@app.get("/panel/team/{team_id}", response_class=HTMLResponse)
async def panel_team(request: Request, team_id: str):
    if team_id not in game.teams:
        return HTMLResponse(
            '<section class="card"><p>Tento tým již neexistuje. '
            '<a href="/join">Zpět do vestibulu</a>.</p></section>'
        )
    ctx = _panel_context(request)
    ctx["team"] = game.teams[team_id]
    return templates.TemplateResponse("_team_main.html", ctx)


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------


@app.get("/stream")
async def stream(request: Request):
    async def event_gen():
        q = await broadcaster.subscribe()
        try:
            # Prime the new client so it fetches its panel immediately.
            yield _sse_format("changed", "")
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broadcaster.unsubscribe(q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Action endpoints (POST)
# ---------------------------------------------------------------------------


def _no_content() -> Response:
    return Response(status_code=204)


def _handle_game_error(e: GameError) -> JSONResponse:
    return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/setup")
async def setup(
    duration_minutes: int = Form(...),
    countdown_seconds: int = Form(30),
    per_capture: int = Form(10),
    per_minute_held: int = Form(1),
    per_ball_delivered: int = Form(5),
    end_game_flag_bonus: int = Form(20),
):
    try:
        game.setup(
            duration_minutes=duration_minutes,
            countdown_seconds=countdown_seconds,
            points=PointValues(
                per_capture=per_capture,
                per_minute_held=per_minute_held,
                per_ball_delivered=per_ball_delivered,
                end_game_flag_bonus=end_game_flag_bonus,
            ),
        )
    except GameError as e:
        return _handle_game_error(e)
    await broadcast_change()
    return _no_content()


@app.post("/start")
async def start_game():
    try:
        game.start()
    except GameError as e:
        return _handle_game_error(e)
    if game.status == "countdown":
        _start_bg_task(_run_countdown())
    else:
        _start_bg_task(_auto_end_wait())
    await broadcast_change()
    return _no_content()


@app.post("/skip_countdown")
async def skip_countdown():
    try:
        game.begin_running()
    except GameError as e:
        return _handle_game_error(e)
    _start_bg_task(_auto_end_wait())
    await broadcast_change()
    return _no_content()


@app.post("/adjust_time")
async def adjust_time(delta_seconds: int = Form(...)):
    try:
        ended = game.adjust_time(delta_seconds=delta_seconds)
    except GameError as e:
        return _handle_game_error(e)
    if ended:
        _cancel_bg_task()
    # If still running, the auto-end loop notices the new ends_at on its next
    # wake — but we cancel and restart it so it re-computes immediately.
    elif game.status == "running":
        _start_bg_task(_auto_end_wait())
    await broadcast_change()
    return _no_content()


@app.post("/end")
async def end_game():
    game.end()
    _cancel_bg_task()
    await broadcast_change()
    return _no_content()


@app.post("/reset")
async def reset_game():
    _cancel_bg_task()
    game.reset()
    await broadcast_change()
    return _no_content()


@app.post("/flag/{owner_id}/grab")
async def flag_grab(owner_id: str, by_team_id: str = Form(...)):
    try:
        game.grab(flag_owner_id=owner_id, by_team_id=by_team_id)
    except GameError as e:
        return _handle_game_error(e)
    await broadcast_change()
    return _no_content()


@app.post("/flag/{owner_id}/capture")
async def flag_capture(owner_id: str):
    try:
        game.capture(flag_owner_id=owner_id)
    except GameError as e:
        return _handle_game_error(e)
    await broadcast_change()
    return _no_content()


@app.post("/flag/{owner_id}/recover")
async def flag_recover(owner_id: str):
    try:
        game.recover(flag_owner_id=owner_id)
    except GameError as e:
        return _handle_game_error(e)
    await broadcast_change()
    return _no_content()


@app.post("/flag/{owner_id}/lose")
async def flag_lose(owner_id: str):
    try:
        game.lose_flag(flag_owner_id=owner_id)
    except GameError as e:
        return _handle_game_error(e)
    await broadcast_change()
    return _no_content()


@app.post("/ball/{team_id}/delivered")
async def ball_delivered(team_id: str):
    try:
        game.ball_delivered(team_id)
    except GameError as e:
        return _handle_game_error(e)
    await broadcast_change()
    return _no_content()


@app.post("/ball/{team_id}/hit")
async def ball_hit(team_id: str):
    try:
        game.ball_hit(team_id)
    except GameError as e:
        return _handle_game_error(e)
    await broadcast_change()
    return _no_content()


@app.post("/points")
async def update_points(
    per_capture: int = Form(...),
    per_minute_held: int = Form(...),
    per_ball_delivered: int = Form(...),
    end_game_flag_bonus: int = Form(...),
):
    game.update_points(
        per_capture=per_capture,
        per_minute_held=per_minute_held,
        per_ball_delivered=per_ball_delivered,
        end_game_flag_bonus=end_game_flag_bonus,
    )
    await broadcast_change()
    return _no_content()


@app.post("/undo")
async def undo():
    try:
        game.undo_last()
    except GameError as e:
        return _handle_game_error(e)
    await broadcast_change()
    return _no_content()


@app.get("/health")
async def health():
    return {"status": "ok", "game_status": game.status}


@app.get("/state.json")
async def state_json():
    """Debug endpoint — returns full raw state as JSON."""
    return {
        "status": game.status,
        "started_at": game.started_at.isoformat() if game.started_at else None,
        "ends_at": game.ends_at.isoformat() if game.ends_at else None,
        "ended_at": game.ended_at.isoformat() if game.ended_at else None,
        "teams": [{"id": t.id, "name": t.name} for t in game.teams.values()],
        "scores": game.compute_scores(),
        "flags": game.flag_status_snapshot(),
        "points": {
            "per_capture": game.points.per_capture,
            "per_minute_held": game.points.per_minute_held,
            "per_ball_delivered": game.points.per_ball_delivered,
            "end_game_flag_bonus": game.points.end_game_flag_bonus,
        },
        "log_tail": game.log[-20:],
    }
