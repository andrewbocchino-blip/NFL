#!/usr/bin/env python3
"""nfl_baselines.py — what you get with no model at all.

Every model result has to be read against this. A strategy that requires no
information, no ratings and no projection sets the floor; anything the model
produces that does not clearly clear this floor is not a finding.

It also settles some folklore against the data rather than against a
podcast: home dogs, unders, road teams. And it prints the era drift in the
key numbers and in home-field advantage, which is where the model's
constants come from.

Writes docs/NFL_BASELINES.md.

Run:  python nfl_baselines.py --min-season 2016
"""

from __future__ import annotations

import argparse
import os
import random
import statistics
from collections import Counter

import nfl_model as M

ERAS = [(2000, 2009), (2010, 2017), (2018, 2025)]


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def boot_ci(wins: int, losses: int, iters: int = 3000, seed: int = 1):
    """Bootstrap ROI CI at -110. Returns (win_rate, roi, lo, hi, n)."""
    n = wins + losses
    if n == 0:
        return None
    pls = [0.909] * wins + [-1.0] * losses
    rnd = random.Random(seed)
    boots = sorted(sum(pls[rnd.randrange(n)] for _ in range(n)) / n
                   for _ in range(iters))
    return wins / n, sum(pls) / n, boots[int(iters * 0.025)], \
        boots[int(iters * 0.975) - 1], n


