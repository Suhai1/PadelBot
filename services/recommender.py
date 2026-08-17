"""
recommender.py - the actual product, per ARCHITECTURE.md.

This file contains no AI, no network calls, and no I/O. It is pure
Python: given a player profile and the racket catalogue (already loaded
into memory by catalogue.py), it returns a shortlist. Nothing in here
is asked to be creative - it is asked to be *correct*, which is why it
has to be plain deterministic code, not a prompt.

THE CONTRACT THIS FILE EXPECTS
-------------------------------
`catalogue.py` (not built yet) must hand this file a list of dicts,
one per racket, where every dict has AT LEAST these keys, already
typed (not raw CSV strings):

    brand:        str
    name:         str
    shape:        str   "round" | "teardrop" | "diamond" | "" (unknown)
    profile:      str   "control" | "power" | "hybrid" | "" (unknown)
    core:         str   e.g. "soft EVA", "hard EVA", "foam", "" (unknown)
    surface:      str   e.g. "12K carbon", "18K carbon", "" (unknown)
    availability: str   "high" | "medium" | "low"
    stock_status: str   "in stock" | "order in" | "" (unknown)
    level:        str   "beginner" | "improver" | "intermediate" | "advanced"
    price_zar:    int

A blank string ("") is this codebase's way of saying "we do not know
this spec" - never None, never missing key. That matches how
csv.DictReader hands back an empty cell, so catalogue.py's job is
mostly "convert price_zar and weight_g to int" and leave the rest as
strings.

HARD FILTERS vs SOFT SCORING - why the split exists
----------------------------------------------------
A hard filter is a yes/no gate: fails one, and the racket is gone,
full stop. Soft scoring only ever ranks whatever survives the gates.

The reason to keep these as two clearly separate passes, rather than
one big "give it minus 1000 points if it's dangerous for a bad elbow"
scoring function, is safety-critical: with scoring, a big enough bonus
somewhere else could mathematically outweigh the penalty and let a
disqualified racket back into the results. With a hard filter, there
is no number large enough to undo a rejection - the racket is removed
from the list before scoring ever runs. PRODUCT.md's rule that "arm
pain overrides everything" is only really true if it is enforced this
way.

Soft scoring, on the other hand, is deliberately NOT allowed to
disqualify anything - it only ever re-orders what the hard filters
already approved. That split is what makes the system testable: you
can write a test asserting "no hard-core racket ever reaches someone
with elbow pain" and it will hold no matter how the scoring weights
get tuned later.
"""

from collections import Counter

# ---------------------------------------------------------------------------
# Domain constants
#
# LEVEL_ORDER is a list, not a set, because order is the whole point: we
# need to measure how far apart two levels are, and Python lists let us
# do that with .index() - find a value's position - and subtract.
# ---------------------------------------------------------------------------

LEVEL_ORDER = ["beginner", "improver", "intermediate", "advanced"]

# How many "bands" away from the player's own level a racket is allowed
# to sit. 1 means an improver (index 1) can see beginner (0) and
# intermediate (2), but not advanced (3) - matches the brief exactly.
LEVEL_BAND_TOLERANCE = 1

# Exact strings, as they appear in the catalogue, that count as "too
# stiff/hard for a sore arm". These are sets (not lists) purely because
# checking "is this value in the set" is what we need, and sets do that
# check faster than lists - doesn't matter at a catalogue this size, but
# it is the correct tool for "is X one of these known values".
HARD_CORES = {"hard EVA"}
HIGH_GRADE_CARBON_SURFACES = {"18K carbon", "15K carbon"}
POWER_SHAPE = "diamond"

# ---------------------------------------------------------------------------
# Soft scoring weights - tune these numbers without touching any logic
# below. Bigger weight = that signal matters more when ranking survivors.
# They are all on the same rough 0-3 scale on purpose, so nudging one
# doesn't accidentally make it drown out all the others.
# ---------------------------------------------------------------------------

