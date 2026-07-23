// Theme toggle — light / dark. Persists to localStorage. The initial theme
// is applied by an inline script in each page's <head> to avoid FOUC.
window.__toggleTheme = function () {
  var current = document.documentElement.dataset.theme || 'dark';
  var next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('theme', next); } catch (e) {}
};

// Client-side ticker: updates countdown clocks, "held for X" counters,
// and each team's live-scoring row every 500ms. Runs against whatever
// DOM the server-rendered SSE payload put on the page, so it just works
// after every state push.

(function () {
  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function fmtCountdown(ms) {
    if (ms <= 0) return "00:00";
    const s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
  }

  function fmtHeld(secs) {
    if (secs < 0) secs = 0;
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${pad(s)}`;
  }

  function fmtLong(secs) {
    if (secs < 0) secs = 0;
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}m ${s}s`;
  }

  function tick() {
    const now = Date.now();

    // Game countdown.
    document.querySelectorAll("[data-countdown-to]").forEach((el) => {
      const target = Date.parse(el.getAttribute("data-countdown-to"));
      if (isNaN(target)) return;
      el.textContent = fmtCountdown(target - now);
    });

    // Per-flag "held since" counters.
    document.querySelectorAll("[data-tick-since]").forEach((el) => {
      const since = Date.parse(el.getAttribute("data-tick-since"));
      if (isNaN(since)) return;
      const secs = Math.floor((now - since) / 1000);
      el.textContent = fmtHeld(secs);
    });

    // Live scoreboard: for each team, add live delta if any flag is currently
    // accruing time for them. Delta is measured from the server render moment
    // (data-server-now) so client clock skew doesn't drift the score up or down.
    const serverNowEl = document.querySelector("[data-server-now]");
    if (!serverNowEl) return;
    const serverNow = Date.parse(serverNowEl.getAttribute("data-server-now"));
    if (isNaN(serverNow)) return;
    const clientDelta = Math.max(0, Math.floor((now - serverNow) / 1000));

    // Which teams have an active accrual right now?
    const activeTeams = new Set();
    document.querySelectorAll(".flag[data-active-team]").forEach((f) => {
      activeTeams.add(f.getAttribute("data-active-team"));
    });

    document.querySelectorAll("[data-live-time]").forEach((el) => {
      const team = el.getAttribute("data-team");
      const base = parseInt(el.getAttribute("data-base-seconds") || "0", 10);
      const extra = activeTeams.has(team) ? clientDelta : 0;
      el.textContent = fmtLong(base + extra);
    });

    document.querySelectorAll("[data-live-score]").forEach((el) => {
      const team = el.getAttribute("data-team");
      const cap = parseInt(el.getAttribute("data-capture-points") || "0", 10);
      const ball = parseInt(el.getAttribute("data-ball-points") || "0", 10);
      const bonus = parseInt(el.getAttribute("data-end-bonus") || "0", 10);
      const perMin = parseFloat(el.getAttribute("data-per-minute") || "0");
      const base = parseInt(el.getAttribute("data-base-seconds") || "0", 10);
      const extra = activeTeams.has(team) ? clientDelta : 0;
      const timePts = Math.floor(((base + extra) * perMin) / 60);
      el.textContent = String(cap + ball + bonus + timePts);
    });
  }

  setInterval(tick, 500);
  tick();
})();
