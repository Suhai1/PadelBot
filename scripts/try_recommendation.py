"""
scripts/try_recommendation.py - a manual, run-from-the-terminal check
that the whole non-web pipeline works end to end: load the catalogue,
filter and score it for one hardcoded player, then ask Gemini to
explain three picks. Nothing in this file is imported by the real app -
it exists purely so you can see real output before Sprint 4 wires any
of this into Flask.

Run it from the project root with:

    python scripts/try_recommendation.py

Change PLAYER below and re-run to try a different profile - a beginner
with elbow pain, an advanced player wanting power, and so on.
"""

import json
import sys
from pathlib import Path

# This script lives in scripts/, one level below the project root, and
# is run directly (not as a package with `-m`) - so unlike tests/,
# which get the project root on sys.path via pytest.ini, nothing puts
# it there automatically here. Without this line, `from services import
# ...` below would fail with ModuleNotFoundError the same way the bare
# `pytest` command did before pytest.ini existed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import ai, catalogue, recommender


# A hardcoded player profile - deliberately an improver with elbow pain,
# the case PRODUCT.md calls out as the one that matters most (arm pain
# overrides everything). Edit this dict and re-run to try other cases.
PLAYER = {
    "level": "improver",
    "side": "left",
    "style": "balanced",
    "budget_max": 4000,
    "arm_issues": True,
    "frequency": "weekly",
}


def main():
    shortlist = recommender.recommend(PLAYER, catalogue.get_all())
    print(f"Recommender returned {len(shortlist)} candidates for this profile.\n")

    if not shortlist:
        print("No candidates survived the hard filters - nothing to send the AI.")
        return

    try:
        result = ai.get_recommendations(PLAYER, shortlist)
    except ai.AIError as e:
        print(f"AI layer error: {e}")
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
