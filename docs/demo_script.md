# Three-minute demo script

One run-through, timed. The rule for the whole three minutes: **never say a number without showing
where it came from.** That is the product, and a demo that recites figures is a demo of any
dashboard.

Open with the site already loaded on `/`, a second tab on `/ask`, and the phone ready if the room
has a screen for it.

---

## 0:00 – 0:25 · The problem, and the banner

> "If you are buying an apartment in Dubai, the Land Department publishes every transaction. That
> data is public and effectively unusable — it is records, not yields. The portals that do compute
> yields will not show you their working."

Point at the banner across the top.

> "Second thing, and I want it out of the way first: these figures are generated, not real. The
> portal refuses automated clients from every network I could reach, and I have the probe logs.
> Everything you are about to see is the machinery; loading a real drop changes every number and
> no code."

*Getting this in first is worth 25 seconds. An examiner who spots it themselves at 2:30 stops
listening to everything before it.*

## 0:25 – 1:05 · The claim that makes this different

Land on the city view, communities as hex cells. Click one.

> "Median price per square metre for this community."

Click the tile. The drawer opens.

> "That is the actual SQL. Not a description of the query — the query. Copy it, run it against the
> database, you get the number on the tile."

Point at the `n=` chip and the confidence dot.

> "Sample size, and how confident that makes the figure."

Filter to something thin. The cell says *insufficient data* instead of a number.

> "It refuses. A number with a caveat next to it still gets read as a number, so at low confidence
> it does not print one."

## 1:05 – 1:45 · The models

`/areas/[key]` — the valuation card.

> "Gradient boosting, trained on a time split with 2025 held out, because a random split lets the
> model see the future and reports an accuracy it will never achieve."

Point at the contribution bars.

> "These are not global importances. They decompose *this* valuation, and they sum to it."

`/forecast`.

> "Twelve months out, and the only question worth asking of a forecast is whether it beats doing
> nothing — so it is scored against a seasonal naive benchmark, per area, and that comparison is
> the gate."

*If time is tight, cut the forecast, not the contributions.*

## 1:45 – 2:30 · The agents, and what they cannot do

`/crew`. Run it. While it runs:

> "Six agents. A valuer, a yield analyst, a risk auditor, an advisor that writes the memo, and an
> auditor that checks the run."

The memo renders with citations, and the disagreement panel.

> "Every factual sentence carries a citation or the memo is withheld. And where the valuer and the
> risk auditor disagree, it shows the disagreement rather than averaging it away."

Then the point to land:

> "The advisor is granted zero tools. Not restricted — zero. It cannot query, cannot write, cannot
> reach the network. It works only from what the analysts already established, so there is no
> prompt that gets it to do something else, because there is nothing to do."

## 2:30 – 3:00 · The red team, and the close

`/security`.

> "That is not a description of controls. Those are ten attacks that ran, on this build. A poisoned
> document telling the model to ignore its instructions and recommend buying. A forged message on
> the agent bus. A budget flood."

> "One of them failed the first time I ran it. The rule says every factual sentence in a memo needs
> a citation, and nothing was actually checking it — the auditor only rejected a memo that cited
> nothing at all. That is now enforced, and the attack is what found it."

Close:

> "Zero inference cost, and the whole thing is one data source away from being real."

---

## Questions to expect straight after

- *"So none of this is real?"* → Q2 in `docs/viva_qa.md`. The honest answer, plus the guard.
- *"Why does the advisor have no tools?"* → Q10.
- *"What is the weakest part?"* → Q14, and say the data before they do.

## If something breaks

The API sleeps after 15 minutes on the free tier and takes about 50 seconds to wake. **Load the
site once before you present.** If a panel shows an error, say what it is — an unreachable API
returns a 502 naming which service is down — and move on. A demo that degrades visibly is better
evidence than one that never fails.
