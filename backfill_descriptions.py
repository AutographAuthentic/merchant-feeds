"""Backfill product descriptions on careerjerseys.com.

Dry run by default. It exports every active product, composes a new description
for the thin ones with descriptions.py, repairs punctuation on the rest, and
writes a proposal and a rollback file for both passes. Nothing reaches Shopify
unless APPLY=1 is set.

    python backfill_descriptions.py            # proposal + rollback only
    APPLY=1 python backfill_descriptions.py    # also writes to Shopify

Outputs, committed by the workflow so every run is reviewable in git:
    descriptions/proposed.csv   product_id, title, old_words, new_words, html
    descriptions/rollback.csv   product_id, previous descriptionHtml
    descriptions/skipped.csv    products left alone, with the reason
    descriptions/repaired.csv   punctuation repairs, before and after
"""

import csv
import json
import os
import sys
import time
import urllib.request

from descriptions import build, words
from repair_punctuation import changed as repair_changed, safe as repair_safe

SHOP = os.environ["SHOPIFY_SHOP"]
CLIENT_ID = os.environ["SHOPIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SHOPIFY_CLIENT_SECRET"]
API = "2025-07"
APPLY = os.environ.get("APPLY") == "1"
OUT_DIR = "descriptions"

WORD_THRESHOLD = int(os.environ.get("WORD_THRESHOLD", "50"))
# A single run should never rewrite most of the catalogue. If it wants to, the
# threshold or the export is wrong and stopping is the correct outcome.
MAX_SHARE = float(os.environ.get("MAX_SHARE", "0.85"))
# Shipping Protection and the Gift Card are not products a shopper reads.
EXCLUDE = {"8333997932633", "7453800235097"}

BULK_QUERY = """
{
  products(query: "status:active") {
    edges { node {
      id
      title
      handle
      vendor
      productType
      tags
      description
      descriptionHtml
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
    for _ in range(120):
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


def apply_batch(tok, batch):
    ops = "\n".join(
        f'  u{i}: productUpdate(product: {{id: "{p["id"]}", '
        f"descriptionHtml: {json.dumps(p['html'])}}}) "
        "{ userErrors { field message } }"
        for i, p in enumerate(batch)
    )
    data = gql(tok, "mutation {\n" + ops + "\n}")
    for key, res in data.items():
        if res and res.get("userErrors"):
            raise SystemExit(f"productUpdate failed on {key}: {res['userErrors']}")


def main():
    tok = token()
    raw = export(tok)

    products = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        if not o["id"].startswith("gid://shopify/Product/"):
            continue
        products.append({
            "id": o["id"],
            "pid": o["id"].rsplit("/", 1)[-1],
            "title": o.get("title") or "",
            "handle": o.get("handle") or "",
            "tags": o.get("tags") or [],
            "productType": o.get("productType") or "",
            "description": o.get("description") or "",
            "descriptionHtml": o.get("descriptionHtml") or "",
        })
    if not products:
        raise SystemExit("Refusing to act on an empty export")
    print(f"{len(products)} active products")

    targets, skipped = [], []
    for p in products:
        if p["pid"] in EXCLUDE:
            skipped.append((p["pid"], p["title"], "excluded by design"))
            continue
        old = len(p["description"].split())
        if old >= WORD_THRESHOLD:
            skipped.append((p["pid"], p["title"], f"already {old} words"))
            continue
        html = build({"id": p["id"], "title": p["title"], "tags": p["tags"],
                      "productType": p["productType"], "description": p["description"]})
        new = words(html)
        if new <= old:
            skipped.append((p["pid"], p["title"], f"would not lengthen ({old} -> {new})"))
            continue
        targets.append({**p, "html": html, "old_words": old, "new_words": new})

    share = len(targets) / len(products)
    print(f"{len(targets)} to rewrite ({share:.0%}), {len(skipped)} left alone")
    if share > MAX_SHARE:
        raise SystemExit(
            f"Refusing to rewrite {share:.0%} of the catalogue. Check WORD_THRESHOLD."
        )

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(f"{OUT_DIR}/proposed.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "handle", "title", "old_words", "new_words", "new_html"])
        for p in targets:
            w.writerow([p["pid"], p["handle"], p["title"],
                        p["old_words"], p["new_words"], p["html"]])
    with open(f"{OUT_DIR}/rollback.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "previous_description_html"])
        for p in targets:
            w.writerow([p["pid"], p["descriptionHtml"]])
    with open(f"{OUT_DIR}/skipped.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "title", "reason"])
        w.writerows(skipped)

    # Second pass: punctuation repair across every active product the rewrite
    # left alone. Those kept whatever punctuation they already had, and a lot of
    # it carries em dashes, which are not allowed in our copy. Products
    # rewritten above are skipped because build() already produces clean text.
    rewritten = {p["pid"] for p in targets}
    repairs = []
    for p in products:
        if p["pid"] in rewritten:
            continue
        fixed = repair_changed(p["descriptionHtml"])
        if not fixed:
            continue
        if not repair_safe(p["descriptionHtml"], fixed):
            raise SystemExit(
                f"Punctuation repair altered more than punctuation on {p['pid']}. "
                "Refusing to write anything."
            )
        repairs.append({**p, "html": fixed})
    print(f"{len(repairs)} products need punctuation repair")

    with open(f"{OUT_DIR}/repaired.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "handle", "title", "before_html", "after_html"])
        for p in repairs:
            w.writerow([p["pid"], p["handle"], p["title"],
                        p["descriptionHtml"], p["html"]])

    if not APPLY:
        print("DRY RUN. Nothing written to Shopify.")
        print(f"Review {OUT_DIR}/proposed.csv and {OUT_DIR}/repaired.csv, "
              "then re-run with APPLY=1.")
        return 0

    for i in range(0, len(targets), 25):
        batch = targets[i:i + 25]
        apply_batch(tok, batch)
        print(f"applied {i + len(batch)} of {len(targets)}")
        time.sleep(1)
    print(f"done. {len(targets)} descriptions written.")

    for i in range(0, len(repairs), 25):
        batch = repairs[i:i + 25]
        apply_batch(tok, batch)
        print(f"repaired {i + len(batch)} of {len(repairs)}")
        time.sleep(1)
    print(f"done. {len(repairs)} descriptions repaired.")

    print(f"Rollback values are in {OUT_DIR}/rollback.csv and {OUT_DIR}/repaired.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
