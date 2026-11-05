"""Provider-contract tests. Generated colored geometry is test data, not company artwork."""
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image, ImageDraw
from openpyxl import Workbook, load_workbook
import requests
from tag_logo_bank.api import BASE, Download, LogoAPI, Transport, normalized_name
from tag_logo_bank.workbook import build_logo_bank

FIVE = [('Microsoft', 'microsoft.com'), ('Apple', 'apple.com'), ('NVIDIA', 'nvidia.com'),
        ('Salesforce', 'salesforce.com'), ('Adobe', 'adobe.com')]


def png(color='navy'):
    image = Image.new('RGBA', (512, 200))
    ImageDraw.Draw(image).rectangle((20, 20, 350, 150), fill=color)
    stream = BytesIO()
    image.save(stream, 'PNG')
    return stream.getvalue()


def item(name='Microsoft', domain='microsoft.com', **kwargs):
    return {'name': name, 'domain': domain, 'source': 'https://www.' + domain,
            'logo': BASE + '/' + domain + '.svg', 'wordmark': True, **kwargs}


def search(results):
    return Download(json.dumps({'results': results}).encode(), BASE + '/search', {'Content-Type': 'application/json'})


def image(data=None, headers=None):
    return Download(data if data is not None else png(), BASE + '/microsoft.com.png?fallback=404',
                    headers or {'Content-Type': 'image/png'})


