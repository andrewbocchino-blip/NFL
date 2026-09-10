#!/usr/bin/env python3
"""nfl_props.py — player prop capture, screening and grading.

Ports the MLB project's prop infrastructure to NFL. Same discipline: capture
real prices, no-vig them, screen against consensus, grade against real
outcomes, report honestly. No pick generation.

WHY PROPS ARE A SEPARATE FILE FROM GAME LINES
  Game lines come from one bulk endpoint: one call returns every game. Props
  come from the PER-EVENT endpoint, which bills credits per event per market
  per region. That is a completely different cost profile and it needs its
  own schedule, its own budget guard and its own workflow. Running props on
  the game-lines cadence would burn the season's credits in about a week.

CREDIT ARITHMETIC — READ BEFORE SCHEDULING
  cost = events x markets x regions
  16 games x 5 markets x 1 region  = 80 credits per full sweep.
  Every 3 hours, Tue-Sun  ->  ~45,000 for a season. You have 20,000, shared
  with MLB. That does not fit.
  Twice daily, Thu-Sun    ->  ~5,800 for a season. That fits.
  MAX_CREDITS_PER_RUN below is a hard stop, not a guideline.

WHY PROPS AT ALL
  The pooled backtest says the EPA projection carries no information against
  closing NFL spreads (slope +0.007, t=0.13, n=1,578). Props are a thinner,
  slower-moving market, so they are where an edge is more plausible — but
  "more plausible" is a hypothesis, not a finding. This file exists to
  measure it, and it will report a null result just as readily.

GRADING
  Props settle from nflverse play-by-play, which this repo already downloads
  for the backtest. No new data dependency: passing/rushing/receiving yards,
  receptions and TDs are all in pbp with player names attached.

USAGE
  python nfl_props.py selftest      # offline, no credits
  python nfl_props.py budget        # what a sweep would cost, no credits
  python nfl_props.py capture       # per-event props -> JSONL
  python nfl_props.py screen --log  # off-market props, paper only
  python nfl_props.py grade --season 2026 --week 1
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import nfl_lines as L

SPORT = "americanfootball_nfl"
PROPS_PATH = "data/nfl_props_snapshots.jsonl"
PROP_HITS_PATH = "data/nfl_prop_hits.jsonl"
GRADED_PATH = "data/nfl_prop_graded.jsonl"

EVENTS_PATH = os.environ.get("ODDS_EVENTS_TEMPLATE", "/odds/{sport}/events")
EVENT_ODDS_PATH = os.environ.get("ODDS_EVENT_ODDS_TEMPLATE",
                                 "/odds/{sport}/events/{event_id}/odds")

# Markets chosen because pbp can grade every one of them. Adding a market you
# cannot settle produces captures that never become evidence.
DEFAULT_MARKETS = [
    "player_pass_yds",
    "player_rush_yds",
    "player_reception_yds",
    "player_receptions",
    "player_anytime_td",
]

# Hard stop. A runaway sweep is how a 20K plan disappears in a weekend.
MAX_CREDITS_PER_RUN = int(os.environ.get("MAX_CREDITS_PER_RUN", "120"))

# Maps each market to the pbp aggregation that settles it.
GRADERS = {
    "player_pass_yds":      ("passer_player_name",   "passing_yards",   "sum"),
    "player_rush_yds":      ("rusher_player_name",   "rushing_yards",   "sum"),
    "player_reception_yds": ("receiver_player_name", "receiving_yards", "sum"),
    "player_receptions":    ("receiver_player_name", "complete_pass",   "sum"),
}


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def _get(path: str, params: dict | None = None):
    if not L.PROXY:
        raise SystemExit("ODDS_PROXY is not set.")
    url = f"{L.PROXY}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "nfl-props/1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf8")), \
                resp.headers.get("x-requests-remaining")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise SystemExit(
                f"404 at {url}\nThe worker routes events under "
                f"'{EVENTS_PATH}'. If yours differs set ODDS_EVENTS_TEMPLATE / "
                f"ODDS_EVENT_ODDS_TEMPLATE. Open the worker base URL in a "
                f"browser — it lists its own endpoints.") from e
        raise


def fetch_events(within_days: float | None = None) -> list[dict]:
    """Event ids for upcoming games. This call is free on The Odds API.

    THE ENDPOINT RETURNS THE WHOLE SEASON. Measured 2026-09-10: 187 events,
    not the 16 in the current week. Sweeping all of them costs
    187 x 5 markets = 935 credits per run and ~134,000 across a season
    against a 20,000 plan. `within_days` is therefore not optional in
    practice — it is what makes props affordable at all.
    """
    body, _ = _get(EVENTS_PATH.format(sport=SPORT))
    if not isinstance(body, list):
        raise SystemExit(f"expected a list of events, got {type(body).__name__}")
    if within_days is None:
        return body
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                           time.gmtime(time.time() + within_days * 86400))
    kept = [e for e in body if (e.get("commence_time") or "") <= cutoff]
    print(f"[nfl_props] {len(body)} events on the board -> {len(kept)} within "
          f"{within_days:g}d", file=sys.stderr)
    return kept


def estimate_credits(n_events: int, markets: list[str], regions: str = "us") -> int:
    return n_events * len(markets) * len(regions.split(","))


def capture(markets: list[str] | None = None, regions: str = "us",
            max_events: int | None = None, dry_run: bool = False,
            within_days: float | None = 7.0, game_id: str | None = None) -> int:
    """Per-event prop capture, change-only, with a hard credit ceiling."""
    markets = markets or DEFAULT_MARKETS
    events = fetch_events(within_days)
    if game_id:
        events = [e for e in events if e.get("id") == game_id]
        if not events:
            raise SystemExit(f"game_id {game_id} not on the events board")
    if max_events:
        events = events[:max_events]
    cost = estimate_credits(len(events), markets, regions)
    print(f"[nfl_props] {len(events)} events x {len(markets)} markets x "
          f"{len(regions.split(','))} region = ~{cost} credits")
    if cost > MAX_CREDITS_PER_RUN:
        raise SystemExit(
            f"ABORT: estimated {cost} credits exceeds MAX_CREDITS_PER_RUN="
            f"{MAX_CREDITS_PER_RUN}. Reduce --markets or --max-events, or raise "
            f"the ceiling deliberately. This guard exists because a per-event "
            f"sweep on a 3-hour cadence burns a 20K plan in about a week.")
    if dry_run:
        print("[nfl_props] dry run — no credits spent")
        return 0

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(os.path.dirname(PROPS_PATH), exist_ok=True)
    seen = _last_seen()
    n = skipped = 0
    remaining = None
    with open(PROPS_PATH, "a") as f:
        for ev in events:
            gid = ev.get("id")
            try:
                body, remaining = _get(
                    EVENT_ODDS_PATH.format(sport=SPORT, event_id=gid),
                    {"regions": regions, "markets": ",".join(markets),
                     "oddsFormat": "american"})
            except SystemExit:
                raise
            except Exception as exc:
                print(f"  event {gid}: {type(exc).__name__} — skipped",
                      file=sys.stderr)
                continue
            for bk in body.get("bookmakers", []):
                for mk in bk.get("markets", []):
                    for oc in mk.get("outcomes", []):
                        key = (gid, mk.get("key"), bk.get("key"),
                               oc.get("description"), oc.get("name"))
                        cur = (oc.get("price"), oc.get("point"))
                        if seen.get(key) == cur:
                            skipped += 1
                            continue
                        f.write(json.dumps({
                            "captured_at": ts, "game_id": gid,
                            "commence_time": ev.get("commence_time"),
                            "home_team": ev.get("home_team"),
                            "away_team": ev.get("away_team"),
                            "book": bk.get("key"), "market": mk.get("key"),
                            "player": oc.get("description"),
                            "outcome": oc.get("name"),
                            "point": oc.get("point"), "price": oc.get("price"),
                        }) + "\n")
                        n += 1
    if remaining:
        print(f"[nfl_props] credits remaining: {remaining}", file=sys.stderr)
    print(f"[nfl_props] wrote {n} changed rows ({skipped} unchanged) to {PROPS_PATH}")
    return n


def _last_seen(path: str | None = None) -> dict:
    path = path or PROPS_PATH
    seen = {}
    if not os.path.exists(path):
        return seen
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            seen[(r["game_id"], r["market"], r["book"], r.get("player"),
                  r["outcome"])] = (r.get("price"), r.get("point"))
    return seen


def load(path: str | None = None) -> list[dict]:
    path = path or PROPS_PATH
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(x) for x in f if x.strip()]


# ---------------------------------------------------------------------------
# Screen
# ---------------------------------------------------------------------------

def consensus(rows: list[dict], min_books: int = 3) -> dict:
    """No-vig consensus per player/market/side/point.

    The key includes PLAYER and POINT. Two books offering 'over 65.5 rec yds'
    and 'over 71.5 rec yds' are quoting different bets; pooling them values
    the six yards as if it were a mispriced book. This is the same error that
    produced phantom +6% edges on game spreads before it was fixed there.
    """
    latest = {}
    for r in rows:
        k = (r["game_id"], r["market"], r["book"], r.get("player"),
             r["outcome"], r.get("point"))
        if k not in latest or r["captured_at"] > latest[k]["captured_at"]:
            latest[k] = r

    per_book = {}
    for r in latest.values():
        per_book.setdefault((r["game_id"], r["market"], r["book"],
                             r.get("player"), r.get("point")), []).append(r)

    fair = {}
    for (gid, mkt, book, player, point), outs in per_book.items():
        if len(outs) != 2:          # need both sides to strip vig
            continue
        try:
            nv = L.devig([L.american_to_prob(o["price"]) for o in outs])
        except (ValueError, TypeError):
            continue
        for o, p in zip(outs, nv):
            fair.setdefault((gid, mkt, player, o["outcome"], point), []).append(
                {"book": book, "fair": p, "price": o["price"]})

    out = {}
    for k, entries in fair.items():
        if len(entries) < min_books:
            continue
        out[k] = {"consensus": statistics.median(e["fair"] for e in entries),
                  "n_books": len(entries), "entries": entries}
    return out


def screen(rows: list[dict], min_ev: float = 0.03,
           min_books: int = 3) -> list[dict]:
    """Books priced away from prop consensus. No projection involved."""
    cons = consensus(rows, min_books=min_books)
    hits = []
    for (gid, mkt, player, outcome, point), c in cons.items():
        for e in c["entries"]:
            ev = L.ev_at(e["price"], c["consensus"])
            if ev >= min_ev:
                hits.append({
                    "game_id": gid, "market": mkt, "player": player,
                    "outcome": outcome, "point": point, "book": e["book"],
                    "price": e["price"], "consensus_prob": c["consensus"],
                    "fair_price": round(L.prob_to_american(c["consensus"]), 1),
                    "ev": ev, "n_books": c["n_books"],
                    "flagged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                time.gmtime())})
    return sorted(hits, key=lambda h: -h["ev"])


# ---------------------------------------------------------------------------
# Grading — settle against real outcomes from play-by-play
# ---------------------------------------------------------------------------

def actuals(season: int, week: int) -> dict:
    """{(market, player): value} settled from nflverse play-by-play."""
    import pandas as pd
    import urllib.request as _u
    path = f"/tmp/pbp_{season}.parquet"
    if not os.path.exists(path):
        url = (f"https://github.com/nflverse/nflverse-data/releases/download/"
               f"pbp/play_by_play_{season}.parquet")
        req = _u.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with open(path, "wb") as f:
            f.write(_u.urlopen(req, timeout=300).read())
    df = pd.read_parquet(path)
    df = df[df["week"] == week]
    out = {}
    for market, (name_col, val_col, how) in GRADERS.items():
        if name_col not in df.columns or val_col not in df.columns:
            continue
        agg = df.dropna(subset=[name_col]).groupby(name_col)[val_col].agg(how)
        for player, v in agg.items():
            out[(market, player)] = float(v)
    # anytime TD: any rushing or receiving TD
    if {"rush_touchdown", "rusher_player_name"} <= set(df.columns):
        td = set()
        r = df[(df.get("rush_touchdown") == 1)]
        td |= set(r["rusher_player_name"].dropna())
        p = df[(df.get("pass_touchdown") == 1)]
        td |= set(p["receiver_player_name"].dropna())
        for player in td:
            out[("player_anytime_td", player)] = 1.0
    return out


def _match(name: str, actual_keys: set) -> str | None:
    """Odds API gives 'Josh Allen'; pbp gives 'J.Allen'. Bridge them."""
    if not name:
        return None
    parts = name.split()
    if len(parts) < 2:
        return None
    cand = f"{parts[0][0]}.{parts[-1]}"
    return cand if cand in actual_keys else None


def grade(season: int, week: int, hits_path: str | None = None) -> dict:
    """Settle flagged props at real captured prices. Bootstrap ROI CI.

    THIS IS THE SCOREBOARD, alongside CLV. It reports what the flagged prices
    actually returned — not what a projection thought they were worth.
    """
    hits_path = hits_path or PROP_HITS_PATH
    if not os.path.exists(hits_path):
        return {"error": f"no hits log at {hits_path}"}
    with open(hits_path) as f:
        hits = [json.loads(x) for x in f if x.strip()]
    act = actuals(season, week)
    names = {p for (_, p) in act}

    graded = []
    for h in hits:
        if h["market"] not in GRADERS and h["market"] != "player_anytime_td":
            continue
        key = _match(h.get("player"), names)
        if key is None:
            continue
        val = act.get((h["market"], key))
        if val is None:
            val = 0.0 if h["market"] == "player_anytime_td" else None
        if val is None:
            continue
        if h["market"] == "player_anytime_td":
            won = val >= 1.0 if h["outcome"].lower() == "yes" else val < 1.0
        else:
            pt = h.get("point")
            if pt is None:
                continue
            if val == pt:
                continue                      # push
            won = (val > pt) == (h["outcome"].lower() == "over")
        price = h["price"]
        payout = (100 / abs(price)) if price < 0 else (price / 100)
        graded.append({**h, "actual": val, "won": bool(won),
                       "pl": payout if won else -1.0})

    if not graded:
        return {"error": "no flagged props could be settled",
                "hits": len(hits), "actuals": len(act)}

    os.makedirs(os.path.dirname(GRADED_PATH), exist_ok=True)
    with open(GRADED_PATH, "a") as f:
        for g in graded:
            f.write(json.dumps(g) + "\n")

    pls = [g["pl"] for g in graded]
    n = len(pls)
    roi = sum(pls) / n
    import random
    rnd = random.Random(1)
    boots = sorted(sum(pls[rnd.randrange(n)] for _ in range(n)) / n
                   for _ in range(3000))
    lo, hi = boots[75], boots[2925]
    wins = sum(g["won"] for g in graded)
    return {"season": season, "week": week, "graded": n,
            "record": f"{wins}-{n-wins}", "win_rate": round(wins / n, 4),
            "roi": round(roi, 4), "roi_ci_95": [round(lo, 4), round(hi, 4)],
            "verdict": ("indistinguishable from luck — CI straddles zero"
                        if lo <= 0 <= hi else
                        "positive at 95%, but see the sample-size note"
                        if lo > 0 else "negative at 95%"),
            "note": (f"n={n}. Resolving a 2% ROI needs ~"
                     f"{__import__('nfl_model').bets_needed(0.02):,} bets. "
                     f"Do not read a weekly number as evidence.")}


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def selftest() -> int:
    fails = []

    def check(label, cond):
        if not cond:
            fails.append(label)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    print("credit budgeting:")
    check("16 events x 5 markets = 80", estimate_credits(16, DEFAULT_MARKETS) == 80)
    check("ceiling blocks an oversized sweep", estimate_credits(16, DEFAULT_MARKETS * 2)
          > MAX_CREDITS_PER_RUN)

    print("consensus must not pool different prop lines:")
    rows = []
    for bk, pt in [("a", 65.5), ("b", 65.5), ("c", 65.5),
                   ("d", 71.5), ("e", 71.5), ("f", 71.5)]:
        for side, price in (("Over", -110), ("Under", -110)):
            rows.append({"captured_at": "2026-01-01T00:00:00Z", "game_id": "g",
                         "commence_time": "", "home_team": "H", "away_team": "A",
                         "book": bk, "market": "player_reception_yds",
                         "player": "Some Receiver", "outcome": side,
                         "point": pt, "price": price})
    check("no phantom EV across 65.5 vs 71.5", len(screen(rows, min_ev=0.02)) == 0)

    print("screen still finds a genuine outlier at the same number:")
    rows2 = []
    for bk in ["a", "b", "c", "outlier"]:
        over = -110 if bk != "outlier" else 120
        under = -110 if bk != "outlier" else -140
        for side, price in (("Over", over), ("Under", under)):
            rows2.append({"captured_at": "2026-01-01T00:00:00Z", "game_id": "g",
                          "commence_time": "", "home_team": "H", "away_team": "A",
                          "book": bk, "market": "player_pass_yds",
                          "player": "Some QB", "outcome": side,
                          "point": 249.5, "price": price})
    h = screen(rows2, min_ev=0.02)
    check("outlier flagged", any(x["book"] == "outlier" for x in h))
    check("no non-outlier flagged", all(x["book"] == "outlier" for x in h))
    for x in h:
        print(f"        {x['book']} {x['player']} {x['outcome']} {x['point']} "
              f"{x['price']:+.0f} vs fair {x['fair_price']:+.0f} EV {x['ev']:+.2%}")

    print("event filter (the 187-vs-16 bug):")
    import time as _t
    soon = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(_t.time() + 3*86400))
    far  = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(_t.time() + 90*86400))
    fake = [{"id": "a", "commence_time": soon}, {"id": "b", "commence_time": far}]
    cutoff = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(_t.time() + 7*86400))
    kept = [e for e in fake if e["commence_time"] <= cutoff]
    check("7-day filter drops far-future games", len(kept) == 1)
    check("187 unfiltered would abort", estimate_credits(187, DEFAULT_MARKETS)
          > MAX_CREDITS_PER_RUN)
    check("16 filtered fits under ceiling", estimate_credits(16, DEFAULT_MARKETS)
          <= MAX_CREDITS_PER_RUN)

    print("name bridging (Odds API -> pbp):")
    check("'Josh Allen' -> 'J.Allen'", _match("Josh Allen", {"J.Allen"}) == "J.Allen")
    check("unknown player returns None", _match("Nobody Here", {"J.Allen"}) is None)

    print()
    if fails:
        print(f"{len(fails)} FAILED: {fails}")
        return 1
    print("all checks passed — no API credits spent")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["selftest", "budget", "capture", "screen", "grade"])
    ap.add_argument("--markets", nargs="+", default=DEFAULT_MARKETS)
    ap.add_argument("--regions", default="us")
    ap.add_argument("--max-events", type=int, default=None)
    ap.add_argument("--min-ev", type=float, default=0.03)
    ap.add_argument("--min-books", type=int, default=3)
    ap.add_argument("--log", action="store_true")
    ap.add_argument("--within-days", type=float, default=7.0,
                    help="only sweep games kicking off within N days (default 7). "
                         "The events endpoint returns the FULL SEASON; without "
                         "this every run costs ~935 credits.")
    ap.add_argument("--game-id", default=None,
                    help="sweep a single event id — cheapest possible run")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int, default=1)
    args = ap.parse_args()

    if args.cmd == "selftest":
        sys.exit(selftest())
    if args.cmd == "budget":
        ev = fetch_events(args.within_days)
        c = estimate_credits(len(ev), args.markets, args.regions)
        print(json.dumps({"events": len(ev), "markets": args.markets,
                          "credits_per_sweep": c,
                          "ceiling": MAX_CREDITS_PER_RUN,
                          "would_abort": c > MAX_CREDITS_PER_RUN}, indent=2))
        return
    if args.cmd == "capture":
        capture(args.markets, args.regions, args.max_events,
                within_days=args.within_days, game_id=args.game_id)
        return
    if args.cmd == "screen":
        rows = load()
        if not rows:
            raise SystemExit(f"no props at {PROPS_PATH} — run `capture` first")
        hits = screen(rows, min_ev=args.min_ev, min_books=args.min_books)
        if not hits:
            print("No props priced beyond the threshold. Normal result; not a "
                  "reason to lower the threshold.")
            return
        for h in hits:
            pt = "" if h["point"] is None else f" {h['point']}"
            print(f"{h['market']:22s} {str(h['player'])[:20]:20s} "
                  f"{h['outcome']:5s}{pt:>7s}  {h['book']:12s} "
                  f"{h['price']:+5.0f} vs fair {h['fair_price']:+6.1f}  "
                  f"EV {h['ev']:+.2%}  ({h['n_books']} books)")
        print("\nPAPER ONLY. Logged for grading, not authorized bets.")
        if args.log:
            os.makedirs("data", exist_ok=True)
            with open(PROP_HITS_PATH, "a") as f:
                for h in hits:
                    f.write(json.dumps(h) + "\n")
            print(f"logged {len(hits)} prop hits")
        return
    if args.cmd == "grade":
        print(json.dumps(grade(args.season, args.week), indent=2))


if __name__ == "__main__":
    main()
