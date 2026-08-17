# PadelPal - Product Definition

## What this is

A racket advisor for South African padel players. You describe your level,
how you play, your budget and any arm problems. It recommends three
rackets and explains why each one suits you.

It is not a general padel chatbot. It does one job properly.

## The problem

Someone new to padel lands on a store page with 80 rackets. Every one is
described as "premium performance". They have no way to tell a diamond
from a round, do not know that a stiff carbon frame can hurt their elbow,
and end up buying on brand or price alone. Often the wrong racket.

The existing tools are filters dressed up as quizzes. Pick a level, pick a
budget, get a list. They cannot handle "I keep getting elbow pain" or
"I play the left side and mostly defend", which is what people actually
want to say.

## Who it is for

Primary: a South African player, 25 to 45, six months to three years into
the sport, upgrading from a starter racket, budget R2,500 to R6,000.
They know they want something better. They do not know what.

Secondary: a complete beginner buying their first proper racket.

Not for: professionals, who already know exactly what they want.

## What it does

1. Asks a short set of questions: level, side of court, style, budget,
   any arm or elbow issues.
2. Filters the catalogue in Python down to genuine matches.
3. Sends the shortlist to an AI model with the player's answers.
4. Returns three recommendations with a plain-English reason for each.
5. Allows follow-up questions in conversation.

## What it deliberately does not do

- Live match scores or player rankings. Those go stale and an AI will
  make them up. Wrong tool for the job.
- Court booking. Playtomic already does this well.
- Coaching video analysis. Different product entirely.
- Selling. It recommends and links out. It does not take payment.

## The catalogue

521 rackets from seven South African retailers.

| Field | Coverage | Notes |
|---|---|---|
| shape | 93% | round, teardrop, diamond |
| profile | 93% | control, hybrid, power |
| core | 95% | soft EVA through hard EVA |
| surface | 93% | fibreglass through 18K carbon |
| price | 100% | ZAR, lowest across stores |
| level | 100% | derived from price band |
| weight | 75% | often a range, not exact |
| balance | 77% | low, medium, high |

Levels: beginner 94, improver 224, intermediate 147, advanced 56.
Profiles: control 209, power 175, hybrid 100.

Specs marked `inferred` in `spec_source` come from model-line rules, not
the store listing. Good enough to recommend on. Not good enough to
publish as a spec sheet.

**`spec_source` understates this.** The rows it marks as store data for
`shape` were not read off a spec sheet either - they came from an
earlier, cruder pass that keyword-matched "round" / "teardrop" /
"diamond" inside the product description text. That method is wrong
often enough to matter: it's why Head Gravity Pro is labelled round in
this catalogue when Head sells it as a teardrop. So in practice,
`shape`, `core` and `surface` are inferred throughout the catalogue,
`spec_source` or not - there is no tier of this data confirmed by a
manufacturer spec sheet. Treat these three fields as good enough to
rank candidates on, never as a fact to state to a player. Price, brand,
level and availability are real store data and don't have this problem.

## The domain logic

This is the actual product. The mapping from player to racket:

| Player says | Points toward |
|---|---|
| Beginner | round shape, soft core, large sweet spot, under R2,500 |
| Improver | round or teardrop, soft to medium core |
| Plays left side | control, lower balance, round or teardrop |
| Plays right side, finishes points | diamond, high balance, harder core |
| Elbow or shoulder pain | soft EVA, fibreglass or low-grade carbon, lighter |
| Wants more power | diamond, high balance, hard core |
| Struggles to control the ball | round, low balance, soft core |
| Plays twice a week or more | durability matters, avoid cheapest tier |

The rule that matters most: **arm pain overrides everything.** If someone
mentions elbow or shoulder problems, no stiff 18K carbon diamond racket
gets recommended regardless of their level or stated preference.

## Honesty rules

The advisor must be willing to say things that lose a sale:

- If their current racket is fine, say so.
- If elbow pain sounds like technique rather than equipment, suggest a
  lesson before a purchase.
- If nothing in budget genuinely suits them, say that rather than forcing
  a recommendation.
- Never claim a spec it does not have. Blank means blank.

An advisor that sometimes says "do not buy" is the only kind worth
trusting, and it is the only version worth putting a retailer's name on.

## How it is judged

Not by conversation quality. By whether the recommendations are right.

Test: write 10 player profiles with known correct answers. A beginner
with elbow pain and R2,000. An advanced right-side player wanting power.
Run each through the system. Count how many return sensible rackets.

Under 8 out of 10 means the prompt or the filter needs work, not the UI.

## Success looks like

V1: it gives advice a knowledgeable player would agree with.
V2: 20 real people use it and the recommendations hold up.
V3: a retailer wants it on their site.
