import argparse
import json
from pathlib import Path
import sys
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError
from .workbook import build_logo_bank


def main():
    parser = argparse.ArgumentParser(description='Create a TAG investment banking logo bank')
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--sheet', help='Default: existing Logos sheet, otherwise Transactions/active sheet')
    parser.add_argument('--no-api', action='store_true', help='Use verified official websites without LogoAPI.sh')
    parser.add_argument('--cache-dir', type=Path, help='Default: .tag-logo-cache beside output')
    parser.add_argument('--refresh', action='store_true', help='Refresh caches; still obey rate-limit cooldowns')
    parser.add_argument('--limit', type=int, help='Limit empty logo rows processed for a pilot')
    parser.add_argument('--max-wait', type=float, default=2, help='Maximum short backoff in seconds (0–30); longer 429s are deferred')
    parser.add_argument('--web-search', action='store_true', help='Opt-in scoped Brave web search; requires BRAVE_SEARCH_API_KEY')
    parser.add_argument('--search-domains', default='', help='Comma-separated independently verified official search domains')
    parser.add_argument('--logos-dir', type=Path,
                        help='Save downloaded PNGs here (default: OUTPUT_STEM_logos beside output)')
    parser.add_argument('--header-row', type=int, default=1)
    parser.add_argument('--pair', action='append', metavar='COMPANY:WEBSITE',
                        help='Repeat for Target, Buyer, etc.; blank website header allowed')
    parser.add_argument('--overrides', type=Path,
                        help='JSON company-to-website/local-logo mapping; optional hash-bound manual approval (see README)')
    args = parser.parse_args()
    try:
        pairs = [] if args.pair else None
        for pair in args.pair or []:
            name, sep, website = pair.partition(':')
            if not sep or not name:
                raise ValueError('--pair must be COMPANY:WEBSITE')
            pairs.append((name, website))
        if args.header_row < 1:
            raise ValueError('--header-row must be positive')
        if args.limit is not None and args.limit < 1:
            raise ValueError('--limit must be positive')
        if not 0 <= args.max_wait <= 30:
            raise ValueError('--max-wait must be between 0 and 30 seconds')
        if args.web_search:
            import os
            if not os.environ.get('BRAVE_SEARCH_API_KEY'):
                raise ValueError('--web-search requires BRAVE_SEARCH_API_KEY; normal website retrieval requires no key')
        overrides = json.loads(args.overrides.read_text(encoding='utf-8-sig')) if args.overrides else {}
        if not isinstance(overrides, dict) or any(not isinstance(v, dict) for v in overrides.values()):
            raise ValueError('Overrides must map company names to objects')
        for override in overrides.values():
            if 'identity_names' in override and (not isinstance(override['identity_names'], list) or
                    any(not isinstance(n, str) or not n.strip() for n in override['identity_names'])):
                raise ValueError('identity_names must list verified company identity/brand names')
            if override.get('logo_path'):
                override['logo_path'] = str((args.overrides.parent / override['logo_path']).resolve())
        counts = build_logo_bank(args.input, args.output, sheet=args.sheet, pairs=pairs,
                                 header_row=args.header_row, overrides=overrides, logos_dir=args.logos_dir,
                                 cache_dir=args.cache_dir, use_api=not args.no_api, refresh=args.refresh,
                                 limit=args.limit, max_wait=args.max_wait, web_search=args.web_search,
                                 search_domains=[d.strip() for d in args.search_domains.split(',') if d.strip()])
        logos_dir = args.logos_dir or args.output.parent / f'{args.output.stem}_logos'
        print(json.dumps({'output': str(args.output), 'logos_dir': str(logos_dir), 'statuses': counts}, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, BadZipFile, ParseError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

