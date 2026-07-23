# Capture the Flag — Game Rules

Base rules for the summer-camp capture-the-flag game. These rules are the source of truth for the instructor web app that tracks scoring.

## Overview

Three or more teams compete. Each team has one flag and defends it while trying to capture the other teams' flags. Younger kids can also score by bringing balls to their base. The game runs for a fixed time; whichever team has the most points at the end wins.

## Teams and flags

- **Number of teams:** 3 or more (configurable per game).
- **Flags per team:** exactly 1.
- **Home base:** each team has a designated home base where its own flag starts, and where captured flags are brought.

## Game duration

- Instructors set a fixed time limit before the game starts (e.g. 60 minutes).
- When the timer ends, no further captures or ball deliveries count. Final scoring is computed and end-of-game bonuses are applied.

## Flag mechanics

### Immunity while carrying

- When a player grabs an enemy flag, that player has **immunity** until they either reach their own home base (successful capture) or drop/lose the flag by other means.
- Flag carriers cannot be sent home by a ball hit (see [Balls](#balls)) — their immunity overrides the honor rule.

### Stealable at all times once at a base

- A flag sitting at any base (its home or a capturer's base) can be stolen **immediately** — there is no protection or cooldown window.

### What counts as a capture

- A capture is registered when a player brings an enemy flag to **their own home base**.

### Time counting (per-minute scoring)

A flag earns per-minute points for **whichever team currently holds it at a base**:

- **At its home base, undisturbed:** the owning team accumulates per-minute points.
- **In transit (being carried by an enemy):** no team accumulates per-minute points for that flag. These minutes are intentionally "lost."
- **At a capturer's home base:** the capturing team accumulates per-minute points until the flag is stolen away again.

Transitions:

- The moment a team's flag is taken from its base, that team **stops** counting minutes for it.
- The moment a capturing team brings the flag to their home base, that team **starts** counting minutes for it.
- If the flag is stolen again (by any team, including the original owner returning it home), counting switches accordingly.

## Balls

Balls have two roles in the game: they are ammunition for older players and a scoring item for younger ones.

### As ammunition (older kids)

- Players throw balls at opponents.
- **Honor rule:** when a player is hit by a ball, they must return to their own home base before rejoining play. While at home they can pick up more balls as fresh ammunition and then run out again.
- **Flag carriers are immune** — a ball hit does not stop a flag capture in progress.
- Ball hits do **not** contribute to score. They are tracked per team only as a post-game stat.

### As a scoring item (younger kids)

- Younger players score by bringing balls to their team's home base.
- Each delivered ball gives the team **flat points** (see [Point values](#point-values)).
- Balls are not time-tracked; once delivered, they stay with the receiving team.

## Scoring summary

Each team's total score is the sum of:

1. **Capture points** — flat points awarded each time the team successfully brings an enemy flag home.
2. **Time-held points** — per-minute points for every minute the team held a flag at a base (either defending their own or holding a captured one).
3. **Ball delivery points** — flat points per ball delivered to the team's base.
4. **End-of-game flag bonus** — extra points for each flag physically at the team's base when the timer ends.

## Point values

All point values are **variable** and set by instructors:

- Points per capture
- Points per minute held
- Points per ball delivered
- End-of-game bonus per flag held

Instructors can change any point value **during or after the game**. Because the app stores raw events (captures, time intervals held, ball deliveries, final flag holdings) rather than pre-computed scores, changing a point value causes all team scores to recalculate from those events. No history of point-value changes is kept.

## Winning

- The team with the highest total score when the timer ends wins.
- Ties are broken at the instructor's discretion.

## What the app needs to track

To support the rules above, the instructor app should record:

- **Game setup:** list of teams, game duration, point values (capture / per-minute / per-ball / end-of-game bonus).
- **Flag state, per flag:** current location (home / in transit / at which team's base), and who (if anyone) is currently accumulating time for it.
- **Events:**
  - Flag grabbed (from which base, by which team)
  - Flag captured (brought home to which team's base)
  - Flag returned home / recovered by owner
  - Ball delivered (by which team)
  - Ball hit registered (against which team) — stat only, no score impact
- **Timers:** running total of minutes each team has held each flag at a base.
- **Game clock:** overall countdown, with a clear end-of-game moment that freezes further events and triggers final scoring.
- **Live scoreboard:** derived from events + current point values; updates immediately when point values change.
- **Hit tally:** total hits per team, shown as a stat but excluded from scoring.

## Open items to decide before first play

- Exact default point values for each category.
- Tie-breaker rule (if a formal one is preferred over instructor call).
- Handling of disputed simultaneous grabs (currently: instructor call).
- Whether hit-tracking will actually be used during play, or dropped if it slows instructors down.
