# PadelPal - Build Prompts for Claude Code

Run these in order from inside the `padelbot` folder. Each sprint ends
with something you can run and check yourself. Do not start a sprint
until the previous one works.

Before you begin: put `PRODUCT.md`, `ARCHITECTURE.md` and
`rackets_catalogue.csv` in the folder. Claude Code will read them.

---

## The standing instruction

Paste this once at the start of every session. It sets the mode for
everything that follows.

```
I am a final-year CS student. You are writing the code for this project.
My goal is not to type it myself, it is to understand it well enough to
maintain it, debug it, extend it, and explain it in a job interview.

So for every file you write:

1. Before writing, tell me in two or three sentences what this file is
   responsible for and what it deliberately does not do.
2. Write the code with comments in plain English aimed at someone new to
   backend development. Explain what each part does and why.
3. After writing, walk me through the flow of the file from top to
   bottom, as if explaining it to a new team member.
4. Call out any decision where a reasonable engineer might have chosen
   differently, and say why you went the way you did.
5. Flag anything that is a shortcut or a simplification we will need to
   revisit later.

When I ask "why", give me the real reason, including the tradeoff. Do not
just tell me it is best practice.

If I seem to have misunderstood something in my instructions, say so
rather than building what I asked for.
```

---

## Sprint 0 - Project setup

```
Read PRODUCT.md and ARCHITECTURE.md in this folder. They define what we
are building and why.

My venv already exists and is activated.

Set up the project skeleton described in ARCHITECTURE.md:
- the folder structure
- requirements.txt with flask, python-dotenv, google-genai, pytest
- .env.example showing which variables are needed (do not create .env)
- .gitignore covering .env, venv/, __pycache__/, .DS_Store
- config.py that loads environment variables
- move rackets_catalogue.csv into data/
- git init and an initial commit

Do not write any application logic yet. Just the skeleton.

Then explain the structure to me: why the services folder exists, why
config.py is separate from app.py, and what would go wrong if I put my
API key in config.py directly instead of reading it from .env.
```

**Check before moving on:** `pip install -r requirements.txt` succeeds,
`git status` shows `.env` is ignored.

---

## Sprint 1 - The catalogue

```
Build services/catalogue.py.

It should:
- load data/rackets_catalogue.csv once, at import time, into a list of
  dictionaries
- convert price_zar and stores_count to integers, handling blanks safely
- convert weight_g to an integer where it is a single number, and leave
  ranges like "360-375" as a string
- expose a get_all() function and a stats() function that returns counts
  by level, profile and brand

Write tests/test_catalogue.py checking that the catalogue loads, that
there are over 500 rackets, that no price is zero or negative, and that
every racket has a name and brand.

Then show me how to run the tests, and print the stats so I can see what
loaded.

Explain why we are loading a CSV into memory rather than using a
database at this stage.
```

**Check:** tests pass, stats print sensible numbers matching ARCHITECTURE.md.

---

## Sprint 2 - The recommender (the important one)

This is the product. Spend real time here.

```
Build services/recommender.py. This file contains no AI and makes no
network calls. Pure Python.

It takes a player profile:
{
  "level": "beginner" | "improver" | "intermediate" | "advanced",
  "side": "left" | "right" | "either",
  "style": "defensive" | "balanced" | "aggressive",
  "budget_max": integer in rand,
  "budget_min": optional integer,
  "arm_issues": boolean,
  "frequency": "occasional" | "weekly" | "often"
}

Two stages, kept clearly separate in the code.

HARD FILTERS - these disqualify, and run first:
- price must be within budget
- level must be within one band of the player's level (an improver can
  see beginner and intermediate rackets, not advanced)
- if arm_issues is true: exclude hard EVA cores, exclude 18K and 15K
  carbon surfaces, exclude diamond shapes
- exclude rackets with a blank shape (we cannot advise on what we do not
  know)

SOFT SCORING - ranks whatever survives:
- profile matching style (aggressive prefers power, defensive prefers
  control, balanced prefers hybrid)
- side of court (left leans control, right leans power)
- availability: high scores above medium scores above low
- stock_status: in stock scores above order in
- budget fit: sitting comfortably inside budget scores above sitting at
  the ceiling
- frequency: for often, penalise the cheapest tier on durability

DIVERSITY - applied after scoring, before returning:
- maximum 3 rackets per brand
- maximum 2 per model line (derive the line from the first two
  significant words of the name)
- spread across price bands within the budget
- include at least one racket from each profile that was not
  hard-filtered out, so we can offer an alternative direction

Return up to 25 rackets. Fewer is fine when fewer genuinely match. Never
pad with poor matches to hit the number.

Make the scoring weights constants at the top of the file so I can tune
them without hunting through the code.

Explain the reasoning behind the hard versus soft split as you build it.
```

Then, in the same sprint:

```
Write tests/test_recommender.py covering these player profiles, with
assertions about what must and must not appear:

1. Complete beginner, R2000, no issues
2. Beginner with elbow pain, R2000
3. Improver, left side, defensive, R4000
4. Improver, right side, aggressive, R4000
5. Improver with elbow pain, R4000
6. Intermediate, balanced, R6000
7. Intermediate, aggressive, right side, R6000
8. Advanced, aggressive, R9000
9. Someone with a very low budget, R1200
10. Someone with an unrealistic combination: advanced, aggressive, R1500

The critical assertions:
- no result ever exceeds budget_max
- when arm_issues is true, no hard EVA, no 18K carbon, no diamond shapes
- a beginner never receives an advanced racket
- no brand appears more than 3 times
- profile 10 either returns very few results or an empty list, and the
  code handles that gracefully rather than crashing

Run the tests and show me the output. Then print the top 10 results for
profiles 3 and 5 so I can read them and judge whether the advice is
actually sensible.
```

