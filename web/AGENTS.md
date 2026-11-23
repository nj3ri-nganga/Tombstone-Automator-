# Tombstone Studio

This folder is the browser website. The root Python tool is separate.

- Read README.md for setup, user data and deployment behavior.
- Run `npm ci` then `npm test` in this folder after behavior changes. Run `npm run build` after source edits.
- Edit source files rather than generated dist/app.js.
- Preserve the existing IndexedDB database/store names, localStorage migration key, backup format, company IDs, saved deal layouts and reusable layout settings unless implementing an explicit migration.
- Never add user workbooks, workspace backups, logo collections, local storage dumps, credentials or uploads to Git.
- Keep actual uploaded data in ignored work/ directories. Use synthetic examples for committed tests.
- A GitHub change does not itself deploy the existing hosted Site. Follow the available Sites workflow only when deployment is in scope.
