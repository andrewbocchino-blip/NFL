#!/usr/bin/env python3
"""nfl_board.py — publish docs/PICKS.md, the NFL analogue of the MLB board.

FORMAT BORROWED FROM THE MLB REPO, INCLUDING ITS DISCIPLINE
  Boards force a call, lock the line they were read at, mark themselves
  paper-only, and carry a running calibration record that is allowed to say
  "this does not work." The MLB board's own record is the argument for the
  format: NRFI high-confidence sits at 110-106 while its coin-flip tier sits
  at 41-37, which is how you learn that the confidence tiers carry no
  information. A board that cannot embarrass itself is a tout sheet.

WHAT THIS BOARD PUBLISHES, AND WHY EACH SECTION EXISTS

  1. LINE SHOP — best price per game per market across books.
     The only section with demonstrated value. Requires no model. Taking
     -105 instead of -110 is worth roughly two cents a bet and is real
     whether or not any projection ever works.

  2. OFF-MARKET SCREEN — books priced away from no-vig consensus.
     A market-relative claim, not a prediction. Falsifiable on a short
     horizon via CLV. Paper only until the pre-registered bar is cleared.

  3. PROJECTION DIVERGENCE — model number vs market number.
     A CALIBRATION RECORD, NOT BETS. Published so the projection is held to
     account in public, exactly as the MLB prop-divergence board is.

WHAT IT DOES NOT PUBLISH
  A PLAY column. The MLB board emits PLAY verdicts because that model has a
  scoring layer behind it. The NFL projection's disagreements with the
  closing line regress at slope +0.007 (t = 0.13, n = 1,578) — statistically
  indistinguishable from zero — and its Week 1 variant at slope -0.046
  (t = -0.17, n = 111). Emitting PLAY off a zero-information signal would
  manufacture a track record out of noise. When a held-out season clears
  |t| > 2, the column gets added and this comment gets deleted.

Run:  python nfl_board.py --days 8
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from collections import defaultdict

import nfl_lines as L

SNAP = "data/nfl_odds_snapshots.jsonl"
OUT = "docs/PICKS.md"

# Demonstrated skill of each estimator, from nfl_backtest.py. Every board
# that uses a projection must print its stamp. No stamp, no board.
SKILL = {
    "spread_wk6plus": {"slope": 0.0067, "t": 0.13, "n": 1578,
                       "src": "nfl_backtest.py, 2018-2025 walk-forward"},
    "spread_wk1": {"slope": -0.0455, "t": -0.17, "n": 111,
                   "src": "prior-season ratings, 2019-2025 Week 1s"},
}

MARKET_LABEL = {"spreads": "Spread", "totals": "Total", "h2h": "Moneyline"}


def load(path=SNAP):
    if not os.path.exists(path):
        raise SystemExit(f"no snapshots at {path} — run nfl_lines.py snapshot")
    return [json.loads(x) for x in open(path) if x.strip()]


def latest(rows):
    """Most recent quote per book/market/outcome/point."""
    out = {}
    for r in rows:
        k = (r["game_id"], r["market"], r["book"], r["outcome"], r.get("point"))
        if k not in out or r["captured_at"] > out[k]["captured_at"]:
            out[k] = r
    return list(out.values())


def best_prices(rows):
    """Best available price per game/market/outcome/point, and the spread of
    prices across books at that same number."""
    grouped = defaultdict(list)
    for r in rows:
        grouped[(r["game_id"], r["market"], r["outcome"], r.get("point"))].append(r)
    out = {}
    for k, entries in grouped.items():
        if len(entries) < 2:
            continue
        srt = sorted(entries, key=lambda e: -L.ev_at(e["price"], 0.5))
        best, worst = srt[0], srt[-1]
        out[k] = {"best": best, "worst": worst, "n_books": len(entries),
                  "cents": (L.ev_at(best["price"], 0.5)
                            - L.ev_at(worst["price"], 0.5)) * 100}
    return out


def fmt_price(p):
    return f"{p:+.0f}" if p else "—"


def build(rows, days: int, min_books: int, min_ev: float):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() + days * 86400))
    live = [r for r in latest(rows) if (r.get("commence_time") or "") < cutoff]
    games = {}
    for r in live:
        games.setdefault(r["game_id"], (r["away_team"], r["home_team"],
                                        r.get("commence_time", "")))

    o = ["# NFL Board", "",
         f"Generated {now}. Prices locked as captured. **Paper only — nothing "
         f"here is an authorized bet.**", "",
         f"{len(games)} games · {len(set(r['book'] for r in live))} books · "
         f"snapshot rows {len(rows):,}", "",
         "> Ported from the MLB board format, including its discipline: boards "
         "lock the line they were read at, mark themselves paper-only, and "
         "carry a calibration record that is allowed to say the model does not "
         "work.", ""]

    # ---- 1. LINE SHOP -----------------------------------------------------
    o += ["## 1. Line shop — best price per game",
          "",
          "The only section here with demonstrated value, and it requires no "
          "model. `Spread` is the cents you give up by taking the worst posted "
          "price instead of the best, at the same number.",
          "",
          "| Game | Market | Side | Line | Best | Worst | Spread | Books |",
          "|---|---|---|---|---|---|---|---|"]
    bp = best_prices(live)
    ranked = sorted(bp.items(), key=lambda kv: -kv[1]["cents"])[:25]
    for (gid, mkt, outcome, point), v in ranked:
        away, home, _ = games.get(gid, ("?", "?", ""))
        b, w = v["best"], v["worst"]
        pt = "—" if point is None else f"{point:+g}"
        o.append(f"| {away} @ {home} | {MARKET_LABEL.get(mkt, mkt)} | {outcome} "
                 f"| {pt} | **{b['book']} {fmt_price(b['price'])}** "
                 f"| {w['book']} {fmt_price(w['price'])} "
                 f"| {v['cents']:.1f}¢ | {v['n_books']} |")
    o += ["",
          "> Sorted by price dispersion, not by opinion. A wide spread means "
          "the books disagree on price at an identical number — that is free "
          "money left on the table by betting the wrong book, and it is "
          "independent of whether any model works.", ""]

    # ---- 2. OFF-MARKET SCREEN --------------------------------------------
    hits = L.screen(live, min_ev=min_ev, min_books=min_books)
    o += ["## 2. Off-market screen — books away from consensus",
          "",
          "*Calibration record, NOT bets.* No projection is involved: the claim "
          "is only that one book disagrees with every other book at the same "
          "number. Graded by CLV, not by win-loss.",
          ""]
    if not hits:
        o += ["_No book priced beyond the threshold. This is a normal result "
              "and is not a reason to lower the threshold._", ""]
    else:
        o += ["| Game | Market | Side | Line | Book | Price | Fair | EV | Books |",
              "|---|---|---|---|---|---|---|---|---|"]
        for h in hits[:25]:
            away, home, _ = games.get(h["game_id"], ("?", "?", ""))
            pt = "—" if h.get("point") is None else f"{h['point']:+g}"
            o.append(f"| {away} @ {home} | {MARKET_LABEL.get(h['market'], h['market'])} "
                     f"| {h['outcome']} | {pt} | {h['book']} "
                     f"| **{fmt_price(h['price'])}** | {h['fair_price']:+.0f} "
                     f"| {h['ev']:+.2%} | {h['n_books']} |")
        o.append("")
    o += ["> Consensus is keyed on the exact number. Pooling a +3.0 quote with "
          "a +3.5 quote values the half point as if it were a mispriced book — "
          "on a line straddling 3, where 14.8% of NFL margins land, that "
          "invents several points of EV out of nothing. That bug shipped once "
          "here and produced a phantom +6.63%; there is now a regression test "
          "against it.", ""]

    # ---- 3. PROJECTION DIVERGENCE ----------------------------------------
    o += ["## 3. Projection divergence — model vs market",
          "",
          "*Calibration record, NOT bets.*",
          "",
          "> Divergence means our number disagrees with the market — it does "
          "**not** mean the market is wrong. The closing price already contains "
          "every sharp model working on this game; when we disagree, the more "
          "likely explanation is that our number is worse. Until this board "
          "beats its baseline, read a large divergence as a warning about our "
          "projection, not an opportunity.",
          ""]
    o += ["**Demonstrated skill of the estimator behind this board:**", "",
          "| Estimator | slope | t | n | source |", "|---|---|---|---|---|"]
    for k, s in SKILL.items():
        o.append(f"| `{k}` | {s['slope']:+.4f} | **{s['t']:+.2f}** | {s['n']:,} "
                 f"| {s['src']} |")
    o += ["",
          "> Both t-statistics are inside ±2. The projection's disagreements "
          "with the closing line carry no measurable information, so this "
          "board currently publishes no numbers. It exists so that the moment "
          "an estimator clears |t| > 2 on a held-out season, its divergences "
          "appear here already under a calibration record rather than as a "
          "fresh claim.",
          "",
          "_No projection rows: no estimator has cleared the bar in "
          "`README.md`._", ""]

    # ---- graduation -------------------------------------------------------
    o += ["## Graduation criteria (pre-registered)", "",
          "- **Screen → real money:** ≥800 graded prices with the beat-close "
          "rate 95% CI excluding 50%.",
          "- **Projection → published rows:** slope on `(result−line) ~ "
          "(proj−line)` with |t| > 2 on a season the parameters were never "
          "fitted on.",
          "- **An ATS record is never a reason.** 2022 alone read t = +2.04; "
          "2024 alone read t = −2.62. Both were noise around a pooled +0.13.",
          "",
          f"_Board generated by `nfl_board.py`. Detection limit at -110: "
          f"~{__import__('nfl_model').bets_needed(0.02):,} bets to resolve a 2% "
          f"ROI._"]
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--min-books", type=int, default=6)
    ap.add_argument("--min-ev", type=float, default=0.02)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    rows = load()
    md = build(rows, args.days, args.min_books, args.min_ev)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(md)
    print(f"Wrote {args.out} ({len(md.splitlines())} lines)")


if __name__ == "__main__":
    main()
