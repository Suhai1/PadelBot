"""
merge_pass2.py

WHY THIS EXISTS
The first normaliser built its matching key by joining the words of a
product name in the order they appeared. That broke, because stores put
the model year in different places:

    PadelDeals    "2025 Adidas Metalbone 3.4"
    PadelZone     "Adidas Metalbone 3.4"
    Africa Padel  "Adidas Metalbone 3.4 2025"

Three names, one racket, three different keys. So 668 rackets looked like
they were sold at only one store, which is nonsense.

THE TWO FIXES
1. SORT the words before joining. Word order stops mattering, so
   "metalbone 3.4 2025" and "2025 metalbone 3.4" become identical.
2. Pull the YEAR out of the key and handle it separately, because
   Bullpadel Icon 2025 and Bullpadel Icon 2026 really are different
   rackets at very different prices. The rule used here: if two listings
   both state a year and the years differ, keep them apart. If one has no
   year, assume it belongs with the most common year in that group.

THE LESSON WORTH KEEPING
Fuzzy matching real-world data is never "write the rule and walk away".
You write a rule, look at what it merged, find the cases it got wrong,
tighten it, look again. The reports at the bottom of this script exist
so you can keep doing that.

HOW TO RUN
    python merge_pass2.py

Reads rackets_clean.csv, writes rackets_final.csv.
"""

import csv
import re
from collections import defaultdict, Counter


INPUT_FILE = "rackets_clean.csv"
OUTPUT_FILE = "rackets_final.csv"


# Words that carry no model information.
NOISE_WORDS = {
    "padel", "racket", "racquet", "pala", "bat", "paddle", "tennis",
    "new", "sale", "clearance", "edition", "collection", "by",
}

# Longest first so "star vie" is removed before shorter fragments.
BRAND_TOKENS = [
    "black crown", "royal padel", "drop shot", "outer armour", "star vie",
    "el toro", "starvie", "bullpadel", "babolat", "varlion", "hirostar",
    "vibor-a", "vibora", "kuikma", "adidas", "wilson", "dunlop", "cartri",
    "osaka", "siux", "head", "kupe", "hyko", "nox", "lok", "lõk", "puma",
    "4on",
]

BRAND_DISPLAY = {
    "black crown": "Black Crown", "royal padel": "Royal Padel",
    "drop shot": "Drop Shot", "outer armour": "Outer Armour",
    "star vie": "StarVie", "starvie": "StarVie", "el toro": "El Toro",
    "bullpadel": "Bullpadel", "babolat": "Babolat", "varlion": "Varlion",
    "hirostar": "Hirostar", "vibor-a": "Vibor-A", "vibora": "Vibor-A",
    "kuikma": "Kuikma", "adidas": "Adidas", "wilson": "Wilson",
    "dunlop": "Dunlop", "cartri": "Cartri", "osaka": "Osaka",
    "siux": "Siux", "head": "Head", "kupe": "Kupe", "hyko": "Hyko",
    "nox": "Nox", "lok": "LOK", "lõk": "LOK", "puma": "Puma", "4on": "4On",
}


def fix_brand(raw_brand, name):
    """
    Repair the brand field.

    Some rows ended up with a year ("2026") or a store name
    ("Africa Padel Online Store") in the brand column, because that is
    what the shop put in its own data. When the stored brand is not a
    brand we recognise, read it off the product title instead.
    """
    cleaned = (raw_brand or "").strip()
    lowered = cleaned.lower()

    if lowered in BRAND_DISPLAY:
        return BRAND_DISPLAY[lowered]

    # Looks like a year, or a store name, or empty. Read the title.
    name_lower = name.lower()
    for token in BRAND_TOKENS:
        if token in name_lower:
            return BRAND_DISPLAY[token]

    return cleaned or "Unknown"


def extract_year(name):
    match = re.search(r"\b(20\d{2})\b", name)
    return match.group(1) if match else ""


def base_key(name, brand):
    """
    Build an order-independent, year-independent key for a racket.

    "2025 Adidas Metalbone 3.4"  ->  ("Adidas", "3 4 metalbone")
    "Adidas Metalbone 3.4 2025"  ->  ("Adidas", "3 4 metalbone")
    """
    text = name.lower()

    for token in BRAND_TOKENS:
        text = text.replace(token, " ")

    text = re.sub(r"[|/\\\-–—,.:()\[\]&+']", " ", text)
    text = re.sub(r"\b20\d{2}\b", " ", text)          # year handled separately

    words = sorted(w for w in text.split() if w not in NOISE_WORDS)
    return (brand, " ".join(words))


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def pick_best(values):
    """Non-empty wins; if several, the most common wins."""
    filled = [v for v in values if v and str(v).strip()]
    if not filled:
        return ""
    return max(set(filled), key=filled.count)


