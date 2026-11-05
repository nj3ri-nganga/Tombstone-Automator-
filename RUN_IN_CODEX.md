# Run TAG Logo Bank in Codex

The normal command is `python -m tag_logo_bank input.xlsx output.xlsx` after
`python -m pip install -e .`. It requires outbound HTTPS to `logoapi.sh`, no keys,
no company-website access, and no SVG/native conversion stack.

Run offline tests with `python -m unittest discover -s tests -v`.

Check runtime connectivity before a live run. If the configured proxy cannot be
reached, stop without generating a live company workbook. Do not remove proxy
settings or attempt to bypass the environment's network policy. A published
unrestricted HTTP policy does not prove the proxy is functioning.

For the five-company input and local Windows instructions, see README.md. Never
substitute test geometry or generic tiles for real company logos in live outputs.