STYLE_MATCH_WEIGHT = 3.0        # profile matches player's stated style
SIDE_MATCH_WEIGHT = 2.0         # profile matches the lean of their court side
BUDGET_FIT_WEIGHT = 2.0         # sitting comfortably under budget vs at the ceiling
FREQUENCY_DURABILITY_PENALTY = 2.0  # subtracted from the cheapest tier for frequent players

# Points awarded per availability tier - how widely stocked the racket
# is across retailers.
AVAILABILITY_SCORES = {
    "high": 3.0,
    "medium": 1.5,
    "low": 0.0,
    "": 0.0,  # unknown availability - no bonus, no penalty
}

# Points for whether the cheapest listing itself can ship now. This is
# a separate signal from AVAILABILITY_SCORES above: a racket can be
# stocked at three retailers (high availability) and still be on
# order-in at all three, or stocked nowhere else but sitting on the
# shelf at the one store that has it. Kept as a soft scoring bonus, not
# a hard filter, because order-in is still a real, buyable option -
# just a slower one - so it should rank below an identical in-stock
# racket, not be removed from the list.
STOCK_STATUS_SCORES = {
    "in stock": 2.0,
    "order in": 0.0,
    "": 0.0,  # unknown stock status - no bonus, no penalty
}

# What each stated playing style leans toward, and what side of the
# court leans toward, in terms of the catalogue's "profile" field.
# Plain dicts used as lookup tables: "given this key, what's the value".
STYLE_TO_PROFILE = {
    "aggressive": "power",
    "defensive": "control",
    "balanced": "hybrid",
}

SIDE_TO_PROFILE = {
    "left": "control",
    "right": "power",
    # "either" has no entry on purpose: a player who plays both sides
    # gets no side-based scoring lean either way.
}

# The valid values for "side", "style" and "frequency" - exposed here,
# not just implied by the dicts above, so a caller validating an
# incoming player profile (app.py) or building a form (Sprint 5's
# templates/index.html) has one real source of truth instead of
# re-typing its own copy of these lists. VALID_SIDES can't be derived
# from SIDE_TO_PROFILE.keys() the way VALID_STYLES is derived from
# STYLE_TO_PROFILE below, because "either" is a legal side that
# deliberately has no entry in that dict.
#
# Tuples, not sets: a set's iteration order isn't just "unspecified" in
# the abstract - for a set of strings, it depends on Python's per-
# process hash randomization, so it can genuinely differ between two
# runs of the same code. That's invisible for the `in` checks these
# were originally written for, but it matters the moment something
# iterates one of these to build a dropdown - a set here would mean the
# form's option order could reshuffle on every server restart. Tuples
# fix the order permanently. tuple(STYLE_TO_PROFILE) relies on
# dicts preserving insertion order (guaranteed since Python 3.7), so it
# comes out as ("aggressive", "defensive", "balanced") every time.
VALID_SIDES = ("left", "right", "either")
VALID_STYLES = tuple(STYLE_TO_PROFILE)
VALID_FREQUENCIES = ("occasional", "weekly", "often")

# ---------------------------------------------------------------------------
# Diversity limits - applied after scoring, to stop one brand or one
# model line from crowding out everything else in the final list.
# ---------------------------------------------------------------------------

MAX_RESULTS = 25
MAX_PER_BRAND = 5
MAX_PER_MODEL_LINE = 4

# Price bands split the player's own budget range into this many equal
# slices (e.g. 3 = "cheap third", "middle third", "top third" of their
# budget), so the returned list isn't all clustered at one price point.
PRICE_BAND_COUNT = 3
MAX_PER_PRICE_BAND = 15


# ---------------------------------------------------------------------------
# Hard filters
# ---------------------------------------------------------------------------


def _level_within_band(racket_level, player_level):
    """
    True if racket_level is close enough to player_level to be worth
    showing. "Close enough" is defined by LEVEL_BAND_TOLERANCE above.

    Guards against unknown level strings by returning False rather than
    crashing - .index() throws ValueError if the value isn't in the
    list, which would take down the whole request over one bad row.
    """
    if racket_level not in LEVEL_ORDER or player_level not in LEVEL_ORDER:
        return False

    racket_position = LEVEL_ORDER.index(racket_level)
    player_position = LEVEL_ORDER.index(player_level)
    return abs(racket_position - player_position) <= LEVEL_BAND_TOLERANCE