**Check:** read the output yourself. If a beginner with elbow pain is
offered something stiff and aggressive, the rules are wrong. Fix them
before continuing. This is the step that determines whether the product
is any good.

---

## Sprint 3 - The AI layer

```
Build services/ai.py.

One main function: given a player profile and the shortlist from the
recommender, return three recommended rackets with an explanation for
each.

Use the Google Gemini API with the gemini-flash model. Read the key from
the environment via config.py. Never hardcode it.

The system prompt must carry the padel domain knowledge:
- round shapes are forgiving with a central sweet spot, suited to
  control and to beginners
- teardrop is the middle ground
- diamond puts mass high, giving power at the cost of forgiveness
- softer EVA is kinder to the arm, harder EVA gives more ball speed
- higher carbon grades are stiffer and transmit more shock
- higher balance means more power, lower means more manoeuvrability
- the left side of the court is usually the control player, the right
  side finishes points

The prompt must also carry the honesty rules from PRODUCT.md:
- recommend only from the shortlist provided, never invent a racket
- never state a spec that is not in the data
- if nothing in the shortlist genuinely suits the player, say so rather
  than forcing three picks
- if the problem sounds like technique rather than equipment, say that

Format the shortlist compactly. Do not send the description field.

Ask the model to return JSON with this shape:
{
  "picks": [
    {"name": "...", "why": "...", "tradeoff": "..."},
    ...
  ],
  "note": "optional overall comment"
}

Parse it safely, stripping markdown code fences before parsing, and
handle the case where the model returns something unparseable.

Add retry-once-on-failure and a clear error if the API key is missing.

Then write a small script I can run from the terminal that takes a
hardcoded profile, runs the recommender, calls the AI, and prints the
result. I want to see this working before we add any web layer.
```

**Check:** run it from the terminal several times with different
profiles. Are the explanations accurate? Does it ever mention a racket
not in the shortlist? Does it invent specs?

---

## Sprint 4 - Flask

```
Now wire it up. Build app.py.

Two routes:
- GET  /               serves templates/index.html
- POST /api/recommend  takes a player profile as JSON, returns the
                       recommendations as JSON

Keep the route functions thin. They validate input, call the services,
and return a response. Any logic longer than a few lines belongs in a
service file.

Validate the incoming profile properly: check required fields exist,
check budget is a positive number within a sane range, check enum values
are valid. Return a 400 with a useful message when validation fails,
never a stack trace.

Add error handling so an API failure returns a clean JSON error rather
than crashing.

Show me curl commands to test the endpoint, including a deliberately
invalid request so I can see the validation working.
```

**Check:** the curl commands work. Try sending nonsense and confirm you
get a sensible error, not a 500.

---

## Sprint 5 - Frontend

```
Build templates/index.html, static/style.css and static/script.js.

A single page:
- a short form: level, side, style, budget slider, arm issues checkbox,
  frequency
- a submit button
- a results area showing three racket cards with name, price, shape,
  the explanation, the tradeoff, and a link to the store
- a loading state while waiting
- a visible error message if the request fails

Plain HTML, CSS and JavaScript. No framework, no build step, no CDN
dependencies.

Design notes: clean and uncluttered, works on a phone, South African
rand formatting. Do not make it look like a generic bootstrap template.

Handle the case where the API returns fewer than three picks, or none.
```

**Check:** use it on your phone. Fill it in as if you were a real
beginner. Does the advice make sense?

---

## Sprint 6 - Deployment

```
Prepare this for deployment on Render's free tier.

- add gunicorn to requirements.txt
- create a Procfile or render.yaml as appropriate
- make sure config.py reads the port from the environment
- write a README.md covering what the project is, how to run it locally,
  the environment variables needed, and how the architecture works

Then walk me through deploying it, including where to set the API key in
the Render dashboard.

Warn me about anything that will behave differently in production
compared to local.
```

**Check:** it is live on a public URL. Send it to someone who plays
padel and watch them use it without helping.

---

## Sprint 7 - Follow-up conversation

Only start this once everything above works and you have shown it to
real people.

```
Add a conversational follow-up to the recommendation.

After the initial three picks, the user can ask questions like "what
about something cheaper" or "why not the Bullpadel one".

Rules:
- keep the original shortlist pinned for the conversation
- if the user changes a constraint, such as budget, re-run the
  recommender rather than letting the model invent alternatives
- cap conversation history at the last 8 messages to control cost
- the model still recommends only from the current shortlist

Add a POST /api/chat endpoint and extend the frontend with a simple
message thread below the results.
```

---

## Working notes

**Understanding is checked by prediction, not by reading.** Before
running the tests in Sprint 2, write down what you expect the top three
rackets to be for a beginner with elbow pain. Then run it. If you were
wrong, you do not understand the scoring yet, and reading the code again
will not fix that. Ask why.

**The best question to ask Claude Code is "what would break if".** What
would break if I removed the hard filter and made arm_issues a scoring
weight instead? What would break if the shortlist were 5 instead of 25?
Those answers teach you the system's shape far faster than a walkthrough.

**Change one weight and re-run the tests every sprint.** Watching results
move when you nudge a constant is how the scoring stops being a black
box.

**Commit at the end of every sprint.** Message describing what changed,
not "update".

**Do not skip Sprint 2's tests.** They are what let you tune the scoring
without fear of breaking something.

**If a sprint balloons,** stop and split it. Sprint 2 is genuinely two
sessions of work. That is expected.

**At the end, explain the architecture out loud to someone.** If you
cannot say why filtering happens in Python and explanation happens in the
model, in your own words, without notes, go back and ask.
