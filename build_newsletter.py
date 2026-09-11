#!/usr/bin/env python3
"""
build_newsletter.py  --  Build the weekly SIFintel newsletter from data already in the repo.

Nothing here fetches anything. Every number comes from the JSON the daily workflow already
commits, so the newsletter cannot disagree with the site: same NAVs, same AUM, same NFO list.

    python build_newsletter.py                      # build for the week ending today
    python build_newsletter.py --week 2026-09-11    # a specific week
    python build_newsletter.py --out-dir newsletter

Writes, for the week ending <date>:
    newsletter/<date>.html        archive page, in site chrome
    newsletter/<date>.email.html  the email body (inline styles, 600px, no external CSS)
    newsletter/<date>.email.txt   plain-text alternative
    newsletter/index.html         archive index
    newsletter/latest.json        {date, subject, preheader} for the sender

stdlib only.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

import sitetpl

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = sitetpl.SITE

# One plan per fund in the movers table. A SIF lists the same strategy as Direct/Regular and
# Growth/IDCW, so an unfiltered leaderboard is four rows of the same fund and no information.
PREFERRED_PLAN = re.compile(r"direct.*growth", re.I)

# One row per STRATEGY. Without this a fund appears four times (Direct/Regular x Growth/IDCW)
# and the leaderboard is three houses repeated.
#
# The key is the name TRUNCATED at the first plan/option marker, not the name with those words
# deleted. Deleting them is an arms race the data keeps winning -- "RegularPlan" with no space,
# "Half Yearly IDCW", "Income Distribution Cum Capital Withdrawal" spelled out in full. Every
# one of those sits AFTER the strategy name, so cutting at the first marker handles the whole
# family with one rule.
PLAN_CUT = re.compile(
    r"[-–]?\s*\b(direct|regular|growth|idcw|income\s+distribution|payout|reinvest|plan|option)",
    re.I)


def load(name, default=None):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        sys.stderr.write(f"[newsletter] could not read {name}: {e}\n")
        return default


def money(cr):
    """AMFI reports in INR crore; show crore under 1 lakh cr and lakh crore above."""
    if cr is None:
        return "—"
    if abs(cr) >= 100000:
        return f"₹{cr/100000:,.2f} lakh cr"
    return f"₹{cr:,.0f} cr"


def pct(x, places=2):
    return "—" if x is None else f"{x*100:+.{places}f}%"


# --- the week's sections --------------------------------------------------------------

def week_bounds(end):
    """The seven days ending on `end`, inclusive."""
    return end - dt.timedelta(days=6), end


def industry_block(ind):
    """Latest official AMFI month, with the month-on-month move."""
    if not ind:
        return None
    totals = ind.get("totals") or []
    latest = ind.get("latest_total") or (totals[-1] if totals else None)
    if not latest:
        return None
    prev = None
    for row in totals:
        if row.get("period") and latest.get("period") and row["period"] < latest["period"]:
            prev = row if prev is None or row["period"] > prev["period"] else prev
    out = {
        "period": latest.get("period"),
        "aum_cr": latest.get("aum_cr"),
        "net_flow_cr": latest.get("net_flow_cr"),
        "folios": latest.get("folios"),
        "schemes": latest.get("schemes"),
        "aum_mom": None, "folios_mom": None,
    }
    if prev and prev.get("aum_cr") and latest.get("aum_cr"):
        out["aum_mom"] = latest["aum_cr"] / prev["aum_cr"] - 1
    if prev and prev.get("folios") and latest.get("folios"):
        out["folios_mom"] = latest["folios"] / prev["folios"] - 1
    return out


def movers(nav, start, end, limit=5):
    """
    Per-fund NAV change across the week.

    Uses the first and last NAV actually published inside the window rather than assuming
    daily points — SIFs do not all publish every day, and a missing Friday would otherwise
    read as a flat week.
    """
    rows = []
    for s in (nav or {}).get("schemes", []):
        series = s.get("series") or []
        inside = [(d, v) for d, v in series
                  if start.isoformat() <= d <= end.isoformat() and v]
        if len(inside) < 2:
            continue
        first, last = inside[0][1], inside[-1][1]
        if not first:
            continue
        rows.append({
            "code": s.get("code"), "name": s.get("name", ""), "sif": s.get("sif", ""),
            "cat": s.get("cat", ""), "nav": last, "chg": last / first - 1,
            "from": inside[0][0], "to": inside[-1][0],
            "preferred": bool(PREFERRED_PLAN.search(s.get("name", ""))),
        })

    # Collapse plan variants to one row per strategy, preferring Direct-Growth.
    by_fund = {}
    for r in rows:
        cut = PLAN_CUT.search(r["name"])
        base = r["name"][:cut.start()] if cut else r["name"]
        base = re.sub(r"[^a-z0-9]+", " ", base.lower())
        key = (r["sif"], " ".join(base.split()))
        keep = by_fund.get(key)
        if keep is None or (r["preferred"] and not keep["preferred"]):
            by_fund[key] = r
    uniq = sorted(by_fund.values(), key=lambda r: r["chg"], reverse=True)
    return {"top": uniq[:limit], "bottom": list(reversed(uniq[-limit:])) if len(uniq) > limit else [],
            "count": len(uniq)}


def launches(nav, start, end):
    """Schemes whose very first NAV landed inside the window."""
    out = []
    for s in (nav or {}).get("schemes", []):
        series = s.get("series") or []
        if not series:
            continue
        first_date = series[0][0]
        if start.isoformat() <= first_date <= end.isoformat():
            out.append({"name": s.get("name", ""), "sif": s.get("sif", ""),
                        "cat": s.get("cat", ""), "since": first_date})
    return out


def open_nfos(nfo):
    """Offers AMFI still lists as open. Names come from fund_house + strategy."""
    out = []
    for n in (nfo or {}).get("nfos", []):
        if (n.get("status") or "").lower() != "open":
            continue
        out.append({"house": n.get("fund_house") or "",
                    "strategy": n.get("strategy") or "",
                    "since": n.get("first_seen") or ""})
    return out[:8]


CHANGELOG_HEAD = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})")

# monitor.py writes an operations log: alongside real news it records dead AMC links and how
# many NAVs refreshed. Those are for the maintainer. Telling subscribers to "check the AMC
# site" reads as an internal note escaping into a published email, so only the sections that
# are genuinely news are carried through.
SUBSCRIBER_SECTIONS = re.compile(r"(portfolio disclosure|fund-manager|manager change)", re.I)
NOISE_LINE = re.compile(r"(NAV updated on|links? that went broken|missing presentation|^https?://)", re.I)


def changelog_slice(start, end, path="monitor/CHANGELOG.md"):
    """The monitor's own entries for the window, already grouped by type."""
    full = os.path.join(HERE, path)
    if not os.path.exists(full):
        return []
    out, keep, current, in_section = [], False, None, False
    with open(full, encoding="utf-8") as f:
        for line in f:
            m = CHANGELOG_HEAD.match(line)
            if m:
                day = m.group(1)
                keep = start.isoformat() <= day <= end.isoformat()
                current = {"date": day, "lines": []}
                in_section = False
                if keep:
                    out.append(current)
                continue
            if not keep or current is None:
                continue
            text = line.rstrip()
            if not text:
                continue
            if text.startswith("**"):                    # a section heading
                in_section = bool(SUBSCRIBER_SECTIONS.search(text))
                continue
            if in_section and text.lstrip().startswith("-") and not NOISE_LINE.search(text):
                current["lines"].append(text.lstrip("- ").strip())
    return [d for d in out if d["lines"]]


