"""
fetch_rackets_v2.py

WHAT CHANGED FROM VERSION 1
Version 1 only understood Shopify stores. World of Padel runs on
WooCommerce instead, which is a completely different e-commerce platform
built on WordPress. It stores the same kind of data but hands it over at
a different address and in a different shape.

So this version knows about both. Each store in the list below now has a
"platform" key, and the script picks the right fetching function based
on that. This is a common pattern in real backend work: you write one
small adapter per external service, then everything downstream works with
the same tidy format regardless of where the data came from.

THE TWO ENDPOINTS
  Shopify:     /collections/<name>/products.json?limit=250&page=1
  WooCommerce: /wp-json/wc/store/v1/products?per_page=100&page=1

Both are public. Neither needs a key. Neither is scraping.

BEFORE YOU RUN THIS
Paste each store's endpoint into your browser first and check you get
JSON back. If you get a 404 or an HTML error page, the collection name
or category id is wrong, or the site has its API switched off.

HOW TO RUN
    source venv/bin/activate
    pip install requests
    python fetch_rackets_v2.py
"""

import csv
import html
import re
import time

import requests


# ---------------------------------------------------------------------
# 1. STORES
# ---------------------------------------------------------------------
# For Shopify stores, "collection" is the racket collection in the URL.
# For WooCommerce stores, "category_slug" filters to rackets only. If you
# leave it blank the script pulls everything and filters by name later,
# which is slower but works when you do not know the slug.

STORES = [
    {
        "name": "PadelGear",
        "platform": "shopify",
        "base_url": "https://www.padelgear.co.za",
        "collection": "rackets",
    },
    {
        "name": "PadelZone",
        "platform": "shopify",
        "base_url": "https://padelzone.co.za",
        "collection": "padel-rackets",
    },
    {
        "name": "PadelDeals",
        "platform": "shopify",
        "base_url": "https://padeldeals.co.za",
        "collection": "padel-rackets",
    },
    {
        "name": "World of Padel",
        "platform": "woocommerce",
        "base_url": "https://worldofpadel.co.za",
        "category_slug": "padel-rackets",
    },
    {
    "name": "Virgin Active Padel Club",
    "platform": "shopify",
    "base_url": "https://virginactivepadelclub.co.za",
    "collection": "rackets",
},
{
    "name": "The Padel Market",
    "platform": "shopify",
    "base_url": "https://thepadelmarket.co.za",
    "collection": "padel-rackets",
},
{
    "name": "Africa Padel",
    "platform": "shopify",
    "base_url": "https://africapadelshop.com",
    "collection": "rackets",
},
{
    "name": "Spin Blade",
    "platform": "woocommerce",
    "base_url": "https://spinblade.co.za",
    "category_slug": "padel-rackets",
},
]


HEADERS = {
    "User-Agent": "PadelPal-Research/1.0 (student project; contact: your@email.com)"
}

POLITE_DELAY = 1.5

# If a product name contains none of these, we assume it is not a racket.
# This is a safety net for when the category filter does not work.
RACKET_HINTS = ["racket", "racquet", "pala", "bat", "paddle"]

# And if it contains any of these it is definitely not a racket, even if
# the word "racket" appears (for example "racket bag").
NOT_RACKET = ["bag", "cover", "grip", "overgrip", "protector", "ball",
              "sock", "shoe", "cap", "towel", "shirt", "short", "gift card",
              "pressurizer", "spray", "wristband", "machine"]


# ---------------------------------------------------------------------
# 2. TEXT HELPERS
# ---------------------------------------------------------------------

