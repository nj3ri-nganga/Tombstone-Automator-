"""Discover current official-site assets and validate raster images."""
from dataclasses import dataclass
from io import BytesIO
import hashlib
import ipaddress
import json
import socket
import warnings
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
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
    return value


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
    soup = BeautifulSoup(html, 'html.parser')
    found = []
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
        label = ' '.join([str(img.get(k, '')) for k in ('alt', 'class', 'id', 'src')]).lower()
        if 'logo' in label:
            add(img.get('src') or img.get('data-src'), 90 if img.find_parent(['header', 'nav']) else 80, 'logo_image')
    for link in soup.find_all('link'):
        if any('icon' in rel.lower() for rel in link.get('rel', [])):
            add(link.get('href'), 20, 'icon_review')
    unique = {}
    for rank, url, kind in sorted(found, reverse=True):
        unique.setdefault(url, (url, kind))
    return list(unique.values())[:25]


def verify_image(data):
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


def find_logo(website, fetcher=None, local=None):
    if local:
        try:
            data = local.read_bytes()
            if len(data) > MAX_BYTES:
                raise ValueError('Local image exceeds 8 MB')
            png, width, height = verify_image(data)
            return Logo(png, str(local), '', 'MANUAL_REVIEW', 'User-supplied asset; confirm brand approval', width, height, hashlib.sha256(png).hexdigest())
        except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            return Logo(status='ERROR', detail=str(error))
    if not website:
        return Logo(detail='Supply an official website or local logo override')
    fetcher = fetcher or Fetcher()
    errors = []
    try:
        html, page = fetcher.get(normalize_site(website))
        for url, kind in candidates(html, page):
            try:
                data, source = fetcher.get(url)
                png, width, height = verify_image(data)
                return Logo(png, source, page, 'REVIEW_REQUIRED', f'{kind}; image validated; identity and latest brand version need review', width, height, hashlib.sha256(png).hexdigest())
            except (requests.RequestException, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
                errors.append(f'{url}: {error}')
        return Logo(page=page, status='NOT_FOUND', detail='; '.join(errors) or 'No supported logo candidates on official page')
    except (requests.RequestException, OSError, ValueError) as error:
        return Logo(status='ERROR', detail=str(error))
