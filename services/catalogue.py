"""
catalogue.py - loads data/rackets_catalogue.csv into memory once, when
this module is first imported, and does the minimum possible parsing:
turn price_zar into a real int (recommender.py cannot function without
that), turn weight_g into an int where that's meaningful, and leave
every other column exactly as the CSV wrote it - a string, where ""
means "we don't know this spec". That's the exact contract
services/recommender.py's own docstring already promises its caller,
so this file's job is simply to keep that promise true.

This file answers ONE question: "what's in the catalogue?" It never
asks "what should this player be shown?" - that's recommender.py's job
entirely, and it stays that way on purpose (see ARCHITECTURE.md: no AI,
no filtering logic here).
"""

import csv

from config import Config


def _parse_price(raw):
    """
    price_zar is the one field the whole product cannot work without:
    every hard filter and every soft-scoring signal in recommender.py
    assumes it's a real, positive integer. A blank or unparseable price
    isn't "unknown" the way a blank shape or core is - a racket with no
    known price can't be checked against anyone's budget at all, so it
    isn't a genuine option to recommend.

    Returns an int, or None if the value can't be parsed as a positive
    whole number. None is a signal to the caller: skip this row
    entirely, don't fake a price for it.
    """
    raw = raw.strip()
    if not raw.isdigit():
        return None

    price = int(raw)
    return price if price > 0 else None


def _parse_stores_count(raw):
    """
    How many stores stock this racket. Blank becomes 0 rather than
    crashing - nothing in recommender.py reads this field yet, so 0
    ("we don't know of any store carrying it") is a safe default for
    now. Worth revisiting the moment stores_count is actually used for
    scoring, because "we don't know" and "definitely zero stores" are
    different claims and 0 currently means both.
    """
    raw = raw.strip()
    return int(raw) if raw.isdigit() else 0


def _parse_weight(raw):
    """
    Most rackets in the catalogue have one weight in grams ("370").
    Some only have a manufacturer's range ("360-375") - there's no
    honest single number to collapse a range into, so it's left exactly
    as printed, as a string. Converting only the clean single-number
    case to an int keeps that common case usable for real arithmetic
    (e.g. sorting or averaging by weight, if that's ever needed) without
    inventing precision the data doesn't have for the rest.

    Blank becomes "" - same "unknown" convention as every other field.
    """
    raw = raw.strip()
    if not raw:
        return ""
    if raw.isdigit():
        return int(raw)
    return raw  # a range like "360-375", or any other unexpected text


def _load():
    """
    Reads the CSV exactly once and returns (rackets, skipped_count).
    Kept as its own function, separate from the module-level call
    below, purely so it can be unit tested without relying on import
    side effects - calling _load() twice in a test doesn't re-trigger
    "the whole app's startup sequence", it's just a plain function call.
    """
    rackets = []
    skipped = 0

    with open(Config.CATALOGUE_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            price = _parse_price(row["price_zar"])
            if price is None:
                skipped += 1
                continue

            # Spread the original row first, then overwrite just the
            # three columns that need real parsing - every other column
            # (shape, core, surface, ...) passes through untouched as
            # the plain string csv.DictReader gave us.
            rackets.append(
                {
                    **row,
                    "price_zar": price,
                    "stores_count": _parse_stores_count(row["stores_count"]),
                    "weight_g": _parse_weight(row["weight_g"]),
                }
            )

    return rackets, skipped


# ---------------------------------------------------------------------------
# Runs exactly once: the moment something first does
# `from services import catalogue` (e.g. app.py at Flask startup, or a
# test file). Every other file that imports this module afterwards
# gets the SAME list object back - Python caches modules after their
# first import, so this loop does not run again. See get_all()'s
# docstring for why sharing one list (instead of copying it per caller)
# is deliberate, not an oversight.
# ---------------------------------------------------------------------------

_RACKETS, _SKIPPED_ROWS = _load()


def get_all():
    """
    Returns every racket that loaded successfully.

    This is the SAME list object every caller gets, not a fresh copy -
    copying all ~450 dicts on every single call would undercut the
    entire point of loading the CSV into memory once. That makes this
    list, in effect, shared read-only state for the process: callers
    must not mutate a racket dict in place or add/remove/sort entries
    on the returned list, or the change leaks into every other request
    that ever calls get_all() again. recommender.py already follows
    this rule - it copies each racket dict (`dict(racket)`) before
    adding its own _score/_model_line fields rather than writing onto
    what get_all() hands back.
    """
    return _RACKETS


def stats():
    """
    A few numbers about what actually loaded - useful for a startup log
    line or a debug endpoint later. Not used by recommender.py; it only
    ever calls get_all().
    """
    return {
        "total_rackets": len(_RACKETS),
        "rows_skipped_missing_price": _SKIPPED_ROWS,
    }
