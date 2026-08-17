"""
test_recommender.py - "the tests that actually matter", per
ARCHITECTURE.md's file layout.

These run recommender.py's real functions against the REAL catalogue
CSV, not a small hand-built fake one. That's deliberate: recommender.py
exists to stay safe and fair against messy, uneven real data (blank
specs, 6 rackets from one brand, etc.), and a tidy fake catalogue could
easily hide a diversity bug that only shows up once a brand genuinely
has more entries than the cap allows.

The catalogue itself is loaded through services/catalogue.py - the
same module app.py will use at runtime - rather than a test-only
loader. That way there is exactly one place in the codebase that knows
how to parse the CSV, and these tests exercise it for free.
"""

from collections import Counter

import pytest

from services import catalogue as catalogue_module
from services import recommender
from services.recommender import _SelectionTracker


@pytest.fixture(scope="module")
def catalogue():
    return catalogue_module.get_all()


# ---------------------------------------------------------------------------
# Ten player profiles, in the spirit of PRODUCT.md's own testing method
# ("write 10 player profiles with known correct answers"). These lean
# on the combinations most likely to expose a bad interaction between
# hard filters, scoring, and diversity: arm issues, tight budgets,
# opposite sides/styles, every level, big and small budgets.
#
# Profile 6 (advanced / right / aggressive / R6000) is the exact shape
# of player that originally triggered the "6 Head rackets" bug - kept
# here on purpose as a regression guard, not just a random sample.
# ---------------------------------------------------------------------------

PLAYER_PROFILES = [
    {"level": "beginner", "side": "either", "style": "balanced", "budget_max": 2000, "arm_issues": True, "frequency": "occasional"},
    {"level": "beginner", "side": "left", "style": "defensive", "budget_max": 3000, "arm_issues": False, "frequency": "weekly"},
    {"level": "improver", "side": "right", "style": "aggressive", "budget_max": 4000, "arm_issues": False, "frequency": "often"},
    {"level": "improver", "side": "left", "style": "balanced", "budget_max": 3500, "arm_issues": True, "frequency": "weekly"},
    {"level": "intermediate", "side": "right", "style": "aggressive", "budget_max": 5000, "arm_issues": False, "frequency": "often"},
    {"level": "intermediate", "side": "either", "style": "balanced", "budget_max": 4500, "arm_issues": True, "frequency": "occasional"},
    {"level": "advanced", "side": "right", "style": "aggressive", "budget_max": 6000, "arm_issues": False, "frequency": "often"},
    {"level": "advanced", "side": "left", "style": "defensive", "budget_max": 5500, "arm_issues": False, "frequency": "weekly"},
    {"level": "improver", "side": "right", "style": "aggressive", "budget_max": 2500, "arm_issues": True, "frequency": "occasional"},
    {"level": "beginner", "side": "either", "style": "balanced", "budget_max": 10000, "arm_issues": False, "frequency": "often"},
]


@pytest.mark.parametrize(
    "player", PLAYER_PROFILES, ids=[f"profile_{i}" for i in range(len(PLAYER_PROFILES))]
)
def test_no_brand_exceeds_cap(player, catalogue):
    results = recommender.recommend(player, catalogue)
    brand_counts = Counter(r["brand"] for r in results)

    for brand, count in brand_counts.items():
        assert count <= recommender.MAX_PER_BRAND, (
            f"{brand} appears {count} times in the results, "
            f"cap is {recommender.MAX_PER_BRAND}"
        )


@pytest.mark.parametrize(
    "player", PLAYER_PROFILES, ids=[f"profile_{i}" for i in range(len(PLAYER_PROFILES))]
)
def test_no_model_line_exceeds_cap(player, catalogue):
    results = recommender.recommend(player, catalogue)
    line_counts = Counter(r["_model_line"] for r in results)

    for line, count in line_counts.items():
        assert count <= recommender.MAX_PER_MODEL_LINE, (
            f'model line "{line}" appears {count} times in the results, '
            f"cap is {recommender.MAX_PER_MODEL_LINE}"
        )


# ---------------------------------------------------------------------------
# _SelectionTracker - the running counters that back the two tests
# above. These are unit tests, not run against the real catalogue: they
# exercise take()/drop() directly with small fake racket dicts so the
# exact "take, fill to cap, then swap" sequence that caused the
# original bug can be reproduced on demand, rather than hoping some
# combination of the 10 real player profiles happens to trigger it.
# ---------------------------------------------------------------------------


