"""Official-page discovery; conservative identity checks, never search-engine images."""
from dataclasses import dataclass
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from PIL import Image
from urllib.parse import urljoin, urlsplit

from .api import normalized_name
from .logos import Logo, verify_image, website_domain
from .network import RateLimited


def identity(company, label, aliases=()):
    label = normalized_name(label)
    return any(re.search(r'(?<!\w)' + re.escape(normalized_name(n)) + r'(?!\w)', label)
               for n in [company, *aliases] if normalized_name(n))


@dataclass
class Candidate:
    value: str
    method: str
    rank: int


def discover(html, page, company, aliases=()):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    candidates, evidence, brands = [], [], []
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    site_name = soup.find('meta', property='og:site_name')
    if site_name:
        evidence.append(site_name.get('content', ''))
        brands.append(site_name.get('content', ''))
    evidence.append(title)

    def add(value, method, rank):
        if isinstance(value, dict):
            value = value.get('contentUrl') or value.get('url')
        if isinstance(value, str) and value.strip():
            url = urljoin(page, value.strip())
            if urlsplit(url).scheme in ('http', 'https'):
                candidates.append(Candidate(url, method, rank))

    def walk(obj):
        if isinstance(obj, list):
            for value in obj:
                walk(value)
        elif isinstance(obj, dict):
            types = obj.get('@type', [])
            if isinstance(types, str):
                types = [types]
            if any(t in ('Organization', 'Corporation', 'InsuranceAgency', 'BankOrCreditUnion', 'LocalBusiness') for t in types):
                name = obj.get('name', '')
                if isinstance(name, str):
                    evidence.append(name)
                    brands.append(name)
                    if identity(company, name, aliases):
                        add(obj.get('logo'), 'organization_schema', 100)
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    walk(value)

    for script in soup.find_all('script', type='application/ld+json'):
        try:
            walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            pass
    # Page brand, not body text about an acquisition, must match the target.
    page_matches = (all(identity(company, value, aliases) for value in brands if value) if any(brands)
                    else identity(company, title, aliases) and not re.search(
                        r'acquir|merger|merges|joins|now part|welcomes', title, re.I))
    for img in soup.find_all('img'):
        parent = img.find_parent('a')
        label = ' '.join(str(node.get(key, '')) for node in (img, parent or img.parent)
                         for key in ('alt', 'aria-label', 'title', 'class', 'id'))
        location = ' '.join(str(img.get(k, '')) for k in ('src', 'data-src', 'data-lazy-src'))
        context = ' '.join(str(p.get('class', '')) for p in list(img.parents)[:3])
        if re.search(r'partner|sponsor|client-logos|carrier-logos', context, re.I):
            continue
        logo_hint = 'logo' in (label + location).lower()
        # Never treat the old domain name in an absolute image URL as evidence
        # that a renamed/acquired company's current header is the historical mark.
        filenames = ' '.join(urlsplit(img.get(k, '')).path.rsplit('/', 1)[-1]
                             for k in ('src', 'data-src', 'data-lazy-src'))
        display_label = ' '.join(str(img.get(k, '')) for k in ('alt', 'title', 'aria-label'))
        alt = img.get('alt', '').strip()
        generic = not normalized_name(img.get('alt', '')) or normalized_name(img.get('alt', '')) in {'logo', 'home', 'company logo'}
        # Export labels may be "HUB Logo_H_Full Color_RGB". The prefix can
        # corroborate an abbreviation only when the full page brand matches.
        short_brand = re.split(r'\b(?:logo|home)\b', normalized_name(img.get('alt', '')), maxsplit=1)[0].strip()
        partial = bool(short_brand) and short_brand in normalized_name(company).split()
        if not generic and not identity(company, display_label, aliases) and not (page_matches and partial):
            continue
        name_matches = identity(company, display_label, aliases) or (page_matches and identity(company, filenames, aliases))
        if not (name_matches or (page_matches and logo_hint and (generic or partial))):
            continue
        if not logo_hint and not (name_matches and img.find_parent(['header', 'nav'])):
            continue
        rank = 90 if img.find_parent(['header', 'nav']) or 'logo' in label.lower() else 75
        for attr in ('src', 'data-src', 'data-lazy-src'):
            add(img.get(attr), 'header_logo' if rank == 90 else 'official_logo_asset', rank)
        for node in [img] + (list(img.parent.find_all('source')) if img.parent.name == 'picture' else []):
            for attr in ('srcset', 'data-srcset'):
                for item in node.get(attr, '').split(','):
                    if item.strip():
                        add(item.strip().split()[0], 'responsive_logo', rank)
    if page_matches:
        for meta in soup.find_all('meta', property='og:image'):
            value = meta.get('content', '')
            # A generic social photo is not a company logo.
            if re.search(r'logo|brand', value, re.I):
                add(value, 'open_graph_logo_review', 40)
        for link in soup.find_all('link', rel='image_src'):
            if 'logo' in link.get('href', '').lower():
                add(link.get('href'), 'official_image_link', 50)
        for svg in soup.find_all('svg'):
            label = ' '.join(str(svg.get(k, '')) for k in ('aria-label', 'class', 'id'))
            if 'logo' in label.lower() and svg.find_parent(['header', 'nav']):
                tags = {n.lower(): n for n in ('linearGradient', 'radialGradient', 'clipPath')}
                attrs = {n.lower(): n for n in ('viewBox', 'preserveAspectRatio', 'gradientTransform',
                         'gradientUnits', 'spreadMethod', 'clipPathUnits', 'maskUnits', 'maskContentUnits')}
                for node in [svg] + list(svg.find_all(True)):
                    node.name = tags.get(node.name, node.name)
                    for key in list(node.attrs):
                        if key in attrs:
                            node[attrs[key]] = node.attrs.pop(key)
                candidates.append(Candidate(str(svg), 'inline_svg', 85))
    unique = {}
    for candidate in sorted(candidates, key=lambda c: -c.rank):
        unique.setdefault(candidate.value, candidate)
    if not unique:
        hints = [{'alt': str(i.get('alt', ''))[:100], 'class': str(i.get('class', ''))[:100],
                  'src': str(i.get('src') or i.get('data-src') or '')[:250],
                  'parent': str(i.parent.attrs)[:200]} for i in soup.find_all('img')[:8]]
        evidence.append('No accepted candidate; image hints=' + json.dumps(hints))
    return list(unique.values())[:16], '; '.join(evidence)[:3500]


