# PadelPal - Architecture

## The one decision that shapes everything

Python filters. The AI explains.

The catalogue has 521 rackets. Pasting it into a prompt would be roughly
60,000 tokens per message: slow, expensive, and the model would lose
track of it anyway.

So the work splits:

- **Python** decides *which* rackets are candidates. Deterministic, free,
  instant, testable, and it cannot hallucinate a racket that does not
  exist.
- **The AI** decides *which of those* to recommend and explains why in
  language a human wants to read.

Getting this split wrong is the single most common failure in AI apps.
People ask the model to do retrieval and reasoning at once, then wonder
why it invents products and costs a fortune.

## Components

```
Browser (HTML/CSS/JS)
    |  HTTP POST, JSON
    v
Flask
    |-- routes.py        receives requests, returns responses
    |-- recommender.py   filters and scores the catalogue   <- the product
    |-- ai.py            talks to the model
    |-- catalogue.py     loads the CSV into memory at startup
    v
Gemini API (or Claude)
```

### catalogue.py

Reads `rackets_catalogue.csv` once when Flask boots and keeps it as a
list of dictionaries in memory.

Why not a database yet: 521 rows is about 300KB. Loading it at startup
takes milliseconds and every lookup is a list comprehension. A database
adds connection handling, migrations and a deployment dependency to solve
a problem you do not have. Move to Supabase when you need writes, not
before.

### recommender.py

The heart of the app. No AI in this file at all.

Takes a player profile:

```python
{
  "level": "improver",
  "side": "left",
  "style": "defensive",
  "budget_max": 4000,
  "arm_issues": True
}
```

Returns a shortlist of 6 to 8 rackets, scored.

Two stages:

**Hard filters** remove anything disqualified. Over budget, out of the
level band, and if `arm_issues` is true, anything with a hard core or
high-grade carbon. These are non-negotiable, so they run first.

**Soft scoring** ranks what is left. Points for matching profile to
playing style, for being stocked at multiple stores, for being in stock
rather than order-in, for sitting comfortably inside budget rather than
at the ceiling.

Being explicit about which rules are hard and which are soft is what
makes the system testable. You can write a test asserting no hard-core
racket ever reaches someone with elbow pain, and that test will hold
regardless of what the model does.

### ai.py

One function: given the player profile and the shortlist, return three
picks with explanations.

The shortlist goes into the prompt as compact text, not the whole CSV.
Eight rackets is maybe 400 tokens.

The system prompt carries the domain knowledge: what shapes mean, what
core hardness does to the arm, how balance affects manoeuvrability. That
is what turns a list into advice.

Everything about which model you call lives in this one file. Switching
from Gemini to Claude is a one-file change.

### routes.py

Thin. Reads JSON, calls the recommender, calls the AI, returns JSON.
If a route function grows past about 20 lines, logic has leaked into it
and belongs in a service file.

## Request flow

```
1. User answers the form in the browser
2. JS sends POST /api/recommend with the profile as JSON
3. Flask validates the input
4. recommender.py filters 521 -> ~8
5. ai.py sends profile + 8 rackets to the model
6. Model returns 3 picks with reasons
7. Flask returns JSON
8. JS renders three cards
```

Steps 4 and 5 are the whole architecture. Everything else is plumbing.

## Data flow for follow-up chat

After the first recommendation, the user can ask questions. The
conversation history plus the same shortlist gets sent each time. The
model has no memory of its own, so you send the context every call.

Keep the shortlist pinned across the conversation. If the user says
"what about something cheaper", re-run the filter with a lower budget
rather than letting the model invent options.

## Why not RAG

RAG solves the problem of too much unstructured text to fit in a prompt.
Your data is structured: 521 rows with clean columns. A filter answers
"which rackets suit this person" perfectly and for free. Embeddings would
answer it worse, slower and at a cost.

RAG becomes right when you add technique and coaching content, which is
genuinely unstructured. Not for the catalogue.

## Cost control

- Filtering in Python means the prompt stays small. Roughly 1,200 tokens
  in, 400 out per recommendation.
- Gemini Flash free tier covers 1,500 requests a day, more than enough.
- Cache the system prompt string; do not rebuild it per request.
- The follow-up chat is where cost creeps in, since history grows. Cap
  it at the last 8 messages.

## What is deliberately absent from V1

| Not building | Why |
|---|---|
| Auth | Nothing to protect yet |
| Database | CSV in memory is sufficient |
| Chat history storage | Session state is fine |
| Admin panel | You edit the CSV directly |
| RAG | Structured data does not need it |
| Analytics | Add it when there are users |

Every one of these is easy to add later and none of them is needed to
prove the product works.

## File layout

```
padelbot/
  app.py                  Flask entry point
  config.py               settings, reads .env
  services/
    catalogue.py          loads the CSV
    recommender.py        filtering and scoring
    ai.py                 model calls
  data/
    rackets_catalogue.csv
  templates/
    index.html
  static/
    style.css
    script.js
  tests/
    test_recommender.py   the tests that actually matter
  .env                    secrets, never committed
  .gitignore
  requirements.txt
```

## Scaling later, in order of when it becomes necessary

1. **Supabase** when you want saved conversations or user accounts.
2. **Scheduled re-scrape** so prices do not go stale. A weekly cron.
3. **Multi-tenant config** if a retailer wants their own branded version.
   Same pattern as any per-client theming: one config object per tenant,
   one deployment pointing at the same codebase.
4. **RAG** when you add coaching and technique content.
