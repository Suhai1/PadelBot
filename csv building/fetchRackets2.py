"""
normalise_rackets.py

WHAT THIS DOES
Takes the messy rackets.csv from the fetcher and turns it into
rackets_clean.csv, where each row is ONE racket model rather than one
shop listing. Prices from every store that carries it get collapsed into
that single row, along with which store is cheapest.

WHY THIS MATTERS FOR THE CHATBOT
Right now the same racket appears up to seven times. If you feed that to
an AI, it will happily recommend "the Adidas Metalbone Team" three times
in one answer at three different prices, which looks broken. It also
wastes tokens on repeated data.

What you actually want the bot to say is: this racket, here is what it
costs, and here is the cheapest place to get it. That needs one row per
model, which is what this script produces.

THE HARD PART
Deciding whether two listings are the same racket. Stores write names
differently:
    "Adidas Metalbone Team Padel Racket | 2026"
    "adidas Metalbone Team 2026"
    "Adidas METALBONE TEAM - 2026"
All three are one racket. The approach here is to strip away everything
that is noise (brand name, the words "padel racket", the year, punctuation)
and compare what is left. That leftover is called a "key".

This is not perfect and it is not meant to be. It will merge a few things
it should not and miss a few it should catch. The script prints the
biggest groups so you can eyeball them and fix the rules.

HOW TO RUN
    python normalise_rackets.py
"""

import csv
import re
from collections import defaultdict


INPUT_FILE = "rackets.csv"
OUTPUT_FILE = "rackets_clean.csv"


# ---------------------------------------------------------------------
# 1. BRAND CLEANUP
# ---------------------------------------------------------------------
# Maps every spelling variant we saw onto one canonical name. Add to this
# list whenever you spot a new variant in the output.

BRAND_MAP = {
    "adidas": "Adidas",
    "bullpadel": "Bullpadel",
    "babolat": "Babolat",
    "siux": "Siux",
    "nox": "Nox",
    "head": "Head",
    "lok": "LOK",
    "lõk": "LOK",
    "varlion": "Varlion",
    "wilson": "Wilson",
    "starvie": "StarVie",
    "star vie": "StarVie",
    "hirostar": "Hirostar",
    "kupe": "Kupe",
    "hyko": "Hyko",
    "el toro": "El Toro",
    "cartri": "Cartri",
    "black crown": "Black Crown",
    "dunlop": "Dunlop",
    "royal padel": "Royal Padel",
    "vibor-a": "Vibor-A",
    "vibora": "Vibor-A",
    "drop shot": "Drop Shot",
    "kuikma": "Kuikma",
    "4on": "4On",
    "outer armour": "Outer Armour",
}

# Longest first, so "star vie" is checked before "vie" style fragments
# and "black crown" before any single word inside it.
BRANDS_BY_LENGTH = sorted(BRAND_MAP.keys(), key=len, reverse=True)


def clean_brand(raw_brand, product_name):
    """
    Work out the real manufacturer.

    Some stores put their own name in the brand field (Africa Padel does
    this), so if the stored brand is not one we recognise, we fall back
    to reading the brand off the front of the product name.
    """
    if raw_brand:
        lowered = raw_brand.strip().lower()
        if lowered in BRAND_MAP:
            return BRAND_MAP[lowered]

    # Fall back to searching the product title.
    name_lower = product_name.lower()
    for candidate in BRANDS_BY_LENGTH:
        if candidate in name_lower:
            return BRAND_MAP[candidate]

    return raw_brand.strip() if raw_brand else "Unknown"


# ---------------------------------------------------------------------
# 2. MODEL KEY
# ---------------------------------------------------------------------
# Strip out everything that is not the model name, so the same racket
# from different stores produces the same key.

NOISE_WORDS = [
    "padel", "racket", "racquet", "pala", "bat", "paddle",
    "tennis", "new", "sale", "clearance", "edition", "collection",
]


def make_model_key(name, brand):
    """
    Turn a messy product title into a comparable key.

    Example:
        "Adidas Metalbone Team Padel Racket | 2026"  ->  "metalbone team 2026"
        "adidas Metalbone Team 2026"                 ->  "metalbone team 2026"
    """
    text = name.lower()

    # Remove the brand name, since we track it separately.
    for candidate in BRANDS_BY_LENGTH:
        text = text.replace(candidate, " ")

    # Remove punctuation and separators.
    text = re.sub(r"[|/\\\-–—,.:()\[\]&+']", " ", text)

    # Remove noise words.
    words = [w for w in text.split() if w not in NOISE_WORDS]

    # Collapse whitespace.
    return " ".join(words).strip()


def extract_year(name):
    """Pull a model year out of the title if there is one."""
    match = re.search(r"\b(20\d{2})\b", name)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------
# 3. MERGING
# ---------------------------------------------------------------------

