"""
app.py - the Flask entry point. This file's only job is HTTP: turn an
incoming request into a call to the services that already exist
(catalogue, recommender, ai), and turn their output into a response.

It owns exactly two routes and the validation that guards them. It
deliberately contains no filtering logic (recommender.py), no model
calls (ai.py), and no CSV parsing (catalogue.py) - if you're looking
for the actual product logic, it isn't in this file, by design. Per
ARCHITECTURE.md: "if a route function grows past about 20 lines, logic
has leaked into it and belongs in a service file."
"""

import logging

from flask import Flask, jsonify, render_template, request

from config import Config
from services import ai, catalogue, recommender

# Configures Python's ROOT logger - every logger.getLogger(...) call
# anywhere in this codebase (this file, and any service that adds
# logging later) inherits this setup unless it's overridden locally.
# level=logging.INFO means INFO and above (INFO, WARNING, ERROR,
# CRITICAL) actually produce output; DEBUG stays silent unless this is
# changed later.
#
# Why this was missing until now: Python's logging module has a
# fallback "handler of last resort" that prints WARNING-and-above to
# stderr with zero setup, which is exactly why logger.error(...) below
# already appeared to work without this line - by accident, not by
# design. The moment anything in this codebase called logger.info(...)
# or logger.debug(...), it would have vanished silently, in both local
# and production, since neither is at or above WARNING.
#
# Called exactly once, here, and NOT inside `if __name__ == "__main__":`
# below - gunicorn in production never executes that block (it imports
# `app:app` as a module, it never runs this file as a script), so
# putting it there would mean logging works locally but silently never
# gets configured in production. Module level guarantees this runs
# during import, in every process, under both `python app.py` and
# gunicorn alike.
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config["SECRET_KEY"] = Config.FLASK_SECRET_KEY
app.config["DEBUG"] = Config.DEBUG

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input validation
#
# Deliberately hand-rolled rather than pulling in a schema library
# (Pydantic, marshmallow, ...) - the shape being validated is small and
# fixed (six fields, four of them simple enums), so a library would add
# a dependency and a learning curve without saving much code here. If
# this profile shape grows much more complex, that tradeoff flips.
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = ("level", "side", "style", "budget_max", "arm_issues", "frequency")

# Sanity bounds on budget, not a business rule - the cheapest racket in
# the catalogue is ~R899 and the most expensive is ~R25,000 today, so
# these bounds exist purely to catch obviously bogus input (a negative
# number, a typo with an extra zero) before it ever reaches the
# recommender, with generous headroom for the catalogue to grow.
MIN_BUDGET_ZAR = 100
MAX_BUDGET_ZAR = 50_000

# Only the fields a results card actually needs, pulled from the
# recommender's shortlist to sit alongside each AI-written pick. Note
# the absence of "core"/"surface" here - see PRODUCT.md's catalogue
# note: those specs are inferred throughout, and the AI has already
# been instructed to hedge on them in "why"/"tradeoff" prose. Showing
# them again as a bare, unhedged field on the card would undo that.
_CARD_FIELDS = ("name", "brand", "price_zar", "shape", "url")

# Matches the frontend's "up to 2 previous rackets" design. Not a
# recommender.py concern - this is purely "how much can one request
# ask us to process", the same category of sanity bound as
# MIN_BUDGET_ZAR/MAX_BUDGET_ZAR above.
MAX_PREVIOUS_RACKETS = 2

# Caps the free-text "notes" field, which goes directly into the
# Gemini prompt (see ai.py) - this bounds how much untrusted text one
# request can inject into a prompt, not just a UI nicety.
MAX_NOTES_LENGTH = 500


class ValidationError(Exception):
    """
    Raised by _validate_profile the moment the incoming JSON breaks the
    player-profile contract recommender.py expects. Caught in exactly
    one place - the route below - and turned into a 400 with this
    exception's message as the body. Never lets a raw stack trace or a
    KeyError reach the client.
    """


