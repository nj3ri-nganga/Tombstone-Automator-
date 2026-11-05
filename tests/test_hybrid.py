"""Offline hybrid/security/cache/preservation tests. No company-site requests."""
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch
from io import BytesIO
from PIL import Image as PILImage, ImageDraw
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image
from openpyxl.styles import Font
from tag_logo_bank.api import Download
from tag_logo_bank.logos import Logo
from tag_logo_bank.network import HTTP, RateLimited, IdentityRedirect
from tag_logo_bank.hybrid import Hybrid, BraveSearch
from tag_logo_bank.discovery import discover, official_logo, image_bytes
from tag_logo_bank.workbook import build_logo_bank, image_cell


def png(fmt='PNG'):
    image = PILImage.new('RGB', (240, 90), 'white')
    ImageDraw.Draw(image).rectangle((3, 3, 120, 80), fill='blue')
    stream = BytesIO()
    image.save(stream, fmt)
    return stream.getvalue()


def response(data=b'page', status=200, headers=None):
    r = MagicMock()
    r.__enter__.return_value = r
    r.status_code = status
    r.is_redirect = status in (301, 302)
    r.headers = headers or {}
    r.iter_content.return_value = [data]
    return r


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 1000
        self.http = HTTP(self.folder.name, clock=lambda: self.now, sleep=self.sleep, max_wait=2)
        self.addCleanup(self.http.close)
        self.dns = patch('tag_logo_bank.network.public_url')
        self.dns.start()
        self.addCleanup(self.dns.stop)

    def sleep(self, seconds):
        self.now += seconds

    def test_persistent_response_cache_avoids_repeat_requests(self):
        with patch.object(self.http.session, 'get', return_value=response()) as get:
            self.http.get('https://company.com/')
            self.http.get('https://company.com/')
            self.assertEqual(get.call_count, 1)
        other = HTTP(self.folder.name, clock=lambda: self.now)
        try:
            with patch.object(other.session, 'get') as get:
                other.get('https://company.com/')
                get.assert_not_called()
        finally:
            other.close()

    def test_429_short_backoff_and_long_cooldown_resume(self):
        with patch.object(self.http.session, 'get', side_effect=[response(status=429, headers={'Retry-After': '1'}), response()]):
            self.http.get('https://company.com/short')
        self.assertEqual(self.now, 1001)
        with patch.object(self.http.session, 'get', return_value=response(status=429, headers={'Retry-After': '60'})) as get:
            with self.assertRaises(RateLimited):
                self.http.get('https://other.com/')
            with self.assertRaises(RateLimited):
                self.http.get('https://other.com/another')
            self.assertEqual(get.call_count, 1)
        self.now += 61
        with patch.object(self.http.session, 'get', return_value=response()) as get:
            self.http.get('https://other.com/')
            self.assertEqual(get.call_count, 1)

    def test_429_http_date_and_restart_cooldown(self):
        with patch.object(self.http.session, 'get', return_value=response(status=429, headers={'Retry-After': 'Thu, 01 Jan 1970 00:18:20 GMT'})):
            with self.assertRaises(RateLimited) as error:
                self.http.get('https://other.com/')
            self.assertEqual(error.exception.retry_at, 1100)
        other = HTTP(self.folder.name, clock=lambda: 1001)
        try:
            with patch.object(other.session, 'get') as get, self.assertRaises(RateLimited):
                other.get('https://other.com/')
            get.assert_not_called()
        finally:
            other.close()

    def test_page_redirect_never_fetches_acquirer(self):
        with patch.object(self.http.session, 'get', return_value=response(status=302, headers={'Location': 'https://acquirer.com/'})) as get:
            with self.assertRaises(IdentityRedirect):
                self.http.get('https://target.com/', allowed_hosts={'target.com'})
            self.assertEqual(get.call_count, 1)

    def test_cached_asset_redirect_cannot_be_reused_as_official_page(self):
        with patch.object(self.http.session, 'get', side_effect=[response(status=302, headers={'Location': 'https://acquirer.com/'}), response()]):
            self.http.get('https://target.com/')
        with self.assertRaises(IdentityRedirect):
            self.http.get('https://target.com/', allowed_hosts={'target.com'})

    def test_downgrade_and_response_limits(self):
        with patch.object(self.http.session, 'get', return_value=response(status=302, headers={'Location': 'http://company.com/'})) as get:
            with self.assertRaises(ValueError):
                self.http.get('https://company.com/', https_only=True)
            self.assertEqual(get.call_count, 1)
        with patch.object(self.http.session, 'get', return_value=response(b'x' * (8 * 1024 * 1024 + 1))):
            with self.assertRaisesRegex(ValueError, '8 MB'):
                self.http.get('https://other.com/')

    def test_api_failure_falls_through_and_company_cache_survives_restart(self):
        hybrid = Hybrid(http=self.http)
        result = Logo(png(), source='https://company.com/logo.png', status='REVIEW_REQUIRED', method='header_logo')
        with patch.object(hybrid.api, 'lookup', return_value=Logo(status='NOT_FOUND')), \
             patch('tag_logo_bank.hybrid.official_logo', return_value=result) as official:
            self.assertTrue(hybrid.lookup('Company', 'https://company.com/').png)
            self.assertTrue(hybrid.lookup('Company', 'https://company.com/').png)
            self.assertEqual(official.call_count, 1)
        other = HTTP(self.folder.name, clock=lambda: self.now)
        try:
            with patch('tag_logo_bank.hybrid.official_logo') as official:
                cached = Hybrid(http=other).lookup('Company', 'https://company.com/')
                self.assertEqual(cached.method, 'header_logo')
                self.assertIn('Cache hit', cached.detail)
                official.assert_not_called()
        finally:
            other.close()

    def test_website_only_and_deferred_company_is_not_negative_cached(self):
        hybrid = Hybrid(http=self.http, use_api=False)
        with patch('tag_logo_bank.hybrid.official_logo', side_effect=[RateLimited('company.com', 1100), Logo(png(), status='REVIEW_REQUIRED')]) as official, \
             patch.object(hybrid.api, 'lookup') as api:
            self.assertEqual(hybrid.lookup('Company', 'https://company.com/').status, 'RATE_LIMITED')
            self.now = 1101
            self.assertTrue(hybrid.lookup('Company', 'https://company.com/').png)
            self.assertEqual(official.call_count, 2)
            api.assert_not_called()

    def test_scoped_search_requires_matching_names_and_allowlist(self):
        web = {'web': {'results': [{'url': 'https://unrelated.com/', 'title': 'Company'},
                                  {'url': 'https://company.com/', 'title': 'Company - Official Website'}]}}
        self.http.get = MagicMock(return_value=Download(json.dumps(web).encode(), '', {}))
        with patch.dict('os.environ', {'BRAVE_SEARCH_API_KEY': 'test-key'}):
            self.assertEqual(BraveSearch(self.http, ['company.com']).sites('Company'), ['https://company.com/'])
            self.assertIn('site%3Acompany.com', self.http.get.call_args.args[0])
            with self.assertRaises(ValueError):
                BraveSearch(self.http, []).sites('Company')