def grade(games, decide):
    """decide(g) -> True (win), False (loss), None (skip/push)."""
    w = l = 0
    for g in games:
        d = decide(g)
        if d is None:
            continue
        w += d
        l += not d
    return w, l


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-season", type=int, default=2016)
    args = ap.parse_args()

    allg = M.fetch_games(1999)
    M.assert_sign_convention(allg)
    g = [r for r in allg
         if (_i(r.get("season")) or 0) >= args.min_season
         and M._f(r.get("result")) is not None]

    out = ["# NFL naive baselines", "",
           "Everything below requires no model, no ratings and no projection. It is "
           "the floor. Any model result that does not clearly clear this floor is not "
           "a finding.", "",
           f"Sample: {args.min_season}-2025, {len(g)} games with results. All records "
           f"exclude pushes; ROI is at -110; CIs are 3,000-sample bootstraps.", ""]

    def ats(g_, want_home):
        res, sp = M._f(g_.get("result")), M._f(g_.get("spread_line"))
        if res is None or sp is None or res == sp:
            return None
        return (res > sp) == want_home

    def dog(g_, home_only=False):
        res, sp = M._f(g_.get("result")), M._f(g_.get("spread_line"))
        if res is None or sp is None or res == sp or sp == 0:
            return None
        if home_only and sp >= 0:
            return None
        return (res > sp) == (sp < 0)

    def tot(g_, want_under):
        t, tl = M._f(g_.get("total")), M._f(g_.get("total_line"))
        if t is None or tl is None or t == tl:
            return None
        return (t < tl) == want_under

    tests = [
        ("Bet every UNDER", lambda x: tot(x, True)),
        ("Bet every OVER", lambda x: tot(x, False)),
        ("Bet every HOME ATS", lambda x: ats(x, True)),
        ("Bet every AWAY ATS", lambda x: ats(x, False)),
        ("Bet every UNDERDOG ATS", lambda x: dog(x)),
        ("Bet every HOME DOG ATS", lambda x: dog(x, home_only=True)),
        ("Bet every FAVOURITE ATS", lambda x: (None if dog(x) is None else not dog(x))),
    ]
    out += ["## Side and total baselines", "",
            "| Strategy | Record | Win% | ROI | 95% CI | n |",
            "|---|---|---|---|---|---|"]
    for label, fn in tests:
        w, l = grade(g, fn)
        r = boot_ci(w, l)
        if not r:
            continue
        wr, roi, lo, hi, n = r
        out.append(f"| {label} | {w}-{l} | {wr:.1%} | {roi:+.1%} | "
                   f"{lo:+.1%} to {hi:+.1%} | {n} |")
    out += ["",
            "> Every one loses at -110. Note in particular that betting every under "
            "goes above 50% and still loses money — a win rate over 50% is not an "
            "edge, it is what the vig is for. Any headline ATS record from the model "
            "must be read against this column, not against 50%.", ""]

    base = M.market_baseline_check(g)
    out += ["## The closing line itself", "",
            f"- games: **{base['games']}**",
            f"- closing-spread RMSE: **{base['rmse']:.2f}** points",
            f"- home cover rate: **{base['home_cover_rate']:.1%}** · "
            f"push rate {base['push_rate']:.1%}", "",
            "> This is the accuracy the projection has to beat to have any claim on "
            "sides at close. It is also, separately, why the market's own record sits "
            "near 50% — the line is set to split the action, not to predict.", ""]

    fav_w = fav_n = 0
    for r in g:
        sp, res = M._f(r.get("spread_line")), M._f(r.get("result"))
        if sp is None or res is None or sp == 0 or res == 0:
            continue
        fav_n += 1
        fav_w += (res > 0) == (sp > 0)
    if fav_n:
        out += ["## Moneyline base rate", "",
                f"- favourites win **{fav_w/fav_n:.1%}** of games "
                f"(n={fav_n}, ties and pick'em excluded)", "",
                f"> Public NFL models advertising ~64% moneyline accuracy are "
                f"reporting this number. It requires no model. Any moneyline claim "
                f"must be scored against **{fav_w/fav_n:.1%}**, never against 50%.", ""]

    out += ["## Key-number drift", "",
            "| Era | n | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 10 | 14 |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for lo, hi in ERAS:
        m = [abs(M._f(r["result"])) for r in allg
             if lo <= (_i(r.get("season")) or 0) <= hi
             and M._f(r.get("result")) is not None]
        if not m:
            continue
        c, n = Counter(m), len(m)
        cells = " | ".join(f"{c[k]/n:.1%}" for k in (1, 2, 3, 4, 5, 6, 7, 10, 14))
        out.append(f"| {lo}-{hi} | {n} | {cells} |")
    out += ["",
            "> Three is stable and dominant. **Seven has declined** (9.5% -> 8.5%) and "
            "**six has risen** (5.1% -> 6.6%); one and two are up roughly a third, "
            "consistent with the rise in two-point attempts. `KEY_NUMBERS` in "
            "nfl_model.py is fitted to the 2018-2025 row, not the full history — an "
            "all-era table misprices exactly the numbers that matter most.", ""]

    out += ["## Home-field drift", "",
            "| Era | n | mean home margin | mean spread_line | gap |",
            "|---|---|---|---|---|"]
    for lo, hi in ERAS + [(2021, 2025)]:
        sel = [r for r in allg
               if lo <= (_i(r.get("season")) or 0) <= hi
               and M._f(r.get("result")) is not None
               and M._f(r.get("spread_line")) is not None]
        if not sel:
            continue
        mr = statistics.mean([M._f(r["result"]) for r in sel])
        ms = statistics.mean([M._f(r["spread_line"]) for r in sel])
        out.append(f"| {lo}-{hi} | {len(sel)} | {mr:+.2f} | {ms:+.2f} | {mr-ms:+.2f} |")
    out += ["",
            "> HFA fell from ~2.6 points (2000-09) to ~1.7 (2018-25), and the market "
            "tracked it almost exactly. `HOME_FIELD = 1.68` is the fitted intercept, "
            "not an assertion; a stale 3 would be a systematic error on every game.",
            "",
            "> **A trap worth naming.** The 2021-2025 row shows mean margin running "
            "above mean spread, which looks like a half-point HFA mispricing. It is "
            "not: t is about 1.6, and betting every home team ATS loses in the table "
            "above. A gap in means is not an edge.", ""]

    out += ["## Detection limits at -110", "",
            "| True ROI | Bets needed (80% power) | NFL seasons betting half the card |",
            "|---|---|---|"]
    for roi in (0.02, 0.03, 0.05, 0.10):
        n = M.bets_needed(roi)
        out.append(f"| {roi:.0%} | ~{n:,} | ~{n/135:,.0f} |")
    out += ["",
            "> A professional targets ~2% ROI on NFL sides. That is ~17,700 bets to "
            "resolve — roughly 130 seasons. **Results-based validation of an NFL sides "
            "edge is not achievable in a human lifetime.** This is not a criticism of "
            "any particular backtest; it is a structural fact about the sport, and it "
            "is why CLV is not the preferred validation metric here but the only "
            "feasible one.", ""]

    os.makedirs("docs", exist_ok=True)
    with open("docs/NFL_BASELINES.md", "w") as f:
        f.write("\n".join(out))
    print("Wrote docs/NFL_BASELINES.md")


if __name__ == "__main__":
    main()
