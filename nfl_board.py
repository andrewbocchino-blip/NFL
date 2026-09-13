#!/usr/bin/env python3
"""nfl_board.py — publish docs/PICKS.md: top 15 DK/FanDuel bets, ranked.

DESIGN
  Fair value is computed from ALL books (11 on a typical NFL board) because a
  two-book consensus is not a consensus. But only DraftKings and FanDuel
  prices are ranked, because those are the books being bet. A price that is
  off-market at Bovada is useless if you cannot take it.

  Every row is EV against the no-vig consensus AT THE SAME NUMBER. It is a
  claim that DK or FD is priced away from where the market has it — not a
  prediction about who wins. The projection layer contributes nothing to this
  ranking: measured on 1,578 games its disagreements with the closing line
  regress at slope +0.007 (t=0.13) on spreads and -0.107 (t=-2.77) on totals.

Run:  python nfl_board.py --days 8 --top 15
"""

from __future__ import annotations

import argparse
import json
import os
import time

import nfl_lines as L

SNAP = "data/nfl_odds_snapshots.jsonl"
PROPS = "data/nfl_props_snapshots.jsonl"
OUT = "docs/PICKS.md"

BOOKS = {"draftkings": "DK", "fanduel": "FD"}

# Longshots are excluded from the ranking. On a true 2-3% shot the books price
# almost arbitrarily — +2500 against a +1100 median is a two-percentage-point
# disagreement that the EV formula inflates into triple digits. Measured
# 2026-09-12: adding anytime-TD filled all 15 slots with +34% to +117% rows,
# every one a deep longshot. Below this probability floor, price dispersion
# reflects rounding and house policy, not information.
MIN_CONSENSUS_PROB = 0.15

# One-way markets (anytime TD) have no opposite side, so vig cannot be
# stripped and their EV is not on the same scale as two-sided markets.
# They are ranked SEPARATELY rather than merged.
MAX_EV_SANITY = 0.25
MKT = {"spreads": "Spread", "totals": "Total", "h2h": "ML"}
STALE_HOURS = 36


def load(path):
    if not os.path.exists(path):
        return []
    return [json.loads(x) for x in open(path) if x.strip()]


def fmt(p):
    return f"{p:+.0f}" if p is not None else "—"


