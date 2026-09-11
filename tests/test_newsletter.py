#!/usr/bin/env python3
"""
test_newsletter.py  --  Unit tests for the weekly newsletter builder and sender.

    python -m unittest discover -s tests -v

The cross-language check matters most: send_newsletter.sign() must agree byte for byte with
sign() in functions/api/_newsletter.js, because Python mints the unsubscribe links and a
Cloudflare Worker verifies them. A mismatch surfaces only as a dead link in a sent email.
"""

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_newsletter as B  # noqa: E402
import send_newsletter as S  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestStrategyDedupe(unittest.TestCase):
    """One row per strategy, not one per plan/option variant."""

    def key(self, name):
        import re
        cut = B.PLAN_CUT.search(name)
        base = name[:cut.start()] if cut else name
        return " ".join(re.sub(r"[^a-z0-9]+", " ", base.lower()).split())

    def test_plan_and_option_variants_collapse(self):
        variants = [
            "Magnum Hybrid Long Short Fund - Direct  Plan - Growth",
            "Magnum Hybrid Long Short Fund - Direct Plan - Income Distribution Cum Capital Withdrawal",
            "Magnum Hybrid Long Short Fund - Regular Plan - Growth",
        ]
        self.assertEqual(len({self.key(v) for v in variants}), 1)

    def test_spacing_and_wording_quirks_in_the_real_data(self):
        # Each of these defeated a delete-the-words approach; truncation handles them all.
        pairs = [
            ("qsif Sector Rotation Long-Short Fund - Growth Option - Direct Plan",
             "qsif Sector Rotation Long-Short Fund - Growth Option - RegularPlan"),
            ("Apex Hybrid Long-Short Fund - Direct - Payout of IDCW",
             "Apex Hybrid Long-Short Fund - Regular - Growth"),
            ("Arudha Hybrid Long-Short Fund-Direct Plan-Annual IDCW",
             "Arudha Hybrid Long-Short Fund-Direct Plan-Half Yearly IDCW"),
        ]
        for a, b in pairs:
            self.assertEqual(self.key(a), self.key(b), f"{a!r} vs {b!r}")

    def test_distinct_strategies_stay_distinct(self):
        self.assertNotEqual(self.key("Apex Hybrid Long-Short Fund - Direct - Growth"),
                            self.key("Apex Equity Long-Short Fund - Direct - Growth"))


class TestMovers(unittest.TestCase):
    def nav(self, series_by_name):
        return {"schemes": [
            {"code": f"S{i}", "name": n, "sif": "House", "cat": "c", "series": s}
            for i, (n, s) in enumerate(series_by_name.items())]}

    def test_weekly_change_uses_first_and_last_published_nav(self):
        # A fund that does not print every day must not read as flat.
        nav = self.nav({"Fund A - Direct - Growth": [["2026-08-17", 100.0], ["2026-08-20", 110.0]]})
        m = B.movers(nav, dt.date(2026, 8, 15), dt.date(2026, 8, 21))
        self.assertEqual(m["count"], 1)
        self.assertAlmostEqual(m["top"][0]["chg"], 0.10)

    def test_single_nav_in_window_is_skipped(self):
        nav = self.nav({"Fund A - Direct - Growth": [["2026-08-17", 100.0]]})
        self.assertEqual(B.movers(nav, dt.date(2026, 8, 15), dt.date(2026, 8, 21))["count"], 0)

    def test_navs_outside_the_window_are_ignored(self):
        nav = self.nav({"Fund A - Direct - Growth":
                        [["2026-07-01", 50.0], ["2026-08-17", 100.0], ["2026-08-20", 110.0]]})
        m = B.movers(nav, dt.date(2026, 8, 15), dt.date(2026, 8, 21))
        self.assertAlmostEqual(m["top"][0]["chg"], 0.10)


class TestStaleFallback(unittest.TestCase):
    def test_window_slides_back_when_the_feed_is_behind(self):
        """Reporting an empty week when data simply hasn't arrived is the worst failure."""
        nav = {"schemes": [{"code": "S1", "name": "F - Direct - Growth", "sif": "H", "cat": "c",
                            "series": [["2026-08-17", 100.0], ["2026-08-21", 101.0]]}]}
        path = os.path.join(ROOT, "nav_data.json")
        orig = B.load
        B.load = lambda name, default=None: nav if name == "nav_data.json" else (default or {})
        self.addCleanup(lambda: setattr(B, "load", orig))
        d = B.build(dt.date(2026, 9, 11))
        self.assertEqual(d["end"], dt.date(2026, 8, 21))
        self.assertEqual(d["nav_lag_days"], 21)
        self.assertEqual(d["movers"]["count"], 1)

    def test_strict_keeps_the_requested_week(self):
        nav = {"schemes": [{"code": "S1", "name": "F - Direct - Growth", "sif": "H", "cat": "c",
                            "series": [["2026-08-21", 100.0]]}]}
        orig = B.load
        B.load = lambda name, default=None: nav if name == "nav_data.json" else (default or {})
        self.addCleanup(lambda: setattr(B, "load", orig))
        d = B.build(dt.date(2026, 9, 11), strict=True)
        self.assertEqual(d["end"], dt.date(2026, 9, 11))
        self.assertEqual(d["nav_lag_days"], 0)


