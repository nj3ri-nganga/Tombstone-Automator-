"""Small sequential pipeline: optional API -> official site -> opt-in scoped search."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlencode

from .api import LogoAPI, normalized_name
from .discovery import official_logo, identity
from .logos import Logo, normalize_site, website_domain
from .network import HTTP, APITransport, RateLimited, IdentityRedirect


class BraveSearch:
    """Web-page discovery only, restricted to explicitly verified destination domains."""
    def __init__(self, http, domains):
        self.http, self.domains = http, set(domains)

    def sites(self, company):
        token = os.environ.get('BRAVE_SEARCH_API_KEY', '')
        if not token or not self.domains:
            raise ValueError('Web search requires BRAVE_SEARCH_API_KEY and explicitly verified --search-domains')
        query = f'"{company}" official website logo ' + '(' + ' OR '.join('site:' + d for d in sorted(self.domains)) + ')'
        response = self.http.get('https://api.search.brave.com/res/v1/web/search?' + urlencode({'q': query, 'count': 5}),
                                 allowed_hosts={'api.search.brave.com'}, headers={'X-Subscription-Token': token}, https_only=True)
        results = json.loads(response.data).get('web', {}).get('results', [])
        sites = {}
        for item in results[:5]:
            try:
                url = normalize_site(item['url'])
                domain = website_domain(url)
                if domain in self.domains and identity(company, item.get('title', '')):
                    sites.setdefault(domain, url)
            except (ValueError, KeyError, TypeError):
                continue
        if len(sites) > 1:
            raise ValueError('Search returned multiple plausible verified domains; identity requires review')
        return list(sites.values())[:1]


class Hybrid:
    def __init__(self, cache_dir='.tag-logo-cache', *, use_api=True, http=None,
                 web_search=False, search_domains=(), aliases=None, refresh=False, max_wait=2):
        self.http = http or HTTP(cache_dir, refresh=refresh, max_wait=max_wait)
        self.use_api, self.web_search = use_api, web_search
        self.search_domains = tuple(sorted(website_domain(d) for d in search_domains))
        self.aliases = aliases or {}
        self.api = LogoAPI(APITransport(self.http))

    def close(self):
        self.http.close()

    def lookup(self, company, website=''):
        aliases = self.aliases.get(company.casefold(), [])
        try:
            site = normalize_site(website) if website else ''
            if site:
                website_domain(site)
        except ValueError as error:
            return Logo(status='ERROR', detail=f'Invalid verified website: {error}')
        key = hashlib.sha256(json.dumps([normalized_name(company), site, aliases, self.use_api,
                                       self.web_search, self.search_domains, 'hybrid-v1']).encode()).hexdigest()
        cached = self.http.db.execute('SELECT metadata,png,original,expires FROM logos WHERE key=?', (key,)).fetchone()
        if cached and cached[3] > self.http.clock() and not self.http.refresh:
            result = Logo(**json.loads(cached[0]), png=cached[1], downloaded_png=cached[2])
            result.detail = 'Cache hit; ' + result.detail
            return result
        attempts, deferred = [], []
        result = None
        if self.use_api:
            try:
                result = self.api.lookup(company, site)
                result.method = 'logoapi'
                if result.png:
                    return self._save(key, result)
                attempts.append('logoapi: ' + result.detail)
                if result.status == 'RATE_LIMITED':
                    deferred.append(result.retry_at or self.http.clock() + 60)
            except RateLimited as error:
                deferred.append(error.retry_at)
                attempts.append(str(error))
        if site:
            try:
                result = official_logo(company, site, self.http, aliases)
                if result.png:
                    result.detail += '; previous attempts: ' + '; '.join(attempts)
                    return self._save(key, result)
                attempts.append('official website: ' + result.detail)
            except RateLimited as error:
                deferred.append(error.retry_at)
                attempts.append(str(error))
            except (OSError, ValueError) as error:
                attempts.append(f'official website: {type(error).__name__}: {error}')
                result = Logo(status='MATCH_UNCERTAIN' if isinstance(error, IdentityRedirect) else 'ERROR')
        if self.web_search:
            try:
                domains = set(self.search_domains)
                if site:
                    domains.add(website_domain(site))
                for discovered in BraveSearch(self.http, domains).sites(company):
                    result = official_logo(company, discovered, self.http, aliases)
                    if result.png:
                        result.method = 'verified_web_search/' + result.method
                        result.detail += '; web search result and official page independently name the target; ' + '; '.join(attempts)
                        return self._save(key, result)
                    attempts.append('search page: ' + result.detail)
            except RateLimited as error:
                deferred.append(error.retry_at)
                attempts.append(str(error))
            except (OSError, ValueError) as error:
                attempts.append('scoped web search: ' + str(error))
        if deferred:
            result = Logo(status='RATE_LIMITED', retry_at=min(deferred))
        elif result is None:
            result = Logo(status='NEEDS_WEBSITE')
        result.detail = '; '.join(attempts) or 'Supply a verified official website; optional scoped search is disabled'
        result.method = 'hybrid_no_usable_logo'
        return self._save(key, result)

    def _save(self, key, result):
        if result.status == 'RATE_LIMITED':
            return result  # Persistent host cooldown, not a negative logo cache, controls resume.
        metadata = asdict(result)
        metadata.pop('png')
        metadata.pop('downloaded_png')
        self.http.db.execute('INSERT OR REPLACE INTO logos VALUES (?,?,?,?,?)',
                             (key, json.dumps(metadata), result.png, result.downloaded_png,
                              self.http.clock() + (86400 if result.png else 600)))
        self.http.db.commit()
        return result
