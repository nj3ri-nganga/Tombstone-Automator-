"""Public 15-company live retrieval only. No mock routes or confidential workbook."""
import json
from pathlib import Path
import sys
from io import BytesIO
from datetime import datetime, timezone

from PIL import Image, ImageDraw
from openpyxl import Workbook, load_workbook
from tag_logo_bank import build_logo_bank
from tag_logo_bank.workbook import image_cell


def main():
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else 'pilot-output')
    destination.mkdir(parents=True, exist_ok=True)
    companies = json.loads(Path(__file__).with_name('public_pilot.json').read_text())
    wb = Workbook()
    ws = wb.active
    ws.title = 'Logos'
    ws.append(['Company Name', 'Website', 'Current Logo', 'Existing TAG Notes'])
    for name, website in companies:
        ws.append([name, website, '', 'Public pilot only; no confidential transaction data'])
    source, output = destination / 'public-input.xlsx', destination / 'public-logos.xlsx'
    wb.save(source)
    wb.close()
    counts = build_logo_bank(source, output, use_api=False, max_wait=1)
    wb = load_workbook(output)
    ws = wb['Logos']
    headers = {c.value: c.column for c in ws[1]}
    images = {image_cell(i)[0]: i for i in ws._images}
    report = []
    canvas = Image.new('RGB', (1000, 15 * 125), '#eeeeee')
    draw = ImageDraw.Draw(canvas)
    for row, (name, website) in enumerate(companies, 2):
        get = lambda key: ws.cell(row, headers[key]).value
        current = images.get(row)
        item = {'company': name, 'website': website, 'status': get('Latest Retrieval Status'),
                'method': get('Retrieval Method'), 'source': get('Latest Retrieval Source'),
                'page': get('Latest Official Page'), 'notes': get('Latest Retrieval Notes'),
                'local_png': get('Latest Local PNG'), 'embedded_row': row if current else None,
                'identity_verification': 'Official-page evidence recorded; pending human visual review' if current else 'No logo accepted'}
        if current:
            assert image_cell(current) == (row, 3)
            assert current.anchor.ext.cx / current.anchor.ext.cy > 0
        report.append(item)
        y = (row - 2) * 125
        draw.text((10, y + 10), name, fill='black')
        draw.text((10, y + 35), str(item['status']), fill='black')
        draw.text((10, y + 55), str(item['method'])[:45], fill='black')
        if item['local_png']:
            with Image.open(item['local_png']) as logo:
                logo = logo.convert('RGBA')
                logo.thumbnail((450, 105))
                canvas.paste(logo, (400, y + 10), logo)
        else:
            draw.text((400, y + 20), 'NO LOGO ACCEPTED', fill='black')
    summary = {'utc': datetime.now(timezone.utc).isoformat(), 'counts': counts, 'companies': report}
    (destination / 'report.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    canvas.save(destination / 'contact-sheet.png')
    print(json.dumps(summary, indent=2))
    wb.close()


if __name__ == '__main__':
    main()
