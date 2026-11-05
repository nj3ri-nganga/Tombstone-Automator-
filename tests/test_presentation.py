from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock
from PIL import Image as PILImage, ImageDraw
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image
from openpyxl.utils.units import EMU_to_pixels, points_to_pixels
from tag_logo_bank.logos import Logo
from tag_logo_bank.workbook import build_logo_bank, image_cell


def png():
    image = PILImage.new('RGB', (400, 100), 'white')
    ImageDraw.Draw(image).rectangle((2, 2, 250, 80), fill='blue')
    stream = BytesIO()
    image.save(stream, 'PNG')
    return stream.getvalue()


class PresentationTests(unittest.TestCase):
    def test_only_three_columns_and_all_rows_uniform_including_missing_logos(self):
        with TemporaryDirectory() as folder:
            source, output = (Path(folder) / n for n in ('input.xlsx', 'output.xlsx'))
            wb = Workbook()
            wb.active.title = 'Transactions'
            wb.active.append(['Company', 'Website'])
            wb.active.append(['Found', 'https://found.com'])
            wb.active.append(['Missing', 'https://missing.com'])
            wb.save(source)
            api = MagicMock()
            api.lookup.side_effect = [Logo(png(), status='REVIEW_REQUIRED'), Logo(status='NOT_FOUND')]
            build_logo_bank(source, output, fetcher=api)
            result = load_workbook(output)
            ws = result['Logos']
            self.assertEqual([c.value for c in ws[1]], ['Company', 'Website', 'Logo'])
            self.assertEqual(ws.max_column, 3)
            self.assertEqual([ws.row_dimensions[r].height for r in (1, 2, 3)], [72, 72, 72])
            self.assertEqual(image_cell(ws._images[0]), (2, 3))
            anchor = ws._images[0].anchor
            self.assertAlmostEqual(anchor.ext.cx / anchor.ext.cy, 4)
            self.assertAlmostEqual(EMU_to_pixels(anchor._from.rowOff * 2 + anchor.ext.cy), 96, delta=1)
            audit = json.loads(output.with_suffix('.logo-audit.json').read_text())
            self.assertEqual(audit['rows'][1]['cells']['Status'], 'NOT_FOUND')
            self.assertEqual(result['Transactions']['A2'].value, 'Found')
            result.close()

    def test_original_details_preserved_and_existing_images_resized(self):
        with TemporaryDirectory() as folder:
            source, output = (Path(folder) / n for n in ('input.xlsx', 'output.xlsx'))
            wb = Workbook()
            ws = wb.active
            ws.title = 'Logos'
            ws.append(['Company Name', 'Website', 'Notes', 'Current Logo'])
            ws.append(['Existing', 'https://existing.com', 'Keep the old notes', None])
            ws.row_dimensions[2].height = 200
            ws.add_image(Image(BytesIO(png())), 'D2')
            wb.save(source)
            build_logo_bank(source, output, fetcher=MagicMock())
            result = load_workbook(output)
            self.assertEqual(result['Logos'].max_column, 3)
            self.assertEqual(result['Logos'].row_dimensions[2].height, 72)
            self.assertEqual(image_cell(result['Logos']._images[0]), (2, 3))
            details = result['Logo Details']
            self.assertEqual(details.sheet_state, 'hidden')
            self.assertEqual(details['C2'].value, 'Keep the old notes')
            self.assertEqual(len(details._images), 1)
            result.close()

    def test_rerun_of_three_column_sheet_does_not_accumulate_archives(self):
        with TemporaryDirectory() as folder:
            source, first, second = (Path(folder) / n for n in ('input.xlsx', 'first.xlsx', 'second.xlsx'))
            wb = Workbook()
            wb.active.title = 'Logos'
            wb.active.append(['Company', 'Website', 'Logo'])
            wb.active.append(['Company', 'https://company.com', None])
            wb.save(source)
            api = MagicMock()
            api.lookup.return_value = Logo(png(), status='REVIEW_REQUIRED')
            build_logo_bank(source, first, fetcher=api)
            build_logo_bank(first, second, fetcher=api)
            result = load_workbook(second)
            self.assertEqual(result.sheetnames, ['Logos'])
            self.assertEqual(result['Logos'].max_column, 3)
            self.assertEqual(len(result['Logos']._images), 1)
            self.assertEqual(api.lookup.call_count, 1)
            result.close()
