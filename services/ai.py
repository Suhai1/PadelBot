"""
ai.py - the only file in this codebase that talks to an external AI
model, per ARCHITECTURE.md ("everything about which model you call
lives in this one file").

One job: given a player profile and the shortlist recommender.py
already filtered and scored, ask Gemini to pick up to three of them and
explain each in plain English. This file never decides WHICH rackets
are candidates - it only ever chooses among rackets it is handed, and
a validation step below refuses to accept a response that mentions
anything outside that shortlist. That's not just a prompt instruction;
it's checked in Python after the response comes back, the same
"don't just trust it, verify it" instinct that made recommender.py's
hard filters non-negotiable instead of a scoring bonus.

What this file deliberately does not do: no player-facing input
validation (Flask's job, Sprint 4), no conversation history or
follow-up chat (Sprint 7), no knowledge of HTTP at all - it's a plain
function, equally callable from a route or a terminal script.
"""

import json

from google import genai
from google.genai import errors, types

from config import Config


# ---------------------------------------------------------------------------
# Model choice - the one constant most likely to need changing over the
# life of this project as Google ships new models. gemini-3.5-flash-lite
# rather than the flagship gemini-3.7-flash: this task is picking 3
# items from an 8-25 item list and writing a couple of sentences each,
# not "complex coding/agentic workflows" (Google's own description of
# what 3.7 is for) - a lite model is both cheaper and plenty capable
# for it, which matches ARCHITECTURE.md's cost-control goals directly.
# ---------------------------------------------------------------------------

GEMINI_MODEL = "gemini-3.5-flash-lite"

# "retry-once-on-failure" from the brief: try, and if that fails, try
# exactly one more time before giving up. 2 total attempts, not a loop.
MAX_ATTEMPTS = 2

# Only the fields a player actually cares about when judging whether a
# racket suits them. Deliberately excludes "description" (free-text
# marketing copy, often hundreds of tokens, and nothing in it is a fact
# recommender.py's hard filters already checked) and shopping-only
# fields like url/colours/stores - keeping the shortlist this compact
# is what keeps a request to ~1,200 tokens per ARCHITECTURE.md's cost
# section, instead of resending most of the CSV's columns per racket.
_SHORTLIST_FIELDS = [
    "name",
    "brand",
    "price_zar",
    "shape",
    "profile",
    "core",
    "surface",
    "weight_g",
    "balance",
    "level",
    "availability",
    "stock_status",
]

# Built once, at import time, not inside get_recommendations() - this
# is ARCHITECTURE.md's "cache the system prompt string; do not rebuild
# it per request" instruction. A module-level string constant already
# satisfies that: Python evaluates this exactly once, when the module
# is first imported, no matter how many times get_recommendations()
# runs afterwards.
SYSTEM_PROMPT = """
You are PadelPal, an advisor that recommends padel rackets to South African players.

DOMAIN KNOWLEDGE
- Round shapes are forgiving, with the sweet spot centred low in the head - suited to control and to beginners.
- Teardrop shapes are the middle ground between round and diamond.
- Diamond shapes put more mass high in the head, giving power at the cost of forgiveness.
- Softer EVA cores are kinder to the arm; harder EVA gives more ball speed but more shock.
- Higher carbon grades (12K, 18K) are stiffer and transmit more shock to the arm than fibreglass or lower carbon grades.
- Higher balance (weight distributed toward the head) means more power; lower balance (weight toward the handle) means more manoeuvrability.
- On court, the left side is usually the control/defensive player; the right side usually finishes points and needs more power.

HONESTY RULES - these override being helpful, not the other way round:
- Recommend ONLY rackets that appear in the shortlist you are given. Never invent a racket, a brand, or a spec that is not in the shortlist.
- Never state a spec (weight, balance, price, or anything else) that is not present in the data you were given. If a field is blank, do not guess a value for it.
- shape, core and surface in this data are inferred, not confirmed by the manufacturer, even for rackets that otherwise look like clean store listings. You may use these fields to help choose good candidates, but describe them in HEDGED language when explaining a pick - "leans toward a control shape", "likely a softer core" - never as settled fact like "its round shape" or "has a soft EVA core". Price, brand, level and availability come directly from retailers and can be stated plainly.
- If nothing in the shortlist genuinely suits this player, say so in "note" and return an empty "picks" list rather than forcing three recommendations.
- If the player's stated problem (e.g. elbow pain) sounds like it could be technique rather than equipment, say that in "note" - a lesson may help more than a new racket.

OUTPUT FORMAT
Return ONLY valid JSON, with no markdown code fences and no text before or after it, in exactly this shape:
{
  "picks": [
    {"name": "<exact name copied from the shortlist>", "why": "<plain-English reason this suits the player, referencing what they told you>", "tradeoff": "<a genuine downside or what this racket gives up>"}
  ],
  "note": "<optional overall comment - use this for the honesty-rule cases above, otherwise omit it>"
}
Return at most 3 picks. Every "name" must be copied exactly, character for character, from the shortlist you were given.
""".strip()


class AIError(Exception):
    """
    Raised whenever this file cannot hand back a usable response: the
    API key is missing, every attempt failed to reach Gemini, or every
    attempt came back as something other than valid, in-shortlist JSON.

    A dedicated exception type (rather than letting requests.HTTPError
    or json.JSONDecodeError leak out directly) so callers - a Flask
    route in Sprint 4, or the terminal script below - can catch exactly
    "the AI layer didn't work" without also catching unrelated bugs.
    """


