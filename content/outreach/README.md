# Outreach drafts — for a human to send

**Nothing in this folder has been sent.** These are drafts for Aditi Bariar (or Rohit) to send from
their own mail account, signed by whoever actually sends it. They are not published to the site
(`robots.txt` disallows `/content/`, and no page links here).

Two campaigns, aimed at the 30-day revenue target:

| File | Target | Ask | Deal size |
| --- | --- | --- | --- |
| `01-data-licensing.md` | AMCs running SIFs, wealth platforms, research desks | Free API key → paid feed | ₹8k–20k/month |
| `02-white-label.md` | AMCs without a comparison tool, large distributors | 20-minute call | ₹85k–3L one-off |

## How to work this

1. **Build the list first.** All 17 SIF fund houses are already in `nav_data.json` — every one of them
   is a qualified prospect, because the site already tracks their funds and they know they are on it.
   `python -c "import json;d=json.load(open('nav_data.json'));print('\n'.join(sorted({s['sif'] for s in d['schemes']})))"`
2. **Lead with the thing they can check.** Every draft opens with a link to their own funds on the
   live site. That is the credibility, and it costs them nothing to verify.
3. **Send 5–8 a day, personally.** Not a blast. Reply rates on a list this small come from the
   sender clearly having looked at the recipient's funds.
4. **Log replies** so the follow-up (day 4, then day 10) is warm rather than repetitive.

## Do not

- Do not claim SIFintel rates, ranks or recommends anyone's fund — the site says the opposite on
  every page, and a prospect will read it.
- Do not offer paid placement or "featured fund" slots. Independence is the product; selling
  visibility destroys the thing being sold.
- Do not send from a mailbox that isn't the sender's own. These drafts are signed by a person for a
  reason.
