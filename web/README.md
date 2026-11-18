# Tombstone Studio website

This folder contains the website built in the Codex conversation. The existing Python logo-recovery tool at the repository root remains separate.

## Open in the connected Codex project

After this change is merged, sync the project to the latest `main`. Before merging, select the `feat/tombstone-studio-web` branch to work on it directly.

Use Node.js 24 or newer. From the repository root:

```sh
cd web
npm ci
npm run dev
```

The development server prints `http://127.0.0.1:5173`. JavaScript, HTML and CSS changes rebuild automatically; refresh the page to view them. Stop with Ctrl+C. Run `npm test` for the build and application checks, or `npm run build` to create deployable files in `web/dist/`.

## What is included

- Excel/CSV company-library import, including Excel in-cell images and floating PNG/JPEG/WebP logos.
- Company selectors, logo normalization and saved company sizing.
- Exact approved border PNG on its original 459 × 609 canvas, with transparent areas over white. PNG downloads are 1377 × 1827 (3×); PDFs retain the original 150 DPI physical size of 3.06 × 4.06 inches. Saved layout coordinates are mapped uniformly from the earlier 480 × 600 canvas without stretching logos.
- Saved deals, independent duplication, per-deal logo/font sizes, alignment, positioning, section spacing, guides and reusable layouts.
- A sticky preview while editing layout controls.
- IndexedDB persistence, legacy localStorage loading and JSON backup/restore.

Edit `app-source.js` for application behavior, `layout-model.js` for layout rules, `workbook-images.js` for XLSX image relationships, `border-asset.js` for the original approved border, and `index.html`/`style.css` for the interface. Generated `dist/app.js` is not source and is ignored.

## User data and the existing website

Logos, saved deals, settings and reusable layouts are stored in each browser and origin, not in GitHub. The approved template border is included in border-asset.js. No confidential workbook, company logo library, workspace backup, credential or hosting identity is included here. Demo entries are illustrative placeholders.

The current hosted website remains running separately. Pushing or merging this repository does **not** automatically deploy or replace it. Hosting needs a separate deployment configuration if GitHub should become the deployment source.

Opening this application at a new address creates a separate browser workspace. Download **Back up workspace** from the old address before migrating. Use **Restore** at the new address to load that backup; keep backups private and out of Git.

## Import behavior and limits

Use a `Logos` sheet with `Company` and `Current Logo` headers. Files are limited to 25 MB, up to 1,000 company names per import; logos are limited to 5 MB each. Imports show a pairing review, add new companies and fill missing logos, and preserve existing approved logos and company sizing. Replacing an existing logo uses its company editor. Deal layouts and reusable presets are independent of logo import.

Linked images and SVG/EMF logos are not imported. Missing logos remain empty. The app currently uses one active template and a browser-local workspace, without shared team storage or automatic Excel synchronization.

## Verification

`npm test` covers metadata-to-image mapping, basic workspace operations, layout persistence/duplication, reset/presets and IndexedDB storage with a 7 MB payload. These are DOM and parser tests; they do not verify browser scrolling, canvas exports or visual alignment. Review a real PNG/PDF and responsive layout in a supported browser before production changes.
