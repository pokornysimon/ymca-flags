"""Capture-the-flag game state and scoring.

In-memory single-game model. All timestamps are timezone-aware UTC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


def now() -> datetime:
    return datetime.now(timezone.utc)


# Fixed team roster. The game always has exactly these four teams.
# Names are the display labels shown in the UI (Czech).
FIXED_TEAMS: list[tuple[str, str]] = [
    ("t1", "Červení"),
    ("t2", "Modří"),
    ("t3", "Žlutí"),
    ("t4", "Zelení"),
]


@dataclass
class Team:
    id: str
    name: str


@dataclass
class Holding:
    """A continuous interval during which one team held a flag at a base."""
    team_id: str
    started_at: datetime
    ended_at: Optional[datetime] = None

    def duration_seconds(self, at: Optional[datetime] = None) -> float:
        end = self.ended_at or (at or now())
        return max(0.0, (end - self.started_at).total_seconds())


@dataclass
class Flag:
    owner_team_id: str
    # "home" — at owner's base, owner accrues time
    # "in_transit" — being carried, nobody accrues time
    # "captured" — at another team's base, that team accrues time
    location: str = "home"
    carrier_team_id: Optional[str] = None
    at_base_team_id: Optional[str] = None
    holdings: list[Holding] = field(default_factory=list)


@dataclass
class PointValues:
    per_capture: int = 10
    per_minute_held: int = 1
    per_ball_delivered: int = 5
    end_game_flag_bonus: int = 20


class GameError(Exception):
    pass


class Game:
    def __init__(self) -> None:
        self.status: str = "setup"  # setup | countdown | running | ended
        self.duration_minutes: int = 60
        self.countdown_seconds: int = 30
        self.countdown_ends_at: Optional[datetime] = None
        self.started_at: Optional[datetime] = None
        self.ends_at: Optional[datetime] = None
        self.ended_at: Optional[datetime] = None
        self.teams: dict[str, Team] = {}
        self.flags: dict[str, Flag] = {}  # keyed by owner_team_id
        self.points = PointValues()
        self.captures_by_team: dict[str, int] = {}
        self.balls_by_team: dict[str, int] = {}
        self.hits_by_team: dict[str, int] = {}
        self.log: list[dict] = []
        self._init_teams()

    def _init_teams(self) -> None:
        """Populate the fixed 4-team roster with empty flags and counters."""
        self.teams = {}
        self.flags = {}
        self.captures_by_team = {}
        self.balls_by_team = {}
        self.hits_by_team = {}
        for team_id, name in FIXED_TEAMS:
            self.teams[team_id] = Team(id=team_id, name=name)
            self.flags[team_id] = Flag(owner_team_id=team_id)
            self.captures_by_team[team_id] = 0
            self.balls_by_team[team_id] = 0
            self.hits_by_team[team_id] = 0

    def _log(self, kind: str, **data) -> None:
        entry = {"t": now().isoformat(), "kind": kind, **data}
        self.log.append(entry)

    def team_name(self, team_id: str) -> str:
        team = self.teams.get(team_id)
        return team.name if team else team_id

    def setup(
        self,
        duration_minutes: int,
        points: Optional[PointValues] = None,
        countdown_seconds: Optional[int] = None,
    ) -> None:
        if self.status != "setup":
            raise GameError("Game already started. Reset first.")
        if duration_minutes <= 0:
            raise GameError("Duration must be positive.")
        self._init_teams()
        self.duration_minutes = duration_minutes
        if points is not None:
            self.points = points
        if countdown_seconds is not None:
            if countdown_seconds < 0:
                raise GameError("Countdown must be zero or positive.")
            self.countdown_seconds = countdown_seconds

    def start(self) -> None:
        """Begin the pre-game countdown (or the game directly if countdown is 0)."""
        if self.status != "setup":
            raise GameError("Can only start a game from setup.")
        if not self.teams:
            raise GameError("No teams configured.")
        if self.countdown_seconds > 0:
            self.status = "countdown"
            self.countdown_ends_at = now() + timedelta(seconds=self.countdown_seconds)
            self._log("countdown_started", seconds=self.countdown_seconds)
        else:
            self.begin_running()

    def begin_running(self) -> None:
        """Transition from countdown (or setup with zero countdown) to running."""
        if self.status not in ("setup", "countdown"):
            raise GameError("Game is not waiting to start.")
        self.status = "running"
        self.countdown_ends_at = None
        self.started_at = now()
        self.ends_at = self.started_at + timedelta(minutes=self.duration_minutes)
        # Each team starts defending its own flag at home.
        for flag in self.flags.values():
            flag.holdings.append(
                Holding(team_id=flag.owner_team_id, started_at=self.started_at)
            )
        self._log("start")

    def adjust_time(self, delta_seconds: int) -> bool:
        """Add (positive) or remove (negative) time from the running game clock.

        Returns True if the game ended as a result (remaining <= 0), False otherwise.
        """
        if self.status != "running" or not self.ends_at:
            raise GameError("Game clock can only be adjusted while running.")
        new_ends_at = self.ends_at + timedelta(seconds=delta_seconds)
        self._log("adjust_time", delta_seconds=delta_seconds)
        if new_ends_at <= now():
            self.ends_at = new_ends_at
            self.end()
            return True
        self.ends_at = new_ends_at
        return False

    def end(self, at: Optional[datetime] = None) -> None:
        if self.status != "running":
            return
        end_at = at or now()
        if self.ends_at and end_at > self.ends_at:
            end_at = self.ends_at
        self.ended_at = end_at
        # Close all active holdings.
        for flag in self.flags.values():
            for h in flag.holdings:
                if h.ended_at is None:
                    h.ended_at = end_at
        self.status = "ended"
        self._log("end")

    def reset(self) -> None:
        self.status = "setup"
        self.countdown_ends_at = None
        self.started_at = None
        self.ends_at = None
        self.ended_at = None
        self.log = []
        self._init_teams()

    # --- Flag actions ---

    def _require_running(self) -> None:
        if self.status != "running":
            raise GameError("Game is not running.")

    def _close_active_holding(self, flag: Flag, at: datetime) -> None:
        for h in flag.holdings:
            if h.ended_at is None:
                h.ended_at = at
                return

    def grab(self, flag_owner_id: str, by_team_id: str) -> None:
        """A team grabs a flag. Allowed from any base state, or from in_transit
        when the carrier is unknown (assigns the carrier)."""
        self._require_running()
        flag = self.flags.get(flag_owner_id)
        if not flag:
            raise GameError("Unknown flag.")
        if by_team_id not in self.teams:
            raise GameError("Unknown team.")
        if flag.location == "in_transit" and flag.carrier_team_id is not None:
            raise GameError("Flag is already being carried.")
        if by_team_id == flag.owner_team_id and flag.location == "home":
            raise GameError("Team cannot grab their own flag from their own base.")
        t = now()
        self._close_active_holding(flag, t)
        flag.location = "in_transit"
        flag.carrier_team_id = by_team_id
        flag.at_base_team_id = None
        self._log(
            "grab",
            flag=flag_owner_id,
            by=by_team_id,
            flag_name=self.team_name(flag_owner_id),
            by_name=self.team_name(by_team_id),
        )

    def lose_flag(self, flag_owner_id: str) -> None:
        """The current holder loses the flag to an unknown team. Flag becomes
        in_transit with no known carrier and nobody accrues time until it turns
        up somewhere (recovered home, or grabbed by an identified team)."""
        self._require_running()
        flag = self.flags.get(flag_owner_id)
        if not flag:
            raise GameError("Unknown flag.")
        if flag.location == "in_transit" and flag.carrier_team_id is None:
            raise GameError("Flag already lost to an unknown team.")
        lost_from = flag.at_base_team_id or flag.owner_team_id if flag.location != "in_transit" else flag.carrier_team_id
        t = now()
        self._close_active_holding(flag, t)
        flag.location = "in_transit"
        flag.carrier_team_id = None
        flag.at_base_team_id = None
        self._log(
            "lost",
            flag=flag_owner_id,
            flag_name=self.team_name(flag_owner_id),
            from_team=lost_from,
            from_name=self.team_name(lost_from) if lost_from else None,
        )

    def capture(self, flag_owner_id: str) -> None:
        """Carrier delivers the flag to their own base (successful capture).

        If the carrier IS the flag's owner (team rescuing their own flag), this
        is treated as a recovery — the flag goes home and no capture points are
        awarded.
        """
        self._require_running()
        flag = self.flags.get(flag_owner_id)
        if not flag or flag.location != "in_transit" or not flag.carrier_team_id:
            raise GameError("Flag is not in transit.")
        captor = flag.carrier_team_id
        if captor == flag.owner_team_id:
            self.recover(flag_owner_id)
            return
        t = now()
        flag.location = "captured"
        flag.at_base_team_id = captor
        flag.carrier_team_id = None
        flag.holdings.append(Holding(team_id=captor, started_at=t))
        self.captures_by_team[captor] = self.captures_by_team.get(captor, 0) + 1
        self._log(
            "capture",
            flag=flag_owner_id,
            by=captor,
            flag_name=self.team_name(flag_owner_id),
            by_name=self.team_name(captor),
        )

    def recover(self, flag_owner_id: str) -> None:
        """Flag returns to its owner's home base (no capture points)."""
        self._require_running()
        flag = self.flags.get(flag_owner_id)
        if not flag or flag.location != "in_transit":
            raise GameError("Flag is not in transit.")
        t = now()
        flag.location = "home"
        flag.carrier_team_id = None
        flag.at_base_team_id = None
        flag.holdings.append(Holding(team_id=flag.owner_team_id, started_at=t))
        self._log(
            "recover",
            flag=flag_owner_id,
            flag_name=self.team_name(flag_owner_id),
        )

    def undo_last(self) -> None:
        """Best-effort undo of the last flag action. Not exhaustive; for correcting typos."""
        # Find last flag-modifying event in log
        for i in range(len(self.log) - 1, -1, -1):
            entry = self.log[i]
            if entry["kind"] in ("grab", "capture", "recover", "lost"):
                # Rewind the corresponding flag by rebuilding holdings from the start
                # of the game up to just before this event. Simpler: rebuild all flags
                # by replaying the log without this entry.
                removed = self.log.pop(i)
                self._replay_from_log()
                self._log("undo", of=removed)
                return
            if entry["kind"] in ("ball_delivered", "ball_hit"):
                team = entry["team"]
                if entry["kind"] == "ball_delivered":
                    self.balls_by_team[team] = max(0, self.balls_by_team.get(team, 0) - 1)
                else:
                    self.hits_by_team[team] = max(0, self.hits_by_team.get(team, 0) - 1)
                self.log.pop(i)
                self._log("undo", of=entry)
                return
        raise GameError("Nothing to undo.")

    def _replay_from_log(self) -> None:
        """Rebuild flag state and captures counters from the retained log entries."""
        if not self.started_at:
            return
        # Reset flags and captures.
        for team_id in self.teams:
            self.captures_by_team[team_id] = 0
            self.flags[team_id] = Flag(owner_team_id=team_id)
            self.flags[team_id].holdings.append(
                Holding(team_id=team_id, started_at=self.started_at)
            )
        # Replay flag-related events in order.
        for entry in self.log:
            kind = entry["kind"]
            t = datetime.fromisoformat(entry["t"])
            if kind == "grab":
                flag = self.flags[entry["flag"]]
                self._close_active_holding(flag, t)
                flag.location = "in_transit"
                flag.carrier_team_id = entry["by"]
            elif kind == "capture":
                flag = self.flags[entry["flag"]]
                flag.location = "captured"
                flag.at_base_team_id = entry["by"]
                flag.carrier_team_id = None
                flag.holdings.append(Holding(team_id=entry["by"], started_at=t))
                self.captures_by_team[entry["by"]] = (
                    self.captures_by_team.get(entry["by"], 0) + 1
                )
            elif kind == "recover":
                flag = self.flags[entry["flag"]]
                flag.location = "home"
                flag.carrier_team_id = None
                flag.at_base_team_id = None
                flag.holdings.append(
                    Holding(team_id=flag.owner_team_id, started_at=t)
                )
            elif kind == "lost":
                flag = self.flags[entry["flag"]]
                self._close_active_holding(flag, t)
                flag.location = "in_transit"
                flag.carrier_team_id = None
                flag.at_base_team_id = None

    # --- Ball actions ---

    def ball_delivered(self, team_id: str) -> None:
        self._require_running()
        if team_id not in self.teams:
            raise GameError("Unknown team.")
        self.balls_by_team[team_id] = self.balls_by_team.get(team_id, 0) + 1
        self._log("ball_delivered", team=team_id, team_name=self.team_name(team_id))

    def ball_hit(self, team_id: str) -> None:
        self._require_running()
        if team_id not in self.teams:
            raise GameError("Unknown team.")
        self.hits_by_team[team_id] = self.hits_by_team.get(team_id, 0) + 1
        self._log("ball_hit", team=team_id, team_name=self.team_name(team_id))

    # --- Point values ---

    def update_points(
        self,
        per_capture: Optional[int] = None,
        per_minute_held: Optional[int] = None,
        per_ball_delivered: Optional[int] = None,
        end_game_flag_bonus: Optional[int] = None,
    ) -> None:
        if per_capture is not None:
            self.points.per_capture = int(per_capture)
        if per_minute_held is not None:
            self.points.per_minute_held = int(per_minute_held)
        if per_ball_delivered is not None:
            self.points.per_ball_delivered = int(per_ball_delivered)
        if end_game_flag_bonus is not None:
            self.points.end_game_flag_bonus = int(end_game_flag_bonus)

    # --- Scoring ---

    def scoring_reference_time(self) -> datetime:
        if self.status == "ended" and self.ended_at:
            return self.ended_at
        return now()

    def compute_scores(self) -> dict[str, dict]:
        at = self.scoring_reference_time()
        scores: dict[str, dict] = {}
        for team_id in self.teams:
            seconds_held = 0.0
            for flag in self.flags.values():
                for h in flag.holdings:
                    if h.team_id == team_id:
                        seconds_held += h.duration_seconds(at)
            capture_points = (
                self.captures_by_team.get(team_id, 0) * self.points.per_capture
            )
            ball_points = (
                self.balls_by_team.get(team_id, 0) * self.points.per_ball_delivered
            )
            time_points = int(seconds_held * self.points.per_minute_held / 60)
            end_bonus = 0
            if self.status == "ended":
                for flag in self.flags.values():
                    if flag.location == "home" and flag.owner_team_id == team_id:
                        end_bonus += self.points.end_game_flag_bonus
                    elif (
                        flag.location == "captured"
                        and flag.at_base_team_id == team_id
                    ):
                        end_bonus += self.points.end_game_flag_bonus
            total = capture_points + time_points + ball_points + end_bonus
            scores[team_id] = {
                "team_id": team_id,
                "team_name": self.team_name(team_id),
                "captures": self.captures_by_team.get(team_id, 0),
                "balls": self.balls_by_team.get(team_id, 0),
                "hits": self.hits_by_team.get(team_id, 0),
                "seconds_held": int(seconds_held),
                "capture_points": capture_points,
                "time_points": time_points,
                "ball_points": ball_points,
                "end_bonus": end_bonus,
                "total": total,
            }
        return scores

    def flag_status_snapshot(self) -> list[dict]:
        at = self.scoring_reference_time()
        result = []
        for owner_id, flag in self.flags.items():
            active_holder = None
            active_since = None
            for h in flag.holdings:
                if h.ended_at is None:
                    active_holder = h.team_id
                    active_since = h.started_at
                    break
            result.append(
                {
                    "owner_id": owner_id,
                    "owner_name": self.team_name(owner_id),
                    "location": flag.location,
                    "carrier_id": flag.carrier_team_id,
                    "carrier_name": (
                        self.team_name(flag.carrier_team_id)
                        if flag.carrier_team_id
                        else None
                    ),
                    "at_base_id": flag.at_base_team_id,
                    "at_base_name": (
                        self.team_name(flag.at_base_team_id)
                        if flag.at_base_team_id
                        else None
                    ),
                    "active_holder_id": active_holder,
                    "active_holder_name": (
                        self.team_name(active_holder) if active_holder else None
                    ),
                    "active_since": (
                        active_since.isoformat() if active_since else None
                    ),
                    "reference_time": at.isoformat(),
                }
            )
        return result