class TestChangelogFiltering(unittest.TestCase):
    LOG = """# changelog

## 2026-08-19 (data as of 2026-08-19)

**🆕 New schemes / launches:**
- House A · Fund One (first NAV 2026-08-19)

**🔗 Links that went broken (check the AMC site):**
- https://example.com/broken.pdf

**📄 New portfolio disclosures:**
- House B · Fund Two → 2026-07

_NAV updated on 105 scheme(s)._
## 2026-01-01 (old)

**📄 New portfolio disclosures:**
- House C · Fund Three → 2025-12
"""

    def slice_(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "CHANGELOG.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.LOG)
            orig_here = B.HERE
            B.HERE = d
            try:
                return B.changelog_slice(dt.date(2026, 8, 15), dt.date(2026, 8, 21), "CHANGELOG.md")
            finally:
                B.HERE = orig_here

    def test_only_subscriber_relevant_sections_survive(self):
        out = self.slice_()
        lines = [ln for day in out for ln in day["lines"]]
        self.assertTrue(any("Fund Two" in ln for ln in lines), "disclosures kept")
        # Internal ops notes must never reach subscribers.
        self.assertFalse(any("broken" in ln.lower() or ln.startswith("http") for ln in lines))
        self.assertFalse(any("NAV updated" in ln for ln in lines))
        # Launches have their own section built from the NAVs, so they are not repeated here.
        self.assertFalse(any("Fund One" in ln for ln in lines))

    def test_entries_outside_the_window_are_dropped(self):
        self.assertFalse(any("Fund Three" in ln
                             for day in self.slice_() for ln in day["lines"]))


class TestNfoAndFormatting(unittest.TestCase):
    def test_only_open_offers_with_real_names(self):
        nfo = {"nfos": [
            {"fund_house": "Apex SIF", "strategy": "Apex Equity Long-Short Fund",
             "status": "open", "first_seen": "2026-08-13"},
            {"fund_house": "Old SIF", "strategy": "Closed Fund", "status": "closed"}]}
        out = B.open_nfos(nfo)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["house"], "Apex SIF")
        self.assertTrue(out[0]["strategy"])

    def test_money_switches_unit_at_a_lakh_crore(self):
        self.assertEqual(B.money(23177.31), "₹23,177 cr")
        self.assertEqual(B.money(250000), "₹2.50 lakh cr")
        self.assertEqual(B.money(None), "—")

    def test_pct_always_signed(self):
        self.assertEqual(B.pct(0.2979), "+29.79%")
        self.assertEqual(B.pct(-0.01), "-1.00%")
        self.assertEqual(B.pct(None), "—")


class TestSubject(unittest.TestCase):
    def base(self, **kw):
        d = {"launches": [], "industry": None, "movers": {"top": [], "bottom": [], "count": 0},
             "nfos": [], "changelog": [], "start": dt.date(2026, 8, 15),
             "end": dt.date(2026, 8, 21), "nav_lag_days": 0}
        d.update(kw)
        return d

    def test_leads_with_a_launch(self):
        d = self.base(launches=[{"sif": "H", "name": "F", "cat": "c", "since": "2026-08-19"}])
        self.assertIn("new fund", B.subject(d))

    def test_falls_back_to_industry_then_movers_then_generic(self):
        self.assertIn("AUM", B.subject(self.base(
            industry={"aum_cr": 23177.31, "aum_mom": 0.2979, "period": "2026-07"})))
        self.assertIn("leads", B.subject(self.base(
            movers={"top": [{"sif": "House", "chg": 0.038}], "bottom": [], "count": 1})))
        self.assertEqual(B.subject(self.base()), "SIF weekly update")


class TestTokenInterop(unittest.TestCase):
    """send_newsletter.sign() must equal sign() in the Worker's JS, byte for byte."""

    SECRET = "shared-secret"

    def test_matches_the_javascript_implementation(self):
        node = subprocess.run(["node", "--version"], capture_output=True)
        if node.returncode != 0:
            self.skipTest("node not available")

        cases = [("unsub", "a@b.com"), ("unsub", "first.last+tag@sub.domain.co.in"),
                 ("confirm", "x@y.io")]
        mine = {f"{k}|{e}": S.sign(self.SECRET, k, e, 0) for k, e in cases}

        script = (
            'import { sign, verify } from "%s/functions/api/_newsletter.js";'
            'const py = JSON.parse(process.argv[2]); const out = {};'
            'for (const key of Object.keys(py)) {'
            '  const [k, e] = key.split("|");'
            '  out[key] = { mine: await sign("%s", k, e, 0),'
            '               verified: (await verify("%s", k, py[key])).email };'
            '} console.log(JSON.stringify(out));' % (ROOT, self.SECRET, self.SECRET))
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as f:
            f.write(script)
            path = f.name
        self.addCleanup(os.unlink, path)

        res = subprocess.run(["node", path, json.dumps(mine)],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        got = json.loads(res.stdout)
        for key, expected in mine.items():
            self.assertEqual(got[key]["mine"], expected, f"JS and Python disagree for {key}")
            self.assertEqual(got[key]["verified"], key.split("|", 1)[1],
                             f"Worker could not verify the Python token for {key}")

    def test_unsubscribe_url_shape(self):
        url = S.unsubscribe_url(self.SECRET, "a@b.com")
        self.assertTrue(url.startswith("https://www.sifintel.com/api/unsubscribe?t="))
        self.assertIn(".", url.split("t=")[1])

    def test_personalise_replaces_both_placeholders(self):
        html, text = S.personalise("x {{UNSUB_HTML}} y", "a {{UNSUB_TEXT}} b", "https://u/1")
        self.assertIn("https://u/1", html)
        self.assertIn("https://u/1", text)
        self.assertNotIn("{{UNSUB", html)
        self.assertNotIn("{{UNSUB", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
