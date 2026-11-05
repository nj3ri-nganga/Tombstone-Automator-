"""Result model, website normalization and bounded raster validation.

Online retrieval uses LogoAPI.sh PNGs. There is no website scraping or SVG renderer.
"""
from dataclasses import dataclass
from datetime import date
from io import BytesIO
import hashlib
import ipaddress
import re
import warnings
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from PIL import Image, ImageStat

MAX_BYTES = 8 * 1024 * 1024


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


def website_domain(value):
    """Use the supplied hostname; never guess a registrable domain or acquirer."""
    parts = urlsplit(normalize_site(value))
    if parts.username or parts.password or parts.port not in (None, 80, 443):
        raise ValueError('Website must have no credentials and use a standard web port')
    host = parts.hostname.rstrip('.').encode('idna').decode('ascii').lower()
    if host.startswith('www.'):
        host = host[4:]
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('Website must be a company domain, not an IP address')
    if (len(host) > 253 or '.' not in host or
            any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                for label in host.split('.')) or
            host.endswith(('.localhost', '.local', '.internal', '.test', '.invalid', '.example'))):
        raise ValueError('Invalid or nonpublic company domain')
    return host


def verify_image(data):
    if len(data) > MAX_BYTES:
        raise ValueError('Image exceeds 8 MB')
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
    # A white logo on transparency is valid too: reject uniform/invisible pixels,
    # not merely an image that disappears on a particular background color.
    visible = image.getbbox()
    if not visible:
        raise ValueError('Blank or invisible image')
    on_white = Image.new('RGBA', image.size, 'white')
    on_white.alpha_composite(image)
    on_black = Image.new('RGBA', image.size, 'black')
    on_black.alpha_composite(image)
    if max(ImageStat.Stat(on_white.convert('RGB')).stddev +
           ImageStat.Stat(on_black.convert('RGB')).stddev) < 1:
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
    downloaded_png: bytes | None = None
    domain: str = ''
    method: str = ''
    retry_at: float = 0


def manual_approval(data, approval):
    """Optional, backwards-compatible human approval of an exact local file."""
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
    website_domain(source)  # Validate syntax only; never fetch a manual source.
    return ('MANUAL_APPROVED', f'Human-verified official asset; reviewer={approval["reviewed_by"]}; '
            f'reviewed_on={approval["reviewed_on"]}; original file SHA256={raw_sha}; '
            'approval is a user attestation, not independent brand verification', source)


def find_logo(website='', fetcher=None, local=None, *, company='', approval=None):
    """A local raster override wins; otherwise use the company-logo API only."""
    if local:
        try:
            data = local.read_bytes()
            if data.lstrip().startswith((b'<', b'\xef\xbb\xbf')):
                raise ValueError('Use a PNG/JPEG/WebP raster logo; SVG conversion is no longer required or supported')
            png, width, height = verify_image(data)
            status, detail, page = manual_approval(data, approval)
            return Logo(png, str(local), page, status, detail, width, height,
                        hashlib.sha256(png).hexdigest(), png)
        except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            return Logo(status='ERROR', detail=f'local asset {local}: {type(error).__name__}: {error}')
    if approval is not None:
        return Logo(status='ERROR', detail='Manual approval requires a local logo_path; no API request attempted')
    if fetcher is None:
        from .hybrid import Hybrid
        fetcher = Hybrid()
        try:
            return fetcher.lookup(company, website)
        finally:
            fetcher.close()
    return fetcher.lookup(company, website)
