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
    parser.add_argument('--sheet', default='Transactions')
    parser.add_argument('--logos-dir', type=Path,
                        help='Save downloaded PNGs here (default: OUTPUT_STEM_logos beside output)')
    parser.add_argument('--header-row', type=int, default=1)
    parser.add_argument('--pair', action='append', metavar='COMPANY:WEBSITE',
                        help='Repeat for Target, Buyer, etc.; blank website header allowed')
    parser.add_argument('--overrides', type=Path,
                        help='JSON company-to-website/local-logo mapping; optional hash-bound manual approval (see README)')
    args = parser.parse_args()
    try:
        pairs = []
        for pair in args.pair or ['Company:Website']:
            name, sep, website = pair.partition(':')
            if not sep or not name:
                raise ValueError('--pair must be COMPANY:WEBSITE')
            pairs.append((name, website))
        if args.header_row < 1:
            raise ValueError('--header-row must be positive')
        overrides = json.loads(args.overrides.read_text(encoding='utf-8-sig')) if args.overrides else {}
        if not isinstance(overrides, dict) or any(not isinstance(v, dict) for v in overrides.values()):
            raise ValueError('Overrides must map company names to objects')
        for override in overrides.values():
            if override.get('logo_path'):
                override['logo_path'] = str((args.overrides.parent / override['logo_path']).resolve())
        counts = build_logo_bank(args.input, args.output, sheet=args.sheet, pairs=pairs,
                                 header_row=args.header_row, overrides=overrides, logos_dir=args.logos_dir)
        logos_dir = args.logos_dir or args.output.parent / f'{args.output.stem}_logos'
        print(json.dumps({'output': str(args.output), 'logos_dir': str(logos_dir), 'statuses': counts}, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, BadZipFile, ParseError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

