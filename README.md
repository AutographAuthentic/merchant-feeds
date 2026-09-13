# Merchant Center title feed for careerjerseys.com

Shoppers on the storefront see a short, readable product title. Google Shopping
needs the long, keyword-rich form. This repo keeps the two apart.

The long form lives in the Shopify product metafield `custom.full_title`.
`build_feed.py` reads it for every active product and writes
`feeds/full_title_feed.tsv`, one row per variant offer. Merchant Center fetches
that file on a schedule and overwrites the `title` attribute with it.

## Setup, in order

1. Add the workflow file `.github/workflows/build-feeds.yml` (in the project
   handoff doc). It could not be pushed from the session that created this repo
   because that token had no `workflow` scope.
2. Add three repository secrets, the same Shopify custom app already used by
   `shopify-theme-changelog`: `SHOPIFY_SHOP` (for example
   `your-store.myshopify.com`), `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`.
   The app needs `read_products` and `write_products`.
3. Run the workflow by hand once: Actions, "Rebuild Merchant Center title feed",
   Run workflow. Check the committed feed before trusting the schedule.
4. Make the feed reachable (below), then point Merchant Center at it.

## The feed URL

```
https://raw.githubusercontent.com/AutographAuthentic/merchant-feeds/main/feeds/full_title_feed.tsv
```

That URL only works once this repository is public. While it is private, either
make it public (the file holds product IDs and titles that are already visible
on the storefront and in Shopping ads) or publish the file elsewhere, such as an
S3 object or Merchant Center's own SFTP endpoint.

Register it twice in Merchant Center, once per catalogue:

| Catalogue | Primary source it attaches to | Feed label |
|---|---|---|
| Canada | Content API | `CA` |
| United States | Shopify App API | `USD_1457881177` |

Data sources, **Supplemental sources** tab, **Add supplemental product data**,
choose scheduled fetch, paste the URL, set a daily fetch, link it to the primary
source above. Use the **test** step first and only apply once the match count
looks right.

Do not use **Add product source** on the Primary sources tab. Doing that on
Aug 18 2026 created a second primary source on the same feed label and took the
live US catalogue to zero products.

## Self-healing

Any active product with an empty `custom.full_title` gets its current storefront
title copied in, so a new product can never reach the feed with a blank title.
Those products are listed in `feeds/missing_full_title.txt` so someone can write
a proper long form for them later. Once the storefront titles are shortened,
that stopgap is the short title, which is safe but not optimal, so check that
file after new products are added.
