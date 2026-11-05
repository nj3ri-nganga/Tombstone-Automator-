# TAG Logo Bank — hybrid recovery

Fill empty company logo cells using an optional LogoAPI.sh lookup, then the
company's verified official website. Preserve the source workbook and existing
Logos rows, notes, statuses, original logos and occupied Current Logo cells.

```powershell
python -m pip install -e .
python -m tag_logo_bank input.xlsx enriched.xlsx
```

No Cairo, GTK, browser or separate system runtime is required. PNG, JPEG and WebP
are supported directly. Optional SVG support uses a prebuilt Python-package wheel:

```powershell
python -m pip install --only-binary=resvg_py -e ".[svg]"
```

This is **not a pure-Python SVG renderer**: resvg_py packages a Rust renderer in
its wheel. It avoids separately installed native libraries. If no wheel is
available, leave SVG support off rather than building/installing a system stack;
the tool continues trying raster candidates. Before conversion a bounded XML/CSS
subset rejects scripts, events, entities/internal subsets, external resources,
embedded images, unknown DTDs and cyclic/expanding references. Safe presentation
CSS is expanded; comments and the recognized SVG 1.1 public DOCTYPE are removed
without fetching a DTD. System fonts are disabled. Unsupported SVG is a diagnostic
failure, never silently accepted. The existing strict preflight is reused rather
than implementing a new renderer.

## Sources and identity

1. LogoAPI.sh is enabled by default; `--no-api` skips it. Its PNG requests still
   disable and reject favicon/generated-tile fallbacks. A catalog miss, mismatch,
   error or rate limit proceeds to the verified website.
2. Official-page discovery considers matching organization schema, header/nav
   branding, lazy/responsive logo images, official logo image links, inline SVG
   and logo-like Open Graph assets. Generic OG photos, site icons and partner/
   carrier logo galleries are not accepted as company logos. Asset CDNs are
   allowed only when referenced by the identity-checked official page.
3. Optional `--web-search` uses Brave's web API, not image search. It requires
   `BRAVE_SEARCH_API_KEY`. Candidates must be inside the supplied official domain
   or explicit `--search-domains`, have a matching search title, then pass the
   same official-page identity checks. Multiple plausible domains are flagged.
   No image-host/aggregator fallback or automatically trusted search hit exists.

Supply websites you have verified belong to the target. Default page redirects
must stay on the same company domain (www/non-www are equivalent). A redirect to
an acquirer, an acquisition article with acquirer site branding, or a new brand
without the target identity is flagged. Do not change this just to improve counts.
This deliberately fails some defunct/rebranded targets instead of inserting the
acquirer's logo. No Internet Archive crawling or transaction-date authenticity is
claimed. A recovered target asset still needs human historical/brand approval.

If you independently verify alternative names of the *same target*, optional
`identity_names` in that company's override can list those names. They are
recorded in retrieval notes. This is an explicit reviewer decision, not a way to
silently equate an acquired target with its parent. For historical requirements,
use an authorized, verified target PNG via `logo_path` when no official asset is
available. Old raster overrides and optional hash-bound approvals still work.

All automatic images remain `REVIEW_REQUIRED`. Other statuses include
`MATCH_UNCERTAIN`, `NOT_FOUND`, `NEEDS_WEBSITE`, `ERROR`, `RATE_LIMITED`,
`ALREADY_PRESENT`, `MANUAL_REVIEW` and `MANUAL_APPROVED`. Empty/uncertain rows stay
empty. Technical and metadata checks cannot independently prove the contents of
arbitrary pixels or that a current logo was valid on a historical deal date.

## Workbook preservation

The default source is an existing `Logos` sheet, otherwise `Transactions` or the
active sheet. Common Company/Company Name/Target headers and Website/Company
Website/URL headers are recognized. Use `--sheet`, `--header-row` and `--pair` for
other layouts, as before. A Logos sheet can be processed directly.

Existing Logos rows are never deleted or reordered. `Current Logo` is filled
when empty; legacy `Logo` is accepted if there is no Current Logo column. Existing
images, formulas/text and manually entered URLs in that cell are left alone.
Original logo columns and analyst information are untouched. Retrieval results
use separate `Latest ...` fields on existing sheets so prior notes/statuses and
provenance are not overwritten. Each retry updates those latest-attempt fields;
existing occupied logo rows are skipped. Existing sheet information is preserved
within openpyxl's supported feature set; unsupported complex Excel objects can
still have its normal round-trip limitations.

