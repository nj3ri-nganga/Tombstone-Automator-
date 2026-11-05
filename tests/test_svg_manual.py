"""Deterministic SVG sanitization and manual approval regressions; no websites."""
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw
from openpyxl import Workbook, load_workbook
import requests
from tag_logo_bank.logos import candidates, find_logo, rasterize_svg
from tag_logo_bank.svg import sanitize_svg
from tag_logo_bank.workbook import build_logo_bank


def png():
    image = Image.new('RGBA', (240, 100))
    ImageDraw.Draw(image).rectangle((10, 10, 180, 90), fill='navy')
    stream = BytesIO()
    image.save(stream, 'PNG')
    return stream.getvalue()


def approval(data):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'reviewed_by': 'Test Reviewer',
            'reviewed_on': '2026-11-05', 'source_url': 'https://brand.example/official?utm_source=test'}


EXPORT = b'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<!-- Exported by a vector editor -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" xml:space="preserve"
     style="enable-background:new 0 0 200 100;">
<style type="text/css"><![CDATA[.st0 {fill:#76B900;} path.st0 {stroke:#000;}]]></style>
<path class="st0" style="opacity:0.9;" d="M0 0h100v100z"/>
</svg>'''


class SVGManualTests(unittest.TestCase):
    def test_legitimate_export_is_sanitized_and_audited(self):
        sanitized, notes = sanitize_svg(EXPORT)
        root = ET.fromstring(sanitized)
        path = root.find('{http://www.w3.org/2000/svg}path')
        self.assertEqual(path.get('fill'), '#76B900')
        self.assertEqual(path.get('stroke'), '#000')
        self.assertEqual(path.get('opacity'), '0.9')
        self.assertNotIn(b'DOCTYPE', sanitized)
        self.assertNotIn(b'<!', sanitized)
        self.assertFalse(any('style' in n.attrib or n.tag.endswith('style') for n in root.iter()))
        self.assertTrue(any('DOCTYPE removed' in note for note in notes))
        self.assertTrue(any('stylesheet' in note for note in notes))

    def test_css_cascade_and_inline_precedence(self):
        data = b'''<svg viewBox="0 0 200 100"><style>
        .a {fill:blue;} #target {fill:red;} .a {fill:green;stroke:black;}
        </style><path id="target" class="a" fill="white" style="stroke:orange"/></svg>'''
        root = ET.fromstring(sanitize_svg(data)[0])
        path = root.find('path')
        self.assertEqual(path.get('fill'), 'red')
        self.assertEqual(path.get('stroke'), 'orange')

    def test_internal_gradient_and_use_are_retained(self):
        data = b'''<svg viewBox="0 0 200 100" xmlns:xlink="http://www.w3.org/1999/xlink">
        <defs><linearGradient id="paint"><stop offset="0" stop-color="#000"/></linearGradient>
        <path id="shape" d="M0 0h100v100z"/></defs><use xlink:href="#shape" fill="url(#paint)"/></svg>'''
        sanitized, _ = sanitize_svg(data)
        self.assertIn(b'#shape', sanitized)
        self.assertIn(b'url(#paint)', sanitized)

    def test_unsafe_or_unsupported_svg_fails_before_renderer(self):
        vectors = [
            b'<!DOCTYPE svg [<!ENTITY a "red">]><svg fill="&a;"/>',
            b'<!DOCTYPE svg SYSTEM "file:///etc/passwd"><svg/>',
            b'<?xml-stylesheet href="https://evil.example/a"?><svg/>',
            b'<svg><script>alert(1)</script></svg>',
            b'<svg onload="alert(1)"/>',
            b'<svg xml:base="https://evil.example/"/>',
            b'<svg><image href="data:image/png;base64,AAAA"/></svg>',
            b'<svg><foreignObject/></svg>',
            b'<svg><use href="https://evil.example/a.svg#x"/></svg>',
            b'<svg><use href="file:///tmp/logo"/></svg>',
            b'<svg><style>@import "https://evil.example/a";</style></svg>',
            b'<svg><path style="fill:url(https://evil.example/a)"/></svg>',
            b'<svg><path fill="url(file:///etc/passwd)"/></svg>',
            b'<svg><path style="fill:u\\72l(https://evil.example/a)"/></svg>',
            b'<svg><path style="width:expression(alert(1))"/></svg>',
            b'<svg><style>.x:hover{fill:red;}</style></svg>',
            b'<svg xmlns="https://evil.example/not-svg"/>',
        ]
        fake = ModuleType('cairosvg.surface')
        fake.PNGSurface = MagicMock()
        with patch.dict(sys.modules, {'cairosvg': ModuleType('cairosvg'), 'cairosvg.surface': fake}):
            for data in vectors:
                with self.subTest(data=data), self.assertRaises(ValueError):
                    rasterize_svg(data)
            fake.PNGSurface.convert.assert_not_called()

    def test_resource_amplification_and_duplicate_ids_rejected(self):
        for data in (b'<svg><use id="a" href="#a"/></svg>',
                     b'<svg><path id="a"/><path id="a"/></svg>',
                     b'<svg><use href="#missing"/></svg>',
                     b'<svg>' * 101 + b'</svg>' * 101):
            with self.subTest(data=data[:100]), self.assertRaises(ValueError):
                sanitize_svg(data)

    def test_sanitized_bytes_reach_renderer_with_blocking_callback(self):
        fake = ModuleType('cairosvg.surface')
        captured = {}
        class Surface:
            @staticmethod
            def convert(**kwargs):
                captured.update(kwargs)
                return png()
        fake.PNGSurface = Surface
        notes = []
        with patch.dict(sys.modules, {'cairosvg': ModuleType('cairosvg'), 'cairosvg.surface': fake}):
            self.assertTrue(rasterize_svg(EXPORT, notes=notes))
        self.assertNotIn(b'DOCTYPE', captured['bytestring'])
        self.assertNotIn(b'<style', captured['bytestring'])
        self.assertEqual((captured['output_width'], captured['output_height']), (1200, 600))
        with self.assertRaises(ValueError):
            captured['url_fetcher']('https://evil.example/a')
        self.assertIn('self-contained SVG sanitized', notes)

    def test_renderer_specific_failure_becomes_candidate_diagnostic(self):
        fake = ModuleType('cairosvg.surface')
        fake.PNGSurface = MagicMock()
        fake.PNGSurface.convert.side_effect = RuntimeError('native backend failure')
        fetcher = MagicMock()
        fetcher.get.side_effect = [(b'page', 'https://brand.example/'),
                                   (EXPORT, 'https://brand.example/logo.svg')]
        with patch.dict(sys.modules, {'cairosvg': ModuleType('cairosvg'), 'cairosvg.surface': fake}), \
             patch('tag_logo_bank.logos.candidates', return_value=[('https://brand.example/logo.svg', 'logo_image')]):
            result = find_logo('https://brand.example/', fetcher)
        self.assertEqual(result.status, 'NOT_FOUND')
        self.assertIn('RuntimeError', result.detail)
        self.assertIn('native backend failure', result.detail)

    def test_schema_favicon_does_not_beat_full_header_logo(self):
        fetcher = MagicMock()
        fetcher.get.side_effect = [(b'page', 'https://brand.example/'),
                                   (png(), 'https://brand.example/favicon.ico'),
                                   (png(), 'https://brand.example/full.png')]
        with patch('tag_logo_bank.logos.candidates', return_value=[
                ('https://brand.example/favicon.ico', 'organization_schema'),
                ('https://brand.example/full.png', 'logo_image')]):
            result = find_logo('https://brand.example/', fetcher)
        self.assertEqual(result.source, 'https://brand.example/full.png')

    def test_verified_local_png_never_fetches_blocked_site(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'verified.png'
            path.write_bytes(png())
            fetcher = MagicMock()
            unapproved = find_logo('https://www.adobe.com/', fetcher, path)
            self.assertEqual(unapproved.status, 'MANUAL_REVIEW')
            result = find_logo('https://www.adobe.com/', fetcher, path, approval=approval(path.read_bytes()))
            self.assertEqual(result.status, 'MANUAL_APPROVED')
            self.assertEqual(result.page, 'https://brand.example/official')
            self.assertEqual(result.source, str(path))
            self.assertIn('Test Reviewer', result.detail)
            self.assertIn('2026-11-05', result.detail)
            self.assertEqual(len(result.sha256), 64)
            fetcher.get.assert_not_called()

    def test_invalid_manual_approval_never_falls_back(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'verified.png'
            path.write_bytes(png())
            valid = approval(path.read_bytes())
            for invalid in ({}, {'approved': True}, {**valid, 'sha256': '0' * 64},
                            {**valid, 'reviewed_by': ''}, {**valid, 'reviewed_on': 'yesterday'},
                            {**valid, 'source_url': 'file:///tmp/logo'},
                            {**valid, 'source_url': 'https://user:secret@brand.example/logo'}):
                fetcher = MagicMock()
                result = find_logo('https://www.adobe.com/', fetcher, path, approval=invalid)
                self.assertEqual(result.status, 'ERROR')
                self.assertFalse(result.png)
                fetcher.get.assert_not_called()
            result = find_logo('https://www.adobe.com/', MagicMock(), approval=valid)
            self.assertEqual(result.status, 'ERROR')
            # Original-file hash changes require a fresh review, even if pixels match.
            path.write_bytes(path.read_bytes() + b'changed')
            self.assertEqual(find_logo('', local=path, approval=valid).status, 'ERROR')
            # Human approval never disables technical SVG safety validation.
            path.write_bytes(b'<svg><script>alert(1)</script></svg>')
            unsafe = find_logo('', local=path, approval=approval(path.read_bytes()))
            self.assertEqual(unsafe.status, 'ERROR')
            self.assertFalse(unsafe.png)

    def test_http_403_gives_manual_instructions_without_retry_or_bypass(self):
        fetcher = MagicMock()
        response = requests.Response()
        response.status_code = 403
        fetcher.get.side_effect = requests.HTTPError('403 Forbidden', response=response)
        result = find_logo('https://www.adobe.com/', fetcher)
        self.assertEqual(result.status, 'ERROR')
        self.assertIn('no bypass attempted', result.detail)
        self.assertIn('--overrides', result.detail)
        self.assertIn('logo_path', result.detail)
        fetcher.get.assert_called_once_with('https://www.adobe.com/')

    @unittest.skipUnless(importlib.util.find_spec('bs4'), 'BeautifulSoup is not installed')
    def test_parent_branding_finds_full_logo_before_favicon(self):
        html = b'''<header><a id="uhfLogo" href="/"><img alt="" src="/assets/ms.png"></a>
        <a href="/"><img alt="Microsoft" src="/assets/ms-full.png"></a>
        <a href="/"><img alt="Search" src="/search.png"></a></header>
        <link rel="icon" href="/favicon.ico">'''
        found = candidates(html, 'https://www.microsoft.com/')
        self.assertIn(('https://www.microsoft.com/assets/ms.png', 'logo_image'), found)
        self.assertIn(('https://www.microsoft.com/assets/ms-full.png', 'logo_image'), found)
        self.assertFalse(any(url.endswith('/search.png') for url, _ in found))
        fetcher = MagicMock()
        def get(url):
            return (html if url.endswith('.com/') else png()), url
        fetcher.get.side_effect = get
        result = find_logo('https://www.microsoft.com/', fetcher)
        self.assertNotIn('favicon', result.source)

    def test_approval_metadata_round_trips_and_invalid_company_does_not_stop_others(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            image = directory / 'verified.png'
            image.write_bytes(png())
            source, output = directory / 'in.xlsx', directory / 'out.xlsx'
            wb = Workbook()
            ws = wb.active
            ws.title = 'Transactions'
            ws.append(['Company', 'Website'])
            ws.append(['Adobe', 'https://www.adobe.com/'])
            ws.append(['Other', ''])
            wb.save(source)
            fetcher = MagicMock()
            counts = build_logo_bank(source, output, fetcher=fetcher, overrides={
                'Adobe': {'logo_path': str(image), 'approval': approval(image.read_bytes())},
                'Other': {'logo_path': str(image), 'approval': {}}})
            self.assertEqual(counts, {'MANUAL_APPROVED': 1, 'ERROR': 1})
            result = load_workbook(output)
            ws = result['Logos']
            self.assertEqual(ws['D2'].value, 'MANUAL_APPROVED')
            self.assertEqual(ws['F2'].value, 'https://brand.example/official')
            self.assertIn('Test Reviewer', ws['J2'].value)
            self.assertEqual(ws['D3'].value, 'ERROR')
            self.assertEqual(len(ws._images), 1)
            result.close()
            fetcher.get.assert_not_called()

    def test_cli_windows_bom_and_relative_override_path(self):
        from tag_logo_bank.cli import main
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            image = directory / 'official verified.png'
            image.write_bytes(png())
            config = directory / 'overrides.json'
            config.write_text(json.dumps({'Adobe': {'logo_path': image.name,
                                                   'approval': approval(image.read_bytes())}}), encoding='utf-8-sig')
            with patch.object(sys, 'argv', ['tag-logos', 'in.xlsx', 'out.xlsx', '--overrides', str(config)]), \
                 patch('tag_logo_bank.cli.build_logo_bank', return_value={}) as build:
                self.assertEqual(main(), 0)
                override = build.call_args.kwargs['overrides']['Adobe']
                self.assertEqual(Path(override['logo_path']), image.resolve())
                self.assertEqual(override['approval']['reviewed_by'], 'Test Reviewer')

    @unittest.skipUnless(importlib.util.find_spec('cairosvg'), 'CairoSVG is not installed')
    def test_real_cairo_renders_sanitized_export(self):
        result = rasterize_svg(EXPORT)
        with Image.open(BytesIO(result)) as image:
            self.assertEqual(image.size, (1200, 600))
            self.assertGreater(image.getpixel((100, 100))[3], 0)


if __name__ == '__main__':
    unittest.main()
