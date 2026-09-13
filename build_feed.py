"""Regenerate the Merchant Center supplemental feed for careerjerseys.com.

Why this exists: the storefront product titles are short and readable for
shoppers. Google Shopping wants the long, keyword-rich form. The long form
lives in the Shopify product metafield custom.full_title, and Merchant Center
reads it from the TSV this script writes.

The feed also carries `size`. Career Jerseys that ship as a wearable garment
have a variant titled "Loose Jersey"; those offers get size L/XL. Framed and
Premium Number editions do not carry that variant title, so they are excluded
by construction. This replaces the old one-time size_feed.tsv upload, which
decayed for the same reason the old title feeds did.

The script also self-heals: any active product with an empty custom.full_title
gets the current product title copied into it, and is listed in
feeds/missing_full_title.txt so a human can write a proper long form later.
"""

import json
import os
import sys
import time
import urllib.request

SHOP = os.environ["SHOPIFY_SHOP"]
CLIENT_ID = os.environ["SHOPIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SHOPIFY_CLIENT_SECRET"]
API = "2025-07"
OUT_DIR = "feeds"
MAX_TITLE = 150  # Google's hard limit on the title attribute
SIZE_VARIANT = "loose jersey"
SIZE_VALUE = "L/XL"

BULK_QUERY = """
{
  products(query: "status:active") {
    edges { node {
      id
      title
      handle
      metafield(namespace: "custom", key: "full_title") { value }
      variants { edges { node { id title } } }
    } }
  }
}
"""


def token():
    body = json.dumps({
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
    }).encode()
    req = urllib.request.Request(
        f"https://{SHOP}/admin/oauth/access_token",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def gql(tok, query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        f"https://{SHOP}/admin/api/{API}/graphql.json",
        data=body,
        headers={"Content-Type": "application/json", "X-Shopify-Access-Token": tok},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.load(r)
    if "errors" in out:
        raise SystemExit(f"GraphQL error: {out['errors']}")
    return out["data"]


def export(tok):
    data = gql(tok, """
      mutation ($q: String!) {
        bulkOperationRunQuery(query: $q) {
          bulkOperation { id status }
          userErrors { field message }
        }
      }""", {"q": BULK_QUERY})
    errs = data["bulkOperationRunQuery"]["userErrors"]
    if errs:
        raise SystemExit(f"Bulk operation refused: {errs}")

    for _ in range(120):  # up to 20 minutes
        time.sleep(10)
        op = gql(tok, """
          { currentBulkOperation(type: QUERY) { status errorCode url objectCount } }
        """)["currentBulkOperation"]
        if op["status"] == "COMPLETED":
            print(f"bulk export complete: {op['objectCount']} objects")
            with urllib.request.urlopen(op["url"], timeout=300) as r:
                return r.read().decode("utf-8")
        if op["status"] in ("FAILED", "CANCELED", "EXPIRED"):
            raise SystemExit(f"Bulk export {op['status']}: {op['errorCode']}")
    raise SystemExit("Bulk export did not finish in time")


def backfill(tok, products):
    """Copy the product title into custom.full_title wherever it is empty."""
    empty = [p for p in products.values() if not p["full_title"]]
    for i in range(0, len(empty), 25):
        batch = [{
            "ownerId": p["id"],
            "namespace": "custom",
            "key": "full_title",
            "type": "single_line_text_field",
            "value": p["title"],
        } for p in empty[i:i + 25]]
        data = gql(tok, """
          mutation ($m: [MetafieldsSetInput!]!) {
            metafieldsSet(metafields: $m) { userErrors { field message } }
          }""", {"m": batch})
        errs = data["metafieldsSet"]["userErrors"]
        if errs:
            raise SystemExit(f"Backfill failed: {errs}")
    for p in empty:
        p["full_title"] = p["title"]
    return empty


def clamp(value):
    """Fit the title inside Google's limit without cutting a word in half."""
    value = value.replace("\t", " ").replace("\n", " ").strip()
    if len(value) <= MAX_TITLE:
        return value
    cut = value[:MAX_TITLE]
    space = cut.rfind(" ")
    return (cut[:space] if space > 60 else cut).rstrip(" ,-")


def main():
    tok = token()
    raw = export(tok)

    products, variants = {}, {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        if o["id"].startswith("gid://shopify/Product/"):
            products[o["id"]] = {
                "id": o["id"],
                "title": o["title"],
                "handle": o["handle"],
                "full_title": (o.get("metafield") or {}).get("value") or "",
                "variants": [],
            }
        else:
            variants.setdefault(o["__parentId"], []).append(
                (o["id"], o.get("title") or "")
            )
    for pid, vids in variants.items():
        if pid in products:
            products[pid]["variants"] = vids

    if not products:
        raise SystemExit("Refusing to write an empty feed")

    healed = backfill(tok, products)

    os.makedirs(OUT_DIR, exist_ok=True)
    rows = 0
    sized = 0
    oversize = []
    with open(f"{OUT_DIR}/full_title_feed.tsv", "w", encoding="utf-8") as f:
        f.write("id\ttitle\tsize\n")
        for p in products.values():
            if len(p["full_title"]) > MAX_TITLE:
                oversize.append(p)
            value = clamp(p["full_title"])
            pid = p["id"].rsplit("/", 1)[-1]
            for vid, vtitle in p["variants"]:
                size = SIZE_VALUE if SIZE_VARIANT in vtitle.lower() else ""
                if size:
                    sized += 1
                f.write(
                    f"shopify_CA_{pid}_{vid.rsplit('/', 1)[-1]}\t{value}\t{size}\n"
                )
                rows += 1

    with open(f"{OUT_DIR}/missing_full_title.txt", "w", encoding="utf-8") as f:
        f.write("Products whose custom.full_title was empty and got the storefront\n")
        f.write("title copied in as a stopgap. Write a proper long-form title for these.\n\n")
        for p in healed:
            f.write(f"{p['handle']}\t{p['title']}\n")

    with open(f"{OUT_DIR}/over_150_chars.txt", "w", encoding="utf-8") as f:
        f.write("Products whose custom.full_title is longer than Google's 150 character\n")
        f.write("limit. The feed cuts them at the last whole word, so the tail is lost.\n")
        f.write("Shorten these by hand to control what survives.\n\n")
        for p in sorted(oversize, key=lambda x: -len(x["full_title"])):
            f.write(f"{len(p['full_title'])}\t{p['handle']}\t{p['full_title']}\n")

    print(f"wrote {rows} offer rows from {len(products)} active products")
    print(f"backfilled custom.full_title on {len(healed)} products")
    print(f"{sized} offers tagged size {SIZE_VALUE}")
    print(f"{len(oversize)} titles exceed {MAX_TITLE} characters and were cut")
    if rows < 1500:
        print("::warning::feed row count is unexpectedly low, check before trusting it")
    if sized == 0:
        print("::warning::no Loose Jersey variants matched, size column is empty")
    return 0


if __name__ == "__main__":
    sys.exit(main())
