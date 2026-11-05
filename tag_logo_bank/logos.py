"""Discover current official-site assets and validate raster images."""
from dataclasses import dataclass
from datetime import date
from io import BytesIO
import hashlib
import ipaddress
import json
import socket
import warnings
import re
import math
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

from PIL import Image, ImageStat
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

MAX_BYTES = 8 * 1024 * 1024


def public_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Expected a public HTTP(S) URL without credentials')
    if parts.port not in (None, 80, 443):
        raise ValueError('Only standard web ports are supported')
    addresses = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Private or nonpublic network addresses are not allowed')
    return url


def normalize_site(value):
    value = str(value).strip()
    if '://' not in value:
        value = 'https://' + value
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise ValueError('Invalid website')
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.casefold().startswith('utm_') and k.casefold() not in
             {'gclid', 'fbclid', 'msclkid', 'dclid', 'mc_cid', 'mc_eid'}]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'TAGLogoBank/1.0', 'Cache-Control': 'no-cache'})
        retries = Retry(total=2, backoff_factor=.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        self.session.mount('http://', HTTPAdapter(max_retries=retries))

    def get(self, url):
        for _ in range(6):
            public_url(url)
            with self.session.get(url, timeout=(5, 20), stream=True, allow_redirects=False) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers['Location'])
                    continue
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ValueError('Download exceeds 8 MB')
                return bytes(data), url
        raise ValueError('Too many redirects')


