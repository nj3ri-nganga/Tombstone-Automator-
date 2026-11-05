# TAG Logo Bank

Read companies from Excel, retrieve their catalog logos through LogoAPI.sh, and
save a workbook with neatly aligned PNGs plus a local folder of downloaded logos.
No website scraping, API key, Cairo, GTK, browser automation or SVG conversion.

## Run

Requires Python 3.10+ (including Windows/Python 3.14) and ordinary Python packages.
From this repository, install once with `python -m pip install -e .`, then:

```powershell
python -m tag_logo_bank transactions.xlsx transactions_with_logos.xlsx
```

Input defaults to the `Transactions` sheet and the `Company` and `Website` headers.
A website can be a URL, domain, Excel hyperlink or blank. If the Website column is
absent, the application searches by company name. Output:

- `transactions_with_logos.xlsx`: original transaction sheets plus a rebuilt
  `Logos` sheet with one row per unique company/website, status and retrieval notes.
- `transactions_with_logos_logos/`: validated downloaded PNGs at their original
  resolution. The `Local PNG` column records each file's absolute path. Files have
  safe domain/name plus content-hash filenames; no company name becomes a path.

Each logo stays inside its company's row with padding and its original proportions.
Failed/uncertain rows have empty logo cells and a yellow highlight. A summary of
statuses and output paths prints when the command finishes. A completed command
can contain flagged rows: inspect the status counts and workbook.

The source workbook is never overwritten. Rerunning rebuilds the Logos sheet,
without reusing stale images for companies that now fail. Other sheets, hyperlinks,
custom column pairs, freeze panes, filters, formula-as-literal protection in the
Logos sheet and atomic workbook saves are retained. Complex Excel features beyond
openpyxl's support may not round-trip; `.xlsx` is the supported file format.

## How matches and images are checked

The website's hostname is used for API lookup (lowercase, IDNA-normalized, `www.`
removed). Tracking parameters/fragments are removed from stored website URLs.
Other subdomains remain exact; the application never guesses a parent/acquirer
domain. For a portal URL, supply the company's verified main website if necessary.

Before downloading, a catalog search must return a matching name, domain and
source-domain provenance. Case, punctuation, whitespace and ordinary legal suffixes
such as Inc./Corporation are normalized; divisions, Group and Holdings are not
silently discarded. With no website, only one unique, exact, non-fuzzy name match
with consistent domain/source metadata is accepted. Ambiguous, fuzzy, mismatched
or malformed results are flagged rather than choosing the first search hit.
This verifies agreement of provider metadata, not legal-entity ownership; an exact
name in a third-party catalog is not independent identity or brand approval. Use a
verified website when names are ambiguous.

The application requests `/{domain}.png?size=1024&fallback=404`, prefers the normal
logo/wordmark endpoint and accepts a genuine catalog mark when no wordmark exists.
Generated tiles, favicon/monogram fallbacks and any nonempty `X-Logo-Fallback`
response are rejected. PNG Content-Type, signature, decoding, dimensions, pixel
limits and visibility are checked. SVG/HTML/error bodies are never converted or
embedded. The PNG archive keeps original downloaded pixels; embedded previews are
normalized to at most 600 × 300 and displayed within 180 × 75 pixels. All automatic
matches retain `REVIEW_REQUIRED`; confirm brand identity before transaction use.

Network requests go only to the fixed `https://logoapi.sh` origin, including on
redirects, with TLS verification, bounded retries, connect/read timeouts and an
8 MB response limit. IP/private website inputs are rejected; API DNS and redirects
are checked. No company site is fetched, including Adobe's restricted website.
As before, DNS checks alone are not protection against DNS rebinding; use network
egress controls in hosted environments. Provider failures (404, rate limits,
network errors or outages) leave cells empty and give actionable status notes.
The service must honor its documented no-fallback behavior and catalog accuracy;
this tool cannot prove the identity of arbitrary pixels returned by a provider.

### LogoAPI.sh evaluation

[Official API documentation](https://logoapi.sh/docs), checked November 5, 2026:
domain lookup, company-name search and server-rendered PNGs work without a key or
account. Download caching is supported; the free service has usage limits and no
client software installation requirement. Its default miss behavior can produce
favicons or generated wordmark tiles, which is why TAG explicitly requests 404 on
misses and also checks fallback headers and catalog metadata. The application
uses the provider's default brand colors, never generated color variants.

Only requested company names/domains are sent to LogoAPI.sh, not the workbook or
other transaction fields. Catalog coverage, current brand files and service
availability remain external dependencies. There is no second-provider or website
scraping fallback that might silently select a different company.

## Options you may already use

```powershell
python -m tag_logo_bank input.xlsx output.xlsx --sheet Deals --header-row 2 --pair "Target:Target Website" --pair "Buyer:Buyer Website"
python -m tag_logo_bank input.xlsx output.xlsx --pair "Company:" --logos-dir downloaded_logos
```

`--overrides overrides.json` still accepts verified websites or optional local
raster assets, with case-insensitive company names and paths relative to the JSON:

```json
{
  "Adobe": {"website": "https://www.adobe.com/"},
  "Your Company": {"logo_path": "logos/verified-official.png"}
}
```

Overrides are optional. A local PNG/JPEG/WebP skips the API and stays
`MANUAL_REVIEW`; invalid files produce `ERROR` without an online fallback. Existing
optional `approval` records still work with exactly `sha256` (original-file hash),
`reviewed_by`, `reviewed_on` (YYYY-MM-DD), and `source_url`, producing
`MANUAL_APPROVED` only for a matching validated local file. Approval is a human
attestation; it is never required for the ordinary API command. SVG overrides are
no longer accepted: use an existing official raster file rather than installing a
conversion stack. UTF-8 BOM override JSON from Windows remains supported.

Statuses: `REVIEW_REQUIRED` (matched API PNG), `MATCH_UNCERTAIN` (empty), `NOT_FOUND`
(empty), `ERROR` (empty), `MANUAL_REVIEW`, and `MANUAL_APPROVED`. No placeholders
are generated. Partial failures do not stop other companies.

## Tests and the five-company live check

All regression tests run offline with the application's dependencies:

```powershell
python -m unittest discover -s tests -v
```

Tests cover Microsoft, Apple, NVIDIA, Salesforce and Adobe through mocked provider
responses, both domain and name lookup, plus workbook image anchors/proportions,
local files, missing-logo gaps, uncertainty, blocked fallbacks, PNG validation,
network restrictions, errors, overrides, source preservation and reruns. Synthetic
colored geometry is only test data; it is never shipped as company artwork.

To run the real five-company check locally:

```powershell
python examples/create_sample.py
python -m tag_logo_bank examples/five_companies.xlsx examples/five_companies_with_logos.xlsx
```

The first command creates only the input companies/websites, not logo artwork.
Review all five output rows and downloaded PNGs for identity, fidelity and desktop
Excel placement. Clear one Website value and rerun to exercise real name search.
No API key or extra system installation is needed. CI runs the offline suite on
Windows/Python 3.14 and Linux/Python 3.12.

Validation in this Codex runtime: the offline suite passed. The runtime's proxy at
`proxy:8080` is unreachable (curl exit 7 / HTTP 000), so real API search/download
and the live five-company workbook could not be tested. The documentation was
read through the web connector; live search endpoints were also inaccessible
through that connector. No failed live workbook was generated. Actual provider
response compatibility/coverage and Windows Excel rendering still need the local
check above.
