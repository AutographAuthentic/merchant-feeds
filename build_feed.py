"""Regenerate the Merchant Center title supplemental feed for careerjerseys.com.

Why this exists: the storefront product titles are short and readable for
shoppers. Google Shopping wants the long, keyword-rich form. The long form
lives in the Shopify product metafield custom.full_title, and Merchant Center
reads it from the TSV this script writes.

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

BULK_QUERY = """
{
  products(query: "status:active") {
    edges { node {
      id
      title
      handle
      metafield(namespace: "custom", key: "full_title") { value }
      variants { edges { node { id } } }
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
            variants.setdefault(o["__parentId"], []).append(o["id"])
    for pid, vids in variants.items():
        if pid in products:
            products[pid]["variants"] = vids

    if not products:
        raise SystemExit("Refusing to write an empty feed")

    healed = backfill(tok, products)

    os.makedirs(OUT_DIR, exist_ok=True)
    rows = 0
    with open(f"{OUT_DIR}/full_title_feed.tsv", "w", encoding="utf-8") as f:
        f.write("id\ttitle\n")
        for p in products.values():
            value = p["full_title"].replace("\t", " ").replace("\n", " ").strip()[:150]
            pid = p["id"].rsplit("/", 1)[-1]
            for vid in p["variants"]:
                f.write(f"shopify_CA_{pid}_{vid.rsplit('/', 1)[-1]}\t{value}\n")
                rows += 1

    with open(f"{OUT_DIR}/missing_full_title.txt", "w", encoding="utf-8") as f:
        f.write("Products whose custom.full_title was empty and got the storefront\n")
        f.write("title copied in as a stopgap. Write a proper long-form title for these.\n\n")
        for p in healed:
            f.write(f"{p['handle']}\t{p['title']}\n")

    print(f"wrote {rows} offer rows from {len(products)} active products")
    print(f"backfilled custom.full_title on {len(healed)} products")
    if rows < 1500:
        print("::warning::feed row count is unexpectedly low, check before trusting it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
