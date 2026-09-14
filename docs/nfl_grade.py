#!/usr/bin/env python3
"""nfl_grade.py — score every published pick against what actually happened.

WHY THIS FILE EXISTS
  The board publishes a ranked top 15 every capture. Until this ran, nothing
  ever checked whether those picks won. A board that makes claims it never
  scores is a tout sheet, and the graduation criteria in README.md were
  unmeasurable because the measurement did not exist.

  Two independent scoreboards, because they answer different questions:

  CLV  — did the price beat its own close? Converges in hundreds of bets and
         is the only feasible validation at NFL sample sizes (resolving a 2%
         ROI from results needs ~17,700 bets).
  ROI  — did the pick win? Honest, but underpowered for years. Reported with
         a bootstrap CI so a hot week cannot be mistaken for evidence.

SETTLEMENT
  Game lines settle from nflverse games.csv (result, total, spread_line).
  Props settle from play-by-play via nfl_props.actuals(). No new dependency.

Run:  python nfl_grade.py --season 2026 --week 1
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics

import nfl_lines as L
import nfl_model as M

PICKS = "data/nfl_board_picks.jsonl"
SNAP = "data/nfl_odds_snapshots.jsonl"
OUT = "data/nfl_graded.jsonl"
REPORT = "docs/GRADED.md"


def load(p):
    return [json.loads(x) for x in open(p) if x.strip()] if os.path.exists(p) else []


def boot_ci(pls, iters=3000, seed=1):
    if not pls:
        return None
    n = len(pls)
    rnd = random.Random(seed)
    b = sorted(sum(pls[rnd.randrange(n)] for _ in range(n)) / n for _ in range(iters))
    return b[int(iters * .025)], b[int(iters * .975) - 1]


def closing_consensus(rows):
    """Last captured no-vig consensus per game/market/outcome/point."""
    return L.consensus(rows, min_books=3)


def grade_clv(picks, snap):
    """Did the published price beat where the market closed?

    A pick beats the close when the price taken implied a LOWER probability
    than the market ultimately settled on for that same outcome.
    """
    close = closing_consensus(snap)
    # index by (matchup, market, bet-ish) is unreliable; match on game_id +
    # the raw outcome text the board printed.
    idx = {}
    for (gid, mkt, out, pt), c in close.items():
        idx[(gid, out + ("" if pt is None else f" {pt:+g}"))] = c
    beat = n = 0
    deltas = []
    for p in picks:
        c = idx.get((p["game_id"], p["bet"]))
        if not c:
            continue
        try:
            taken = L.american_to_prob(p["price"])
        except (ValueError, TypeError):
            continue
        n += 1
        d = c["consensus"] - taken
        deltas.append(d)
        beat += d > 0
    if not n:
        return {"graded": 0, "note": "no published pick matched a closing consensus"}
    rate = beat / n
    se = math.sqrt(0.25 / n)
    return {"graded": n, "beat_close": beat, "beat_rate": round(rate, 4),
            "mean_clv_pts": round(statistics.mean(deltas) * 100, 3),
            "z_vs_50": round((rate - .5) / se, 2) if se else 0.0,
            "verdict": ("no demonstrated CLV — a valueless screen sits at 50%"
                        if abs(rate - .5) < 2 * se
                        else "beats the close" if rate > .5
                        else "LOSES to the close")}


# Odds API sends full team names; nflverse uses codes. This map is the only
# thing that stood between the picks log and a real win/loss record.
TEAM = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


def payout(price):
    return (100 / abs(price)) if price < 0 else (price / 100)


def grade_results(picks, season):
    """Did the published pick actually win? Game lines, settled from games.csv.

    A pick is only counted ONCE — the first time it was published. Republishing
    the same bet every three hours would otherwise inflate a single call into
    dozens of graded rows and make any record meaningless.
    """
    idx = {}
    for g in M.fetch_games(season):
        idx[(g.get("away_team"), g.get("home_team"))] = g

    firsts = {}
    for p in sorted(picks, key=lambda x: x["published_at"]):
        if p["market"] not in ("ML", "Spread", "Total"):
            continue
        key = (p["game_id"], p["market"], p["bet"], p["book"])
        firsts.setdefault(key, p)

    graded = []
    for p in firsts.values():
        try:
            away, home = [t.strip() for t in p["matchup"].split("@")]
        except ValueError:
            continue
        g = idx.get((TEAM.get(away, away), TEAM.get(home, home)))
        if not g:
            continue
        res, tot = M._f(g.get("result")), M._f(g.get("total"))
        if res is None:
            continue                      # not played yet
        bet, won = p["bet"], None
        tokens = bet.rsplit(" ", 1)
        num = None
        if len(tokens) == 2:
            try:
                num = float(tokens[1])
            except ValueError:
                num = None

        if p["market"] == "ML":
            picked_home = TEAM.get(bet, bet) == TEAM.get(home, home)
            if res == 0:
                continue                  # tie, void
            won = (res > 0) == picked_home
        elif p["market"] == "Spread" and num is not None:
            side = tokens[0]
            picked_home = TEAM.get(side, side) == TEAM.get(home, home)
            # nflverse spread_line is home-favoured-positive
            line_home = num if picked_home else -num
            if res == line_home:
                continue                  # push
            won = (res > line_home) == picked_home
        elif p["market"] == "Total" and num is not None and tot is not None:
            if tot == num:
                continue
            won = (tot > num) == bet.lower().startswith("over")
        if won is None:
            continue
        graded.append({**p, "result": res, "total": tot, "won": bool(won),
                       "pl": payout(p["price"]) if won else -1.0})

    if not graded:
        return {"graded": 0, "note": "no published game-line pick has settled yet"}

    pls = [g["pl"] for g in graded]
    n, wins = len(pls), sum(g["won"] for g in graded)
    ci = boot_ci(pls)
    return {"graded": n, "record": f"{wins}-{n-wins}",
            "win_rate": round(wins / n, 4), "roi": round(sum(pls) / n, 4),
            "roi_ci_95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
            "verdict": ("indistinguishable from luck — CI straddles zero"
                        if ci and ci[0] <= 0 <= ci[1]
                        else "positive at 95%" if ci and ci[0] > 0
                        else "negative at 95%"),
            "rows": graded}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int, default=None)
    a = ap.parse_args()

    picks, snap = load(PICKS), load(SNAP)
    if not picks:
        print("no published picks yet — run nfl_board.py first")
        return

    clv = grade_clv(picks, snap)
    res = grade_results(picks, a.season)
    rows = res.pop("rows", [])

    uniq = len({(p["game_id"], p["market"], p["bet"], p["book"]) for p in picks})
    out = ["# Results", "",
           f"Every pick `nfl_board.py` has published, scored against what "
           f"happened. Rows are counted **once**, at first publication — the "
           f"board republishes every capture, and grading each repeat would "
           f"turn one call into dozens.", "",
           f"Pick rows logged: **{len(picks):,}** · unique bets: **{uniq:,}** · "
           f"snapshot rows {len(snap):,}", "",
           "## Win / loss — settled game lines", "",
           "```json", json.dumps(res, indent=2), "```", ""]
    if rows:
        out += ["| Published | Game | Bet | Book | Price | Result | W/L | P/L |",
                "|---|---|---|---|---|---|---|---|"]
        for g in sorted(rows, key=lambda x: x["published_at"]):
            out.append(f"| {g['published_at'][:10]} | {g['matchup']} "
                       f"| {g['bet']} | {g['book']} | {g['price']:+.0f} "
                       f"| {g['result']:+.0f} "
                       f"| {'**W**' if g['won'] else 'L'} | {g['pl']:+.2f} |")
        out.append("")
    out += ["> A winning week is not evidence. Resolving a 2% ROI needs "
            f"~{M.bets_needed(0.02):,} bets; anything under a few hundred is "
            "noise whichever way it lands.", "",
           "## CLV — did published prices beat their close?", "",
           "```json", json.dumps(clv, indent=2), "```", "",
           "> CLV is the primary scoreboard. Resolving a 2% ROI from win/loss "
           f"needs ~{M.bets_needed(0.02):,} bets; CLV converges in hundreds.", ""]

    try:
        import nfl_props as NP
        if a.week:
            pg = NP.grade(a.season, a.week)
            out += ["## Props — settled against play-by-play", "",
                    "```json", json.dumps(pg, indent=2), "```", ""]
    except Exception as exc:
        out += [f"_prop grading unavailable: {type(exc).__name__}: {exc}_", ""]

    out += ["## Graduation criteria (pre-registered)", "",
            "- **Screen → real money:** ≥800 graded prices with the beat-close "
            "rate 95% CI excluding 50%.",
            "- **Projection → published rows:** |t| > 2 on `(result−line) ~ "
            "(proj−line)` for a season the parameters were never fitted on. "
            "Current: spreads +0.007 (t=0.13, n=1,578), totals −0.107 "
            "(t=−2.77), Week-1 −0.046 (t=−0.17).",
            "- **A winning week is never a reason.**", ""]

    os.makedirs("docs", exist_ok=True)
    open(REPORT, "w").write("\n".join(out))
    print(json.dumps(clv, indent=2))
    print(f"Wrote {REPORT}")


if __name__ == "__main__":
    main()
