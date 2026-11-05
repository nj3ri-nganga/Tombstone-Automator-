"""Workbook/raster regressions, using unittest so tests need no extra packages."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest
from unittest.mock import patch, MagicMock
import zipfile

from PIL import Image, ImageDraw
from openpyxl import Workbook, load_workbook
from openpyxl.utils.units import EMU_to_pixels, points_to_pixels
from tag_logo_bank.logos import Logo, find_logo, verify_image, website_domain, normalize_site
from tag_logo_bank.workbook import build_logo_bank, extract_companies


def png(size=(240, 100), color='navy'):
    img = Image.new('RGBA', size)
    ImageDraw.Draw(img).rectangle((3, 3, size[0] // 2, size[1] // 2), fill=color)
    data = BytesIO()
    img.save(data, 'PNG')
    return data.getvalue()


class WorkbookTests(unittest.TestCase):
    def test_missing_website_column_uses_name_lookup(self):
        with TemporaryDirectory() as folder:
            source, output = (Path(folder) / name for name in ('in.xlsx', 'out.xlsx'))
            wb = Workbook()
            wb.active.title = 'Transactions'
            wb.active.append(['Company'])
            wb.active.append(['Adobe'])
            wb.save(source)
            api = MagicMock()
            api.lookup.return_value = Logo(status='NOT_FOUND')
            self.assertEqual(build_logo_bank(source, output, fetcher=api), {'NOT_FOUND': 1})
            api.lookup.assert_called_once_with('Adobe', '')

    def test_domains_and_tracking_urls(self):
        self.assertEqual(website_domain('https://WWW.Microsoft.com/en-us/?utm_source=x'), 'microsoft.com')
        self.assertEqual(website_domain('investor.nvidia.com'), 'investor.nvidia.com')
        self.assertEqual(normalize_site('example.com?a=b&utm_source=x&fbclid=y#top'), 'https://example.com?a=b')
        for value in ('file:///tmp/x', 'https://user:secret@example.com', 'http://127.0.0.1',
                      'http://[::1]', 'https://localhost', 'https://example.com:8080',
                      'https://bad host.com', 'https://company.local', 'https://company.com/path/../../'):
            if value.endswith('/path/../../'):
                self.assertEqual(website_domain(value), 'company.com')
            else:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    website_domain(value)

    def test_invalid_and_blank_images(self):
        for data in (b'bad', b'<svg/>', png((10, 10))):
            with self.subTest(data=data[:15]), self.assertRaises((ValueError, OSError)):
                verify_image(data)
        stream = BytesIO()
        Image.new('RGBA', (200, 100)).save(stream, 'PNG')
        with self.assertRaisesRegex(ValueError, 'Blank'):
            verify_image(stream.getvalue())
        self.assertTrue(verify_image(png(color='white'))[0])

    def test_multiple_pairs_hyperlinks_dedup_and_missing_columns(self):
        ws = Workbook().active
        ws.append(['Target', 'Target Website', 'Buyer'])
        ws.append(['Target Ltd', 'Visit', 'Buyer Ltd'])
        ws['B2'].hyperlink = 'https://target.com?utm_source=x'
        ws.append(['Target Ltd', 'https://target.com', 'Buyer Ltd'])
        self.assertEqual(extract_companies(ws, [('Target', 'Target Website'), ('Buyer', '')]),
                         [('Target Ltd', 'https://target.com'), ('Buyer Ltd', '')])
        with self.assertRaisesRegex(ValueError, 'Missing'):
            extract_companies(ws, [('Unknown', '')])

    def test_workbook_layout_saved_pngs_and_rerun(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            source, output = folder / 'source.xlsx', folder / 'output.xlsx'
            wb = Workbook()
            ws = wb.active
            ws.title = 'Transactions'
            ws.append(['Company', 'Website'])
            for name in ('Microsoft', 'Apple', 'NVIDIA', 'Salesforce', '=Literal Company'):
                ws.append([name, 'https://company.com?utm_source=x'])
            wb.save(source)
            raw = png((1024, 400))
            embedded, width, height = verify_image(raw)
            results = [Logo(embedded, status='REVIEW_REQUIRED', downloaded_png=raw, domain='microsoft.com'),
                       Logo(embedded, status='MANUAL_REVIEW'), Logo(status='NOT_FOUND'),
                       Logo(embedded, status='REVIEW_REQUIRED'), Logo(status='MATCH_UNCERTAIN')]
            with patch('tag_logo_bank.workbook.find_logo', side_effect=results):
                counts = build_logo_bank(source, output)
            self.assertEqual(counts['NOT_FOUND'], 1)
            result = load_workbook(output)
            ws = result['Logos']
            self.assertEqual([i.anchor._from.row for i in ws._images], [1, 2, 4])
            for image in ws._images:
                anchor = image.anchor
                self.assertEqual(anchor._from.col, 2)
                self.assertLessEqual(EMU_to_pixels(anchor._from.rowOff + anchor.ext.cy) + 8,
                                     points_to_pixels(ws.row_dimensions[anchor._from.row + 1].height))
                self.assertLessEqual(EMU_to_pixels(anchor.ext.cx) + 16, 196)
                self.assertAlmostEqual(anchor.ext.cx / anchor.ext.cy, width / height, places=2)
            self.assertEqual(Path(ws['K2'].value).read_bytes(), raw)
            self.assertEqual(ws['D4'].value, 'NOT_FOUND')
            self.assertEqual(ws['C4'].value, None)
            self.assertEqual(ws['K4'].value, None)
            self.assertEqual(ws['A6'].data_type, 's')
            self.assertEqual(ws['A4'].fill.fgColor.rgb, '00FFF2CC')
            self.assertEqual(result['Transactions'].max_row, 6)
            result.close()
            original = load_workbook(source)
            self.assertNotIn('Logos', original)
            original.close()
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(len([n for n in archive.namelist() if n.startswith('xl/media/')]), 3)
            second = folder / 'second.xlsx'
            with patch('tag_logo_bank.workbook.find_logo', return_value=Logo(status='NOT_FOUND')):
                build_logo_bank(output, second)
            result = load_workbook(second)
            self.assertEqual(result.sheetnames.count('Logos'), 1)
            self.assertEqual(len(result['Logos']._images), 0)  # Never reuse stale logos.
            result.close()
            with self.assertRaisesRegex(ValueError, 'separate'):
                build_logo_bank(source, source)

    def test_bad_local_directory_flags_row_and_keeps_cell_empty(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / 'in.xlsx'
            wb = Workbook()
            ws = wb.active
            ws.title = 'Transactions'
            ws.append(['Company', 'Website'])
            ws.append(['Adobe', 'adobe.com'])
            wb.save(source)
            output = folder / 'out.xlsx'
            with patch('tag_logo_bank.workbook.find_logo', return_value=Logo(png(), status='REVIEW_REQUIRED')), \
                 patch('tag_logo_bank.workbook.save_png', side_effect=OSError('disk full')):
                self.assertEqual(build_logo_bank(source, output), {'ERROR': 1})
            result = load_workbook(output)
            self.assertEqual(len(result['Logos']._images), 0)
            self.assertIn('disk full', result['Logos']['J2'].value)
            result.close()

    def test_cli_bad_workbook_and_windows_override_paths(self):
        from tag_logo_bank.cli import main
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            source, output = folder / 'bad.xlsx', folder / 'out.xlsx'
            source.write_bytes(b'bad')
            from io import StringIO
            with patch.object(sys, 'argv', ['tag-logos', str(source), str(output)]), patch('sys.stderr', new_callable=StringIO) as error:
                self.assertEqual(main(), 1)
                self.assertIn('Error:', error.getvalue())
                self.assertFalse(output.exists())
            config = folder / 'override.json'
            config.write_text(json.dumps({'Adobe': {'logo_path': 'official verified.png'}}), encoding='utf-8-sig')
            with patch.object(sys, 'argv', ['tag-logos', 'in.xlsx', 'out.xlsx', '--overrides', str(config)]), \
                 patch('tag_logo_bank.cli.build_logo_bank', return_value={}) as build, patch('sys.stdout', new_callable=StringIO):
                self.assertEqual(main(), 0)
                self.assertEqual(Path(build.call_args.kwargs['overrides']['Adobe']['logo_path']), folder / 'official verified.png')

    def test_optional_manual_approval_and_no_api_calls(self):
        import hashlib
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'local.png'
            data = png()
            path.write_bytes(data)
            api = MagicMock()
            self.assertEqual(find_logo('adobe.com', api, path).status, 'MANUAL_REVIEW')
            approval = {'sha256': hashlib.sha256(data).hexdigest(), 'reviewed_by': 'Reviewer',
                        'reviewed_on': '2026-11-05', 'source_url': 'https://www.adobe.com/'}
            self.assertEqual(find_logo('adobe.com', api, path, approval=approval).status, 'MANUAL_APPROVED')
            approval['sha256'] = '0' * 64
            self.assertEqual(find_logo('adobe.com', api, path, approval=approval).status, 'ERROR')
            self.assertEqual(find_logo('adobe.com', api, approval=approval).status, 'ERROR')
            path.write_bytes(b'<svg><script/></svg>')
            self.assertEqual(find_logo('', api, path).status, 'ERROR')
            path.unlink()
            self.assertEqual(find_logo('adobe.com', api, path).status, 'ERROR')
            api.lookup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