class APITests(unittest.TestCase):
    def api_with(self, matches, download=None):
        transport = MagicMock()
        transport.get.side_effect = [search(matches), download or image()]
        return LogoAPI(transport), transport

    def test_domain_png_request_has_no_fallback_and_no_website_fetch(self):
        api, transport = self.api_with([item()])
        result = api.lookup('Microsoft Corporation', 'https://www.microsoft.com/path?utm_source=x')
        self.assertTrue(result.png)
        self.assertEqual(result.status, 'REVIEW_REQUIRED')
        self.assertEqual(result.domain, 'microsoft.com')
        self.assertEqual(result.width, 512)
        self.assertEqual(len(result.sha256), 64)
        calls = [c.args[0] for c in transport.get.call_args_list]
        self.assertEqual(calls[0], BASE + '/search?q=microsoft.com')
        self.assertEqual(calls[1], BASE + '/microsoft.com.png?size=1024&fallback=404')
        self.assertEqual(result.downloaded_png, png())
        self.assertTrue(all(urlsplit(url).hostname == 'logoapi.sh' for url in calls))

    def test_name_search_unique_exact_match(self):
        api, transport = self.api_with([item(), item('Microsoft Teams', 'teams.com')])
        result = api.lookup('Microsoft')
        self.assertTrue(result.png)
        self.assertIn('unique exact name', result.detail)
        self.assertEqual(transport.get.call_args_list[0].args[0], BASE + '/search?q=Microsoft')

    def test_uncertain_matches_never_download_any_image(self):
        cases = [([item('Microsoft Teams')], ''),
                 ([item(fuzzy=True)], ''),
                 ([item(), item('Microsoft', 'other.com')], ''),
                 ([item('Adobe', 'adobe.com')], 'microsoft.com'),
                 ([item('Microsoft', 'acquirer.com')], 'microsoft.com'),
                 ([item(source='https://acquirer.com')], 'microsoft.com'),
                 ([item(name='Microsoft\x00')], 'microsoft.com'),
                 ([{'name': 'Microsoft', 'domain': 'microsoft.com'}], ''),
                 ([item(domain='127.0.0.1')], '')]
        for matches, website in cases:
            with self.subTest(matches=matches, website=website):
                api, transport = self.api_with(matches)
                result = api.lookup('Microsoft', website)
                self.assertEqual(result.status, 'MATCH_UNCERTAIN')
                self.assertIsNone(result.png)
                self.assertEqual(transport.get.call_count, 1)

    def test_not_found_does_not_request_generated_tiles(self):
        api, transport = self.api_with([])
        result = api.lookup('Microsoft', 'microsoft.com')
        self.assertEqual(result.status, 'NOT_FOUND')
        self.assertFalse(result.png)
        self.assertEqual(transport.get.call_count, 1)

    def test_fallback_headers_rejected_even_with_http_200_valid_png(self):
        for kind in ('tile', 'favicon', 'monogram', 'unknown'):
            with self.subTest(kind=kind):
                api, _ = self.api_with([item()], image(headers={'Content-Type': 'image/png', 'x-logo-fallback': kind}))
                result = api.lookup('Microsoft', 'microsoft.com')
                self.assertEqual(result.status, 'NOT_FOUND')
                self.assertFalse(result.png)
        api, _ = self.api_with([item()], image(headers={'Content-Type': 'image/png', 'X-Logo-Kind': 'tile'}))
        self.assertIsNone(api.lookup('Microsoft', 'microsoft.com').png)

    def test_svg_html_corrupt_and_wrong_type_are_not_embedded(self):
        for data, content_type in [(b'<svg/>', 'image/svg+xml'), (b'error', 'text/html'),
                                   (b'\x89PNG\r\n\x1a\ncorrupt', 'image/png'), (png(), 'image/jpeg')]:
            with self.subTest(content_type=content_type):
                api, _ = self.api_with([item()], image(data, {'Content-Type': content_type}))
                result = api.lookup('Microsoft', 'microsoft.com')
                self.assertEqual(result.status, 'ERROR')
                self.assertFalse(result.png)

    def test_http_404_429_403_and_network_errors(self):
        for code, expected in [(404, 'NOT_FOUND'), (429, 'RATE_LIMITED'), (403, 'ERROR'), (503, 'ERROR')]:
            response = requests.Response()
            response.status_code = code
            transport = MagicMock()
            transport.get.side_effect = requests.HTTPError('provider error', response=response)
            result = LogoAPI(transport).lookup('Microsoft', 'microsoft.com')
            self.assertEqual(result.status, expected)
            self.assertIn(str(code), result.detail)
            self.assertFalse(result.png)
        for error in (requests.Timeout('timeout'), OSError('proxy unavailable')):
            transport = MagicMock()
            transport.get.side_effect = error
            result = LogoAPI(transport).lookup('Microsoft', 'microsoft.com')
            self.assertEqual(result.status, 'ERROR')
            self.assertIn(type(error).__name__, result.detail)

    def test_invalid_json_contract_and_input(self):
        for payload in (b'not-json', b'[]', b'{"results":{}}', json.dumps({'results': [item()] * 9}).encode()):
            transport = MagicMock()
            transport.get.return_value = Download(payload, BASE + '/search', {})
            self.assertEqual(LogoAPI(transport).lookup('Microsoft').status, 'ERROR')
        transport = MagicMock()
        self.assertEqual(LogoAPI(transport).lookup('A').status, 'MATCH_UNCERTAIN')
        self.assertEqual(LogoAPI(transport).lookup('Microsoft', 'file:///tmp/logo').status, 'ERROR')
        transport.get.assert_not_called()
        self.assertNotEqual(normalized_name('Apple Holdings'), normalized_name('Apple'))
        self.assertEqual(normalized_name('NVIDIA Corporation'), normalized_name('NVIDIA'))

    def test_five_companies_domain_and_name_offline_contract(self):
        for by_name in (False, True):
            for name, domain in FIVE:
                with self.subTest(name=name, by_name=by_name):
                    api, transport = self.api_with([item(name, domain)])
                    result = api.lookup(name, '' if by_name else 'https://www.' + domain)
                    self.assertTrue(result.png)
                    self.assertEqual(result.domain, domain)
                    self.assertEqual(result.status, 'REVIEW_REQUIRED')
                    self.assertIn('/' + domain + '.png?', transport.get.call_args.args[0])

    def test_five_company_workbook_has_correct_rows_and_local_downloads(self):
        colors = ['red', 'green', 'blue', 'orange', 'purple']
        by_domain = {domain: (name, png(color)) for (name, domain), color in zip(FIVE, colors)}
        transport = MagicMock()
        def get(url):
            parsed = urlsplit(url)
            if parsed.path == '/search':
                query = parse_qs(parsed.query)['q'][0]
                for domain, (name, _) in by_domain.items():
                    if query in (domain, name):
                        return search([item(name, domain)])
                return search([])
            domain = parsed.path.lstrip('/').removesuffix('.png')
            return Download(by_domain[domain][1], url, {'Content-Type': 'image/png'})
        transport.get.side_effect = get
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            source, output = folder / 'in.xlsx', folder / 'out.xlsx'
            wb = Workbook()
            ws = wb.active
            ws.title = 'Transactions'
            ws.append(['Company', 'Website'])
            for index, (name, domain) in enumerate(FIVE):
                ws.append([name, domain if index % 2 == 0 else ''])
            wb.save(source)
            counts = build_logo_bank(source, output, fetcher=LogoAPI(transport))
            self.assertEqual(counts, {'REVIEW_REQUIRED': 5})
            result = load_workbook(output)
            ws = result['Logos']
            self.assertEqual([i.anchor._from.row for i in ws._images], [1, 2, 3, 4, 5])
            for row, ((name, domain), color) in enumerate(zip(FIVE, colors), 2):
                self.assertEqual(ws.cell(row, 1).value, name)
                self.assertEqual(Path(ws.cell(row, 11).value).read_bytes(), by_domain[domain][1])
            self.assertEqual(len(list((folder / 'out_logos').glob('*.png'))), 5)
            result.close()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.dns = patch('tag_logo_bank.api.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('8.8.8.8', 443))])
        self.dns.start()
        self.addCleanup(self.dns.stop)

    def response(self, data=png(), status=200, headers=None):
        response = MagicMock()
        response.__enter__.return_value = response
        response.is_redirect = status in (301, 302)
        response.headers = headers or {'Content-Type': 'image/png'}
        response.iter_content.return_value = [data]
        return response

    def test_only_fixed_https_origin_and_private_dns_rejected(self):
        transport = Transport()
        with patch.object(transport.session, 'get') as get:
            for url in ('http://logoapi.sh/a', 'https://evil.com/a', 'https://user:pass@logoapi.sh/a',
                        'https://logoapi.sh:8443/a', 'file:///tmp/a'):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    transport.get(url)
            with patch('tag_logo_bank.api.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
                with self.assertRaisesRegex(ValueError, 'nonpublic'):
                    transport.get(BASE + '/search?q=test')
            get.assert_not_called()

    def test_redirect_to_other_origin_never_followed(self):
        transport = Transport()
        response = self.response(status=302, headers={'Location': 'https://evil.com/tile.png'})
        with patch.object(transport.session, 'get', return_value=response) as get:
            with self.assertRaisesRegex(ValueError, 'logoapi.sh'):
                transport.get(BASE + '/microsoft.com.png?fallback=404')
            self.assertEqual(get.call_count, 1)
            self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_bounded_download_and_redirect_limit(self):
        transport = Transport()
        response = self.response(data=b'x' * (8 * 1024 * 1024 + 1))
        with patch.object(transport.session, 'get', return_value=response):
            with self.assertRaisesRegex(ValueError, '8 MB'):
                transport.get(BASE + '/microsoft.com.png')
        response = self.response(status=302, headers={'Location': '/loop'})
        with patch.object(transport.session, 'get', return_value=response) as get:
            with self.assertRaisesRegex(ValueError, 'Too many'):
                transport.get(BASE + '/loop')
            self.assertEqual(get.call_count, 6)

    def test_timeout_stream_and_headers_preserved(self):
        transport = Transport()
        with patch.object(transport.session, 'get', return_value=self.response()) as get:
            result = transport.get(BASE + '/microsoft.com.png')
            self.assertEqual(result.headers['Content-Type'], 'image/png')
            self.assertEqual(get.call_args.kwargs['timeout'], (5, 20))
            self.assertTrue(get.call_args.kwargs['stream'])
            self.assertNotIn('verify', get.call_args.kwargs)  # requests' TLS verification default stays enabled.


if __name__ == '__main__':
    unittest.main()
