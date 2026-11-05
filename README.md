# TAG Tombstone Automator — Logo Bank

Python application for the logo-bank stage of investment banking tombstone production. Reads transaction companies, retrieves logo candidates from their supplied official websites, validates raster images, and embeds them in a styled `Logos` worksheet. Keeps transaction worksheets and writes a separate output workbook.

## Install and run

Requires Python 3.10+.

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e '.[test]'
python -m tag_logo_bank transactions.xlsx transactions_with_logos.xlsx
```

Default input: `Transactions` worksheet, headers `Company` and `Website` in row 1. Websites may be blank, plain domains, URLs, or Excel hyperlinks. Company rows are deduplicated by case-insensitive company name plus website; conflicting websites remain separate entries for review. Names are never used to guess a domain or choose an unrelated company.

For target/buyer columns:

```bash
tag-logos input.xlsx output.xlsx --sheet Deals --header-row 2 \
  --pair 'Target:Target Website' --pair 'Buyer:Buyer Website'
```

A company column without a corresponding website column is supported with `--pair 'Company:'`.

## Companies without websites and manual assets

Use `--overrides overrides.json` to supply verified websites or local PNG/JPEG/WebP logos:

```json
{
  "Example Holdings": {"website": "https://official-company.example"},
  "Private Company": {"logo_path": "logos/private-company.png"}
}
```

Company keys are case insensitive. Paths are relative to the JSON file. A local asset takes precedence over website discovery. Missing websites produce `NEEDS_WEBSITE`, keeping the company in the logo bank. Invalid local assets produce `ERROR` so they can be corrected. No paid logo/search API or API keys are required.

## Sample and tests

The sample generator creates fictional transactions and a logo entirely offline. Generated workbooks and images are excluded from Git:

```bash
python examples/create_sample.py
python -m tag_logo_bank examples/transactions.xlsx examples/transactions_with_logos.xlsx --overrides examples/overrides.json
pytest -q
```

The resulting sample contains one embedded logo (`MANUAL_REVIEW`) and one company awaiting a website (`NEEDS_WEBSITE`). The duplicate sample company becomes one logo-bank row. Tests use generated images and fake HTTP responses, with no company website access.

## Discovery and verification

Each run fetches the website afresh with a no-cache request, follows redirects, then ranks Organization/Corporation/LocalBusiness JSON-LD logos, logo-tagged header/navigation images, other logo-tagged images, and site icons. Asset URLs can point to CDNs when referenced by the official page. Failed candidates fall through to the next candidate. A maximum of 25 candidates is tried per company.

Pillow checks decoding, dimensions, blank/invisible images, and decompression limits. Accepted raster assets become PNGs, retaining transparency and aspect ratio, and are embedded directly in the workbook. The worksheet records company, website, status, source URL/path, final official page, UTC retrieval timestamp, original dimensions, PNG SHA256, and review notes. Embedded previews fit within 180 x 75 pixels; normalized assets are at most 600 x 300.

`REVIEW_REQUIRED` means the image passed technical checks and was referenced by the supplied site. It does **not** establish company identity or branding approval. `MANUAL_REVIEW` identifies a user-supplied image. Confirm the website belongs to the intended legal entity and approve the logo before using it in a tombstone. Retrieval time is not a brand release date: websites cannot prove a logo is the latest approved version. Icons may be unsuitable for a tombstone and are marked in notes.

`NOT_FOUND` means the page had no usable candidates; `ERROR` records a page/network/local-asset failure. One company's failure does not stop the rest of the workbook. Network requests have connect/read timeouts, bounded retries, redirect limits, an 8 MB response cap, and TLS verification. Public URL checks reject private/nonpublic addresses and nonstandard ports, including redirect targets. Use trusted workbook inputs and network egress controls in hosted deployments; DNS checks alone do not prevent DNS rebinding.

## Scope and operational notes

- Supported workbook format: `.xlsx` only. Source and output paths must differ. Back up existing output files; a successful run replaces the output atomically.
- An existing `Logos` worksheet in the output copy is rebuilt. Other worksheets are retained using openpyxl; complex Excel drawings or unsupported features may not round-trip exactly.
- Uses supplied official websites rather than unverified search results. Check redirected sites and CDN sources during manual review.
- Raster PNG/JPEG/WebP and other Pillow-supported formats are accepted. SVG-only logos and JavaScript-rendered pages require a manually exported raster logo. No browser automation is used.
- No automatic crawling of brand portals, OCR, visual identity matching, or tombstone-slide generation in this first stage.
- A network that allows access to company websites and their asset CDNs is needed for live discovery. This project's validation was performed offline with deterministic sample data, not live corporate sites.
- Importable API: `from tag_logo_bank import build_logo_bank`; returns a dictionary of status counts.

## Structure

```text
tag_logo_bank/
  logos.py       # HTTP, discovery, image validation, result model
  workbook.py    # extraction, formatting, embedding, atomic save
  cli.py         # command-line entry point and override loading
  __main__.py
examples/        # generator, sample input/output, local logo, overrides
tests/           # deterministic unit and workbook integration tests
pyproject.toml
requirements.txt
requirements-dev.txt
```