def _passes_hard_filters(racket, player):
    """
    The yes/no gate. Returns True only if this racket is a legal option
    for this player at all - says nothing about how *good* an option it
    is, that's soft scoring's job.

    Order matters a little for readability (cheapest/most obvious
    checks first) but not for correctness - every check here is
    independent of the others.
    """
    # We cannot responsibly recommend a racket we don't even know the
    # shape of - that's the one spec we refuse to guess on.
    if not racket["shape"]:
        return False

    price = racket["price_zar"]
    if price > player["budget_max"]:
        return False

    budget_min = player.get("budget_min")
    if budget_min is not None and price < budget_min:
        return False

    if not _level_within_band(racket["level"], player["level"]):
        return False

    if player.get("arm_issues"):
        if racket["core"] in HARD_CORES:
            return False
        if racket["surface"] in HIGH_GRADE_CARBON_SURFACES:
            return False
        if racket["shape"] == POWER_SHAPE:
            return False

    return True


# ---------------------------------------------------------------------------
# Soft scoring
# ---------------------------------------------------------------------------


def _price_band(price, band_min, band_max):
    """
    Splits [band_min, band_max] into PRICE_BAND_COUNT equal-width slices
    and returns which slice `price` falls into: 0 for the cheapest
    slice, up to PRICE_BAND_COUNT - 1 for the most expensive.

    Used twice: to penalise the cheapest tier for frequent players, and
    later to spread the final list across price bands rather than
    returning eight rackets that are all within R200 of each other.
    """
    if band_max <= band_min:
        # Budget range of zero (or nonsensical) - everything is "band 0",
        # there's nothing meaningful to divide.
        return 0

    band_width = (band_max - band_min) / PRICE_BAND_COUNT
    band = int((price - band_min) // band_width)

    # A racket priced exactly at band_max would otherwise compute to
    # band PRICE_BAND_COUNT, one past the last valid index - clamp it
    # into the top band instead.
    return min(band, PRICE_BAND_COUNT - 1)


def _soft_score(racket, player, budget_min, budget_max, price_band):
    """
    Ranks a racket that has already survived the hard filters. Every
    signal below adds (or subtracts) independently, so the final score
    is just a sum - easy to reason about and easy to unit test one
    signal at a time.
    """
    score = 0.0

    preferred_profile = STYLE_TO_PROFILE.get(player["style"])
    if preferred_profile and racket["profile"] == preferred_profile:
        score += STYLE_MATCH_WEIGHT

    side_lean_profile = SIDE_TO_PROFILE.get(player["side"])
    if side_lean_profile and racket["profile"] == side_lean_profile:
        score += SIDE_MATCH_WEIGHT

    score += AVAILABILITY_SCORES.get(racket["availability"], 0.0)
    score += STOCK_STATUS_SCORES.get(racket["stock_status"], 0.0)

    # "Comfortably inside budget" = a fraction from 0 (priced right at
    # the ceiling) to 1 (priced right at the floor). Multiplying by the
    # weight turns that fraction into points.
    budget_range = budget_max - budget_min
    if budget_range > 0:
        comfort = (budget_max - racket["price_zar"]) / budget_range
        score += comfort * BUDGET_FIT_WEIGHT

    if player.get("frequency") == "often" and price_band == 0:
        score -= FREQUENCY_DURABILITY_PENALTY

    return score


def _model_line(name, brand):
    """
    Guesses a "model line" from a free-text product name, e.g. both
    "2025 Adidas Cross It Light 3.4 by Martita Ortega" and "2024 Adidas
    Cross It Light 2.0" should collapse to the same line ("cross it") so
    the diversity cap can stop one line filling half the results.

    Heuristic, not a lookup table: strip anything that looks like a
    4-digit year and strip the brand name (already tracked separately
    by MAX_PER_BRAND), then take the first two remaining words. This
    will occasionally lump two real lines together or split one in two
    - it does not need to be perfect, it just needs to stop the worst
    case of "12 of these 25 results are the same racket in different
    years".
    """
    brand_words = set(brand.lower().split())
    significant_words = []

    for word in name.split():
        cleaned = word.lower().strip(".,")
        if cleaned.isdigit() and len(cleaned) == 4:
            continue  # looks like a year, e.g. "2025"
        if cleaned in brand_words:
            continue  # the brand name repeated inside the product name
        significant_words.append(cleaned)

    return " ".join(significant_words[:2])


# ---------------------------------------------------------------------------
# Diversity - applied last, after everything is scored and ranked
# ---------------------------------------------------------------------------


class _SelectionTracker:
    """
    Bundles the list of picked rackets with the running brand/model-line
    /price-band counts that decide what still fits the diversity caps.

    Pulled out into its own class (rather than a handful of local
    variables and closures) for one reason: it makes "do the running
    counts still match what's actually in the list" a thing that can be
    asked and unit-tested directly, via counts_match_contents() below.
    That question is exactly what a real bug got wrong once - a code
    path appended straight to the selected list without touching the
    counts, so a cap of 5 silently let a 6th racket from the same brand
    through. take() and drop() are now the ONLY way to mutate either
    side, so that specific mistake can no longer compile past this
    class's boundary.
    """

    def __init__(self):
        self.selected = []
        self.brand_counts = Counter()
        self.line_counts = Counter()
        self.band_counts = Counter()

    def fits_caps(self, racket):
        return (
            self.brand_counts[racket["brand"]] < MAX_PER_BRAND
            and self.line_counts[racket["_model_line"]] < MAX_PER_MODEL_LINE
            and self.band_counts[racket["_price_band"]] < MAX_PER_PRICE_BAND
        )

    def take(self, racket):
        self.selected.append(racket)
        self.brand_counts[racket["brand"]] += 1
        self.line_counts[racket["_model_line"]] += 1
        self.band_counts[racket["_price_band"]] += 1

    def drop(self, index):
        racket = self.selected.pop(index)
        self.brand_counts[racket["brand"]] -= 1
        self.line_counts[racket["_model_line"]] -= 1
        self.band_counts[racket["_price_band"]] -= 1
        return racket

    def counts_match_contents(self):
        """
        Recomputes each count fresh from self.selected and compares it
        to the running counter. `+counter` (unary plus) is a Counter
        trick that returns a copy with only the positive entries - it's
        needed here because take()/drop() can leave a brand's count at
        exactly 0 (e.g. take one, then drop it), which is a real key
        with value 0 in the running counter but simply absent from a
        freshly-built Counter over the current contents. Without
        stripping those zeroes first, a perfectly correct tracker would
        report a false mismatch.
        """
        return (
            +self.brand_counts == Counter(r["brand"] for r in self.selected)
            and +self.line_counts == Counter(r["_model_line"] for r in self.selected)
            and +self.band_counts == Counter(r["_price_band"] for r in self.selected)
        )


def _apply_diversity(ranked_rackets, surviving_profiles):
    """
    Walks the score-ranked list from best to worst, taking each racket
    only if it doesn't breach the brand / model-line / price-band caps,
    until MAX_RESULTS is reached. This is a *greedy* algorithm: it never
    goes back and reconsiders an earlier decision, which is simple and
    fast but not guaranteed to find the single best possible set of 25.
    Good enough here - we are picking a shortlist, not solving a puzzle.

    After the greedy pass, we double back for one thing greed can miss:
    every profile (control / power / hybrid) that had at least one
    racket survive the hard filters should get a seat in the final
    list, even if every racket of that profile happened to score lower
    than the cap allowed through. Without this, a player with a strong
    style preference could end up seeing zero alternatives to compare
    against - and PRODUCT.md's honesty rules are explicitly about
    giving people real options, not just the model's favourite.

    That guarantee is still SUBORDINATE to the brand/line/band caps,
    not above them. If every racket of a missing profile would breach
    a cap, we skip the guarantee for that profile rather than force one
    in. Reasoning: the caps exist so the list never reads like an ad
    for one brand or one price point - that promise holds for the
    whole list, unconditionally. The profile guarantee is a nice-to-
    have for comparison, and forcing in a racket that only qualifies by
    breaking a structural promise is, in effect, padding the list with
    a worse match to hit a target - which PRODUCT.md rules out
    explicitly ("never pad with poor matches to hit the number"). A
    missing profile is a gap; a broken cap is a broken promise. We'd
    rather have the gap.
    """
    tracker = _SelectionTracker()

    for racket in ranked_rackets:
        if len(tracker.selected) >= MAX_RESULTS:
            break
        if tracker.fits_caps(racket):
            tracker.take(racket)

    # Second pass: make sure every surviving profile has a seat, without
    # ever breaking a cap to do it (see the docstring above for why).
    represented_profiles = {r["profile"] for r in tracker.selected}
    missing_profiles = surviving_profiles - represented_profiles

    for profile in missing_profiles:
        candidates = [r for r in ranked_rackets if r["profile"] == profile]
        # Highest-scoring candidate of this profile that still fits the
        # caps. `candidates` is already best-first because it was
        # filtered out of `ranked_rackets`, which recommend() sorted by
        # score before calling this function.
        candidate = next((r for r in candidates if tracker.fits_caps(r)), None)

        if candidate is None:
            # Every racket of this profile would breach a cap - skip
            # the guarantee for this profile rather than force one in.
            continue

        if len(tracker.selected) < MAX_RESULTS:
            tracker.take(candidate)
            continue

        # List is already full: evict the weakest racket that is NOT
        # the only representative of its own profile, so we never
        # remove the one seat another profile's guarantee depends on.
        # fits_caps() above was already checked against the counts
        # BEFORE this eviction - freeing a seat can only reduce counts,
        # never invalidate a check that already passed.
        profile_counts = Counter(r["profile"] for r in tracker.selected)
        for i in range(len(tracker.selected) - 1, -1, -1):
            if profile_counts[tracker.selected[i]["profile"]] > 1:
                tracker.drop(i)
                tracker.take(candidate)
                break

    return tracker.selected


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def recommend(player, catalogue):
    """
    The only function other files should call.

    player:     dict matching the shape described in the module
                docstring's caller contract (level, side, style,
                budget_max, budget_min, arm_issues, frequency).
    catalogue:  list of racket dicts, as produced by catalogue.py.

    Returns a list of up to MAX_RESULTS racket dicts, best match first,
    each with three extra debug fields prefixed with an underscore
    (_score, _model_line, _price_band) so callers and tests can see WHY
    something ranked where it did. Never pads the list to hit a target
    size - if only three rackets are genuinely legal options, three is
    what comes back.
    """
    hard_survivors = [racket for racket in catalogue if _passes_hard_filters(racket, player)]

    if not hard_survivors:
        return []

    budget_min = player.get("budget_min") or 0
    budget_max = player["budget_max"]

    # Which profiles are still in play at all, after the hard filters
    # but before scoring - this is what the diversity guarantee checks
    # against later. Blank profiles ("" = unknown) don't count as a
    # profile worth guaranteeing a seat for.
    surviving_profiles = {r["profile"] for r in hard_survivors if r["profile"]}

    scored = []
    for racket in hard_survivors:
        price_band = _price_band(racket["price_zar"], budget_min, budget_max)

        # Copy the dict rather than mutate the one catalogue.py handed
        # us - catalogue.py's list is shared, in-memory, module-level
        # state that every request reuses, so writing extra keys
        # straight onto it would leak between requests.
        enriched = dict(racket)
        enriched["_score"] = _soft_score(racket, player, budget_min, budget_max, price_band)
        enriched["_model_line"] = _model_line(racket["name"], racket["brand"])
        enriched["_price_band"] = price_band
        scored.append(enriched)

    ranked = sorted(scored, key=lambda r: r["_score"], reverse=True)

    return _apply_diversity(ranked, surviving_profiles)