@unittest.skipUnless(importlib.util.find_spec('bs4'), 'BeautifulSoup installed in Windows/Linux CI')
class DiscoveryTests(unittest.TestCase):
    def test_schema_header_responsive_and_og_candidates(self):
        html = b'''<title>Small Insurer</title><meta property="og:site_name" content="Small Insurer">
        <script type="application/ld+json">{"@type":"InsuranceAgency","name":"Small Insurer","logo":"/schema.png"}</script>
        <header><a class="brand-logo"><picture><source srcset="/large-logo.webp 2x"><img alt="Small Insurer logo" data-src="/logo.jpg"></picture></a></header>
        <meta property="og:image" content="/social-logo.png"><meta property="og:image" content="/landscape.jpg">'''
        found, _ = discover(html, 'https://company.com/', 'Small Insurer')
        self.assertEqual(found[0].method, 'organization_schema')
        self.assertTrue(any(c.value.endswith('large-logo.webp') for c in found))
        self.assertTrue(any(c.method == 'open_graph_logo_review' for c in found))
        self.assertFalse(any(c.value.endswith('landscape.jpg') for c in found))

    def test_acquisition_article_cannot_use_generic_acquirer_logo(self):
        html = b'''<title>Acquirer acquires Historical Target</title><meta property="og:site_name" content="Acquirer">
        <header><img alt="Logo" src="/acquirer-logo.png"><svg class="logo"><path/></svg></header>
        <p>Historical Target is now part of Acquirer.</p>'''
        self.assertEqual(discover(html, 'https://target.com/', 'Historical Target')[0], [])

    def test_explicit_historical_target_asset_allowed_but_not_partner(self):
        html = b'''<title>Historical Target</title><header><img alt="Historical Target logo" src="/old-logo.png"></header>
        <div class="partner-logos"><img alt="Historical Target logo" src="/partner.png"></div>'''
        found, _ = discover(html, 'https://target.com/', 'Historical Target')
        self.assertEqual([c.value for c in found], ['https://target.com/old-logo.png'])

    def test_bad_svg_falls_through_to_real_raster_logo(self):
        http = MagicMock()
        http.get.side_effect = [Download(b'<title>Small Insurer</title><header><img alt="Small Insurer logo" src="/bad.svg"><img alt="Small Insurer logo" src="/good.png"></header>', 'https://company.com/', {}),
                                Download(b'<svg><script/></svg>', '', {}), Download(png(), 'https://company.com/good.png', {})]
        result = official_logo('Small Insurer', 'https://company.com/', http)
        self.assertTrue(result.png)
        self.assertTrue(result.source.endswith('good.png'))
        self.assertIn('unsafe SVG', result.detail)

    def test_png_jpeg_webp_rasters(self):
        for fmt in ('PNG', 'JPEG', 'WEBP'):
            self.assertTrue(image_bytes(png(fmt))[0].startswith(b'\x89PNG'))

    def test_king_rebrand_does_not_silently_become_risk_partners(self):
        html = b'<title>King Risk Partners</title><header><img alt="King Risk Partners logo" src="/king-risk-logo.png"></header>'
        self.assertEqual(discover(html, 'https://www.king-insurance.com/', 'King Insurance')[0], [])


