#!/usr/bin/env python3
"""Generate the four account pages: /subscribe, /account, /auth, /unsubscribe.

Lives at the repo ROOT (not in .build/, which is gitignored scratch) for the same reason
sitetpl.py does: these pages are part of the product, and a fresh clone has to be able to
rebuild them. Same contract as build_aum.py / build_attribution.py — run it after any change
to the page copy, the nav, or the shared template:

    python build_accounts.py

The pages are deliberately thin. All four are static HTML that talk to the Cloudflare Pages
Functions under functions/api/ — there is no server-rendered state, so they cache and deploy
exactly like the rest of the site.

  /subscribe    email + which newsletters      -> POST /api/auth/request
  /auth         redeems the magic-link token   -> POST /api/auth/verify
  /account      view and change preferences    -> GET/POST /api/account
  /unsubscribe  one-click and confirmed opt-out-> GET/POST /api/unsubscribe

Standard library only.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from sitetpl import SITE, EMAIL, COMPANY, KW, build  # noqa: E402

# The two newsletters, described once. Both the subscribe page and the preferences page render
# from this list, so a change to the pitch or the cadence lands on both at the same time.
LISTS = [
    dict(
        key="sif_weekly",
        cadence="Every Monday",
        title="SIF Weekly",
        blurb="What every Indian Specialized Investment Fund did last week — the movers, how they "
              "fared against NIFTY 50, newly disclosed portfolios and any open NFOs. Built from the "
              "same data as the dashboard, so it is numbers, never tips.",
        default=True,
    ),
    dict(
        key="news_daily",
        cadence="Weekday mornings, 7am IST",
        title="Morning Brief",
        blurb="The overnight financial news that actually matters — central banks and regulators "
              "first, then India, then the world. Single-stock noise is filtered out.",
        default=False,
    ),
]


def option_cards(prefix):
    """The checkbox cards. `prefix` keeps element ids unique between the two pages."""
    out = []
    for item in LISTS:
        checked = " checked" if item["default"] else ""
        out.append(
            f'<label class="opt" id="{prefix}-opt-{item["key"]}">'
            f'<input type="checkbox" name="{item["key"]}" id="{prefix}-{item["key"]}"{checked}>'
            f'<span><span class="cadence">{item["cadence"]}</span>'
            f'<h3>{item["title"]}</h3><p>{item["blurb"]}</p>'
            + (
                f'<span class="subopt" id="{prefix}-scope" hidden>'
                f'<label><input type="radio" name="{prefix}-news_scope" value="weekdays" checked> Weekdays only</label>'
                f'<label><input type="radio" name="{prefix}-news_scope" value="everyday"> Every day</label>'
                f"</span>"
                if item["key"] == "news_daily" else ""
            )
            + "</span></label>"
        )
    return "\n".join(out)


# Shared front-end helpers, inlined on every account page. Kept in one string so the four pages
# cannot drift apart in how they talk to the API or report an error.
SHARED_JS = """
<script>
window.SIF = (function(){
  function el(id){ return document.getElementById(id); }
  function say(node, kind, msg){
    if(!node) return;
    node.className = 'alert ' + kind;
    node.innerHTML = msg;
    node.hidden = false;
  }
  function hide(node){ if(node) node.hidden = true; }
  async function api(url, opts){
    var res = await fetch(url, Object.assign({headers:{'Content-Type':'application/json'}}, opts||{}));
    var body = await res.json().catch(function(){ return {}; });
    return { ok: res.ok && body.ok !== false, status: res.status, body: body };
  }
  // Reflect checkbox state onto the card so the whole tile looks selected, and reveal the
  // weekday/everyday choice only when the daily brief is actually ticked.
  function wireCards(prefix){
    ['sif_weekly','news_daily'].forEach(function(key){
      var box = el(prefix + '-' + key), card = el(prefix + '-opt-' + key);
      if(!box || !card) return;
      function sync(){
        card.classList.toggle('on', box.checked);
        if(key === 'news_daily'){
          var scope = el(prefix + '-scope');
          if(scope) scope.hidden = !box.checked;
        }
      }
      box.addEventListener('change', sync);
      sync();
    });
  }
  function scope(prefix){
    var picked = document.querySelector('input[name="' + prefix + '-news_scope"]:checked');
    return picked ? picked.value : 'weekdays';
  }
  return { el: el, say: say, hide: hide, api: api, wireCards: wireCards, scope: scope };
})();
</script>
"""


# --------------------------------------------------------------------------- /subscribe

SUBSCRIBE = """<article class="doc">
<h1>Get the SIF intel in your inbox</h1>
<p class="lede">Two free newsletters, built from the data on this site. Pick either, or both —
you can change your mind on any email, in one click.</p>
<p class="meta">Free · No spam · Unsubscribe any time</p>