def pick_best(values):
    """
    Given the same field from several listings, pick the most useful one.
    Non-empty beats empty. If several are filled, take the most common.
    """
    filled = [v for v in values if v and str(v).strip()]
    if not filled:
        return ""
    # Most frequently occurring value wins.
    return max(set(filled), key=filled.count)


def merge_group(listings):
    """Turn several listings of the same racket into one clean row."""

    names = [item["name"] for item in listings]
    brand = pick_best([item["_brand"] for item in listings])

    # Use the shortest name as the display name. Shorter titles tend to
    # be cleaner, with less marketing padding.
    display_name = min(names, key=len).strip()

    # Gather prices per store.
    prices = {}
    for item in listings:
        try:
            price = int(item["price_zar"])
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        store = item["store"]
        # If a store lists it twice, keep the lower price.
        if store not in prices or price < prices[store]:
            prices[store] = price

    if prices:
        cheapest_store = min(prices, key=prices.get)
        cheapest_price = prices[cheapest_store]
        highest_price = max(prices.values())
    else:
        cheapest_store = ""
        cheapest_price = ""
        highest_price = ""

    # Prefer a URL from the cheapest store.
    url = ""
    for item in listings:
        if item["store"] == cheapest_store:
            url = item["url"]
            break
    if not url and listings:
        url = listings[0]["url"]

    # Longest description usually has the most spec detail in it.
    description = max(
        (item.get("description", "") for item in listings), key=len, default=""
    )

    in_stock_anywhere = any(item.get("in_stock") == "yes" for item in listings)

    return {
        "brand": brand,
        "name": display_name,
        "year": pick_best([extract_year(n) for n in names]),
        "shape": pick_best([item["shape"] for item in listings]),
        "weight_g": pick_best([item["weight_g"] for item in listings]),
        "balance": pick_best([item["balance"] for item in listings]),
        "core": pick_best([item["core"] for item in listings]),
        "surface": pick_best([item["surface"] for item in listings]),
        "price_zar": cheapest_price,
        "price_high_zar": highest_price,
        "cheapest_store": cheapest_store,
        "stores_count": len(prices),
        "stores": " | ".join(sorted(prices.keys())),
        "level": pick_best([item["level"] for item in listings]),
        "best_for": "",
        "in_stock": "yes" if in_stock_anywhere else "no",
        "url": url,
        "description": description[:400],
    }


# ---------------------------------------------------------------------
# 4. MAIN
# ---------------------------------------------------------------------

def main():
    with open(INPUT_FILE, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    print(f"Read {len(rows)} listings\n")

    # Group listings by brand plus model key.
    groups = defaultdict(list)

    for row in rows:
        brand = clean_brand(row.get("brand", ""), row.get("name", ""))
        row["_brand"] = brand

        key = make_model_key(row.get("name", ""), brand)

        # Skip anything with an empty key, it is almost certainly junk.
        if not key:
            continue

        groups[(brand, key)].append(row)

    merged = [merge_group(listings) for listings in groups.values()]

    # Sort by brand then name so the file is easy to read by hand.
    merged.sort(key=lambda r: (r["brand"].lower(), r["name"].lower()))

    fieldnames = [
        "brand", "name", "year", "shape", "weight_g", "balance", "core",
        "surface", "price_zar", "price_high_zar", "cheapest_store",
        "stores_count", "stores", "level", "best_for", "in_stock", "url",
        "description",
    ]

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged)

    print(f"Wrote {len(merged)} unique models to {OUTPUT_FILE}")
    print(f"Collapsed {len(rows)} listings down to {len(merged)}\n")

    # --- Reports so you can sanity check the result ---

    print("Models per brand:")
    per_brand = defaultdict(int)
    for row in merged:
        per_brand[row["brand"]] += 1
    for brand, count in sorted(per_brand.items(), key=lambda x: -x[1]):
        print(f"  {count:4}  {brand}")

    print("\nCarried by the most stores (these merges are most likely correct):")
    for row in sorted(merged, key=lambda r: -r["stores_count"])[:12]:
        print(f"  {row['stores_count']} stores  R{row['price_zar']:<6} {row['name']}")

    print("\nBiggest price gaps (check these, a wrong merge shows up here):")
    gaps = []
    for row in merged:
        try:
            low, high = int(row["price_zar"]), int(row["price_high_zar"])
        except (TypeError, ValueError):
            continue
        if low and high > low:
            gaps.append((high - low, row))
    for gap, row in sorted(gaps, key=lambda x: -x[0])[:10]:
        print(f"  R{gap:<6} R{row['price_zar']}-R{row['price_high_zar']}  {row['name']}")

    print("\nStill missing specs:")
    for field in ["shape", "weight_g", "balance", "core"]:
        blank = sum(1 for r in merged if not r[field])
        print(f"  {field}: {blank} of {len(merged)}")


if __name__ == "__main__":
    main()