def strip_html(raw):
    """Turn HTML into plain readable text."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def looks_like_racket(name):
    """Rough check so we do not fill the CSV with bags and socks."""
    lowered = name.lower()
    if any(bad in lowered for bad in NOT_RACKET):
        return False
    return True


def guess_shape(text):
    lowered = text.lower()
    if "diamond" in lowered:
        return "diamond"
    if "teardrop" in lowered or "tear drop" in lowered or "tear-drop" in lowered:
        return "teardrop"
    if "round" in lowered:
        return "round"
    return ""


def guess_weight(text):
    match = re.search(r"(\d{3})\s*[-–]?\s*(\d{3})?\s*g\b", text, re.IGNORECASE)
    return match.group(1) if match else ""


def guess_balance(text):
    lowered = text.lower()
    if "high balance" in lowered:
        return "high"
    if "low balance" in lowered:
        return "low"
    if "medium balance" in lowered or "mid balance" in lowered:
        return "medium"
    return ""


def guess_core(text):
    lowered = text.lower()
    if "soft eva" in lowered or "eva soft" in lowered:
        return "soft EVA"
    if "hard eva" in lowered or "eva hard" in lowered:
        return "hard EVA"
    if "medium eva" in lowered or "eva medium" in lowered:
        return "medium EVA"
    if "foam" in lowered:
        return "foam"
    if "eva" in lowered:
        return "EVA"
    return ""


def guess_surface(text):
    lowered = text.lower()
    for grade in ["18k", "15k", "12k", "3k"]:
        if grade in lowered:
            return f"{grade.upper()} carbon"
    if "carbon" in lowered:
        return "carbon"
    if "fibreglass" in lowered or "fiberglass" in lowered:
        return "fibreglass"
    return ""


def guess_level_from_price(price):
    if not price:
        return ""
    if price < 2500:
        return "beginner"
    if price < 4500:
        return "improver"
    if price < 6500:
        return "intermediate"
    return "advanced"


def make_row(name, brand, price, description, in_stock, url, store_name):
    """
    One place that builds a tidy row, used by both platform fetchers.
    Keeping this shared means the CSV always has the same shape no matter
    which store the data came from.
    """
    searchable = f"{name} {description}"
    return {
        "name": name.strip(),
        "brand": brand.strip(),
        "shape": guess_shape(searchable),
        "weight_g": guess_weight(searchable),
        "balance": guess_balance(searchable),
        "core": guess_core(searchable),
        "surface": guess_surface(searchable),
        "price_zar": int(price) if price else "",
        "level": guess_level_from_price(price),
        "best_for": "",
        "in_stock": "yes" if in_stock else "no",
        "store": store_name,
        "url": url,
        "description": description[:400],
    }


# ---------------------------------------------------------------------
# 3. SHOPIFY FETCHER
# ---------------------------------------------------------------------

def fetch_shopify(store):
    rows = []
    page = 1

    while True:
        url = (
            f"{store['base_url']}/collections/{store['collection']}"
            f"/products.json?limit=250&page={page}"
        )
        print(f"  page {page}...")

        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
        except requests.RequestException as error:
            print(f"  could not reach store: {error}")
            break

        if response.status_code != 200:
            print(f"  status {response.status_code}, stopping")
            break

        try:
            products = response.json().get("products", [])
        except ValueError:
            print("  not JSON. Check the collection name.")
            break

        if not products:
            break

        for product in products:
            name = product.get("title", "")
            if not looks_like_racket(name):
                continue

            variants = product.get("variants") or [{}]
            first = variants[0]

            try:
                price = float(first.get("price") or 0)
            except (TypeError, ValueError):
                price = 0.0

            rows.append(make_row(
                name=name,
                brand=product.get("vendor", ""),
                price=price,
                description=strip_html(product.get("body_html", "")),
                in_stock=first.get("available"),
                url=f"{store['base_url']}/products/{product.get('handle', '')}",
                store_name=store["name"],
            ))

        page += 1
        time.sleep(POLITE_DELAY)

    return rows


# ---------------------------------------------------------------------
# 4. WOOCOMMERCE FETCHER
# ---------------------------------------------------------------------
# WooCommerce shapes its data differently to Shopify:
#   - price lives in prices.price and is in CENTS, so we divide by 100
#   - brand is usually not a field at all, so we guess it from the name
#   - stock status is a string like "instock" rather than a true/false
# This is exactly why we have a separate function per platform.

KNOWN_BRANDS = [
    "Adidas", "Babolat", "Bullpadel", "Nox", "Head", "Varlion", "Siux",
    "StarVie", "Star Vie", "El Toro", "Cartri", "Lok", "Hyko", "Kupe",
    "Black Crown", "Wilson", "Dunlop", "Royal Padel", "Vibor-A", "Drop Shot",
]


def guess_brand_from_name(name):
    """WooCommerce rarely stores a brand field, so read it off the title."""
    for brand in KNOWN_BRANDS:
        if brand.lower() in name.lower():
            return brand
    # Fall back to the first word, which is usually the brand.
    return name.split()[0] if name.split() else ""


def fetch_woocommerce(store):
    rows = []
    page = 1

    while True:
        url = f"{store['base_url']}/wp-json/wc/store/v1/products"
        params = {"per_page": 100, "page": page}

        # Filter to rackets if we know the category slug.
        if store.get("category_slug"):
            params["category"] = store["category_slug"]

        print(f"  page {page}...")

        try:
            response = requests.get(
                url, headers=HEADERS, params=params, timeout=20
            )
        except requests.RequestException as error:
            print(f"  could not reach store: {error}")
            break

        if response.status_code == 404:
            print("  404. The Store API may be disabled, or the slug is wrong.")
            print("  Try opening this in your browser to check:")
            print(f"  {url}?per_page=5")
            break

        if response.status_code != 200:
            print(f"  status {response.status_code}, stopping")
            break

        try:
            products = response.json()
        except ValueError:
            print("  not JSON. The API is probably off for this site.")
            break

        if not isinstance(products, list) or not products:
            break

        for product in products:
            name = product.get("name", "")
            if not looks_like_racket(name):
                continue

            # WooCommerce gives prices in the smallest currency unit.
            # For rands that means cents, so 349500 is R3495.
            prices = product.get("prices") or {}
            raw_price = prices.get("price")
            try:
                minor_units = int(prices.get("currency_minor_unit", 2))
                price = float(raw_price) / (10 ** minor_units) if raw_price else 0.0
            except (TypeError, ValueError):
                price = 0.0

            description = strip_html(
                product.get("description") or product.get("short_description", "")
            )

            rows.append(make_row(
                name=name,
                brand=guess_brand_from_name(name),
                price=price,
                description=description,
                in_stock=product.get("is_in_stock", False),
                url=product.get("permalink", ""),
                store_name=store["name"],
            ))

        page += 1
        time.sleep(POLITE_DELAY)

    return rows


# ---------------------------------------------------------------------
# 5. MAIN
# ---------------------------------------------------------------------

def main():
    all_rows = []

    for store in STORES:
        print(f"\n{store['name']} ({store['platform']})")

        if store["platform"] == "shopify":
            rows = fetch_shopify(store)
        elif store["platform"] == "woocommerce":
            rows = fetch_woocommerce(store)
        else:
            print("  unknown platform, skipping")
            rows = []

        print(f"  kept {len(rows)} rackets")
        all_rows.extend(rows)

    if not all_rows:
        print("\nNothing fetched. Check the URLs in STORES.")
        return

    # Same racket at the same store should only appear once.
    seen = set()
    unique_rows = []
    for row in all_rows:
        key = (row["store"], row["name"].lower())
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)

    fieldnames = [
        "name", "brand", "shape", "weight_g", "balance", "core", "surface",
        "price_zar", "level", "best_for", "in_stock", "store", "url",
        "description",
    ]

    with open("rackets.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unique_rows)

    print(f"\nDone. {len(unique_rows)} rackets written to rackets.csv")

    # A quick report so you know how much manual work is left.
    print("\nPer store:")
    for store in STORES:
        count = sum(1 for r in unique_rows if r["store"] == store["name"])
        print(f"  {store['name']}: {count}")

    missing_shape = sum(1 for r in unique_rows if not r["shape"])
    missing_weight = sum(1 for r in unique_rows if not r["weight_g"])
    print(f"\nBlank shape: {missing_shape}")
    print(f"Blank weight: {missing_weight}")
    print("Fill those in by hand. The description column is your source.")


if __name__ == "__main__":
    main()