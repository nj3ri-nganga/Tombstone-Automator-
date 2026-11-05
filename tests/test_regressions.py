"""Offline regressions: synthetic images exercise mechanics, never company identity."""
import importlib.util
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw
from openpyxl import Workbook, load_workbook
from openpyxl.utils.units import EMU_to_pixels, points_to_pixels
from tag_logo_bank.logos import (Logo, Fetcher, public_url, candidates, find_logo, normalize_site,
                                 rasterize_svg, verify_image)
from tag_logo_bank.workbook import build_logo_bank


def png(size=(240, 100)):
    image = Image.new('RGB', size, 'white')
    ImageDraw.Draw(image).rectangle((3, 3, size[0] // 2, size[1] // 2), fill='navy')
    stream = BytesIO()
    image.save(stream, 'PNG')
    return stream.getvalue()


class Routes:
    def __init__(self, routes):
        self.routes = routes
    def get(self, url):
        value = self.routes[url]
        if isinstance(value, Exception):
            raise value
        return value, url


class RegressionTests(unittest.TestCase):
    def test_public_url_security_checks_remain(self):
        for url in ('file:///tmp/logo', 'https://user:pass@example.com/a',
                    'https://example.com:8443/logo'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                public_url(url)
        with patch('tag_logo_bank.logos.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaisesRegex(ValueError, 'nonpublic'):
                public_url('https://example.com/logo')

    def test_redirect_target_revalidated(self):
        from unittest.mock import MagicMock
        fetcher = Fetcher()
        response = MagicMock()
        response.is_redirect = True
        response.headers = {'Location': 'http://127.0.0.1/logo'}
        response.__enter__.return_value = response
        with patch.object(fetcher.session, 'get', return_value=response) as get:
            with patch('tag_logo_bank.logos.public_url', side_effect=[None, ValueError('Private redirect blocked')]):
                with self.assertRaisesRegex(ValueError, 'Private redirect'):
                    fetcher.get('https://example.com')
            self.assertEqual(get.call_count, 1)

    def test_tracking_parameters(self):
        self.assertEqual(normalize_site('example.com/brand?utm_source=x&UTM_medium=y&gclid=z&lang=en#top'),
                         'https://example.com/brand?lang=en')

    def test_failure_stage_url_and_exception(self):
        result = find_logo('example.com', Routes({'https://example.com': OSError('connection timeout')}))
        self.assertEqual(result.status, 'ERROR')
        for expected in ('website fetch', 'example.com', 'OSError', 'connection timeout'):
            self.assertIn(expected, result.detail)

    def test_better_resolution_and_favicon_fallback(self):
        routes = {'https://example.com': b'page',
                  'https://example.com/small': png(),
                  'https://example.com/large': png((900, 300)),
                  'https://example.com/icon': png((1000, 1000))}
        options = [(f'https://example.com/{name}', kind) for name, kind in
                   [('small', 'logo_image'), ('large', 'logo_image'), ('icon', 'icon_review')]]
        with patch('tag_logo_bank.logos.candidates', return_value=options):
            result = find_logo('example.com', Routes(routes))
            self.assertTrue(result.source.endswith('/large'))
            self.assertEqual(result.status, 'REVIEW_REQUIRED')
            routes['https://example.com/small'] = b'broken'
            routes['https://example.com/large'] = b'broken'
            result = find_logo('example.com', Routes(routes))
            self.assertTrue(result.source.endswith('/icon'))
            self.assertIn('rejected candidates', result.detail)
            self.assertIn('UnidentifiedImageError', result.detail)

    def test_no_valid_asset_retains_candidate_error(self):
        with patch('tag_logo_bank.logos.candidates', return_value=[('https://example.com/logo', 'logo_image')]):
            result = find_logo('example.com', Routes({'https://example.com': b'page',
                              'https://example.com/logo': OSError('HTTP 403 Forbidden')}))
        self.assertEqual(result.status, 'NOT_FOUND')
        self.assertIn('candidate https://example.com/logo: OSError: HTTP 403', result.detail)

    @unittest.skipUnless(importlib.util.find_spec('bs4'), 'BeautifulSoup is not installed')
    def test_discovery_picture_lazy_schema_and_inline(self):
        html = '''<script type="application/ld+json">{"@type":"Organization","logo":"/schema.svg"}</script>
        <header><picture><source srcset="/wide.svg 2x"><img alt="Company logo" data-src="/lazy.png" srcset="/big.png 2x"></picture>
        <svg aria-label="Company logo" viewBox="0 0 200 100"><path d="M0 0h100v100z"/></svg></header>
        <link rel="icon" href="/icon.png">'''
        found = candidates(html, 'https://example.com')
        self.assertEqual(found[0], ('https://example.com/schema.svg', 'organization_schema'))
        for name in ('wide.svg', 'lazy.png', 'big.png'):
            self.assertIn(('https://example.com/' + name, 'logo_image'), found)
        self.assertTrue(any(kind == 'inline_svg' for _, kind in found))

    def test_svg_unsafe_content_rejected_before_renderer(self):
        for content in ('<!DOCTYPE svg><svg/>', '<svg><script/></svg>',
                        '<svg><image href="https://evil.example/a"/></svg>',
                        '<svg><use href="file:///etc/passwd"/></svg>',
                        '<svg><path fill="url(https://evil.example/a)"/></svg>',
                        '<svg><path style="fill:red"/></svg>'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                rasterize_svg(content.encode())

    def test_svg_conversion_is_bounded_and_blocks_fetches(self):
        import sys
        from types import ModuleType
        fake = ModuleType('cairosvg.surface')
        class Surface:
            @staticmethod
            def convert(**kwargs):
                self.assertEqual(kwargs['output_width'], 1200)
                self.assertEqual(kwargs['output_height'], 600)
                with self.assertRaises(ValueError):
                    kwargs['url_fetcher']('https://evil.example')
                return png((1200, 600))
        fake.PNGSurface = Surface
        with patch.dict(sys.modules, {'cairosvg': ModuleType('cairosvg'), 'cairosvg.surface': fake}):
            result, width, height = verify_image(b'<svg viewBox="0 0 200 100"><path d="M0 0h100v100z"/></svg>')
        self.assertEqual((width, height), (1200, 600))
        self.assertTrue(result.startswith(b'\x89PNG'))

    def test_workbook_images_stay_in_own_rows_with_gaps(self):
        with TemporaryDirectory() as directory:
            source, output = (Path(directory) / name for name in ('in.xlsx', 'out.xlsx'))
            wb = Workbook()
            ws = wb.active
            ws.title = 'Transactions'
            ws.append(['Company', 'Website'])
            for name in ('Microsoft', 'Apple', 'NVIDIA', 'Salesforce', 'Adobe'):
                ws.append([name, 'https://example.com?utm_source=test&lang=en'])
            wb.save(source)
            results = [Logo(png((600, 300)), status='REVIEW_REQUIRED'),
                       Logo(png((100, 300)), status='MANUAL_REVIEW'),
                       Logo(status='NOT_FOUND'), Logo(png(), status='REVIEW_REQUIRED'),
                       Logo(status='ERROR', detail='website fetch: HTTPError: 403')]
            with patch('tag_logo_bank.workbook.find_logo', side_effect=results) as find:
                counts = build_logo_bank(source, output, overrides={'Apple': {'website': 'https://apple.example?utm_source=x'}})
            self.assertEqual(find.call_args_list[1].args[0], 'https://apple.example')
            self.assertEqual(counts['ERROR'], 1)
            wb = load_workbook(output)
            ws = wb['Logos']
            self.assertEqual([image.anchor._from.row for image in ws._images], [1, 2, 4])
            for image in ws._images:
                anchor = image.anchor
                self.assertEqual(anchor._from.col, 2)
                height = points_to_pixels(ws.row_dimensions[anchor._from.row + 1].height)
                self.assertLessEqual(EMU_to_pixels(anchor._from.rowOff + anchor.ext.cy) + 8, height)
                self.assertLessEqual(EMU_to_pixels(anchor.ext.cx) + 16, 196)
            self.assertEqual(ws['B2'].value, 'https://example.com?lang=en')
            self.assertEqual(ws['D3'].value, 'MANUAL_REVIEW')
            self.assertEqual(ws['D4'].value, 'NOT_FOUND')
            self.assertIn('403', ws['J6'].value)
            wb.close()


if __name__ == '__main__':
    unittest.main()