<form id="subform" novalidate>
  <div class="optlist">
%OPTIONS%
  </div>

  <div class="authbox">
    <div class="field"><label for="sub-email">Your email</label>
      <input id="sub-email" name="email" type="email" autocomplete="email" required
             placeholder="you@company.com"></div>
    <div class="field"><label for="sub-name">Your name <span style="color:var(--ink-faint)">(optional)</span></label>
      <input id="sub-name" name="name" autocomplete="name" placeholder="So we can address you properly"></div>
    <!-- honeypot: hidden from humans; bots fill it and are silently dropped -->
    <div style="position:absolute;left:-5000px" aria-hidden="true">
      <input name="company" tabindex="-1" autocomplete="off"></div>
    <button class="btn" type="submit" id="sub-go">Subscribe free</button>
    <div class="alert" id="sub-msg" hidden></div>
    <p class="meta" style="margin:14px 0 0">We will email you a one-time link to confirm. No password
    to choose, and none to forget.</p>
  </div>
</form>

<h2>What you are signing up to</h2>
<div class="qa">
  <div class="q">Is it really free?</div>
  <div class="a">Yes. Both newsletters are free and always will be. The paid product is the
  <a href="/data">data feed and API</a>, not the writing.</div>
  <div class="q">How do I stop it?</div>
  <div class="a">Every email carries a one-click unsubscribe link, and your mail app's own
  unsubscribe button works too. You can also change exactly what you get at any time from
  <a href="/account">your preferences page</a> — no need to leave entirely if you only want less.</div>
  <div class="q">What do you do with my address?</div>
  <div class="a">We send you the newsletters you asked for. That is the whole list. We do not sell,
  rent or share it, and we store nothing about you beyond your email, your name if you gave one,
  and which newsletters you chose.</div>
  <div class="q">Is this investment advice?</div>
  <div class="a">No. Both newsletters report data and news. Nothing in them is a recommendation to
  buy or sell any fund, and %COMPANY% is not a SEBI-registered adviser, research analyst or
  distributor.</div>
</div>

<div class="callout">Already subscribed? <a href="/account">Sign in to change your preferences</a>
— same one-time link, no password.</div>
</article>
%SHARED_JS%
<script>
(function(){
  var S = window.SIF;
  S.wireCards('sub');
  var form = S.el('subform'), msg = S.el('sub-msg'), go = S.el('sub-go');
  form.addEventListener('submit', async function(e){
    e.preventDefault();
    var email = S.el('sub-email').value.trim();
    var sif = S.el('sub-sif_weekly').checked, news = S.el('sub-news_daily').checked;
    if(!email){ S.say(msg,'err','Please enter your email address.'); return; }
    if(!sif && !news){ S.say(msg,'err','Pick at least one newsletter.'); return; }
    go.disabled = true; S.say(msg,'','Sending your confirmation link…');
    var r = await S.api('/api/auth/request', { method:'POST', body: JSON.stringify({
      email: email,
      name: S.el('sub-name').value.trim(),
      source: 'subscribe',
      lists: { sif_weekly: sif, news_daily: news },
      news_scope: S.scope('sub'),
      company: form.company.value
    })});
    go.disabled = false;
    if(r.ok){
      form.querySelector('.authbox').innerHTML =
        '<h3 style="margin:0 0 6px">Check your inbox</h3>' +
        '<p style="margin:0;color:var(--ink-dim)">We sent a confirmation link to <b>' +
        email.replace(/[<>&]/g,'') + '</b>. Click it and you are subscribed. ' +
        'The link is valid for 15 minutes — if it does not arrive, look in spam.</p>';
    } else {
      S.say(msg,'err', (r.body && r.body.error) || 'Something went wrong. Please try again, or email ' +
        '<a href="mailto:%EMAIL%">%EMAIL%</a>.');
    }
  });
})();
</script>"""


# ----------------------------------------------------------------------------- /account

ACCOUNT = """<article class="doc">
<h1>Your SIFintel preferences</h1>
<p class="lede">Choose what we send you. Changes take effect from the next edition.</p>