def _validate_profile(data):
    """
    Checks an incoming JSON body matches the player-profile shape
    recommender.py's own docstring promises it will receive, and
    returns a clean dict built ONLY from known-good fields - never the
    raw `data` dict, so an attacker (or a confused frontend) can't slip
    extra keys through to the services layer.

    Raises ValidationError with a specific, human-readable message on
    the first problem found - not a batch of every problem at once,
    which would be more helpful but is more code than this project
    needs right now.
    """
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")

    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise ValidationError(f"Missing required field(s): {', '.join(missing)}.")

    level = data["level"]
    if level not in recommender.LEVEL_ORDER:
        raise ValidationError(f"'level' must be one of {sorted(recommender.LEVEL_ORDER)}.")

    side = data["side"]
    if side not in recommender.VALID_SIDES:
        raise ValidationError(f"'side' must be one of {sorted(recommender.VALID_SIDES)}.")

    style = data["style"]
    if style not in recommender.VALID_STYLES:
        raise ValidationError(f"'style' must be one of {sorted(recommender.VALID_STYLES)}.")

    frequency = data["frequency"]
    if frequency not in recommender.VALID_FREQUENCIES:
        raise ValidationError(f"'frequency' must be one of {sorted(recommender.VALID_FREQUENCIES)}.")

    budget_max = data["budget_max"]
    # isinstance(True, int) is True in Python - bool is a subclass of
    # int - so without excluding bool explicitly, {"budget_max": true}
    # would silently pass this check as if it were the number 1.
    if isinstance(budget_max, bool) or not isinstance(budget_max, (int, float)):
        raise ValidationError("'budget_max' must be a number.")
    if not (MIN_BUDGET_ZAR <= budget_max <= MAX_BUDGET_ZAR):
        raise ValidationError(f"'budget_max' must be between R{MIN_BUDGET_ZAR} and R{MAX_BUDGET_ZAR}.")

    budget_min = data.get("budget_min")
    if budget_min is not None:
        if isinstance(budget_min, bool) or not isinstance(budget_min, (int, float)):
            raise ValidationError("'budget_min' must be a number.")
        if budget_min < 0:
            raise ValidationError("'budget_min' cannot be negative.")
        if budget_min > budget_max:
            raise ValidationError("'budget_min' cannot be greater than 'budget_max'.")

    arm_issues = data["arm_issues"]
    if not isinstance(arm_issues, bool):
        raise ValidationError("'arm_issues' must be true or false.")

    profile = {
        "level": level,
        "side": side,
        "style": style,
        "budget_max": budget_max,
        "arm_issues": arm_issues,
        "frequency": frequency,
    }
    if budget_min is not None:
        profile["budget_min"] = budget_min

    previous_rackets = data.get("previous_rackets")
    if previous_rackets is not None:
        profile["previous_rackets"] = _validate_previous_rackets(previous_rackets)

    return profile


def _validate_previous_rackets(previous_rackets):
    """
    Validates the optional "rackets the player already used" list.
    Every name is checked against the REAL catalogue, not trusted
    blindly - recommender.py's owned-racket exclusion and similarity
    scoring both assume every entry resolves to an actual racket, and
    this is the one place that guarantee gets enforced before anything
    downstream relies on it.

    Also resolves and attaches each racket's shape/core/balance from
    the catalogue onto the cleaned entry - ai.py needs these to
    describe the comparison in the prompt, and this is the natural
    place to do it: we're already looking each name up here to check
    it's real, so pulling its specs at the same time avoids a second
    catalogue pass elsewhere. recommender.py does its own independent
    lookup against the `catalogue` list it's given directly, so these
    extra keys just ride along unused when this dict reaches it.

    Returns a clean list built only from known-good fields, same
    reasoning as _validate_profile: never pass the raw client dict
    through to the services layer.
    """
    if not isinstance(previous_rackets, list):
        raise ValidationError("'previous_rackets' must be a list.")
    if len(previous_rackets) > MAX_PREVIOUS_RACKETS:
        raise ValidationError(f"'previous_rackets' can have at most {MAX_PREVIOUS_RACKETS} entries.")

    # Built once here, not once per entry - a dict lookup by name is
    # one hash lookup; scanning the whole 521-row catalogue for every
    # entry would still be fast at this size, but there's no reason to
    # do it the slow way.
    catalogue_by_name = {racket["name"]: racket for racket in catalogue.get_all()}

    cleaned = []
    for entry in previous_rackets:
        if not isinstance(entry, dict):
            raise ValidationError("Each entry in 'previous_rackets' must be an object.")

        name = entry.get("name")
        racket = catalogue_by_name.get(name)
        if racket is None:
            raise ValidationError(f"'previous_rackets' contains a racket not in the catalogue: {name!r}.")

        rating = entry.get("rating")
        if rating not in recommender.VALID_RATINGS:
            raise ValidationError(f"'rating' must be one of {sorted(recommender.VALID_RATINGS)}.")

        notes = entry.get("notes", "")
        if not isinstance(notes, str):
            raise ValidationError("'notes' must be text.")
        if len(notes) > MAX_NOTES_LENGTH:
            raise ValidationError(f"'notes' must be {MAX_NOTES_LENGTH} characters or fewer.")

        cleaned_entry = {
            "name": name,
            "rating": rating,
            "shape": racket["shape"],
            "core": racket["core"],
            "balance": racket["balance"],
        }
        if notes:
            cleaned_entry["notes"] = notes
        cleaned.append(cleaned_entry)

    return cleaned