def latest_nav_date(nav):
    last = ""
    for s in (nav or {}).get("schemes", []):
        series = s.get("series") or []
        if series and series[-1][0] > last:
            last = series[-1][0]
    return dt.date.fromisoformat(last) if last else None


def build(end=None, strict=False):
    """
    Build the digest for the week ending `end`.

    If AMFI has not published since that week — the NAV feed runs a day or two behind, and
    longer over holidays — the window slides back to the last week that actually has NAVs and
    the lag is recorded. Publishing a blank "no movers this week" when the truth is "we have
    not received data yet" is the one failure mode that makes a newsletter untrustworthy.
    """
    end = end or dt.date.today()
    nav = load("nav_data.json", {})
    asof = latest_nav_date(nav)
    lag = 0
    if not strict and asof and asof < end:
        lag = (end - asof).days
        end = asof
    start, end = week_bounds(end)
    return {
        "start": start, "end": end, "nav_lag_days": lag,
        "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "industry": industry_block(load("industry_data.json", {})),
        "movers": movers(nav, start, end),
        "launches": launches(nav, start, end),
        "nfos": open_nfos(load("nfo_data.json", {})),
        "changelog": changelog_slice(start, end),
        "scheme_count": len((nav or {}).get("schemes", [])),
        "nav_asof": (nav or {}).get("generated", "")[:10],
    }