When importing from another sheet into an existing Logos sheet, existing rows are
matched by company/domain and new companies are appended, without rebuilding the
sheet. Input and output filenames must differ. Workbook output is atomic.

New embedded images have explicit row/column anchors, padding, preserved aspect
ratio and sufficient row height. Existing row heights are never shrunk. Downloaded
PNGs (or raster/SVG assets normalized to PNG) are saved in OUTPUT_STEM_logos.
Retrieval method, asset URL, official page URL, status, notes, dimensions, embedded
SHA256, local file and retry-after timestamp are recorded. No mock or placeholder
artwork is inserted in live runs.

## Caching, backoff and resume

The default `.tag-logo-cache/` beside the output holds private local SQLite state:
HTTP bytes/provenance, successful company results (24 hours), short negative
results (10 minutes), and per-host 429 cooldowns. Repeated company/domain/URL work
is avoided, including after restarting. Company cache keys include website path,
verified aliases and source/search policy so historical subpages and changed
identity decisions do not accidentally share results. SQLite commits happen as
each response/result completes, so interrupted runs can reuse completed work.

429 honors numeric or HTTP-date Retry-After, or exponential backoff when absent.
Short waits retry at most twice; waits beyond `--max-wait` (default 2 seconds) are
recorded as deferred instead of blocking the whole workbook. Other domains can
continue. `RATE_LIMITED` results are not negative-cached. Rerun the command after
the recorded deadline, using the last output workbook to preserve filled cells,
or the original input to regenerate empty cells from the response/logo cache.
`--refresh` bypasses cached responses/results but **does not bypass cooldowns**.

Requests use TLS verification, connect/read timeouts, response/pixel caps, public
address checks and redirect validation. API/search credentials stay on HTTPS
provider origins; all page redirects are rechecked. No authentication/403 bypass,
proxy removal or user-agent rotation is attempted. As before, use network egress
controls where DNS rebinding is a concern. A website is not accessed merely
because a search result says it is official; domain scope must be verified first.

The cache and downloaded files may contain company names and URLs. Keep them
local; `.gitignore` excludes them, all workbooks and image outputs. Never commit
private TAG transaction inputs or source screenshots.

## Examples

```powershell
python -m tag_logo_bank tag.xlsx tag_enriched.xlsx --sheet Logos --limit 15
python -m tag_logo_bank tag.xlsx tag_enriched.xlsx --no-api --cache-dir .tag-logo-cache
python -m tag_logo_bank input.xlsx output.xlsx --sheet Deals --pair "Target:Target Website" --pair "Buyer:Buyer Website"
python -m tag_logo_bank input.xlsx output.xlsx --web-search --search-domains verified-target.com
```

`--overrides overrides.json` remains optional. Paths are relative to the JSON,
including Windows paths with spaces; UTF-8 BOM is supported. Example schema:

```json
{
  "Verified Company": {
    "website": "https://verified-target.com",
    "identity_names": ["Verified Company Legal Name"]
  }
}
```

`logo_path` accepts a verified local raster instead; optional `approval` keeps the
existing sha256/reviewed_by/reviewed_on/source_url format. Nothing in the normal
hybrid command requires manually converting SVG or approving an override.

## Public 15-company pilot and tests

```powershell
python -m unittest discover -s tests -v
python examples/live_pilot.py pilot-output
```

The live script contains only the 15 user-selected public company names/domains,
not transaction amounts, dates, analyst notes or private TAG data. It performs
real official-site retrieval (`use_api=False`), writes a public workbook with
Current Logo in column C, verifies embedded row coordinates, and creates
`report.json` and `contact-sheet.png` for visual identity review. It does not use
mock routes or generate company artwork. Failures remain blank and are reported;
a successful script exit does not imply all 15 logos were found or approved.

GitHub Actions installs ordinary Python packages plus the optional prebuilt SVG
wheel, runs offline tests on Windows/Python 3.14 and Linux/Python 3.12, then runs
the public pilot on each runner. Seven-day artifacts include only public pilot
report, contact sheet, workbook and recovered PNGs; private caches are excluded.
Native SVG and HTML discovery tests can be skipped locally if optional packages
are unavailable, but run with real installed dependencies in CI.

HUB International, XPT Specialty, Bankwell and NFP use their named public sites.
King Insurance uses king-insurance.com, which currently presents King Risk
Partners: a different current brand is not automatically approved as the
historical King Insurance logo. The remaining ten domains are exactly those
supplied by the user. Redirect/rebrand cases are reported rather than relabeled.