def _format_player(player):
    """
    Turns the player profile dict into a short, plain-English block for
    the prompt. Deliberately not JSON - the model does not need to
    parse this, a human-readable sentence per fact is easier for it (and
    for you, reading a debug log) to work with than a nested object.
    """
    lines = [
        f"level: {player['level']}",
        f"side of court: {player['side']}",
        f"playing style: {player['style']}",
        f"budget: up to R{player['budget_max']}",
        f"arm or shoulder issues: {'yes' if player.get('arm_issues') else 'no'}",
        f"how often they play: {player.get('frequency', 'not specified')}",
    ]
    if player.get("budget_min"):
        lines.append(f"minimum budget: R{player['budget_min']}")

    return "Player profile:\n" + "\n".join(lines)


def _format_shortlist(shortlist):
    """
    Turns the recommender's list of racket dicts into compact text -
    one line per racket, "field=value" pairs joined by " | ". Not JSON
    for the same reason as _format_player: this is going into a prompt
    to be read, not parsed, and plain key=value pairs use noticeably
    fewer tokens than the equivalent JSON (no repeated quote marks or
    brace/bracket nesting for every single racket).
    """
    lines = []
    for racket in shortlist:
        pairs = [f"{field}={racket.get(field, '')}" for field in _SHORTLIST_FIELDS]
        lines.append(" | ".join(pairs))
    return "\n".join(lines)


def _strip_code_fences(text):
    """
    Models asked for JSON very often wrap it in a markdown code block
    anyway (```json ... ```), even when told not to - it's how they're
    trained to present code-shaped output in chat. This removes that
    wrapping if present, and leaves the text alone if it isn't, so
    json.loads() downstream sees the same shape either way.
    """
    text = text.strip()
    if not text.startswith("```"):
        return text

    # Drop the opening fence line (```` ```json ```` or plain ```` ``` ````)
    # and the closing ```` ``` ```` if the text ends with one.
    without_opening = text.split("\n", 1)[1] if "\n" in text else ""
    if without_opening.endswith("```"):
        without_opening = without_opening[: -len("```")]
    return without_opening.strip()


def _is_valid_shape(parsed, shortlist_names):
    """
    Checks the parsed JSON actually matches the contract this codebase
    promised the player: a "picks" list of at most 3 objects, each with
    the three required keys, and - the one check that matters most -
    every "name" genuinely came from the shortlist we sent. This is the
    code-level enforcement of the honesty rule "never invent a racket":
    the system prompt asks nicely, this function is what actually
    refuses to pass an invented name back to the caller.

    An EMPTY picks list is valid on purpose - that's exactly what a
    model should return for PRODUCT.md's "nothing in budget genuinely
    suits them" case, not something to reject as malformed.
    """
    if not isinstance(parsed, dict):
        return False

    picks = parsed.get("picks")
    if not isinstance(picks, list) or len(picks) > 3:
        return False

    for pick in picks:
        if not isinstance(pick, dict):
            return False
        if not all(key in pick for key in ("name", "why", "tradeoff")):
            return False
        if pick["name"] not in shortlist_names:
            return False

    if "note" in parsed and not isinstance(parsed["note"], str):
        return False

    return True


def _parse_response(raw_text, shortlist_names):
    """
    The single place that turns Gemini's raw text into either a usable
    dict or None. Returning None (rather than raising) on any failure
    lets get_recommendations() treat "bad JSON" and "well-formed JSON
    that invented a racket" identically - both are just "this attempt
    didn't work, try again if there's a retry left".
    """
    cleaned = _strip_code_fences(raw_text)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None

    if not _is_valid_shape(parsed, shortlist_names):
        return None

    return parsed


def get_recommendations(player, shortlist):
    """
    The only function other files should call.

    player:     dict matching recommender.py's player profile shape.
    shortlist:  the list recommender.recommend(player, catalogue) returned.

    Returns a dict shaped like {"picks": [...], "note": "..."} - "note"
    may be absent. Raises AIError if the key is missing, or if Gemini
    never produced a usable, in-shortlist response within MAX_ATTEMPTS.
    """
    if not Config.GEMINI_API_KEY:
        raise AIError(
            "GEMINI_API_KEY is not set. Add it to a .env file in the "
            "project root - see .env.example for the exact variable name."
        )

    if not shortlist:
        # Nothing to send the model - spending an API call just to be
        # told "there's nothing here" wastes a request for no benefit.
        return {"picks": [], "note": "No rackets matched this player's filters."}

    client = genai.Client(api_key=Config.GEMINI_API_KEY)
    shortlist_names = {racket["name"] for racket in shortlist}
    prompt = _format_player(player) + "\n\nShortlist:\n" + _format_shortlist(shortlist)

    last_error = "unknown error"
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    # Tells the API itself to only ever emit valid JSON
                    # syntax - no markdown fences, no chatty preamble.
                    # This does NOT replace _parse_response()'s checks
                    # below, because "valid JSON" and "the JSON we
                    # asked for" are different guarantees: the API can
                    # enforce the former but has no idea what shape our
                    # "picks"/"why"/"tradeoff" contract is, and it
                    # certainly cannot check whether a racket name it
                    # generated actually exists in OUR shortlist - only
                    # our own code has that list. Keep both: this flag
                    # cuts out an entire class of failure (fences,
                    # stray text) for free, and _parse_response() is
                    # still the backstop for the failures it can't see.
                    response_mime_type="application/json",
                ),
            )
        except errors.APIError as e:
            # Network blip, rate limit, model overloaded, etc. - worth
            # one retry. errors.APIError is the base class for both
            # ClientError and ServerError in this SDK, so this catches
            # both a bad request and a server-side failure the same way.
            last_error = str(e)
            continue

        parsed = _parse_response(response.text, shortlist_names)
        if parsed is not None:
            return parsed

        last_error = "the model's response was not valid, in-shortlist JSON"

    raise AIError(
        f"Gemini did not return a usable response after {MAX_ATTEMPTS} "
        f"attempt(s): {last_error}"
    )