def build(days, top_n, min_ev):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cut = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + days * 86400))
    stale = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                          time.gmtime(time.time() - STALE_HOURS * 3600))

    rows = load(SNAP)
    # Upcoming only, and fresh only. A completed game's leftover quotes scatter
    # as books drop the market at different times; that wreckage reads as edge.
    live = [r for r in rows
            if now < (r.get("commence_time") or "") < cut
            and r["captured_at"] >= stale]
    games = {r["game_id"]: (r["away_team"], r["home_team"], r["commence_time"])
             for r in live}

    # ---- NEWS GUARD -------------------------------------------------------
    # The screen sees prices and nothing else. When a market is repricing on
    # news, the slow book looks generous right up until it moves against you —
    # you are the one being picked off, not the picker.
    # Measured 2026-09-12: ATL @ PIT went +3.5 -> +6.5 and ML +150 -> +240 in
    # 48h after Tua Tagovailoa was ruled out (Penix already out, Cooper Rush
    # starting). The screen ranked Falcons ML as the #1 play throughout.
    # This suppresses any game whose consensus has moved hard and recently.
    MOVE_PTS, MOVE_CENTS, WINDOW_H = 1.5, 30, 48
    horizon = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                            time.gmtime(time.time() - WINDOW_H * 3600))
    hist = {}
    for r in rows:
        if r["captured_at"] < horizon or r["game_id"] not in games:
            continue
        hist.setdefault((r["game_id"], r["market"], r["outcome"]), []).append(r)
    moving = {}
    for (gid, mkt, out), lst in hist.items():
        lst.sort(key=lambda x: x["captured_at"])
        if mkt == "spreads":
            pts = [x["point"] for x in lst if x.get("point") is not None]
            if len(pts) > 1 and abs(pts[-1] - pts[0]) >= MOVE_PTS:
                moving[gid] = max(moving.get(gid, 0), abs(pts[-1] - pts[0]))
        elif mkt == "h2h":
            pr = [x["price"] for x in lst if x.get("price")]
            if len(pr) > 1 and abs(pr[-1] - pr[0]) >= MOVE_CENTS:
                moving.setdefault(gid, 0.01)

    picks = []
    oneway_picks = []

    # ---- game lines -------------------------------------------------------
    cons = L.consensus(live, min_books=5)
    for (gid, mkt, outcome, point), c in cons.items():
        for e in c["entries"]:
            if e["book"] not in BOOKS:
                continue
            # No longshot floor here. Game lines are two-sided and de-vigged,
            # so a big underdog's probability is estimated reliably; excluding
            # them would drop legitimate value for no reason. The floor exists
            # for one-way markets, where it is doing real work.
            if gid in moving:
                continue
            ev = L.ev_at(e["price"], c["consensus"])
            if ev > MAX_EV_SANITY:
                continue
            picks.append({
                "ev": L.ev_at(e["price"], c["consensus"]),
                "game": gid, "kind": MKT.get(mkt, mkt),
                "bet": outcome + ("" if point is None else f" {point:+g}"),
                "book": BOOKS[e["book"]], "price": e["price"],
                "fair": L.prob_to_american(c["consensus"]),
                "nb": c["n_books"]})

    # ---- props ------------------------------------------------------------
    # Props get the SAME two filters as game lines. Omitting the staleness
    # bound was the identical mistake that produced the +22% NE/SEA rows:
    # 7,463 of 20,859 prop quotes were older than 36h and were being compared
    # against current ones as if both were live.
    prop_rows = [r for r in load(PROPS)
                 if now < (r.get("commence_time") or "") < cut
                 and r["captured_at"] >= stale]
    n_props = 0
    if prop_rows:
        import nfl_props as NP
        pc = NP.consensus(prop_rows, min_books=3)
        for (gid, mkt, player, side, point), c in pc.items():
            one_way = c.get("one_way", False)
            for e in c["entries"]:
                if e["book"] not in BOOKS or gid in moving:
                    continue
                # Floor applies to one-way markets only, for the reason above.
                if one_way and c["consensus"] < MIN_CONSENSUS_PROB:
                    continue
                ev = L.ev_at(e["price"], c["consensus"])
                if ev > MAX_EV_SANITY:
                    continue
                if one_way:
                    oneway_picks.append((ev, gid, mkt, player, side, point,
                                         e["book"], e["price"], c["consensus"],
                                         c["n_books"]))
                    continue
                n_props += 1
                lbl = mkt.replace("player_", "").replace("_", " ")
                picks.append({
                    "ev": L.ev_at(e["price"], c["consensus"]),
                    "game": gid, "kind": lbl,
                    "bet": f"{player} {side}" + ("" if point is None else f" {point:g}"),
                    "book": BOOKS[e["book"]], "price": e["price"],
                    "fair": L.prob_to_american(c["consensus"]),
                    "nb": c["n_books"]})

    picks.sort(key=lambda p: -p["ev"])
    best = picks[:top_n]

    # Every published pick is appended to a log with the price it was read at.
    # Without this the board makes claims that can never be scored, which is
    # the failure mode the whole project exists to avoid.
    os.makedirs("data", exist_ok=True)
    with open("data/nfl_board_picks.jsonl", "a") as _f:
        for _i, _p in enumerate(picks[:top_n], 1):
            _a, _h, _ct = games.get(_p["game"], ("?", "?", ""))
            _f.write(json.dumps({
                "published_at": now, "rank": _i, "game_id": _p["game"],
                "matchup": f"{_a} @ {_h}", "commence_time": _ct,
                "market": _p["kind"], "bet": _p["bet"], "book": _p["book"],
                "price": _p["price"], "fair": round(_p["fair"], 1),
                "ev": round(_p["ev"], 5)}) + "\n")

    o = [f"# NFL — Top {top_n} Bets (DraftKings & FanDuel)", "",
         f"Updated {now} · {len(games)} upcoming games · "
         f"{len(picks):,} DK/FD prices ranked", "",
         "**Paper only.** EV is measured against the no-vig consensus of all "
         "books at the same number — a claim that DK or FD is off-market, not "
         "a prediction of the result.", ""]

    if not best:
        o += ["_No DK or FD prices on the board right now._", ""]
    else:
        o += ["| # | Game | Bet | Type | Book | Price | Fair | EV |",
              "|---|---|---|---|---|---|---|---|"]
        for i, p in enumerate(best, 1):
            a, h, _ = games.get(p["game"], ("?", "?", ""))
            flag = " ✅" if p["ev"] >= min_ev else ""
            o.append(f"| {i} | {a} @ {h} | **{p['bet']}** | {p['kind']} "
                     f"| {p['book']} | **{fmt(p['price'])}** | {fmt(p['fair'])} "
                     f"| {p['ev']:+.2%}{flag} |")
        n_pos = sum(1 for p in best if p["ev"] >= min_ev)
        o += ["", f"✅ = clears +{min_ev:.0%} EV · {n_pos} of {len(best)} qualify",
              ""]

    # ---- what is being analyzed ------------------------------------------
    if prop_rows:
        import nfl_props as NP2
        from collections import Counter as _C
        cap = _C(x["market"] for x in prop_rows)
        pc2 = NP2.consensus(prop_rows, min_books=3)
        anal = _C(k[1] for k in pc2)
        o += ["", "### Prop markets analyzed", "",
              "| Market | Quotes captured | Comparable lines | Note |",
              "|---|---|---|---|"]
        for m in sorted(cap, key=lambda x: -cap[x]):
            n_an = anal.get(m, 0)
            if m in getattr(NP2, "ONE_WAY", set()):
                note = "one-way — benchmarked vs median posted price, vig included"
            elif "yds" in m:
                note = "fragments across numbers; many lines quoted by 1–2 books"
            else:
                note = "integer scale — books cluster on the same number"
            o.append(f"| {m.replace('player_','')} | {cap[m]:,} | {n_an} | {note} |")
        o += ["",
              "> A quote is only *comparable* when 3+ books post the same "
              "player at the same number. Yards markets fragment across "
              "65.5/67.5/70.5, so most of their quotes never get a peer to "
              "measure against — which is why integer markets dominate the "
              "ranking regardless of where value actually is.", ""]

    if oneway_picks:
        oneway_picks.sort(key=lambda x: -x[0])
        o += ["", "### Anytime TD — ranked separately", "",
              "One-way market: no opposite side exists, so vig cannot be "
              "stripped. The benchmark is the **median posted price** across "
              "books, which still contains each book's margin. EV here is not "
              "comparable to the table above and is systematically overstated.",
              "",
              "| Player | Game | Book | Price | Median | Gap |",
              "|---|---|---|---|---|---|"]
        for ev, gid, mkt, pl, side, pt, bk, pr, cp, nb in oneway_picks[:10]:
            a, h, _ = games.get(gid, ("?", "?", ""))
            o.append(f"| {pl} | {a} @ {h} | {BOOKS[bk]} | **{fmt(pr)}** "
                     f"| {fmt(L.prob_to_american(cp))} | {ev:+.1%} |")
        o += ["", f"> Filtered to shots with a consensus probability above "
              f"{MIN_CONSENSUS_PROB:.0%}. Below that, price dispersion between "
              f"books reflects rounding and house policy rather than "
              f"information.", ""]

    if moving:
        o += ["", "### Suppressed — market moving on news", "",
              "| Game | Consensus move (48h) |", "|---|---|"]
        for gid, mv in sorted(moving.items(), key=lambda kv: -kv[1]):
            a, h, _ = games.get(gid, ("?", "?", ""))
            o.append(f"| {a} @ {h} | "
                     f"{'%.1f pts' % mv if mv > 0.5 else 'moneyline >30c'} |")
        o += ["",
              "> Excluded from the ranking. A book that lags a repricing market "
              "looks generous until it moves against you. The screen reads "
              "prices only — it cannot see the news causing the move.", ""]

    if not prop_rows:
        o += ["> **No props on the board.** Run the `capture-props` workflow — "
              "`data/nfl_props_snapshots.jsonl` is empty.", ""]
    else:
        o += [f"> {n_props:,} DK/FD prop prices included in the ranking above.", ""]

    # ---- SPREADS: which number, and what the half point is worth ---------
    import nfl_model as MM

    def halfpt_value(k):
        """EV gain from crossing key number k, at -110. Push becomes win on
        the mass of games decided by exactly k."""
        return MM.KEY_NUMBERS.get(abs(int(k)), 0.0) * 0.909

    o += ["---", "", "## Spreads — the number matters more than the price", "",
          "Books scatter across numbers, so a spread board cannot be read on "
          "price alone. Crossing **3** converts a push into a win on the 14.8% "
          "of NFL games decided by exactly three points — worth about "
          "**13.5 cents**. Line shopping across every book on this slate is "
          "worth 2–15 cents *in total*. Near a key number, the number wins.", "",
          "| Cross | Mass | Worth |", "|---|---|---|"]
    for k in (3, 7, 6, 4, 2, 1):
        o.append(f"| {k} → {k}.5 | {MM.KEY_NUMBERS[k]:.1%} | "
                 f"**{halfpt_value(k)*100:.1f}¢** |")
    o += ["", "### DK vs FD — spread numbers side by side", "",
          "| Game | Side | DK | FD | Books split across | Key # |",
          "|---|---|---|---|---|---|"]
    sp = {}
    for r in live:
        if r["market"] != "spreads":
            continue
        sp.setdefault((r["game_id"], r["outcome"]), {})[r["book"]] = \
            (r.get("point"), r["price"])
    for (gid, side), d in sorted(sp.items(),
                                 key=lambda kv: games.get(kv[0][0], ("", "", "zz"))[2]):
        a, h, _ = games.get(gid, ("?", "?", ""))
        dk = d.get("draftkings")
        fd = d.get("fanduel")
        if not dk and not fd:
            continue
        nums = sorted({v[0] for v in d.values() if v[0] is not None})
        spread_txt = "/".join(f"{n:+g}" for n in nums) if nums else "—"
        # A straddle needs books on BOTH sides of the number. If every book
        # sits ON the key number there is no half point to buy — that is a
        # different fact and gets a different label.
        akeys = {abs(n) for n in nums}
        straddle = [k for k in (3, 7, 6)
                    if nums and min(akeys) < k < max(akeys)]
        on_key = [k for k in (3, 7, 6) if akeys == {float(k)}]
        if straddle:
            k = straddle[0]
            keytxt = f"⚠️ split across {k} — half pt worth {halfpt_value(k)*100:.0f}¢"
        elif on_key:
            keytxt = f"on {on_key[0]} ({MM.KEY_NUMBERS[on_key[0]]:.1%} land here)"
        else:
            keytxt = "—"
        o.append(f"| {a} @ {h} | {side} "
                 f"| {f'{dk[0]:+g} {fmt(dk[1])}' if dk else '—'} "
                 f"| {f'{fd[0]:+g} {fmt(fd[1])}' if fd else '—'} "
                 f"| {spread_txt} | {keytxt} |")
    o += ["", "> ⚠️ means the books disagree across a key number. Take the "
          "better NUMBER unless the price gap exceeds the value in the table "
          "above.", ""]

    # ---- TOTALS -----------------------------------------------------------
    o += ["## Totals — DK vs FD", "",
          "| Game | Side | DK | FD | Books split across |",
          "|---|---|---|---|---|"]
    tt = {}
    for r in live:
        if r["market"] != "totals":
            continue
        tt.setdefault((r["game_id"], r["outcome"]), {})[r["book"]] = \
            (r.get("point"), r["price"])
    for (gid, side), d in sorted(tt.items(),
                                 key=lambda kv: games.get(kv[0][0], ("", "", "zz"))[2]):
        a, h, _ = games.get(gid, ("?", "?", ""))
        dk, fd = d.get("draftkings"), d.get("fanduel")
        if not dk and not fd:
            continue
        nums = sorted({v[0] for v in d.values() if v[0] is not None})
        o.append(f"| {a} @ {h} | {side} "
                 f"| {f'{dk[0]:g} {fmt(dk[1])}' if dk else '—'} "
                 f"| {f'{fd[0]:g} {fmt(fd[1])}' if fd else '—'} "
                 f"| {'/'.join(f'{n:g}' for n in nums) if nums else '—'} |")
    o += ["",
          "> **Totals carry no projection signal here.** Backtested 2018-2025 "
          "(n=1,578): model RMSE 16.39 vs closing total 13.26, slope −0.107 "
          "(t = −2.77), and betting the model's disagreements went 693-792 "
          "(46.7%). The projection is anti-predictive on totals, so these rows "
          "are price and number only.", ""]

    # ---- full DK vs FD board ---------------------------------------------
    o += ["---", "", "## Every game — DK vs FD", "",
          "| Game | Market | Side | DK | FD | Fair |",
          "|---|---|---|---|---|---|"]
    seen = {}
    for (gid, mkt, outcome, point), c in cons.items():
        d = {BOOKS[e["book"]]: e["price"] for e in c["entries"]
             if e["book"] in BOOKS}
        if not d:
            continue
        seen[(gid, mkt, outcome, point)] = (d, c["consensus"])
    for (gid, mkt, outcome, point), (d, cp) in sorted(
            seen.items(), key=lambda kv: (games.get(kv[0][0], ("", "", "zz"))[2],
                                          kv[0][1], str(kv[0][2]))):
        a, h, _ = games.get(gid, ("?", "?", ""))
        pt = "" if point is None else f" {point:+g}"
        o.append(f"| {a} @ {h} | {MKT.get(mkt, mkt)} | {outcome}{pt} "
                 f"| {fmt(d.get('DK'))} | {fmt(d.get('FD'))} "
                 f"| {fmt(L.prob_to_american(cp))} |")
    o += ["", "_Fair = no-vig consensus across all books at that number._"]
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--min-ev", type=float, default=0.01)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    md = build(a.days, a.top, a.min_ev)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w").write(md)
    print(f"Wrote {a.out} ({len(md.splitlines())} lines)")


if __name__ == "__main__":
    main()
