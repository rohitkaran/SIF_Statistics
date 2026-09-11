#!/usr/bin/env python3
"""
greeks.py  --  Black-Scholes-Merton pricing, greeks and implied-vol solving. stdlib only.

Vendor option feeds are inconsistent about greeks: Polygon returns them only on paid tiers,
Tradier returns them on a delayed cadence, and neither returns them for every contract. The
engine needs greeks on EVERY contract it evaluates, so we always compute locally from the
mid price and treat any vendor-supplied greek as a cross-check rather than the source.

Conventions (these matter -- they are the units the rules are written against):
  * `t` is time to expiry in YEARS.
  * `sigma`, `r`, `q` are annualised decimals (0.25 == 25%).
  * vega  is per 1.00 of vol; divide by 100 for "per vol point".
  * theta is per YEAR; divide by 365 for "per calendar day".
"""

import math

SQRT_2PI = math.sqrt(2.0 * math.pi)

# Vol bounds for the IV solver. 0.01% .. 1000% brackets every listed option we have seen;
# anything outside is a bad quote, not a real vol.
IV_LO = 1e-4
IV_HI = 10.0


def _n(x):
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _N(x):
    """Standard normal CDF, via erf (no scipy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1_d2(s, k, t, sigma, r=0.0, q=0.0):
    v = sigma * math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / v
    return d1, d1 - v


def intrinsic(s, k, right):
    return max(0.0, s - k) if right == "C" else max(0.0, k - s)


def price(s, k, t, sigma, right, r=0.0, q=0.0):
    """Black-Scholes-Merton price of a European option. Expired/zero-vol -> intrinsic."""
    if s <= 0 or k <= 0 or t <= 0 or sigma <= 0:
        return intrinsic(s, k, right)
    d1, d2 = _d1_d2(s, k, t, sigma, r, q)
    df_r, df_q = math.exp(-r * t), math.exp(-q * t)
    if right == "C":
        return s * df_q * _N(d1) - k * df_r * _N(d2)
    return k * df_r * _N(-d2) - s * df_q * _N(-d1)


def greeks(s, k, t, sigma, right, r=0.0, q=0.0):
    """All five greeks in one pass -- d1/d2 and the discount factors are shared."""
    if s <= 0 or k <= 0 or t <= 0 or sigma <= 0:
        # At/after expiry only delta survives, as a step function at the strike.
        itm = (s > k) if right == "C" else (s < k)
        d = (1.0 if right == "C" else -1.0) if itm else 0.0
        return {"delta": d, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}

    d1, d2 = _d1_d2(s, k, t, sigma, r, q)
    sqrt_t = math.sqrt(t)
    df_r, df_q = math.exp(-r * t), math.exp(-q * t)
    pdf = _n(d1)

    gamma = df_q * pdf / (s * sigma * sqrt_t)
    vega = s * df_q * pdf * sqrt_t
    decay = -(s * df_q * pdf * sigma) / (2.0 * sqrt_t)   # shared theta term

    if right == "C":
        delta = df_q * _N(d1)
        theta = decay - r * k * df_r * _N(d2) + q * s * df_q * _N(d1)
        rho = k * t * df_r * _N(d2)
    else:
        delta = df_q * (_N(d1) - 1.0)
        theta = decay + r * k * df_r * _N(-d2) - q * s * df_q * _N(-d1)
        rho = -k * t * df_r * _N(-d2)

    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho}


def implied_vol(target, s, k, t, right, r=0.0, q=0.0):
    """
    Back out sigma from an observed premium. Returns None when no vol can explain the price.

    Bisection rather than Newton: vega collapses toward zero on deep ITM/OTM contracts, which
    is exactly where a live chain is noisiest, and Newton diverges there. Bisection is slower
    but cannot run away, and the price function is monotonic in sigma so it always converges.
    """
    if target is None or target <= 0 or t <= 0 or s <= 0 or k <= 0:
        return None
    # Bracket against the model's OWN extremes rather than an analytic intrinsic bound.
    # A deep-ITM European put legitimately trades below undiscounted (K - S), because the
    # strike is discounted: testing against max(0, K-S) rejected those real quotes and blanked
    # the IV on every deep put in the chain. price() at IV_LO is the true floor of the search.
    if target < price(s, k, t, IV_LO, right, r, q) - 1e-9:
        return None
    if target > price(s, k, t, IV_HI, right, r, q):
        return None

    lo, hi = IV_LO, IV_HI
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if price(s, k, t, mid, right, r, q) < target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-7:
            break
    return 0.5 * (lo + hi)


def year_fraction(now, expiry_utc):
    """
    Time to expiry in years, from two aware datetimes. Never returns a negative.

    365-day basis, not 252: greeks decay on calendar time (weekends included), and every
    vendor IV we compare against is quoted on a calendar basis too.
    """
    secs = (expiry_utc - now).total_seconds()
    return max(0.0, secs / (365.0 * 24 * 3600))