def candidates(html, base):
    """Rank explicit organization logos before header images and site icons."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    found = []
    def label(node):
        if node is None:
            return ''
        return ' '.join(str(node.get(k, '')) for k in
                        ('alt', 'aria-label', 'title', 'class', 'id', 'src', 'data-src')).lower()

    def branded(node):
        # Logos often have empty alt text; their containing link carries branding.
        parent = node.find_parent('a')
        context = ' '.join((label(node), label(node.parent), label(parent)))
        if 'logo' in context:
            return True
        if parent and node.find_parent(['header', 'nav']):
            target, official = urlsplit(urljoin(base, parent.get('href', ''))), urlsplit(base)
            home = (target.netloc.casefold() == official.netloc.casefold() and
                    target.path.rstrip('/') == '')
            title = (node.get('alt') or parent.get('aria-label') or '').strip()
            return home and bool(title) and not re.search(r'\b(search|menu|cart|account|sign in)\b', title, re.I)
        return False
    def add(value, rank, kind):
        if isinstance(value, dict):
            value = value.get('contentUrl') or value.get('url')
        if isinstance(value, str) and value.strip():
            target = urljoin(base, value.strip())
            if urlsplit(target).scheme in ('http', 'https'):
                found.append((rank, target, kind))
    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            types = obj.get('@type', [])
            if isinstance(types, str):
                types = [types]
            if any(t in ('Organization', 'Corporation', 'LocalBusiness') for t in types):
                add(obj.get('logo'), 100, 'organization_schema')
            for value in obj.values():
                if isinstance(value, (list, dict)):
                    walk(value)
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            pass
    for img in soup.find_all('img'):
        if branded(img):
            rank = 90 if img.find_parent(['header', 'nav']) else 80
            for attr in ('src', 'data-src', 'data-lazy-src'):
                add(img.get(attr), rank, 'logo_image')
            for node in [img] + (list(img.parent.find_all('source')) if img.parent.name == 'picture' else []):
                for attr in ('srcset', 'data-srcset'):
                    for item in node.get(attr, '').split(','):
                        if item.strip():
                            add(item.strip().split()[0], rank, 'logo_image')
    # Inline vectors in a branded header/nav often have no raster counterpart.
    for svg in soup.find_all('svg'):
        if (branded(svg) or 'logo' in svg.get_text(' ', strip=True).lower()) and svg.find_parent(['header', 'nav']):
            # HTML parsers lowercase SVG names; restore known case-sensitive XML
            # names without relaxing the downstream sanitizer's allowlist.
            tags = {name.lower(): name for name in ('linearGradient', 'radialGradient', 'clipPath')}
            attrs = {name.lower(): name for name in ('viewBox', 'preserveAspectRatio',
                     'gradientTransform', 'gradientUnits', 'spreadMethod',
                     'clipPathUnits', 'maskUnits', 'maskContentUnits')}
            for node in [svg] + list(svg.find_all(True)):
                node.name = tags.get(node.name, node.name)
                for key in list(node.attrs):
                    if key in attrs:
                        node[attrs[key]] = node.attrs.pop(key)
            found.append((90, str(svg), 'inline_svg'))
    for obj in soup.find_all('object', type='image/svg+xml'):
        if branded(obj):
            add(obj.get('data'), 85, 'logo_image')
    for link in soup.find_all('link'):
        if any('icon' in rel.lower() for rel in link.get('rel', [])):
            add(link.get('href'), 20, 'icon_review')
    unique = {}
    for rank, url, kind in sorted(found, reverse=True):
        unique.setdefault(url, (url, kind))
    return list(unique.values())[:25]


def rasterize_svg(data, notes=None):
    """Render only self-contained SVGs; never resolve external resources."""
    from .svg import sanitize_svg
    sanitized, audit = sanitize_svg(data)
    root = ET.fromstring(sanitized)
    if notes is not None:
        notes.extend(['self-contained SVG sanitized'] + audit)
    viewbox = root.get('viewBox', '').replace(',', ' ').split()
    try:
        width, height = (map(float, viewbox[2:]) if len(viewbox) == 4 else
                         (float(root.get('width', '300').removesuffix('px')),
                          float(root.get('height', '150').removesuffix('px'))))
    except ValueError as error:
        raise ValueError('SVG needs numeric dimensions or viewBox') from error
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError('Invalid SVG dimensions')
    ratio = min(1200 / width, 600 / height)
    if min(width * ratio, height * ratio) < 1:
        raise ValueError('SVG aspect ratio is too extreme')
    try:
        from cairosvg.surface import PNGSurface
    except (ImportError, OSError) as error:
        raise ValueError('SVG conversion unavailable: install the svg extra and Cairo runtime') from error
    def deny_resource(*args, **kwargs):
        raise ValueError('SVG resource loading is forbidden')
    try:
        return PNGSurface.convert(bytestring=sanitized, output_width=round(width * ratio),
                                  output_height=round(height * ratio), url_fetcher=deny_resource)
    except Exception as error:
        # Cairo backends raise platform-specific exception types. Record them as a
        # candidate failure rather than aborting the remaining companies.
        raise ValueError(f'SVG conversion failed ({type(error).__name__}): {error}') from error


def verify_image(data, *, notes=None):
    if len(data) > MAX_BYTES:
        raise ValueError('Image exceeds 8 MB')
    if data.lstrip().startswith((b'<', b'\xef\xbb\xbf')):
        data = rasterize_svg(data, notes=notes)
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as original:
            if original.width * original.height > 16_000_000:
                raise ValueError('Image exceeds 16 megapixels')
            original.verify()
        with Image.open(BytesIO(data)) as original:
            original.seek(0)
            image = original.convert('RGBA')
    width, height = image.size
    if min(width, height) < 24 or max(width, height) < 64:
        raise ValueError('Image is too small')
    background = Image.new('RGBA', image.size, 'white')
    background.alpha_composite(image)
    if max(ImageStat.Stat(background.convert('RGB')).stddev) < 1:
        raise ValueError('Blank or invisible image')
    image.thumbnail((600, 300), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue(), width, height


@dataclass
class Logo:
    png: bytes | None = None
    source: str = ''
    page: str = ''
    status: str = 'NEEDS_WEBSITE'
    detail: str = ''
    width: int = 0
    height: int = 0
    sha256: str = ''


def manual_approval(data, approval):
    """A human attestation bound to the original file, not automatic brand approval."""
    raw_sha = hashlib.sha256(data).hexdigest()
    if approval is None:
        return ('MANUAL_REVIEW', 'User-supplied asset; confirm brand approval; '
                f'original file SHA256={raw_sha}', '')
    required = {'sha256', 'reviewed_by', 'reviewed_on', 'source_url'}
    if not isinstance(approval, dict) or set(approval) != required or any(
            not isinstance(approval[k], str) or not approval[k].strip() for k in required):
        raise ValueError('approval requires exactly sha256, reviewed_by, reviewed_on and source_url strings')
    if not re.fullmatch(r'[0-9a-fA-F]{64}', approval['sha256']) or approval['sha256'].lower() != raw_sha:
        raise ValueError('Manual approval SHA256 does not match the original logo file; review it again')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', approval['reviewed_on']):
        raise ValueError('reviewed_on must be YYYY-MM-DD')
    date.fromisoformat(approval['reviewed_on'])
    if urlsplit(approval['source_url']).scheme not in ('http', 'https'):
        raise ValueError('Manual source_url requires an explicit HTTP(S) URL')
    source = normalize_site(approval['source_url'])
    parts = urlsplit(source)
    if parts.username or parts.password or parts.port not in (None, 80, 443):
        raise ValueError('Manual source URL must be HTTP(S), without credentials or nonstandard ports')
    return ('MANUAL_APPROVED', f'Human-verified official asset; reviewer={approval["reviewed_by"]}; '
            f'reviewed_on={approval["reviewed_on"]}; original file SHA256={raw_sha}; '
            'approval is a user attestation, not independent brand verification', source)


def find_logo(website, fetcher=None, local=None, *, approval=None):
    if local:
        try:
            data = local.read_bytes()
            if len(data) > MAX_BYTES:
                raise ValueError('Local image exceeds 8 MB')
            audit = []
            png, width, height = verify_image(data, notes=audit)
            status, detail, page = manual_approval(data, approval)
            if audit:
                detail += '; ' + '; '.join(audit)
            return Logo(png, str(local), page, status, detail, width, height, hashlib.sha256(png).hexdigest())
        except (OSError, ValueError, ET.ParseError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            return Logo(status='ERROR', detail=f'local asset {local}: {type(error).__name__}: {error}')
    if approval is not None:
        return Logo(status='ERROR', detail='Manual approval requires a local logo_path; no website retrieval attempted')
    if not website:
        return Logo(detail='Supply an official website or local logo override')
    fetcher = fetcher or Fetcher()
    errors = []
    stage = 'website fetch'
    try:
        html, page = fetcher.get(normalize_site(website))
        stage = 'candidate discovery'
        best = None
        best_score = (-1, -1)
        for url, kind in candidates(html, page):
            try:
                if kind == 'inline_svg':
                    data, source = url.encode(), page + '#inline-logo'
                else:
                    data, source = fetcher.get(url)
                audit = []
                png, width, height = verify_image(data, notes=audit)
                path = urlsplit(source).path.lower()
                favicon = (kind == 'icon_review' or path.endswith('.ico') or
                           'favicon' in path or 'apple-touch-icon' in path)
                score = (0 if favicon else 2 if kind == 'organization_schema' else 1,
                         width * height)
                if score > best_score:
                    best_score = score
                    best = Logo(png, source, page, 'REVIEW_REQUIRED', f'{kind}; image validated; identity and latest brand version need review' + ('; ' + '; '.join(audit) if audit else ''), width, height, hashlib.sha256(png).hexdigest())
            except (requests.RequestException, OSError, ValueError, ET.ParseError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
                target = page + '#inline-logo' if kind == 'inline_svg' else url
                errors.append(f'candidate {target}: {type(error).__name__}: {error}')
        if best:
            if best_score[0] == 0:
                best.detail += '; favicon fallback only; supply a verified full logo via logo_path if unsuitable'
            if errors:
                best.detail += '; rejected candidates: ' + '; '.join(errors)
            return best
        return Logo(page=page, status='NOT_FOUND', detail='; '.join(errors) or 'No supported logo candidates on official page')
    except (requests.RequestException, OSError, ValueError) as error:
        detail = f'{stage} {website}: {type(error).__name__}: {error}'
        if isinstance(error, requests.HTTPError) and getattr(error.response, 'status_code', None) == 403:
            detail += ('; website blocks automated access (HTTP 403); no bypass attempted. '
                       'Supply a verified official PNG with --overrides and logo_path; '
                       'see README manual logo approval instructions')
        return Logo(status='ERROR', detail=detail)