<div class="alert" id="acc-flash" hidden></div>

<!-- Signed out: ask for a link. -->
<div id="acc-signin" hidden>
  <div class="authbox">
    <h3 style="margin:0 0 4px">Sign in</h3>
    <p style="margin:0 0 14px;color:var(--ink-dim);font-size:14.5px">Enter your email and we will send
    you a one-time sign-in link. There is no password.</p>
    <form id="signinform" novalidate>
      <div class="field"><label for="acc-email">Email</label>
        <input id="acc-email" name="email" type="email" autocomplete="email" required
               placeholder="you@company.com"></div>
      <div style="position:absolute;left:-5000px" aria-hidden="true">
        <input name="company" tabindex="-1" autocomplete="off"></div>
      <button class="btn" type="submit" id="acc-go">Email me a link</button>
      <div class="alert" id="acc-msg" hidden></div>
    </form>
    <p class="meta" style="margin:14px 0 0">Not subscribed yet? <a href="/subscribe">Start here</a>.</p>
  </div>
</div>

<!-- Signed in: the actual preferences. -->
<div id="acc-prefs" hidden>
  <div class="authbox">
    <p class="whoami">Signed in as <b id="acc-who"></b></p>
    <div class="optlist">
%OPTIONS%
    </div>
    <button class="btn" id="acc-save">Save preferences</button>
    <button class="btn ghost" id="acc-out" style="margin-left:8px">Sign out</button>
    <div class="alert" id="acc-saved" hidden></div>
    <p class="meta" style="margin:16px 0 0">Want out entirely? Untick both and save — or
    <a href="#" id="acc-unsub">unsubscribe from everything</a>.</p>
  </div>
</div>

<div id="acc-loading"><p class="meta">Loading your preferences…</p></div>
</article>
%SHARED_JS%
<script>
(function(){
  var S = window.SIF;
  var params = new URLSearchParams(location.search);

  // Explain how we got here. `e` comes from a failed magic-link redemption; `welcome` from a
  // successful one. "used" is the common, benign case — mail scanners follow links first.
  var REASONS = {
    missing:'That link was incomplete. Request a fresh one below.',
    unknown:'That sign-in link is not valid. Request a fresh one below.',
    used:'That sign-in link had already been used. They work once — here is a new one.',
    expired:'That sign-in link expired. Links last 15 minutes — request another below.'
  };
  var flash = S.el('acc-flash');
  if(params.get('e')) S.say(flash,'warn', REASONS[params.get('e')] || REASONS.unknown);
  else if(params.get('welcome')) S.say(flash,'ok','<b>You are in.</b> Set what you would like to receive below.');

  function show(which){
    ['acc-signin','acc-prefs','acc-loading'].forEach(function(id){ S.el(id).hidden = (id !== which); });
  }

  function fill(user){
    S.el('acc-who').textContent = user.email;
    S.el('acc-sif_weekly').checked = !!user.prefs.sif_weekly;
    S.el('acc-news_daily').checked = !!user.prefs.news_daily;
    var radio = document.querySelector('input[name="acc-news_scope"][value="' + user.prefs.news_scope + '"]');
    if(radio) radio.checked = true;
    S.wireCards('acc');
  }

  async function load(){
    var r = await S.api('/api/account');
    if(r.ok && r.body.user){ fill(r.body.user); show('acc-prefs'); }
    else { show('acc-signin'); }
  }

  // --- signed out: request a link
  var form = S.el('signinform'), msg = S.el('acc-msg'), go = S.el('acc-go');
  form.addEventListener('submit', async function(e){
    e.preventDefault();
    var email = S.el('acc-email').value.trim();
    if(!email){ S.say(msg,'err','Please enter your email address.'); return; }
    go.disabled = true; S.say(msg,'','Sending…');
    var r = await S.api('/api/auth/request', { method:'POST',
      body: JSON.stringify({ email: email, source:'account', company: form.company.value }) });
    go.disabled = false;
    if(r.ok) S.say(msg,'ok','<b>Check your inbox.</b> We sent a sign-in link to ' +
      email.replace(/[<>&]/g,'') + '. It is valid for 15 minutes.');
    else S.say(msg,'err',(r.body && r.body.error) || 'Could not send the link. Please try again.');
  });

  // --- signed in: save
  S.el('acc-save').addEventListener('click', async function(){
    var btn = this, saved = S.el('acc-saved');
    btn.disabled = true; S.say(saved,'','Saving…');
    var r = await S.api('/api/account', { method:'POST', body: JSON.stringify({
      sif_weekly: S.el('acc-sif_weekly').checked,
      news_daily: S.el('acc-news_daily').checked,
      news_scope: S.scope('acc')
    })});
    btn.disabled = false;
    if(r.ok){
      var none = !S.el('acc-sif_weekly').checked && !S.el('acc-news_daily').checked;
      S.say(saved,'ok', none
        ? '<b>Saved.</b> You are unsubscribed from everything. Tick a box and save to start again.'
        : '<b>Saved.</b> Your preferences are updated.');
    } else {
      S.say(saved,'err',(r.body && r.body.error) || 'Could not save. Please try again.');
    }
  });

  S.el('acc-out').addEventListener('click', async function(){
    await fetch('/api/auth/logout', { method:'POST' });
    location.href = '/account';
  });

  S.el('acc-unsub').addEventListener('click', async function(e){
    e.preventDefault();
    var r = await S.api('/api/account');
    location.href = (r.ok && r.body.unsubscribe_url) ? r.body.unsubscribe_url : '/unsubscribe';
  });

  load();
})();
</script>"""


# -------------------------------------------------------------------------------- /auth

AUTH = """<article class="doc">
<h1>Signing you in…</h1>
<div class="authbox">
  <div class="alert" id="auth-msg">Checking your link…</div>
  <!-- No-JS fallback. Also the reason redemption is a POST: mail scanners and link-preview
       bots issue GETs and never run scripts, so they cannot burn a one-time token. -->
  <noscript>
    <form method="post" action="/api/auth/verify" id="auth-form">
      <input type="hidden" name="t" id="auth-t-nojs">
      <p style="color:var(--ink-dim)">JavaScript is off. Press the button to finish signing in.</p>
      <button class="btn" type="submit">Complete sign-in</button>
    </form>
  </noscript>