def _racket(brand, line, band, profile="control"):
    """A minimal fake racket dict - just the fields the tracker reads."""
    return {"brand": brand, "_model_line": line, "_price_band": band, "profile": profile}


def test_tracker_counts_match_after_take():
    tracker = _SelectionTracker()
    tracker.take(_racket("Head", "extreme motion", 0))
    tracker.take(_racket("Head", "extreme motion", 1))
    tracker.take(_racket("Adidas", "match light", 0))

    assert tracker.counts_match_contents()
    assert tracker.brand_counts["Head"] == 2
    assert tracker.brand_counts["Adidas"] == 1


def test_tracker_counts_match_after_drop():
    tracker = _SelectionTracker()
    tracker.take(_racket("Head", "extreme motion", 0))
    tracker.take(_racket("Adidas", "match light", 0))
    tracker.drop(0)  # removes the Head racket

    assert tracker.counts_match_contents()
    assert tracker.brand_counts["Head"] == 0
    assert list(tracker.selected) == [_racket("Adidas", "match light", 0)]


def test_tracker_counts_match_through_swap_at_cap():
    """
    Reproduces the exact shape of the original bug: fill a brand up to
    its cap, then run the drop-and-take swap that the profile guarantee
    uses when the selected list is already full. Before the fix, the
    equivalent code path appended straight to the list without touching
    brand_counts - this test fails loudly if that ever regresses.
    """
    tracker = _SelectionTracker()
    for i in range(recommender.MAX_PER_BRAND):
        tracker.take(_racket("Head", f"line {i}", 0, profile="control"))

    assert tracker.brand_counts["Head"] == recommender.MAX_PER_BRAND
    assert tracker.counts_match_contents()

    # Swap: evict one Head racket, take a Bullpadel one in its place -
    # the same drop() then take() pairing _apply_diversity uses.
    tracker.drop(0)
    tracker.take(_racket("Bullpadel", "flow legend", 0, profile="power"))

    assert tracker.counts_match_contents()
    assert tracker.brand_counts["Head"] == recommender.MAX_PER_BRAND - 1
    assert tracker.brand_counts["Bullpadel"] == 1
    assert len(tracker.selected) == recommender.MAX_PER_BRAND


# ---------------------------------------------------------------------------
# Previous rackets - the capture-based signals: similarity scoring,
# the arm-issues override from pain language in free-text notes, and
# the owned-racket exclusion. Real catalogue data throughout, same
# convention as the rest of this file: a hand-built fake catalogue
# could hide a case where a real racket's blank/messy spec breaks one
# of these checks.
# ---------------------------------------------------------------------------

# A wide-open, level/budget-agnostic player profile - hard filters
# should exclude as little of the catalogue as possible, so the tests
# below are actually comparing scores for the SAME surviving rackets
# across two runs, not accidentally testing filtering instead.
_PERMISSIVE_PLAYER = {
    "level": "advanced",
    "side": "either",
    "style": "balanced",
    "budget_max": 25000,
    "arm_issues": False,
    "frequency": "occasional",
}


def test_disliked_racket_shape_is_down_weighted(catalogue):
    """
    A candidate sharing shape with a racket the player disliked should
    score measurably lower than the same candidate scores when there's
    no previous-racket signal at all - not just theoretically wired in,
    visibly subtracting points in the real, scored output.
    """
    disliked = next(r for r in catalogue if r["shape"] == "diamond" and r["core"])
    player_with_dislike = {
        **_PERMISSIVE_PLAYER,
        "previous_rackets": [{"name": disliked["name"], "rating": "disliked"}],
    }

    baseline = {r["name"]: r["_score"] for r in recommender.recommend(_PERMISSIVE_PLAYER, catalogue)}
    with_dislike = {r["name"]: r["_score"] for r in recommender.recommend(player_with_dislike, catalogue)}

    by_name = {r["name"]: r for r in catalogue}
    same_shape_in_both = [
        name
        for name in baseline
        if name in with_dislike and by_name[name]["shape"] == "diamond" and name != disliked["name"]
    ]

    assert same_shape_in_both, "no overlapping diamond-shaped racket survived both runs - test setup problem"
    for name in same_shape_in_both:
        assert with_dislike[name] < baseline[name], f"{name} did not score lower after a diamond racket was disliked"


