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
- Raster PNG/JPEG/WebP and other Pillow-supported formats are accepted. SVG logos use the optional sanitizer/converter described below; unsupported SVGs and JavaScript-rendered pages require a verified raster export. No browser automation is used.
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


### Discovery and diagnostics

Discovery includes organization JSON-LD, logo images with lazy-loading and
picture/srcset variants, and self-contained header/navigation SVGs. Organization
schema logos retain priority; within each tier the largest validated original
image wins. Favicons are a last resort. Every discovered asset still requires
brand review. No substitute or placeholder company artwork is generated.

SVG conversion is optional: `python -m pip install -e ".[svg]"`. CairoSVG also
requires a working native Cairo runtime, particularly on Windows. Unsupported
SVGs or unavailable conversion are recorded in candidate diagnostics and raster
fallbacks are still attempted. The SVG sanitizer accepts XML declarations, comments,
CDATA, and the standard SVG 1.1 public DOCTYPE emitted by common vector editors.
It removes that DOCTYPE without fetching it. Safe inline presentation styles and
simple element/class/ID stylesheet rules are expanded into attributes; no CSS
text reaches the renderer. Sanitization is recorded in review notes. Internal
entities/subsets, unknown DTDs, processing instructions, scripts, event handlers,
base URLs, embedded images, external references and unsupported CSS are rejected.
Local gradient/clip/use references are allowed with cycle and expansion limits. The renderer also blocks
resource fetching and bounds output dimensions. Existing URL, redirect, download
size and raster validation checks remain active.

Website URLs in the Logos sheet omit fragments and common tracking parameters
(`utm_*`, click IDs and Mailchimp IDs), retaining functional query parameters.
Failure notes include the stage, candidate URL and exception type/message.
Successful fallbacks also retain rejected-candidate diagnostics. Manual overrides
and MANUAL_REVIEW / REVIEW_REQUIRED / NOT_FOUND / ERROR statuses are preserved.

### Offline regression checks and local live validation

Install development dependencies, then run `python -m pytest -q`. The additional
regressions can also run with `python -m unittest discover -s tests -p test_regressions.py -v`.
They use synthetic geometry solely as test fixtures, not substitute company logos.
The SVG renderer unit test mocks conversion; it verifies the dimension bounds and
blocked fetch callback, not native Cairo rendering.

The Codex runtime lacks BeautifulSoup, pytest and CairoSVG. Offline unittest
validation ran 25 tests: 22 passed and three skipped (two HTML discovery tests
need BeautifulSoup; one native rendering test needs CairoSVG/Cairo). The
pre-existing pytest suite could not run here. No live logo retrieval was attempted.
Run both unittest regression files with `python -m unittest discover -s tests -p "test_*regressions.py" -v`
and `python -m unittest discover -s tests -p test_svg_manual.py -v`, or run the
complete suite with pytest when all dependencies are installed.

On Windows/Python 3.14, install the normal/dev dependencies (and optionally the svg
extra plus Cairo), run the complete pytest suite, then repeat the real Microsoft,
Apple, NVIDIA, Salesforce and Adobe test. Confirm logo identity and resolution,
review all failure notes (especially Adobe), and open the workbook in desktop
Excel to confirm that Salesforce stays in its row when NVIDIA has no image.
Actual site availability, current markup, native SVG conversion and desktop Excel
rendering require this local validation.


## Verified manual logos when a website blocks automation

HTTP 403 remains an `ERROR` with explicit manual-override guidance. The application
will not spoof a browser, switch domains, crawl another company, or attempt to
bypass that restriction. A local `logo_path` takes precedence and skips website
requests entirely, including when a website is supplied. A missing or invalid
local file produces `ERROR`; it never silently falls back to online discovery.

1. Obtain the logo through an authorized official company brand/press source or
   directly from the company. Confirm the exact legal entity, current branding,
   permitted use, transparency and adequate resolution. Do not use an acquirer's
   or another company's logo. For Adobe, provide a verified official PNG rather
   than trying to defeat adobe.com's automated-access restriction.
2. Save it locally, for example `logos/adobe-official.png`. Create `overrides.json`
   next to the `logos` folder. Use the exact company name from your workbook
   (matching is case insensitive):

   ```json
   {
     "Adobe": {
       "website": "https://www.adobe.com/",
       "logo_path": "logos/adobe-official.png"
     }
   }
   ```

   Paths are relative to the JSON file, including paths containing spaces.
   Windows UTF-8 JSON files with a BOM are supported. In JSON, use `/` in paths
   or escape each Windows backslash as `\\`.
3. Run the existing command:

   ```powershell
   python -m tag_logo_bank transactions.xlsx reviewed-logos.xlsx --overrides overrides.json
   ```

   The asset is validated and embedded as `MANUAL_REVIEW`. Inspect it in Excel,
   verify its official source and identity, and obtain your normal brand approval.
   Supplying a file alone does not approve it.
4. To record your explicit approval for future runs, calculate the SHA256 of the
   **original local file** after verification:

   ```powershell
   (Get-FileHash -Algorithm SHA256 .\logos\adobe-official.png).Hash.ToLowerInvariant()
   ```

   Add an `approval` object to the same override. Replace the explanatory values
   below with the actual 64-character hash, reviewer, ISO date and official source
   URL you verified; this example is a schema, not a preapproved asset:

   ```json
   {
     "Adobe": {
       "website": "https://www.adobe.com/",
       "logo_path": "logos/adobe-official.png",
       "approval": {
         "sha256": "REPLACE_WITH_ORIGINAL_FILE_SHA256",
         "reviewed_by": "REPLACE_WITH_REVIEWER_NAME",
         "reviewed_on": "2026-11-05",
         "source_url": "https://www.adobe.com/"
       }
     }
   }
   ```

   Use the actual official brand page or asset URL when known, rather than the
   homepage in this schema. All four approval fields are required. The source
   URL is recorded as provenance and is not fetched or independently verified.
   Rerun with a separate output filename. A matching hash and valid approval
   record produce `MANUAL_APPROVED`; reviewer, date and original file hash appear
   in notes, the official source is in `Official page`, and `Source` retains the
   local path. A changed file, invalid record or missing file produces `ERROR`.
   Reverify changed files before replacing their approval hashes.

The existing `SHA256 (embedded PNG)` column identifies the normalized embedded
image; it is different from the original-file approval hash. Human approval is
an explicit user attestation, not automatic proof of brand ownership or permission.
Old overrides remain valid and retain `MANUAL_REVIEW` without an approval object.
Online logos always retain `REVIEW_REQUIRED`. Rerunning rebuilds the Logos sheet,
so keep approvals in your override JSON rather than editing worksheet statuses.

### Windows validation still required

Run `python -m pip install -e ".[test,svg]"`, ensure the native Cairo runtime is
available to Python 3.14, then run `python -m pytest -q`. The optional native SVG
test should run rather than skip; check any native-runtime error explicitly.
Repeat the live company test to confirm whether NVIDIA's actual exports fall
within the supported SVG/CSS subset and whether Microsoft's current page exposes
its full logo. Unsupported SVGs must remain diagnostic failures and should be
replaced only with a manually verified official raster export. Check Adobe via
a local official PNG and the approval workflow above. Confirm native conversion
fidelity, identity, resolution, transparency and desktop Excel appearance. No
claim is made here that the actual live company assets have been retrieved.
