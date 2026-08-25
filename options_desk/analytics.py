#!/usr/bin/env python3
"""
analytics.py  --  Derived reads for the dashboard: expected move, max pain, PCR, OI walls,
the IV smile, and a transparent long/short bias score. stdlib only.

Everything here is descriptive. None of it is predictive, and the bias score least of all --
it is a weighted sum of things you could read off the screen yourself, shown with its
components visible precisely so it can be argued with rather than obeyed.
"""

import math

from .history import nearest_delta


# --- option-chain reads -------------------------------------------------------------

def expected_move(snap, expiry=None):
    """
    How far the market is pricing this underlying to move by expiry.

    Two independent estimates, because they disagree in useful ways:
      * `straddle`  -- the ATM call + put premium. What it actually costs to own the move.
      * `sigma`     -- spot * ATM_IV * sqrt(T). The model's 1-standard-deviation move.

    A straddle much richer than the sigma estimate is the market paying up for an event
    (earnings, a policy decision) that plain vol does not capture.
    """
    from . import greeks as bs
    from .models import expiry_utc

    exp = expiry or snap.nearest_expiry()
    if exp is None:
        return None
    k = snap.atm_strike(exp)
    if k is None:
        return None
    call, put = snap.get(exp, k, "C"), snap.get(exp, k, "P")
    if not call or not put or call.mid is None or put.mid is None:
        return None

    straddle = call.mid + put.mid
    t = bs.year_fraction(snap.ts, expiry_utc(exp))
    iv = snap.atm_iv(exp)
    sigma_move = (snap.spot * iv * math.sqrt(t)) if (iv and t > 0) else None

    return {
        "expiry": exp.isoformat(),
        "dte": (exp - snap.ts.date()).days,
        "atm_strike": k,
        "straddle": straddle,
        "straddle_pct": straddle / snap.spot if snap.spot else None,
        "sigma": sigma_move,
        "sigma_pct": (sigma_move / snap.spot) if (sigma_move and snap.spot) else None,
        "low": snap.spot - sigma_move if sigma_move else None,
        "high": snap.spot + sigma_move if sigma_move else None,
    }


def max_pain(snap, expiry=None):
    """
    The strike at which the total intrinsic value of all open contracts is smallest --
    i.e. where option buyers collectively lose the most.

    Widely watched as a pin candidate into expiry. Treat it as one crowded reference point,
    not a forecast: the correlation with where price actually settles is weak outside the
    last day or two, and it moves as open interest changes.
    """
    exp = expiry or snap.nearest_expiry()
    if exp is None:
        return None
    quotes = [q for q in snap.by_expiry(exp) if (q.open_interest or 0) > 0]
    if not quotes:
        return None

    strikes = sorted({q.contract.strike for q in quotes})
    calls = {k: 0 for k in strikes}
    puts = {k: 0 for k in strikes}
    for q in quotes:
        (calls if q.contract.right == "C" else puts)[q.contract.strike] += q.open_interest or 0

    best, best_loss, curve = None, None, []
    for settle in strikes:
        loss = sum(oi * max(0.0, settle - k) for k, oi in calls.items())
        loss += sum(oi * max(0.0, k - settle) for k, oi in puts.items())
        curve.append({"strike": settle, "loss": loss})
        if best_loss is None or loss < best_loss:
            best, best_loss = settle, loss

    return {"expiry": exp.isoformat(), "strike": best, "loss": best_loss,
            "distance_pct": ((best - snap.spot) / snap.spot) if snap.spot else None,
            "curve": curve}


def put_call_ratio(snap, expiry=None):
    """
    Put/call ratio on open interest and on volume.

    OI PCR is positioning that has built up; volume PCR is what traded today. They diverge
    when a crowded book starts being unwound, which is the part worth noticing.
    """
    exp = expiry or snap.nearest_expiry()
    if exp is None:
        return None
    c_oi = p_oi = c_vol = p_vol = 0
    for q in snap.by_expiry(exp):
        is_put = q.contract.right == "P"
        if is_put:
            p_oi += q.open_interest or 0
            p_vol += q.volume or 0
        else:
            c_oi += q.open_interest or 0
            c_vol += q.volume or 0
    return {
        "expiry": exp.isoformat(),
        "oi": (p_oi / c_oi) if c_oi else None,
        "volume": (p_vol / c_vol) if c_vol else None,
        "call_oi": c_oi, "put_oi": p_oi, "call_volume": c_vol, "put_volume": p_vol,
    }


def oi_walls(snap, expiry=None, top=3):
    """
    Strikes carrying the most call and put open interest.

    These act as reference points the same way a pivot does -- a large written call strike is
    somewhere dealers have reason to defend. Reported alongside the pivots so both show up in
    the same ladder rather than in two mental models.
    """
    exp = expiry or snap.nearest_expiry()
    if exp is None:
        return None
    calls, puts = {}, {}
    for q in snap.by_expiry(exp):
        if not q.open_interest:
            continue
        (calls if q.contract.right == "C" else puts)[q.contract.strike] = q.open_interest
    top_c = sorted(calls.items(), key=lambda kv: -kv[1])[:top]
    top_p = sorted(puts.items(), key=lambda kv: -kv[1])[:top]
    return {
        "expiry": exp.isoformat(),
        "call_walls": [{"strike": k, "oi": v} for k, v in top_c],
        "put_walls": [{"strike": k, "oi": v} for k, v in top_p],
        "resistance": top_c[0][0] if top_c else None,
        "support": top_p[0][0] if top_p else None,
    }


