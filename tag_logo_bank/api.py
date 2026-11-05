"""LogoAPI.sh catalog matching and PNG downloads. No target-website requests."""
import hashlib
import ipaddress
import json
import re
import socket
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin, urlsplit

import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .logos import Logo, MAX_BYTES, verify_image, website_domain

BASE = 'https://logoapi.sh'


@dataclass
class Download:
    data: bytes
    url: str
    headers: dict


class Transport:
    """Only the fixed HTTPS API origin, including on every redirect."""
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'TAGLogoBank/2.0'})
        retries = Retry(total=2, backoff_factor=.5, status_forcelist=[500, 502, 503, 504],
                        respect_retry_after_header=False)
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    def get(self, url):
        for _ in range(6):
            parts = urlsplit(url)
            if (parts.scheme != 'https' or parts.hostname != 'logoapi.sh' or
                    parts.username or parts.password or parts.port not in (None, 443)):
                raise ValueError('Only HTTPS requests to logoapi.sh are allowed')
            addresses = socket.getaddrinfo('logoapi.sh', 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise ValueError('API resolved to a nonpublic network address')
            with self.session.get(url, timeout=(5, 20), stream=True, allow_redirects=False) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers['Location'])
                    continue
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ValueError('API response exceeds 8 MB')
                return Download(bytes(data), url, dict(response.headers))
        raise ValueError('Too many API redirects')


def normalized_name(value):
    words = re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', value).casefold())
    # Only legal suffixes, not brands, divisions, "Group" or "Holdings".
    while words and words[-1] in {'inc', 'incorporated', 'corp', 'corporation',
                                 'ltd', 'limited', 'llc', 'plc'}:
        words.pop()
    return ' '.join(words)


def header(response, name):
    return next((str(v) for k, v in response.headers.items() if k.lower() == name.lower()), '')


class LogoAPI:
    def __init__(self, transport=None):
        self.transport = transport or Transport()

    def lookup(self, company, website=''):
        stage = 'identity lookup'
        try:
            requested = website_domain(website) if website else ''
            query = requested or str(company).strip()
            if not 2 <= len(query) <= 80 or not normalized_name(company):
                return Logo(status='MATCH_UNCERTAIN', detail='Supply a company name (2–80 characters for name search) and a verified website')
            response = self.transport.get(BASE + '/search?' + urlencode({'q': query}))
            payload = json.loads(response.data)
            if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
                raise ValueError('Invalid LogoAPI search response')
            results = payload['results']
            if len(results) > 8:
                raise ValueError('LogoAPI returned more results than its documented search limit')
            if not results:
                return Logo(status='NOT_FOUND', detail=f'LogoAPI has no catalog match for {query}; no placeholder inserted')
            matches = {}
            for item in results:
                if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ('name', 'domain', 'source')):
                    continue
                if any(re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', item[k]) for k in ('name', 'domain', 'source')):
                    continue
                if item.get('fuzzy', False) is not False:
                    continue
                try:
                    domain = website_domain(item['domain'])
                    # Source provenance must corroborate the same company domain.
                    if website_domain(item['source']) != domain:
                        continue
                except ValueError:
                    continue
                if requested and domain != requested:
                    continue  # Never substitute an alias, acquirer or parent domain.
                if normalized_name(item['name']) != normalized_name(company):
                    continue
                matches[domain] = item
            if len(matches) != 1:
                return Logo(status='MATCH_UNCERTAIN', detail=(f'LogoAPI identity is uncertain for {company!r} ({query}); '
                            'need one exact, non-fuzzy name/domain/source match. Supply or correct the verified Website; no logo inserted'))
            domain, match = next(iter(matches.items()))
            stage = 'PNG download'
            url = BASE + '/' + domain + '.png?' + urlencode({'size': 1024, 'fallback': '404'})
            response = self.transport.get(url)
            if header(response, 'X-Logo-Fallback').strip():
                return Logo(status='NOT_FOUND', detail='LogoAPI returned a fallback image; rejected to avoid placeholders or favicons')
            kind = header(response, 'X-Logo-Kind').strip().lower()
            if kind and kind not in {'wordmark', 'icon', 'raster'}:
                return Logo(status='NOT_FOUND', detail=f'LogoAPI returned an unsupported logo kind ({kind}); no image inserted')
            if (header(response, 'Content-Type').split(';')[0].strip().lower() != 'image/png' or
                    not response.data.startswith(b'\x89PNG\r\n\x1a\n')):
                raise ValueError('LogoAPI did not return a PNG; no SVG conversion or fallback attempted')
            png, width, height = verify_image(response.data)
            method = 'website domain' if requested else 'unique exact name search'
            return Logo(png, response.url, 'https://' + domain, 'REVIEW_REQUIRED',
                        f'LogoAPI catalog: {match["name"]}; matched by {method}; '
                        'name, domain and source metadata agree; brand/legal-entity approval remains a human decision',
                        width, height, hashlib.sha256(png).hexdigest(), response.data, domain)
        except requests.HTTPError as error:
            code = getattr(error.response, 'status_code', None)
            status = 'NOT_FOUND' if code == 404 else 'RATE_LIMITED' if code == 429 else 'ERROR'
            advice = 'Rate limited; retry later.' if code == 429 else 'No website scraping or fallback attempted.'
            return Logo(status=status, detail=f'LogoAPI {stage}: HTTP {code}; {advice}')
        except (requests.RequestException, OSError, ValueError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as error:
            if hasattr(error, 'retry_at'):
                return Logo(status='RATE_LIMITED', retry_at=error.retry_at, detail=str(error))
            return Logo(status='ERROR', detail=f'LogoAPI {stage}: {type(error).__name__}: {error}')
