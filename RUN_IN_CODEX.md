# Run with Codex online (no local Python installation)

1. In this Codex conversation, attach your actual `.xlsx` transaction workbook using the attachment control. In a new conversation, select the GitHub repository and branch containing this application, or attach its GitHub source ZIP and ask Codex to extract it.
2. Send: "Run TAG Logo Bank against the attached workbook. Inspect its worksheet names and headers, map the company and website columns, preserve the original, and create a separate workbook with a Logos worksheet. Report missing websites and failed logo downloads."
3. Specify target and buyer columns if you need both. Attach any approved local logos and identify their companies. Codex can construct the overrides JSON for you.
4. Codex runs Python and installs dependencies in its hosted environment. Nothing needs to be installed on your computer. Public company websites and logo CDN domains must be allowed by the environment's network policy; allow them through Codex's environment settings if access is blocked.
5. Review the status summary and download the resulting workbook when your interface exposes file outputs. File-export availability depends on the Codex environment; a workspace path alone is not a download attachment.
6. Review every logo before using it in a tombstone. Technical image validation does not establish brand approval or prove the latest official version.

## Commands Codex can run in its cloud terminal

From the extracted project directory:

```bash
python -m venv /workspace/work/tag-logo-env
/workspace/work/tag-logo-env/bin/python -m pip install -e '.[test]'
/workspace/work/tag-logo-env/bin/python -m pytest -q
/workspace/work/tag-logo-env/bin/python -m tag_logo_bank /path/to/uploaded.xlsx /workspace/output/transactions_with_logos.xlsx --sheet 'Transactions' --pair 'Company:Website'
```

For two parties:

```bash
/workspace/work/tag-logo-env/bin/python -m tag_logo_bank /path/to/uploaded.xlsx /workspace/output/transactions_with_logos.xlsx --sheet 'Deals' --pair 'Target:Target Website' --pair 'Buyer:Buyer Website'
```

These commands execute online, not on your local machine. Replace file paths and headers with the actual uploaded workbook's values. Only `.xlsx` is supported; save `.xls` or macro-enabled files as an `.xlsx` copy first if appropriate.
