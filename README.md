# PadelPal

A racket advisor for South African padel players. Describe your level,
how you play, your budget, and any arm problems — it recommends three
rackets from a catalogue of real South African retailer listings and
explains why each one suits you, in plain English.

It is not a general padel chatbot. It does one job: given a shortlist
Python has already filtered and scored, an AI model explains the
tradeoffs. See [PRODUCT.md](PRODUCT.md) for the full product reasoning
and [ARCHITECTURE.md](ARCHITECTURE.md) for the technical design.

## How it works, in one paragraph

**Python filters. The AI explains.** The catalogue (521 rackets) is
loaded into memory once at startup. A player's answers run through
hard filters (budget, level, arm-safety) and soft scoring (style fit,
availability, budget comfort) entirely in Python — deterministic,
free, and incapable of inventing a racket that doesn't exist. Only the
resulting shortlist (6-25 rackets, never the whole catalogue) goes to
Gemini, which picks and explains three. Getting this split wrong —
asking a model to do retrieval and reasoning at once — is the most
common failure mode in AI apps; this project is built specifically to
avoid it.

## Running it locally

```bash
git clone <this repo>
cd padelbot

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# then open .env and fill in GEMINI_API_KEY at minimum - see below

python app.py
```

Visit `http://127.0.0.1:5000`. On macOS, if that doesn't respond, port
5000 is sometimes already claimed by AirPlay Receiver (System
Settings → General → AirDrop & Handoff) - set `PORT=5001` in `.env` and
visit `http://127.0.0.1:5001` instead.

### Running the tests

```bash
pytest
```

43 tests, all against the real catalogue CSV, no mocked data. See
`tests/test_recommender.py` in particular — those are the tests that
actually verify the product works, per ARCHITECTURE.md.

## Environment variables

All read by `config.py`. Copy `.env.example` to `.env` and fill these
in — `.env` is gitignored and must never be committed.

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google Gemini API key. Get one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Without this, `/api/recommend` returns a clear 502 rather than crashing. |
| `FLASK_SECRET_KEY` | Recommended | Signs Flask's session cookies. Generate one with `python -c "import secrets; print(secrets.token_hex(32))"`. Falls back to an insecure dev-only default if unset - fine locally, not for a deployed instance. |
| `FLASK_ENV` | No | `development` (default) enables Flask's debug mode and detailed error pages. Set to `production` when deployed - Render's config does this automatically. |
| `PORT` | No | Which port the local dev server binds to. Defaults to `5000`. Not used in production - Render assigns this itself and gunicorn reads it directly. |

## Project structure

```
padelbot/
  app.py                    Flask entry point - two routes, input validation, nothing else
  config.py                 reads all environment variables in one place
  render.yaml               Render deployment config, checked into git
  services/
    catalogue.py             loads and type-converts the CSV once, at import time
    recommender.py           hard filters + soft scoring + diversity - the actual product, no AI
    ai.py                    the only file that talks to Gemini
  data/
    rackets_catalogue.csv    521 rackets, 7 South African retailers
  templates/
    index.html                the one page, enum options rendered from recommender.py's constants
  static/
    style.css, script.js      no framework, no build step, no CDN
  scripts/
    try_recommendation.py     manual terminal check of the full pipeline, no web layer needed
  tests/
    test_catalogue.py, test_recommender.py, test_ai.py
```

## Deploying to Render

The whole deploy config lives in `render.yaml` (Render's "Blueprint"
format), so most of this is a few clicks rather than manual dashboard
setup:

1. Push this repo to GitHub.
2. In the Render dashboard: **New → Blueprint**, point it at the repo.
   Render reads `render.yaml` and proposes the service.
3. Render will prompt for the two variables marked `sync: false` in
   `render.yaml` - paste in your real `GEMINI_API_KEY` and a generated
   `FLASK_SECRET_KEY` (same command as above). These are typed directly
   into Render's dashboard, never committed to the repo.
4. Deploy. First build takes a few minutes; every push to the branch
   Render is tracking redeploys automatically afterwards.

Render's free tier spins a service down after 15 minutes with no
traffic, and the next request pays a ~30-60 second cold start to boot
it back up. For a portfolio project you're actively sending people to,
consider pinging the service every 10 minutes with a free uptime
monitor (e.g. UptimeRobot / cron-job.org hitting `GET /`) for the
period you're actually sharing the link, rather than upgrading to a
paid instance you don't need the rest of the time.

## What's deliberately not built (yet)

No auth, no database, no chat history storage, no RAG. Every one of
these is a deliberate scope cut, not an oversight - see
[ARCHITECTURE.md](ARCHITECTURE.md#what-is-deliberately-absent-from-v1)
for the reasoning behind each.