def test_loved_racket_shape_is_rewarded(catalogue):
    """The reward side of the same signal, for symmetry - a loved racket should push matching candidates UP, not just a disliked one pushing them down."""
    loved = next(r for r in catalogue if r["shape"] == "diamond" and r["core"])
    player_with_love = {
        **_PERMISSIVE_PLAYER,
        "previous_rackets": [{"name": loved["name"], "rating": "loved"}],
    }

    baseline = {r["name"]: r["_score"] for r in recommender.recommend(_PERMISSIVE_PLAYER, catalogue)}
    with_love = {r["name"]: r["_score"] for r in recommender.recommend(player_with_love, catalogue)}

    by_name = {r["name"]: r for r in catalogue}
    same_shape_in_both = [
        name
        for name in baseline
        if name in with_love and by_name[name]["shape"] == "diamond" and name != loved["name"]
    ]

    assert same_shape_in_both, "no overlapping diamond-shaped racket survived both runs - test setup problem"
    for name in same_shape_in_both:
        assert with_love[name] > baseline[name], f"{name} did not score higher after a diamond racket was loved"


def test_pain_language_triggers_arm_issues_exclusions(catalogue):
    """
    The safety-critical case: arm_issues=False on the checkbox, but the
    free-text notes on a DISLIKED racket mention pain. No hard-core,
    high-grade-carbon, or diamond-shaped racket should reach the
    results - the same guarantee as if arm_issues had been ticked
    directly.

    A control run (same disliked racket, notes WITHOUT pain language)
    is checked too, and asserted to still contain dangerous-shape
    rackets - proving the exclusion is genuinely conditional on the
    pain language, not coincidentally empty for some unrelated reason.
    """
    disliked = next(r for r in catalogue if r["shape"] == "diamond" and r["core"] == "hard EVA")

    def _is_dangerous(racket):
        return (
            racket["core"] in recommender.HARD_CORES
            or racket["surface"] in recommender.HIGH_GRADE_CARBON_SURFACES
            or racket["shape"] == recommender.POWER_SHAPE
        )

    player_with_pain = {
        **_PERMISSIVE_PLAYER,
        "previous_rackets": [
            {"name": disliked["name"], "rating": "disliked", "notes": "too stiff, my elbow was aching afterwards"}
        ],
    }
    results_with_pain = recommender.recommend(player_with_pain, catalogue)
    assert not any(_is_dangerous(r) for r in results_with_pain)

    player_without_pain = {
        **_PERMISSIVE_PLAYER,
        "previous_rackets": [{"name": disliked["name"], "rating": "disliked", "notes": "just not my style"}],
    }
    results_without_pain = recommender.recommend(player_without_pain, catalogue)
    assert any(_is_dangerous(r) for r in results_without_pain), (
        "control run with no pain language should still contain dangerous-shape rackets - "
        "otherwise this test can't prove the exclusion is conditional on the pain language"
    )


def test_owned_racket_never_appears_in_results(catalogue):
    """
    Never recommend a racket the player already told us they own -
    regardless of how they rated it.

    The "owned" racket here must be one that would otherwise genuinely
    survive _PERMISSIVE_PLAYER's hard filters and rank well enough to
    appear in the top MAX_RESULTS - otherwise this test could pass
    vacuously, "proving" an exclusion that was never actually exercised
    because the racket was never going to show up anyway. Picked from
    _PERMISSIVE_PLAYER's own baseline results for exactly that reason.
    """
    baseline_names = {r["name"] for r in recommender.recommend(_PERMISSIVE_PLAYER, catalogue)}
    owned = next(r for r in catalogue if r["name"] in baseline_names)

    for rating in recommender.VALID_RATINGS:
        player = {**_PERMISSIVE_PLAYER, "previous_rackets": [{"name": owned["name"], "rating": rating}]}
        results = recommender.recommend(player, catalogue)

        assert owned["name"] not in {r["name"] for r in results}, (
            f'owned racket "{owned["name"]}" appeared in results despite rating "{rating}"'
        )