# --- rendering ------------------------------------------------------------------------

E = sitetpl  # re-exported for the archive page


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def subject(d):
    """Lead with the week's most newsworthy fact, not a generic 'weekly update'."""
    if d["launches"]:
        n = len(d["launches"])
        return f"SIF weekly: {n} new fund{'s' if n > 1 else ''} listed"
    ind = d["industry"]
    if ind and ind.get("aum_mom") is not None:
        return f"SIF weekly: industry AUM {money(ind['aum_cr'])}, {pct(ind['aum_mom'])} MoM"
    top = (d["movers"]["top"] or [None])[0]
    if top:
        return f"SIF weekly: {top['sif']} leads at {pct(top['chg'])}"
    return "SIF weekly update"


def preheader(d):
    bits = []
    if d["movers"]["count"]:
        bits.append(f"{d['movers']['count']} funds tracked")
    if d["launches"]:
        bits.append(f"{len(d['launches'])} new listing(s)")
    if d["nfos"]:
        bits.append(f"{len(d['nfos'])} NFO(s) open")
    return " · ".join(bits) or "This week in India's Specialized Investment Funds."


def text_body(d):
    L = []
    A = L.append
    A(f"SIFintel — the week in Indian SIFs")
    A(f"{d['start']:%d %b} to {d['end']:%d %b %Y}"
      + (f"  (latest published NAVs; AMFI is {d['nav_lag_days']} day(s) behind)"
         if d["nav_lag_days"] else ""))
    A("")
    ind = d["industry"]
    if ind:
        A("INDUSTRY (AMFI, month-end " + str(ind["period"]) + ")")
        A(f"  AUM           {money(ind['aum_cr'])}" +
          (f"   ({pct(ind['aum_mom'])} MoM)" if ind["aum_mom"] is not None else ""))
        A(f"  Net flow      {money(ind['net_flow_cr'])}")
        A(f"  Folios        {ind['folios']:,.0f}" if ind.get("folios") else "  Folios        —")
        A(f"  Schemes       {ind['schemes']:,.0f}" if ind.get("schemes") else "  Schemes       —")
        A("")
    if d["movers"]["top"]:
        A(f"WEEK'S MOVERS ({d['movers']['count']} funds)")
        for r in d["movers"]["top"]:
            A(f"  {pct(r['chg']):>8}  {r['sif']} — {r['name'][:58]}")
        if d["movers"]["bottom"]:
            A("  ...")
            for r in d["movers"]["bottom"]:
                A(f"  {pct(r['chg']):>8}  {r['sif']} — {r['name'][:58]}")
        A("")
    if d["launches"]:
        A("NEW THIS WEEK")
        for r in d["launches"]:
            A(f"  {r['sif']} — {r['name']} (first NAV {r['since']})")
        A("")
    if d["nfos"]:
        A("NFOs OPEN")
        for n in d["nfos"]:
            A(f"  {n['house']} — {n['strategy']}")
        A("")
    if d["changelog"]:
        A("ALSO THIS WEEK")
        for day in d["changelog"]:
            for line in day["lines"][:8]:
                A(f"  [{day['date']}] " + re.sub(r"[*_`]", "", line))
        A("")
    A(f"Full dashboard: {SITE}/")
    A(f"Every number here comes from AMFI and AMC disclosures. Education only — not advice.")
    A("{{UNSUB_TEXT}}")
    return "\n".join(L)


def _row(label, value, sub=""):
    return (f'<tr><td style="padding:7px 0;color:#5a6485;font-size:14px">{esc(label)}</td>'
            f'<td style="padding:7px 0;text-align:right;font-weight:600;color:#14161f;'
            f'font-size:15px">{value}'
            + (f'<span style="font-weight:400;color:#6b7291;font-size:13px"> {sub}</span>' if sub else "")
            + "</td></tr>")


def _movers_rows(rows, tint):
    out = []
    for r in rows:
        out.append(
            f'<tr><td style="padding:8px 0;border-top:1px solid #ecedf3">'
            f'<div style="font-size:14px;color:#14161f;font-weight:600">{esc(r["sif"])}</div>'
            f'<div style="font-size:12px;color:#6b7291">{esc(r["name"][:70])}</div></td>'
            f'<td style="padding:8px 0;border-top:1px solid #ecedf3;text-align:right;'
            f'white-space:nowrap;font-weight:700;font-size:15px;color:{tint}">{pct(r["chg"])}</td></tr>')
    return "".join(out)


