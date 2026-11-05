"""Generate fictional transactions and local logo; no internet needed."""
from pathlib import Path
import json
from openpyxl import Workbook
from PIL import Image, ImageDraw


def create_sample(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Transactions'
    ws.append(['Company', 'Website', 'Transaction Value ($m)'])
    ws.append(['Acme Sample Holdings', None, 125])
    ws.append(['No Website Partners', None, 80])
    ws.append(['Acme Sample Holdings', None, 250])
    wb.save(folder / 'transactions.xlsx')
    image = Image.new('RGBA', (400, 160), '#17365D')
    ImageDraw.Draw(image).text((30, 65), 'ACME SAMPLE', fill='white', stroke_width=1)
    image.save(folder / 'acme.png')
    (folder / 'overrides.json').write_text(json.dumps({'Acme Sample Holdings': {'logo_path': 'acme.png'}}, indent=2))


if __name__ == '__main__':
    create_sample(Path(__file__).parent)