def _attach_racket_details(ai_result, shortlist):
    """
    ai.py only ever returns {"name", "why", "tradeoff"} per pick - it
    never even sees a full racket dict beyond the compact text it was
    given (see ai.py's docstring). A results card needs more than that
    (price, shape, a link to the store), so this stitches each pick
    back onto its matching racket from the recommender's own shortlist
    - the exact same one ai.py chose from, so a match by name is always
    guaranteed to exist; that guarantee is what ai.py's own shape
    validation enforces before a pick is ever returned.
    """
    by_name = {racket["name"]: racket for racket in shortlist}

    picks = []
    for pick in ai_result.get("picks", []):
        racket = by_name[pick["name"]]
        picks.append(
            {
                **{field: racket[field] for field in _CARD_FIELDS},
                "why": pick["why"],
                "tradeoff": pick["tradeoff"],
            }
        )

    response = {"picks": picks}
    if "note" in ai_result:
        response["note"] = ai_result["note"]
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _racket_search_index():
    """
    A compact {name, brand, price_zar} entry per racket, for the
    "which racket did you used to play with" search widget in
    script.js. Deliberately not the full racket dict - the widget only
    needs enough to show a human a recognisable result and to submit a
    name back to /api/recommend, not shape/core/every other field.

    At 521 rackets this comes to roughly 30KB serialised - small enough
    to embed directly in the page via Jinja's |tojson, one render, no
    extra network round-trip for a dedicated search endpoint. Would be
    worth revisiting if the catalogue ever grew into the thousands.
    """
    return [
        {"name": racket["name"], "brand": racket["brand"], "price_zar": racket["price_zar"]}
        for racket in catalogue.get_all()
    ]


@app.route("/", methods=["GET"])
def index():
    # Passing these in rather than hardcoding <option> tags in the
    # template means the dropdowns physically cannot offer a value
    # _validate_profile() would reject - there is exactly one place
    # (recommender.py) that defines what a valid level/side/style/
    # frequency is, and both the form and the validator read from it.
    return render_template(
        "index.html",
        levels=recommender.LEVEL_ORDER,
        sides=recommender.VALID_SIDES,
        styles=recommender.VALID_STYLES,
        frequencies=recommender.VALID_FREQUENCIES,
        ratings=recommender.VALID_RATINGS,
        racket_search_index=_racket_search_index(),
        max_previous_rackets=MAX_PREVIOUS_RACKETS,
    )


@app.route("/api/recommend", methods=["POST"])
def recommend():
    # silent=True: on a missing/invalid JSON body this returns None
    # instead of raising - we want ONE validation path (below) that
    # always produces our own clean JSON error, not two different error
    # formats depending on whether the body was unparseable JSON versus
    # parseable-but-wrong.
    data = request.get_json(silent=True)

    try:
        profile = _validate_profile(data)
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400

    try:
        shortlist = recommender.recommend(profile, catalogue.get_all())
        ai_result = ai.get_recommendations(profile, shortlist)
    except ai.AIError as e:
        logger.error("AI layer failed: %s", e)
        return (
            jsonify({"error": "Could not generate recommendations right now. Please try again shortly."}),
            502,
        )
    except Exception:
        # Anything else unexpected in the recommend/AI pipeline - this
        # is the "API failure returns a clean JSON error rather than
        # crashing" guarantee from the brief. Deliberately scoped to
        # just this route: GET / is left to Flask's normal error
        # handling for now, since templates/index.html doesn't exist
        # until Sprint 5 and Flask's debug-mode error page is more
        # useful than a generic JSON blob while that's still expected.
        logger.exception("Unexpected error while building a recommendation")
        return jsonify({"error": "Something went wrong while building your recommendation."}), 500

    return jsonify(_attach_racket_details(ai_result, shortlist))


if __name__ == "__main__":
    # This block only runs for `python app.py` - Render's actual
    # production process is gunicorn (see render.yaml), which never
    # imports this file as __main__ and never reaches this line.
    app.run(port=Config.PORT, debug=Config.DEBUG)