def email_html(d):
    ind = d["industry"]
    parts = []
    A = parts.append
    A(f'''<div style="background:#f6f7fb;padding:24px 12px;font-family:-apple-system,BlinkMacSystemFont,
'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{esc(preheader(d))}</div>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
 style="max-width:600px;margin:0 auto;background:#fff;border:1px solid #e7e9f0;border-radius:12px">
<tr><td style="padding:26px 28px 8px">
  <div style="font-size:12px;letter-spacing:.9px;text-transform:uppercase;color:#5b5bf0;font-weight:700">SIFintel</div>
  <h1 style="margin:6px 0 2px;font-size:21px;line-height:1.3;color:#14161f">The week in Indian SIFs</h1>
  <div style="font-size:13px;color:#6b7291">{d['start']:%d %b} – {d['end']:%d %b %Y}{"" if not d["nav_lag_days"] else f" · latest published NAVs, AMFI {d['nav_lag_days']}d behind"}</div>
</td></tr>''')

    if ind:
        A(f'''<tr><td style="padding:14px 28px 0">
  <h2 style="font-size:13px;text-transform:uppercase;letter-spacing:.7px;color:#6b7291;margin:14px 0 2px">
    Industry · AMFI month-end {esc(ind["period"])}</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    {_row("Assets under management", money(ind["aum_cr"]),
          pct(ind["aum_mom"]) + " MoM" if ind["aum_mom"] is not None else "")}
    {_row("Net flow", money(ind["net_flow_cr"]))}
    {_row("Folios", f"{ind['folios']:,.0f}" if ind.get("folios") else "—",
          pct(ind["folios_mom"]) + " MoM" if ind.get("folios_mom") is not None else "")}
    {_row("Schemes", f"{ind['schemes']:,.0f}" if ind.get("schemes") else "—")}
  </table>
</td></tr>''')

    m = d["movers"]
    if m["top"]:
        A(f'''<tr><td style="padding:10px 28px 0">
  <h2 style="font-size:13px;text-transform:uppercase;letter-spacing:.7px;color:#6b7291;margin:18px 0 2px">
    Week's movers · {m["count"]} funds</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    {_movers_rows(m["top"], "#12a150")}
    {_movers_rows(m["bottom"], "#e5484d")}
  </table>
</td></tr>''')

    if d["launches"]:
        items = "".join(
            f'<li style="margin:5px 0;font-size:14px;color:#14161f">{esc(r["sif"])} — '
            f'<span style="color:#4a5170">{esc(r["name"])}</span> '
            f'<span style="color:#6b7291;font-size:12px">(first NAV {esc(r["since"])})</span></li>'
            for r in d["launches"])
        A(f'''<tr><td style="padding:10px 28px 0">
  <h2 style="font-size:13px;text-transform:uppercase;letter-spacing:.7px;color:#6b7291;margin:18px 0 2px">
    New this week</h2>
  <ul style="margin:6px 0;padding-left:18px">{items}</ul>
</td></tr>''')

    if d["nfos"]:
        items = "".join(
            f'<li style="margin:5px 0;font-size:14px;color:#14161f">'
            f'{esc(n["house"])} — '
            f'<span style="color:#4a5170">{esc(n["strategy"])}</span></li>'
            for n in d["nfos"])
        A(f'''<tr><td style="padding:10px 28px 0">
  <h2 style="font-size:13px;text-transform:uppercase;letter-spacing:.7px;color:#6b7291;margin:18px 0 2px">
    NFOs open now</h2>
  <ul style="margin:6px 0;padding-left:18px">{items}</ul>
</td></tr>''')

    A(f'''<tr><td style="padding:22px 28px 26px">
  <a href="{SITE}/" style="display:inline-block;background:#5b5bf0;color:#fff;font-weight:600;
     text-decoration:none;padding:11px 20px;border-radius:8px;font-size:15px">Open the dashboard</a>
  <p style="margin:18px 0 0;font-size:12px;line-height:1.6;color:#8a90a8">
    Every figure comes from AMFI filings and AMC disclosures, and matches what is on the site.
    SIFintel is an independent data and education platform — not a SEBI-registered adviser,
    research analyst or distributor. Nothing here is investment advice, and no fund is
    recommended or ranked.
  </p>
  <p style="margin:12px 0 0;font-size:12px;color:#8a90a8">
    You're getting this because you confirmed a subscription at sifintel.com.
    {{{{UNSUB_HTML}}}}
  </p>
</td></tr>
</table></div>''')
    return "".join(parts)


