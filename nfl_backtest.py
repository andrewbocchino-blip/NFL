#!/usr/bin/env python3
"""nfl_backtest.py — measure the NFL model against real closing lines.

WHAT CHANGED FROM v1
  1. SIGN CONVENTION. v1 computed model edge as `proj + line`. nflverse
     spread_line is home-favoured-positive, so the edge is `proj - line`.
     Those expressions have opposite signs whenever |line| > |proj| — about
     half of all games — so v1's ATS record, correlation and band table were
     built on a partly inverted pick direction and are void.
  2. THE HEADLINE METRIC. v1 reported corr(edge, margin-vs-line). This
     reports the regression of (result - line) on (proj - line): slope,
     t-stat, R². The slope is interpretable — points the game moves the
     model's way per point of disagreement — and the t-stat is a real test.
  3. PER-SEASON STABILITY TABLE. A single NFL season swings far enough to
     read as significant in either direction by chance. 2022 alone shows
     t=+2.04; 2024 alone shows t=-2.62; pooled over 1,578 games the slope is
     +0.007. This table exists so that mistake cannot be made silently.
  4. DETECTION LIMITS on every ATS record.

Run:  python nfl_backtest.py --seasons 2018 2019 2020 2021 2022 2023 2024 2025
"""

from __future__ import annotations

import argparse
import math
import os
import random
import urllib.request

import nfl_model as M


def load_pbp(season: int):
    import pandas as pd
    path = f"/tmp/pbp_{season}.parquet"
    if not os.path.exists(path):
        url = M.PBP_URL.format(season=season)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with open(path, "wb") as f:
            f.write(urllib.request.urlopen(req, timeout=300).read())
    return pd.read_parquet(path)