def iv_smile(snap, expiry=None):
    """Per-strike call/put IV and open interest -- the smile chart and the OI histogram."""
    exp = expiry or snap.nearest_expiry()
    if exp is None:
        return []
    rows = []
    for k in snap.strikes(exp):
        c, p = snap.get(exp, k, "C"), snap.get(exp, k, "P")
        rows.append({
            "strike": k,
            "call_iv": c.iv if c else None, "put_iv": p.iv if p else None,
            "call_oi": (c.open_interest if c else None) or 0,
            "put_oi": (p.open_interest if p else None) or 0,
            "call_volume": (c.volume if c else None) or 0,
            "put_volume": (p.volume if p else None) or 0,
        })
    return rows


def chain_analytics(snap, expiry=None):
    """Everything the dashboard needs from one option chain."""
    exp = expiry or snap.nearest_expiry()
    return {
        "expiry": exp.isoformat() if exp else None,
        "expiries": [e.isoformat() for e in snap.expiries()],
        "atm_iv": snap.atm_iv(exp),
        "expected_move": expected_move(snap, exp),
        "max_pain": max_pain(snap, exp),
        "pcr": put_call_ratio(snap, exp),
        "walls": oi_walls(snap, exp),
        "smile": iv_smile(snap, exp),
    }


# --- long / short bias --------------------------------------------------------------

def _clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def bias(bar_snap=None, chain_snap=None, hist=None):
    """
    A transparent long/short read.

    Each component scores in [-1, +1] and carries a weight; the total is their weighted mean.
    The components are returned so the number can be interrogated -- if the score says LONG
    only because PCR is elevated, that is visible rather than buried.

    THIS IS NOT A TRADE SIGNAL. It is a summary of readings already on the screen, weighted by
    hand. It has no edge of its own, is not backtested as a strategy, and ignores spread,
    slippage, position size and risk entirely.
    """
    comps = []

    if bar_snap is not None and bar_snap.levels is not None:
        pos = bar_snap.cpr_position
        comps.append(_c("CPR position", {"above": 1.0, "inside": 0.0, "below": -1.0}.get(pos, 0.0),
                        2.0, f"price is {pos} the central pivot range"))

        vwap = bar_snap.vwap_value
        if vwap:
            side = 1.0 if bar_snap.price > vwap else -1.0
            comps.append(_c("VWAP side", side, 2.0,
                            f"price {'above' if side > 0 else 'below'} session VWAP {vwap:.2f}"))

        z = bar_snap.vwap_z
        if z is not None:
            # Stretch is a COUNTER-signal: distance from the anchor is where reversion lives.
            # Stretched ABOVE VWAP therefore tilts bearish, and vice versa -- it damps the
            # "price is above VWAP" component rather than compounding it.
            if abs(z) > 1.5:
                magnitude = _clip((abs(z) - 1.5) / 1.5, 0.0, 1.0)   # 0 at 1.5σ, 1 at 3σ
                stretch = -magnitude if z > 0 else magnitude
                note = f"{z:+.2f}σ from VWAP -- extended, reversion risk"
            else:
                stretch, note = 0.0, f"{z:+.2f}σ from VWAP"
            comps.append(_c("VWAP stretch", stretch, 1.0, note))

        prev_close = bar_snap.levels.prev_close
        if prev_close:
            chg = (bar_snap.price - prev_close) / prev_close
            comps.append(_c("vs prev close", _clip(chg / 0.01), 1.0,
                            f"{chg*100:+.2f}% vs previous close"))

        w = bar_snap.levels.width_pct
        if w is not None:
            # Narrow CPR does not pick a side; it says whichever side breaks should run. So it
            # amplifies nothing on its own and is reported at zero with a note.
            comps.append(_c("CPR width", 0.0, 0.0,
                            f"{w*100:.3f}% -- "
                            + ("narrow, trending-day setup" if w <= 0.0025 else
                               "wide, range-day setup" if w >= 0.006 else "normal")))

    if chain_snap is not None:
        exp = chain_snap.nearest_expiry()
        if exp:
            from .history import skew_25d
            sk = skew_25d(chain_snap, exp)
            if sk is not None:
                # Puts bid over calls = demand for downside protection = bearish tilt.
                comps.append(_c("25d skew", _clip(-sk / 0.05), 1.0,
                                f"{sk*100:+.2f} vol pts "
                                + ("(puts bid -- downside demand)" if sk > 0 else "(calls bid)")))

            pcr = put_call_ratio(chain_snap, exp)
            if pcr and pcr.get("oi"):
                # Deliberately low weight: PCR is noisy and its contrarian reading only holds
                # at extremes. Included because it is watched, not because it is reliable.
                comps.append(_c("PCR (OI)", _clip((pcr["oi"] - 1.0) / 0.6), 0.5,
                                f"{pcr['oi']:.2f} put/call open interest"))

    scored = [c for c in comps if c["weight"] > 0]
    total_w = sum(c["weight"] for c in scored)
    score = (sum(c["score"] * c["weight"] for c in scored) / total_w) if total_w else 0.0

    if score >= 0.5:
        label, strength = "LONG", "strong"
    elif score >= 0.2:
        label, strength = "LONG", "mild"
    elif score <= -0.5:
        label, strength = "SHORT", "strong"
    elif score <= -0.2:
        label, strength = "SHORT", "mild"
    else:
        label, strength = "NEUTRAL", "flat"

    return {"score": score, "label": label, "strength": strength, "components": comps,
            "disclaimer": "Heuristic summary of on-screen readings. Not a trade signal, "
                          "not backtested, ignores spread, slippage and risk."}


def _c(name, score, weight, note):
    return {"name": name, "score": round(float(score), 4), "weight": float(weight), "note": note}