def archive_html(d):
    """The same issue as a page on the site, so every email has a public permalink."""
    body = email_html(d).replace("{{UNSUB_HTML}}", "").replace(
        '<div style="background:#f6f7fb;padding:24px 12px;',
        '<div style="padding:0;')
    return (f'<p class="meta">SIFintel · Newsletter</p>'
            f'<h2>The week in Indian SIFs — {d["end"]:%d %b %Y}</h2>'
            f'<p>Sent to subscribers on {d["end"]:%d %B %Y}. '
            f'<a href="/newsletter">Get it weekly</a>.</p>'
            f'{body}')


LANDING = """<p class="meta">SIFintel · Newsletter</p>
<h2>The week in Indian SIFs</h2>
<p>One email a week. It covers what actually changed in India's Specialized Investment Fund
category — not commentary, not picks.</p>

<h3>What's in it</h3>
<ul>
  <li><strong>Industry figures</strong> — AUM, net flows, folios and scheme count from AMFI's
      official month-end filings, with the month-on-month move.</li>
  <li><strong>The week's movers</strong> — every SIF's NAV change over the week, one row per
      strategy rather than four rows of the same fund's plan variants.</li>
  <li><strong>New launches and open NFOs</strong> — as soon as a scheme's first NAV appears.</li>
  <li><strong>Fresh portfolio disclosures</strong> — which houses filed, and for which month.</li>
</ul>
<p>Every figure is the same one on the dashboard, from the same AMFI and AMC sources. If a
number here disagrees with the site, the site is wrong and we want to know.</p>

<h3>Subscribe</h3>
<p>Enter your email in the box at the foot of any page, or here:</p>
<form class="subform" id="subform2" novalidate style="max-width:420px">
  <label class="sr" for="subemail2">Your email</label>
  <input id="subemail2" name="email" type="email" inputmode="email" autocomplete="email"
         placeholder="you@example.com" required>
  <div style="position:absolute;left:-5000px" aria-hidden="true">
    <input name="company" tabindex="-1" autocomplete="off"></div>
  <button class="btn" type="submit">Subscribe</button>
  <p class="substatus" id="substatus2" role="status" aria-live="polite"></p>
</form>
<script>
(function(){
  var f=document.getElementById('subform2'); if(!f) return;
  var s=document.getElementById('substatus2');
  f.addEventListener('submit', async function(e){
    e.preventDefault();
    var btn=f.querySelector('button[type=submit]');
    var email=(f.email.value||'').trim();
    if(!/^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(email)){
      s.className='substatus warn'; s.textContent='Please enter a valid email address.'; return; }
    btn.disabled=true; s.className='substatus'; s.textContent='Sending…';
    try{
      var r=await fetch('/api/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({email:email,company:f.company.value})});
      var j=await r.json().catch(function(){return {};});
      if(r.ok&&j.ok){ s.className='substatus good';
        s.textContent='Check your inbox — click the link to confirm.'; f.reset(); }
      else { s.className='substatus warn';
        s.textContent=(j&&j.error)||'Could not subscribe. Please try again.'; }
    }catch(err){ s.className='substatus warn'; s.textContent='Network error. Please try again.'; }
    btn.disabled=false;
  });
})();
</script>

<h3>The small print</h3>
<p>We send a confirmation email first — nothing is added to any list until you click the link in
it, so nobody can sign up an address that isn't theirs. Your address is used for this newsletter
and nothing else: it is never sold, rented or shared, and every issue carries a one-click
unsubscribe. Ask us to delete it at any time at
<a href="mailto:%EMAIL%">%EMAIL%</a>.</p>

<div class="callout">SIFintel is an independent data and education platform. We are not a
SEBI-registered investment adviser, research analyst or distributor. The newsletter reports
published data — it does not recommend, rank or promote any fund, and it is not investment,
legal or tax advice.</div>

<h3>Past issues</h3>
%ARCHIVE%
"""


