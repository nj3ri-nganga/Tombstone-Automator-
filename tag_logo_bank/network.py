"""Bounded public HTTP with persistent response caching and resumable throttling."""
from email.utils import parsedate_to_datetime
import ipaddress
import json
from pathlib import Path
import socket
import sqlite3
import time
import math
from urllib.parse import urljoin, urlsplit

import requests
from .api import Download
from .logos import MAX_BYTES, website_domain


class RateLimited(ValueError):
    def __init__(self, host, retry_at):
        self.retry_at = retry_at
        super().__init__(f'{host}: HTTP 429; resume after {retry_at:.0f} (UTC epoch)')


class IdentityRedirect(ValueError):
    pass


def public_url(url):
    parts = urlsplit(url)
    website_domain(url)
    addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Nonpublic network destination is forbidden')
    return parts


class HTTP:
    def __init__(self, cache_dir, *, clock=time.time, sleep=time.sleep, max_wait=2, refresh=False):
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(Path(cache_dir) / 'cache.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS responses (url TEXT PRIMARY KEY, body BLOB, final TEXT, headers TEXT, expires REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS cooldowns (host TEXT PRIMARY KEY, deadline REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS logos (key TEXT PRIMARY KEY, metadata TEXT, png BLOB, original BLOB, expires REAL)')
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'TAGLogoBank/3.0 (public logo retrieval)'
        self.clock, self.sleep, self.max_wait, self.refresh = clock, sleep, max_wait, refresh

    def get(self, url, *, allowed_hosts=None, headers=None, https_only=False):
        original = url
        for redirect in range(6):
            parts = urlsplit(url)
            if https_only and parts.scheme != 'https':
                raise ValueError('HTTPS downgrade is forbidden')
            host = website_domain(url)
            if allowed_hosts is not None and host not in allowed_hosts:
                raise IdentityRedirect(f'Cross-domain page redirect blocked: {original} -> {url}; possible acquirer/rebrand')
            cached = self.db.execute('SELECT body,final,headers,expires FROM responses WHERE url=?', (url,)).fetchone()
            if cached and cached[3] > self.clock() and not self.refresh:
                if https_only and urlsplit(cached[1]).scheme != 'https':
                    raise ValueError('Cached HTTPS downgrade is forbidden')
                if allowed_hosts is not None and website_domain(cached[1]) not in allowed_hosts:
                    raise IdentityRedirect(f'Cached cross-domain page redirect blocked: {original} -> {cached[1]}')
                return Download(cached[0], cached[1], json.loads(cached[2]))
            public_url(url)  # Validate every redirect, including cached-page asset destinations.
            deadline = self.db.execute('SELECT deadline FROM cooldowns WHERE host=?', (host,)).fetchone()
            if deadline and deadline[0] > self.clock():
                raise RateLimited(host, deadline[0])
            for attempt in range(3):
                with self.session.get(url, headers=headers or {}, timeout=(5, 20), stream=True, allow_redirects=False) as response:
                    if response.status_code == 429:
                        raw = response.headers.get('Retry-After', '')
                        try:
                            delay = max(1, float(raw))
                        except ValueError:
                            try:
                                delay = max(1, parsedate_to_datetime(raw).timestamp() - self.clock())
                            except (ValueError, TypeError, OverflowError):
                                delay = 2 ** (attempt + 1)
                        if not math.isfinite(delay):
                            delay = 2 ** (attempt + 1)
                        deadline = self.clock() + delay
                        self.db.execute('INSERT OR REPLACE INTO cooldowns VALUES (?,?)', (host, deadline))
                        self.db.commit()
                        if attempt < 2 and delay <= self.max_wait:
                            self.sleep(delay)
                            continue
                        raise RateLimited(host, deadline)
                    if response.status_code in (500, 502, 503, 504) and attempt < 2:
                        self.sleep(min(2 ** attempt, self.max_wait))
                        continue
                    if response.is_redirect:
                        url = urljoin(url, response.headers['Location'])
                        break
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise ValueError('Response exceeds 8 MB')
                    safe_headers = {k: v for k, v in response.headers.items() if k.lower() in
                                    {'content-type', 'x-logo-fallback', 'x-logo-kind', 'retry-after'}}
                    self.db.execute('INSERT OR REPLACE INTO responses VALUES (?,?,?,?,?)',
                                    (original, bytes(data), url, json.dumps(safe_headers), self.clock() + 86400))
                    self.db.commit()
                    return Download(bytes(data), url, safe_headers)
        raise ValueError('Too many redirects')

    def close(self):
        self.session.close()
        self.db.close()


class APITransport:
    def __init__(self, http):
        self.http = http

    def get(self, url):
        if urlsplit(url).scheme != 'https':
            raise ValueError('API requires HTTPS')
        return self.http.get(url, allowed_hosts={'logoapi.sh'}, https_only=True)