class SVGTests(unittest.TestCase):
    def test_unsafe_svg_rejected_without_any_renderer(self):
        from tag_logo_bank.svg import sanitize_svg
        for data in [b'<!DOCTYPE svg [<!ENTITY x "red">]><svg/>', b'<svg><script/></svg>',
                     b'<svg><image href="file:///etc/passwd"/></svg>',
                     b'<svg><path style="fill:url(https://evil.com/a)"/></svg>']:
            with self.assertRaises(ValueError):
                sanitize_svg(data)

    @unittest.skipUnless(importlib.util.find_spec('resvg_py'), 'Optional resvg wheel installed in Windows/Linux CI')
    def test_real_packaged_svg_renderer_without_cairo(self):
        data = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"><style>.a{fill:blue;}</style><path class="a" d="M0 0h100v100z"/></svg>'
        png_bytes, width, height, note = image_bytes(data)
        self.assertTrue(png_bytes.startswith(b'\x89PNG'))
        self.assertEqual((width, height), (1200, 600))
        self.assertIn('resvg', note)


class PreservationTests(unittest.TestCase):
    def test_current_logo_is_filled_without_replacing_notes_rows_or_existing_image(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            source, output = directory / 'tag.xlsx', directory / 'enriched.xlsx'
            wb = Workbook()
            ws = wb.active
            ws.title = 'Logos'
            ws.append(['Company Name', 'Website', 'Original Logo', 'Current Logo', 'Status', 'Analyst Notes'])
            ws.append(['Historical Target', 'https://target.com', 'historic link', None, 'Approved historical', 'Keep this note'])
            ws.append(['Other', 'https://other.com', None, None, 'Existing approval', 'Keep this too'])
            ws['F2'].font = Font(bold=True)
            ws['B2'].hyperlink = 'https://target.com/'
            ws.add_image(Image(BytesIO(png())), 'D3')
            ws.row_dimensions[3].height = 100
            ws.freeze_panes = 'B2'
            wb.save(source)
            api = MagicMock()
            api.lookup.return_value = Logo(png(), source='https://target.com/logo.png', status='REVIEW_REQUIRED', method='header_logo')
            counts = build_logo_bank(source, output, fetcher=api)
            self.assertEqual(counts, {'REVIEW_REQUIRED': 1, 'ALREADY_PRESENT': 1})
            result = load_workbook(output)
            ws = result['Logos']
            self.assertEqual(ws['C2'].value, 'historic link')
            self.assertEqual(ws['E2'].value, 'Approved historical')
            self.assertEqual(ws['F2'].value, 'Keep this note')
            self.assertTrue(ws['F2'].font.bold)
            self.assertEqual(ws['B2'].hyperlink.target, 'https://target.com/')
            self.assertEqual(sorted(image_cell(i) for i in ws._images), [(2, 4), (3, 4)])
            self.assertEqual(ws.freeze_panes, 'B2')
            self.assertEqual(ws.row_dimensions[3].height, 100)
            self.assertEqual(ws.max_row, 3)
            self.assertEqual(api.lookup.call_count, 1)
            result.close()
            original = load_workbook(source)
            self.assertEqual(len(original['Logos']._images), 1)
            original.close()