def write_pages(out_dir="newsletter"):
    """The /newsletter landing page and the archive index."""
    out = os.path.join(HERE, out_dir)
    os.makedirs(out, exist_ok=True)
    issues = sorted((f[:-5] for f in os.listdir(out)
                     if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.html", f)), reverse=True)

    if issues:
        items = "".join(
            f'<li><a href="/{out_dir}/{i}">Week ending '
            f'{dt.date.fromisoformat(i):%d %B %Y}</a></li>' for i in issues[:40])
        archive = f"<ul>{items}</ul>"
    else:
        archive = "<p>The first issue goes out this week.</p>"

    sitetpl.build(
        "newsletter.html",
        title="SIF newsletter — the week in Indian SIFs | SIFintel",
        desc=("One email a week on India's Specialized Investment Funds: new launches and NFOs, "
              "portfolio disclosures, AUM and flows, and weekly performance."),
        keywords=sitetpl.KW, canon=f"{SITE}/newsletter", active="",
        crumbs=[("Home", "/"), ("Newsletter", None)],
        main_html=LANDING.replace("%ARCHIVE%", archive).replace("%EMAIL%", sitetpl.EMAIL),
        ld=sitetpl.article_ld(f"{SITE}/newsletter", "SIFintel weekly newsletter",
                              "The week in Indian Specialized Investment Funds."),
        ogtype="website")

    sitetpl.build(
        f"{out_dir}/index.html",
        title="Newsletter archive | SIFintel",
        desc="Every past issue of the SIFintel weekly newsletter.",
        keywords=sitetpl.KW, canon=f"{SITE}/{out_dir}/", active="",
        crumbs=[("Home", "/"), ("Newsletter", "/newsletter"), ("Archive", None)],
        main_html=('<p class="meta">SIFintel · Newsletter</p><h2>Archive</h2>'
                   '<p>Every issue, as it was sent. '
                   '<a href="/newsletter">Subscribe</a> to get the next one.</p>' + archive),
        ld=sitetpl.article_ld(f"{SITE}/{out_dir}/", "SIFintel newsletter archive",
                              "Every past issue."),
        ogtype="website")


def main(argv=None):
    p = argparse.ArgumentParser(description="Build the weekly SIFintel newsletter.")
    p.add_argument("--week", help="week ENDING date, YYYY-MM-DD (default: today)")
    p.add_argument("--out-dir", default="newsletter")
    p.add_argument("--pages-only", action="store_true",
                   help="rebuild the landing page and archive index, without a new issue")
    p.add_argument("--strict", action="store_true",
                   help="use the requested week even if no NAVs have been published for it")
    a = p.parse_args(argv)

    if a.pages_only:
        write_pages(a.out_dir)
        return 0

    end = dt.date.fromisoformat(a.week) if a.week else dt.date.today()
    d = build(end, strict=a.strict)
    out = os.path.join(HERE, a.out_dir)
    os.makedirs(out, exist_ok=True)
    stem = d["end"].isoformat()

    with open(os.path.join(out, f"{stem}.email.html"), "w", encoding="utf-8") as f:
        f.write(email_html(d))
    with open(os.path.join(out, f"{stem}.email.txt"), "w", encoding="utf-8") as f:
        f.write(text_body(d))
    with open(os.path.join(out, "latest.json"), "w", encoding="utf-8") as f:
        json.dump({"date": stem, "subject": subject(d), "preheader": preheader(d),
                   "generated": d["generated"]}, f, indent=1)

    sitetpl.build(
        f"{a.out_dir}/{stem}.html",
        title=f"{subject(d)} — SIFintel newsletter",
        desc=preheader(d), keywords=sitetpl.KW,
        canon=f"{SITE}/{a.out_dir}/{stem}",
        active="", crumbs=[("Home", "/"), ("Newsletter", "/newsletter"), (stem, None)],
        main_html=archive_html(d),
        ld=sitetpl.article_ld(f"{SITE}/{a.out_dir}/{stem}", subject(d), preheader(d), stem))

    if d["nav_lag_days"]:
        sys.stderr.write(f"[newsletter] NAV feed is {d['nav_lag_days']} day(s) behind; "
                         f"reporting the week ending {d['end']}\n")
    write_pages(a.out_dir)
    sys.stderr.write(
        f"[newsletter] week {d['start']} .. {d['end']}  "
        f"movers={d['movers']['count']} launches={len(d['launches'])} "
        f"nfos={len(d['nfos'])} log={len(d['changelog'])}\n"
        f"[newsletter] subject: {subject(d)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
