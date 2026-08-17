"""
test_ai.py - unit tests for the pure, network-free parts of ai.py:
turning raw model text into either a trustworthy dict or None. These
never call the Gemini API - they feed in strings shaped like what a
model might return (well-formed, fenced, malformed, or naming a racket
that was never in the shortlist) and check the parsing/validation
logic handles each case on its own.

get_recommendations() itself isn't tested here since it needs a live
API key and a real network call - see scripts/try_recommendation.py
for exercising that path for real.
"""

import json

from services import ai


SHORTLIST_NAMES = {"Adidas Metalbone 3.4", "Head Extreme Motion", "Bullpadel Vertex 04"}


def _picks_response(names, note=None):
    """Builds a JSON string shaped like a real model response, for a given list of racket names."""
    payload = {
        "picks": [
            {"name": name, "why": "fits their style", "tradeoff": "a bit heavier"}
            for name in names
        ]
    }
    if note is not None:
        payload["note"] = note
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# _strip_code_fences
# ---------------------------------------------------------------------------


def test_strip_code_fences_removes_json_fence():
    raw = '```json\n{"a": 1}\n```'
    assert ai._strip_code_fences(raw) == '{"a": 1}'


def test_strip_code_fences_removes_plain_fence():
    raw = '```\n{"a": 1}\n```'
    assert ai._strip_code_fences(raw) == '{"a": 1}'


def test_strip_code_fences_leaves_unfenced_text_alone():
    raw = '{"a": 1}'
    assert ai._strip_code_fences(raw) == '{"a": 1}'


# ---------------------------------------------------------------------------
# _is_valid_shape
# ---------------------------------------------------------------------------


def test_valid_shape_accepts_well_formed_picks():
    parsed = {
        "picks": [{"name": "Head Extreme Motion", "why": "x", "tradeoff": "y"}],
        "note": "a comment",
    }
    assert ai._is_valid_shape(parsed, SHORTLIST_NAMES) is True


def test_valid_shape_accepts_empty_picks_for_honesty_rule_case():
    # PRODUCT.md: "if nothing in budget genuinely suits them, say that
    # rather than forcing a recommendation" - an empty list plus a note
    # is the CORRECT shape here, not a malformed one.
    parsed = {"picks": [], "note": "nothing here suits this player"}
    assert ai._is_valid_shape(parsed, SHORTLIST_NAMES) is True


def test_valid_shape_rejects_racket_not_in_shortlist():
    parsed = {"picks": [{"name": "Made Up Racket 9000", "why": "x", "tradeoff": "y"}]}
    assert ai._is_valid_shape(parsed, SHORTLIST_NAMES) is False


def test_valid_shape_rejects_missing_required_key():
    parsed = {"picks": [{"name": "Head Extreme Motion", "why": "x"}]}  # no "tradeoff"
    assert ai._is_valid_shape(parsed, SHORTLIST_NAMES) is False


def test_valid_shape_rejects_more_than_three_picks():
    pick = {"name": "Head Extreme Motion", "why": "x", "tradeoff": "y"}
    parsed = {"picks": [pick, pick, pick, pick]}
    assert ai._is_valid_shape(parsed, SHORTLIST_NAMES) is False


def test_valid_shape_rejects_non_dict_top_level():
    assert ai._is_valid_shape(["not", "a", "dict"], SHORTLIST_NAMES) is False


def test_valid_shape_rejects_non_string_note():
    parsed = {"picks": [], "note": 12345}
    assert ai._is_valid_shape(parsed, SHORTLIST_NAMES) is False


# ---------------------------------------------------------------------------
# _parse_response - the full pipeline end to end: fence-stripping,
# json.loads, then shape validation.
# ---------------------------------------------------------------------------


def test_parse_response_handles_well_formed_fenced_json():
    raw = "```json\n" + _picks_response(["Head Extreme Motion"]) + "\n```"
    result = ai._parse_response(raw, SHORTLIST_NAMES)
    assert result is not None
    assert result["picks"][0]["name"] == "Head Extreme Motion"


def test_parse_response_handles_well_formed_unfenced_json():
    raw = _picks_response(["Bullpadel Vertex 04"])
    assert ai._parse_response(raw, SHORTLIST_NAMES) is not None


def test_parse_response_rejects_invalid_json_syntax():
    raw = "{this is not valid json"
    assert ai._parse_response(raw, SHORTLIST_NAMES) is None


def test_parse_response_rejects_well_formed_json_naming_a_racket_not_in_shortlist():
    """
    The case that matters most: the model can produce perfectly valid
    JSON syntax while still inventing a racket that was never in the
    shortlist we sent it. response_mime_type="application/json" would
    NOT catch this - the API only guarantees valid JSON syntax, it has
    no idea what our shortlist contains. Only this codebase's own
    membership check does.
    """
    raw = _picks_response(["Racket That Does Not Exist"])
    assert ai._parse_response(raw, SHORTLIST_NAMES) is None


def test_parse_response_accepts_empty_picks_with_note():
    raw = json.dumps({"picks": [], "note": "nothing suits this player"})
    assert ai._parse_response(raw, SHORTLIST_NAMES) == {
        "picks": [],
        "note": "nothing suits this player",
    }