def merge_group(rows):
    """Combine several rows describing the same racket into one."""

    # Price range across every store that stocks it.
    lows = [to_int(r.get("price_zar")) for r in rows]
    highs = [to_int(r.get("price_high_zar")) for r in rows]
    lows = [p for p in lows if p]
    highs = [p for p in highs if p]

    low = min(lows) if lows else ""
    high = max(highs + lows) if (highs or lows) else ""

    # Whichever row held the lowest price tells us the cheapest store.
    cheapest_store = ""
    url = ""
    best = None
    for row in rows:
        price = to_int(row.get("price_zar"))
        if price and (best is None or price < best):
            best = price
            cheapest_store = row.get("cheapest_store", "")
            url = row.get("url", "")
    if not url and rows:
        url = rows[0].get("url", "")

    # Union of every store name mentioned across the group.
    stores = set()
    for row in rows:
        for name in (row.get("stores") or "").split("|"):
            name = name.strip()
            if name:
                stores.add(name)

    description = max(
        (r.get("description", "") for r in rows), key=len, default=""
    )

    # Shortest title is usually the cleanest, minus marketing padding.
    display_name = min((r["name"] for r in rows), key=len).strip()

    return {
        "brand": rows[0]["_brand"],
        "name": display_name,
        "year": pick_best([extract_year(r["name"]) for r in rows]),
        "shape": pick_best([r.get("shape", "") for r in rows]),
        "weight_g": pick_best([r.get("weight_g", "") for r in rows]),
        "balance": pick_best([r.get("balance", "") for r in rows]),
        "core": pick_best([r.get("core", "") for r in rows]),
        "surface": pick_best([r.get("surface", "") for r in rows]),
        "price_zar": low,
        "price_high_zar": high,
        "price_spread": (high - low) if (low and high) else "",
        "cheapest_store": cheapest_store,
        "stores_count": len(stores),
        "stores": " | ".join(sorted(stores)),
        "level": pick_best([r.get("level", "") for r in rows]),
        "best_for": "",
        "in_stock": "yes" if any(r.get("in_stock") == "yes" for r in rows) else "no",
        "url": url,
        "description": description[:400],
    }


def main():
    with open(INPUT_FILE, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    print(f"Read {len(rows)} rows\n")

    # Repair brands first, since the key depends on them.
    for row in rows:
        row["_brand"] = fix_brand(row.get("brand"), row.get("name", ""))

    # PASS ONE: group ignoring the year completely.
    loose = defaultdict(list)
    for row in rows:
        loose[base_key(row["name"], row["_brand"])].append(row)

    # PASS TWO: split any group where two listings state different years.
    final = defaultdict(list)
    for key, group in loose.items():
        years = [extract_year(r["name"]) for r in group]
        stated = [y for y in years if y]

        if len(set(stated)) <= 1:
            # All agree, or nobody said. Keep as one racket.
            final[key + ("",)] = group
        else:
            # Genuinely different model years. Split them.
            # Rows with no year join the most common year in the group.
            fallback = Counter(stated).most_common(1)[0][0]
            for row in group:
                year = extract_year(row["name"]) or fallback
                final[key + (year,)].append(row)

    merged = [merge_group(group) for group in final.values()]
    merged.sort(key=lambda r: (r["brand"].lower(), r["name"].lower()))

    fieldnames = [
        "brand", "name", "year", "shape", "weight_g", "balance", "core",
        "surface", "price_zar", "price_high_zar", "price_spread",
        "cheapest_store", "stores_count", "stores", "level", "best_for",
        "in_stock", "url", "description",
    ]

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged)

    print(f"{len(rows)} -> {len(merged)} unique models\n")

    # --- REPORTS: read these, do not skip them ---

    print("Models per brand:")
    per_brand = Counter(r["brand"] for r in merged)
    for brand, count in per_brand.most_common():
        print(f"  {count:4}  {brand}")

    print("\nStocked at the most stores:")
    for row in sorted(merged, key=lambda r: -r["stores_count"])[:10]:
        print(f"  {row['stores_count']}x  R{row['price_zar']:<6} {row['name']}")

    print("\nBiggest price spreads (verify these are the same racket):")
    spreads = [r for r in merged if isinstance(r["price_spread"], int)]
    for row in sorted(spreads, key=lambda r: -r["price_spread"])[:10]:
        print(
            f"  R{row['price_spread']:<6} "
            f"R{row['price_zar']}-R{row['price_high_zar']}  {row['name']}"
        )

    print("\nMissing specs:")
    for field in ["shape", "weight_g", "balance", "core", "surface"]:
        blank = sum(1 for r in merged if not r[field])
        pct = round(100 * blank / len(merged))
        print(f"  {field}: {blank} blank ({pct}%)")


if __name__ == "__main__":
    main()