def ols(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    alpha = my - beta * mx
    sse = sum((y - (alpha + beta * x)) ** 2 for x, y in zip(xs, ys))
    sst = sum((y - my) ** 2 for y in ys)
    se = math.sqrt(sse / (n - 2) / sxx)
    return {"slope": beta, "intercept": alpha, "t": beta / se if se else 0.0,
            "r2": 1 - sse / sst if sst else 0.0, "n": n}


def backtest_season(season, games_by_season, min_week=6, window=10,
                    prior=None, prior_weight=0.0):
    pbp = load_pbp(season)
    rows = []
    for wk in range(min_week, 23):
        ratings = M.team_epa_ratings(pbp, through_week=wk, window=window,
                                     prior=prior, prior_weight=prior_weight)
        if not ratings:
            continue
        for g in games_by_season.get(season, []):
            if str(g.get("week")) != str(wk):
                continue
            res, line = M._f(g.get("result")), M._f(g.get("spread_line"))
            if res is None or line is None:
                continue
            proj, _ = M.project_spread(ratings, g["away_team"], g["home_team"],
                                       M._f(g.get("home_rest")),
                                       M._f(g.get("away_rest")))
            if proj is None:
                continue
            tproj, _ = M.project_total(ratings, g["away_team"], g["home_team"],
                                       roof=g.get("roof"), wind=M._f(g.get("wind")))
            rows.append({"season": season, "week": wk, "proj": proj, "line": line,
                         "result": res, "tproj": tproj,
                         "tline": M._f(g.get("total_line")),
                         "total": M._f(g.get("total"))})
    end = M.team_epa_ratings(pbp, through_week=None, window=0)
    return rows, (end or prior)


def report(rows, out):
    if not rows:
        out.append("_No games scored._")
        return
    n = len(rows)
    m_rmse = math.sqrt(sum((r["result"] - r["proj"]) ** 2 for r in rows) / n)
    k_rmse = math.sqrt(sum((r["result"] - r["line"]) ** 2 for r in rows) / n)
    out += ["## Spread", "",
            f"- games scored (walk-forward, leak-free): **{n}**",
            f"- model RMSE: **{m_rmse:.2f}** points",
            f"- closing line RMSE: **{k_rmse:.2f}** points"]
    out += [f"- {'**model is more accurate than the market**' if m_rmse < k_rmse else f'market more accurate by **{m_rmse - k_rmse:.2f}** points'}", ""]

    xs = [r["proj"] - r["line"] for r in rows]
    ys = [r["result"] - r["line"] for r in rows]
    reg = ols(xs, ys)
    out += ["## (result − line) ~ (projection − line)  ← the number that matters", "",
            f"- slope = **{reg['slope']:+.4f}** (t = **{reg['t']:.2f}**)",
            f"- R² = **{reg['r2']:.5f}** · n = {reg['n']}",
            f"- mean |disagreement| = {sum(abs(x) for x in xs)/len(xs):.2f} pts", "",
            "> Read the slope as: per point the model disagrees with the closing "
            "line, the game lands this many points the model's way. Zero means the "
            "disagreement carries no information about which side covers. One would "
            "mean the model is right and the market wrong, point for point.", ""]
    if abs(reg["t"]) < 2:
        out += [f"> **t = {reg['t']:.2f} — not distinguishable from zero.** The size of "
                f"a disagreement predicts nothing measurable. No threshold, filter or "
                f"band will recover signal that is not present.", ""]
    elif reg["slope"] > 0:
        out += [f"> **t = {reg['t']:.2f}, slope positive.** Must still survive vig, an "
                f"out-of-sample window, and the sample-size arithmetic below.", ""]
    else:
        out += [f"> **t = {reg['t']:.2f}, slope NEGATIVE.** Anti-predictive. Check for "
                f"a sign error or broken input before reading this as a fade.", ""]

    seasons = sorted({r["season"] for r in rows})
    if len(seasons) > 1:
        out += ["### Per-season stability of that slope", "",
                "| Season | n | slope | t | model RMSE | line RMSE |",
                "|---|---|---|---|---|---|"]
        sig = []
        for s in seasons:
            sr = [r for r in rows if r["season"] == s]
            sreg = ols([r["proj"] - r["line"] for r in sr],
                       [r["result"] - r["line"] for r in sr])
            if not sreg:
                continue
            smr = math.sqrt(sum((r["result"] - r["proj"]) ** 2 for r in sr) / len(sr))
            skr = math.sqrt(sum((r["result"] - r["line"]) ** 2 for r in sr) / len(sr))
            flag = ""
            if abs(sreg["t"]) >= 2:
                flag, _ = " ⚠️", sig.append(s)
            out.append(f"| {s} | {len(sr)} | {sreg['slope']:+.3f} | "
                       f"{sreg['t']:+.2f}{flag} | {smr:.2f} | {skr:.2f} |")
        out.append("")
        if sig:
            out += [f"> ⚠️ Seasons {sig} clear |t| ≥ 2 individually while the pooled "
                    f"slope is {reg['slope']:+.4f} (t = {reg['t']:.2f}). A single NFL "
                    f"season is ~200 scored games and swings far enough to read as "
                    f"significant in EITHER direction by chance. Any conclusion drawn "
                    f"from one season — including a flattering one — is variance.", ""]

    w = l = p = 0
    for r in rows:
        edge = r["proj"] - r["line"]
        if abs(edge) < 0.5:
            continue
        if r["result"] == r["line"]:
            p += 1
            continue
        if (r["result"] > r["line"]) == (edge > 0):
            w += 1
        else:
            l += 1
    if w + l:
        rate = w / (w + l)
        roi = (0.909 * w - l) / (w + l)
        out += ["## ATS record", "",
                f"- betting every disagreement >0.5 pts: **{w}-{l}** ({rate:.1%}), "
                f"{p} push",
                f"- ROI at -110: **{roi:+.1%}** · break-even is 52.4%"]
        rnd = random.Random(1)
        pls = [0.909] * w + [-1.0] * l
        boots = sorted(sum(pls[rnd.randrange(len(pls))] for _ in range(len(pls)))
                       / len(pls) for _ in range(3000))
        lo_ci, hi_ci = boots[75], boots[2925]
        se = math.sqrt(0.524 * 0.476 / (w + l))
        out += [f"- ROI 95% CI: **{lo_ci:+.1%} to {hi_ci:+.1%}** "
                f"(z vs break-even = {(rate - 0.524) / se:.2f})", "",
                f"> **Detection limit.** This record rests on {w+l} bets. Resolving a "
                f"2% ROI — what a professional targets on NFL sides — needs "
                f"~{M.bets_needed(0.02):,} bets; a 5% ROI needs "
                f"~{M.bets_needed(0.05):,}. At this sample neither a winning nor a "
                f"losing record is informative. The regression slope above is the "
                f"better-powered test, and CLV is the only metric that can settle "
                f"this.", ""]
        if lo_ci <= 0 <= hi_ci:
            out += ["> The interval straddles zero: **indistinguishable from luck**, "
                    "however the headline reads.", ""]

    out += ["### By size of disagreement", "",
            "| Model edge vs line | n | ATS | Win% |", "|---|---|---|---|"]
    bands = []
    for lo, hi, lab in ((0.5, 3, "0.5-3"), (3, 6, "3-6"), (6, 10, "6-10"),
                        (10, 99, "10+")):
        sel = [r for r in rows if lo <= abs(r["proj"] - r["line"]) < hi
               and r["result"] != r["line"]]
        if not sel:
            continue
        ww = sum(1 for r in sel
                 if (r["result"] > r["line"]) == ((r["proj"] - r["line"]) > 0))
        out.append(f"| {lab} pts | {len(sel)} | {ww}-{len(sel)-ww} | {ww/len(sel):.1%} |")
        bands.append(ww / len(sel))
    out += ["", "> If the biggest disagreements do not win at the highest rate, the "
            "model is finding noise rather than mispricing.", ""]
    monotone = (all(bands[i] <= bands[i + 1] for i in range(len(bands) - 1))
                if len(bands) > 1 else False)
    if bands and not monotone:
        out += [f"> ⚠️ **Not monotonic** ({' → '.join(f'{b:.0%}' for b in bands)}). A "
                f"record that jumps around across bands is variance being sliced, not "
                f"edge being found — the pattern that makes a threshold sweep produce "
                f"a flattering number by accident.", ""]

    tr = [r for r in rows if r.get("tproj") is not None
          and r.get("tline") is not None and r.get("total") is not None]
    if tr:
        tm = math.sqrt(sum((r["total"] - r["tproj"]) ** 2 for r in tr) / len(tr))
        tk = math.sqrt(sum((r["total"] - r["tline"]) ** 2 for r in tr) / len(tr))
        out += ["## Totals", "",
                f"- games: **{len(tr)}** · model RMSE **{tm:.2f}** vs closing total "
                f"RMSE **{tk:.2f}**"]
        ow = ol = 0
        for r in tr:
            if r["total"] == r["tline"]:
                continue
            if (r["total"] > r["tline"]) == (r["tproj"] > r["tline"]):
                ow += 1
            else:
                ol += 1
        if ow + ol:
            out.append(f"- betting disagreements: **{ow}-{ol}** ({ow/(ow+ol):.1%})")
        treg = ols([r["tproj"] - r["tline"] for r in tr],
                   [r["total"] - r["tline"] for r in tr])
        if treg:
            out.append(f"- (total − line) ~ (proj − line): slope "
                       f"**{treg['slope']:+.4f}** (t = {treg['t']:.2f}), "
                       f"R² {treg['r2']:.5f}")
        out += ["", "> Read against NFL_BASELINES.md first. Betting every under went "
                "51.0% over 2016-25 and still lost money at -110.", ""]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, nargs="+",
                    default=[2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025])
    ap.add_argument("--window", type=int, default=10)
    ap.add_argument("--min-week", type=int, default=6)
    ap.add_argument("--prior-weight", type=float, default=0.0)
    args = ap.parse_args()

    games = M.fetch_games(min(args.seasons) - 1)
    rmse_check = M.assert_sign_convention(games)
    by_season = {}
    for g in games:
        try:
            by_season.setdefault(int(g["season"]), []).append(g)
        except (TypeError, ValueError):
            continue

    out = ["# NFL model backtest", "",
           "Walk-forward and leak-free: each week's projection uses only plays from "
           "PRIOR weeks, scored against the closing line that was actually posted.", "",
           f"Parameters: `{M.PARAM_FIT_WINDOW}` · HOME_FIELD {M.HOME_FIELD} · "
           f"EPA_TO_POINTS {M.EPA_TO_POINTS} · window {args.window}wk · "
           f"min_week {args.min_week} · prior-season weight {args.prior_weight}", "",
           f"Sign convention check passed: RMSE(result − spread_line) = "
           f"**{rmse_check:.2f}** (expected ~12.7; near 18 would mean spread_line had "
           f"flipped and every edge below was inverted).", "",
           f"**Coverage caveat:** min_week={args.min_week}, so weeks 1–"
           f"{args.min_week-1} are NOT tested here. The model cannot produce a Week 1 "
           f"projection at all without prior-season carry-forward — there are no prior "
           f"plays to rate teams on.", ""]

    all_rows, prior = [], None
    for s in sorted(args.seasons):
        try:
            rows, prior = backtest_season(s, by_season, min_week=args.min_week,
                                          window=args.window, prior=prior,
                                          prior_weight=args.prior_weight)
        except Exception as exc:
            out.append(f"_Season {s} failed: {exc}_")
            continue
        all_rows.extend(rows)
        print(f"[nfl_backtest] {s}: {len(rows)} games")
    report(all_rows, out)

    os.makedirs("docs", exist_ok=True)
    with open("docs/NFL_BACKTEST.md", "w") as f:
        f.write("\n".join(out))
    print("Wrote docs/NFL_BACKTEST.md")


if __name__ == "__main__":
    main()