def image_bytes(data):
    if data.lstrip().startswith((b'<', b'\xef\xbb\xbf')):
        from .svg import sanitize_svg
        sanitized, notes = sanitize_svg(data)
        root = ET.fromstring(sanitized)
        view = root.get('viewBox', '').replace(',', ' ').split()
        width, height = (map(float, view[2:]) if len(view) == 4 else
                         (float(root.get('width', '300').removesuffix('px')), float(root.get('height', '150').removesuffix('px'))))
        if not all(math.isfinite(v) and v > 0 for v in (width, height)):
            raise ValueError('Invalid SVG dimensions')
        scale = min(1200 / width, 600 / height)
        if min(width * scale, height * scale) < 1:
            raise ValueError('SVG aspect ratio too extreme')
        try:
            import resvg_py
        except ImportError as error:
            raise ValueError('Optional SVG support unavailable; pip install --only-binary=resvg_py resvg_py (no Cairo/GTK)') from error
        try:
            data = resvg_py.svg_to_bytes(svg_string=sanitized.decode(), width=round(width * scale),
                                       height=round(height * scale), skip_system_fonts=True)
        except Exception as error:
            raise ValueError(f'SVG rendering failed: {type(error).__name__}: {error}') from error
        note = 'SVG safely converted by packaged resvg wheel; ' + '; '.join(notes)
    else:
        note = 'Raster PNG/JPEG/WebP validated'
    png, width, height = verify_image(data)
    return png, width, height, note


def official_logo(company, website, http, aliases=()):
    domain = website_domain(website)
    response = http.get(website, allowed_hosts={domain})
    candidates, evidence = discover(response.data, response.url, company, aliases)
    if not candidates:
        return Logo(status='MATCH_UNCERTAIN', page=response.url,
                    detail=f'No identity-supported official logo candidates. Page brand evidence: {evidence}')
    errors = []
    for candidate in candidates:
        try:
            if candidate.method == 'inline_svg':
                data, source = candidate.value.encode(), response.url + '#inline-logo'
            else:
                asset = http.get(candidate.value)  # Only assets referenced on the identity-checked page.
                data, source = asset.data, asset.url
            png, width, height, note = image_bytes(data)
            return Logo(png, source, response.url, 'REVIEW_REQUIRED',
                        f'{note}; company={company}; page brand={evidence}; identity/brand/date require review; '
                        + ('verified aliases=' + repr(list(aliases)) + '; ' if aliases else '') + '; '.join(errors),
                        width, height, hashlib.sha256(png).hexdigest(), png, domain, candidate.method)
        except RateLimited:
            raise
        except (OSError, ValueError, ET.ParseError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            errors.append(f'{candidate.method} {candidate.value[:250]}: {type(error).__name__}: {error}')
    return Logo(status='NOT_FOUND', page=response.url, detail='; '.join(errors))