</div>
</article>
%SHARED_JS%
<script>
(function(){
  var S = window.SIF;
  var msg = S.el('auth-msg');
  var token = new URLSearchParams(location.search).get('t');
  if(!token){
    S.say(msg,'err','That link is incomplete. <a href="/account">Request a new sign-in link</a>.');
    return;
  }
  (async function(){
    var r = await S.api('/api/auth/verify', { method:'POST', body: JSON.stringify({ t: token }) });
    if(r.ok){
      // Replace the history entry so the token is not left in the back button or in a shared URL.
      location.replace(r.body.next || '/account?welcome=1');
    } else {
      S.say(msg,'err',(r.body && r.body.error) ||
        'That link could not be used. <a href="/account">Request a new one</a>.');
    }
  })();
})();
</script>"""


# ------------------------------------------------------------------------- /unsubscribe

UNSUBSCRIBE = """<article class="doc">
<h1>Unsubscribe</h1>
<div id="un-body">
  <div class="authbox" id="un-card">
    <div class="alert" id="un-msg">Checking your link…</div>
    <div id="un-actions" hidden>
      <p class="whoami">Subscription for <b id="un-email"></b></p>
      <p style="color:var(--ink-dim);font-size:14.5px;margin:10px 0 16px">
        You can stop everything, or keep the one you still want.</p>
      <button class="btn" id="un-all">Unsubscribe from everything</button>
      <a class="btn ghost" href="/account" style="margin-left:8px;text-decoration:none">Choose what to keep</a>
    </div>
  </div>
