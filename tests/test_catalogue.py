"""
test_catalogue.py - "the tests that actually matter", per
ARCHITECTURE.md's file layout.

These check the two things recommender.py's whole contract depends on
catalogue.py getting right: the CSV actually loads, and every racket
handed out has a real, usable price and enough identity (name, brand)
to ever be shown to a player. They don't re-test recommender.py's own
logic - that's test_recommender.py's job.
"""

from services import catalogue


def test_catalogue_loads():
    rackets = catalogue.get_all()
    assert isinstance(rackets, list)
    assert len(rackets) > 0


def test_catalogue_has_enough_rackets():
    """
    PRODUCT.md quotes 521 rackets, and the CSV in data/ now matches
    that exactly (level and profile counts line up too - see the
    v2 catalogue swap). 400 is deliberately a sanity floor, not the
    exact number: it's here to catch "the CSV came back empty" or
    "half the rows failed to parse", not to lock in a specific row
    count that will keep drifting every time the scraper re-runs.
    """
    assert len(catalogue.get_all()) > 400


def test_no_price_is_zero_or_negative():
    for racket in catalogue.get_all():
        assert racket["price_zar"] > 0, f'{racket["name"]} has price_zar={racket["price_zar"]}'


def test_every_racket_has_name_and_brand():
    for racket in catalogue.get_all():
        assert racket["name"].strip(), "found a racket with a blank name"
        assert racket["brand"].strip(), f'{racket["name"]} has a blank brand'


def test_stats_matches_get_all():
    assert catalogue.stats()["total_rackets"] == len(catalogue.get_all())