</div>
<p class="meta">Changed your mind later? You can <a href="/subscribe">resubscribe</a> at any time.</p>
</article>
%SHARED_JS%
<script>
(function(){
  var S = window.SIF;
  var msg = S.el('un-msg'), actions = S.el('un-actions');
  var token = new URLSearchParams(location.search).get('u');
  var list  = new URLSearchParams(location.search).get('l');

  if(!token){
    S.say(msg,'warn','This page needs the unsubscribe link from one of our emails. ' +
      'You can also <a href="/account">sign in and change your preferences</a>.');
    return;
  }

  (async function(){
    // Deliberately does NOT unsubscribe on load — a mail scanner prefetching the link would
    // otherwise opt people out without them ever clicking. Confirmation happens on the POST.
    var r = await S.api('/api/unsubscribe?u=' + encodeURIComponent(token));
    if(!r.ok){
      S.say(msg,'err',(r.body && r.body.error) || 'That unsubscribe link is not valid.');
      return;
    }
    S.el('un-email').textContent = r.body.email;
    S.hide(msg);
    actions.hidden = false;

    // If the email named a specific list, offer to leave just that one first.
    if(list && r.body.lists && r.body.lists[list]){
      var only = document.createElement('button');
      only.className = 'btn';
      only.textContent = 'Stop only ' + r.body.lists[list];
      only.addEventListener('click', function(){ go(list); });
      var all = S.el('un-all');
      all.className = 'btn ghost';
      all.parentNode.insertBefore(only, all);
    }
  })();

  async function go(which){
    var r = await S.api('/api/unsubscribe', { method:'POST',
      body: JSON.stringify({ u: token, l: which || '' }) });
    S.el('un-card').innerHTML = r.ok
      ? '<h3 style="margin:0 0 6px">Done</h3><p style="margin:0;color:var(--ink-dim)">' +
        (r.body.message || 'You have been unsubscribed.') +
        ' Sorry to see you go — you can <a href="/subscribe">come back</a> whenever you like.</p>'
      : '<div class="alert err">Could not complete that. Please email ' +
        '<a href="mailto:%EMAIL%">%EMAIL%</a> and we will remove you by hand.</div>';
  }

  S.el('un-all').addEventListener('click', function(){ go(''); });
})();
</script>"""


def page(template, options_prefix):
    """Fill the placeholders. Plain strings + replace (not f-strings) so the inline JS braces
    do not have to be escaped — same approach build_site.py uses for the contact form."""
    return (template
            .replace("%OPTIONS%", option_cards(options_prefix))
            .replace("%SHARED_JS%", SHARED_JS)
            .replace("%EMAIL%", EMAIL)
            .replace("%COMPANY%", COMPANY))


def main():
    # The account pages carry no SEO value and must never be indexed: /auth and /unsubscribe
    # contain single-use tokens in the URL, and an indexed token is a leaked one.
    noindex = '<meta name="robots" content="noindex,nofollow">'

    build("subscribe.html",
          "Subscribe free — SIF Weekly & the Morning Brief | SIFintel",
          "Two free newsletters on India's Specialized Investment Funds: a weekly data digest on "
          "every SIF, and a weekday morning brief on the financial news that matters. No password, "
          "one-click unsubscribe.",
          KW + ", SIF newsletter, SIF weekly, financial news newsletter India",
          f"{SITE}/subscribe", "home",
          [("Home", "/"), ("Subscribe", None)],
          page(SUBSCRIBE, "sub"),
          '{"@context":"https://schema.org","@type":"WebPage","name":"Subscribe to SIFintel",'
          '"description":"Free SIF and financial-news newsletters.","inLanguage":"en-IN"}',
          ogtype="website")

    for outp, slug, title, desc, tpl, prefix, crumb in [
        ("account.html", "account", "Your preferences | SIFintel",
         "Manage which SIFintel newsletters you receive.", ACCOUNT, "acc", "Preferences"),
        ("auth.html", "auth", "Signing in | SIFintel",
         "Completing your SIFintel sign-in.", AUTH, "auth", "Sign in"),
        ("unsubscribe.html", "unsubscribe", "Unsubscribe | SIFintel",
         "Unsubscribe from SIFintel newsletters.", UNSUBSCRIBE, "un", "Unsubscribe"),
    ]:
        build(outp, title, desc, KW, f"{SITE}/{slug}", "home",
              [("Home", "/"), (crumb, None)],
              page(tpl, prefix),
              '{"@context":"https://schema.org","@type":"WebPage","name":' + f'"{crumb}"'
              + ',"inLanguage":"en-IN"}',
              ogtype="website")
        # build() does not take a robots override, so patch the tag in afterwards. Cheaper than
        # threading a parameter through a template shared with every other page on the site.
        full = os.path.join(ROOT, outp)
        with open(full, encoding="utf-8") as f:
            html = f.read()
        html = html.replace('<meta name="robots" content="index,follow,max-image-preview:large">', noindex)
        with open(full, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"   -> {outp} marked noindex")

    print("DONE — 4 account pages built")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
