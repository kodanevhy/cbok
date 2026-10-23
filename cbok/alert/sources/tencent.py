"""Tencent page, feed and article contracts shared by collection and checks."""

import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import requests

from .base import Observation, SourceError, SourceItem


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
ALLOWED_HOSTS = frozenset({'news.qq.com', 'new.qq.com', 'view.inews.qq.com', 'i.news.qq.com'})
API_ROOT = 'https://i.news.qq.com/'


def _changed(message):
    return SourceError('SECTION_CHANGED', message)


def _url(value):
    if not isinstance(value, str):
        return False
    try:
        parts = urlsplit(value)
        return (parts.scheme == 'https' and parts.hostname in ALLOWED_HOSTS
                and parts.port in (None, 443) and not parts.username and not parts.password)
    except ValueError:
        return False


def _object_assignment(html, name):
    match = re.search(r'\bwindow\.' + re.escape(name) + r'\s*=\s*', html)
    if not match:
        raise _changed(f'Missing window.{name} metadata')
    try:
        value, _ = json.JSONDecoder().raw_decode(html[match.end():].lstrip())
    except (ValueError, TypeError) as exc:
        raise _changed(f'Invalid window.{name} metadata') from exc
    if not isinstance(value, dict):
        raise _changed(f'window.{name} must be an object')
    return value


def parse_page(html, channel_key):
    data = _object_assignment(html, 'channelInfo')
    if data.get('channelKey') != channel_key:
        raise _changed('Page channelKey does not match the configured section')
    return data['channelKey']


def parse_feed(payload, feed_kind):
    if feed_kind not in ('hot', 'pc'):
        raise ValueError('feed_kind must be hot or pc')
    if not isinstance(payload, dict):
        raise _changed('Feed must be an object')
    if feed_kind == 'pc' and (type(payload.get('code')) is not int or payload['code'] != 0):
        raise _changed('PC feed success code must be 0')
    if feed_kind == 'hot' and 'code' in payload and payload['code'] != 0:
        raise SourceError('ACCESS_ERROR', 'Hot feed reported an unsuccessful response')
    if not isinstance(payload.get('data'), list):
        raise _changed('Feed data must be an array')
    result, seen = [], set()

    def visit(entries, depth=0):
        if depth > 8:
            raise _changed('Feed module nesting exceeds the supported depth')
        for entry in entries:
            if not isinstance(entry, dict):
                raise _changed('Feed entry must be an object')
            article_type = entry.get('articletype')
            if not isinstance(article_type, (str, int)):
                raise _changed('Feed entry is missing its articletype')
            article_type = str(article_type)
            if article_type == '525':
                if not isinstance(entry.get('sub_item'), list):
                    raise _changed('Feed wrapper sub_item must be an array')
                visit(entry['sub_item'], depth + 1)
                continue
            # Videos, topics, advertisements and future nonarticle module types
            # do not promise the ordinary article contract.
            if article_type != '0':
                continue
            external_id, title = entry.get('id'), entry.get('title')
            link = entry.get('link_info')
            if (not isinstance(external_id, str) or not external_id.strip()
                    or not isinstance(title, str) or not title.strip()
                    or not isinstance(link, dict) or not _url(link.get('url'))):
                raise _changed('Ordinary article requires id, title and a Tencent HTTPS link_info.url')
            if external_id not in seen:
                result.append(SourceItem(external_id, title.strip(), link['url'],
                              entry.get('publish_time'), metadata={'item_type': 'article',
                                                                 'articletype': article_type}))
                seen.add(external_id)

    visit(payload['data'])
    return result


def parse_article(html, url):
    data = _object_assignment(html, 'DATA')
    soup = BeautifulSoup(html, 'html.parser')
    title, body = soup.select_one('h1#article-title'), soup.select_one('#article-content')
    article_id = data.get('article_id')
    if (not title or not title.get_text(strip=True) or not body or not body.get_text(strip=True)
            or not isinstance(article_id, str) or not article_id.strip()):
        raise _changed('Article requires title, content and article_id metadata')
    return SourceItem(article_id, title.get_text(' ', strip=True), url, data.get('pubtime'),
                      body.get_text('\n', strip=True), {'item_type': 'article'})


class TencentSource:
    def __init__(self, config, session=None):
        self.timeout = config.get('timeout', 15)
        if (isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float))
                or not 0 < self.timeout <= 60):
            raise ValueError('Tencent timeout must be greater than 0 and at most 60 seconds')
        trust_env = config.get('trust_env', True)
        if not isinstance(trust_env, bool):
            raise ValueError('Tencent trust_env must be boolean')
        self.session = session if session is not None else requests.Session()
        self.session.trust_env = trust_env
        self._pac_uid = None

    def _request(self, method, url, expected, **kwargs):
        if not _url(url):
            raise ValueError('Tencent request URL must be an allowed Tencent HTTPS URL')
        for redirect in range(MAX_REDIRECTS + 1):
            try:
                response = self.session.request(method, url, timeout=self.timeout, stream=True,
                       allow_redirects=False, verify=True,
                       headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://news.qq.com/'}, **kwargs)
                try:
                    status = response.status_code
                    content_type = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                    metadata = {'status_code': status, 'content_type': content_type, 'url': url}
                    if status in (301, 302, 303, 307, 308):
                        destination = urljoin(url, response.headers.get('Location', ''))
                        if redirect == MAX_REDIRECTS or not _url(destination) or destination == url:
                            raise SourceError('ACCESS_ERROR', 'Unsupported Tencent redirect', metadata)
                        url = destination
                        if status == 303 or (status in (301, 302) and method == 'POST'):
                            method, kwargs = 'GET', {}
                        continue
                    if not 200 <= status < 300:
                        raise SourceError('ACCESS_ERROR', 'Tencent returned an unsuccessful HTTP status', metadata)
                    if ((expected == 'html' and content_type not in ('text/html', 'application/xhtml+xml'))
                            or (expected == 'json' and content_type != 'application/json')):
                        raise SourceError('ACCESS_ERROR', 'Tencent returned an unexpected content type', metadata)
                    declared = response.headers.get('Content-Length')
                    if declared and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
                        raise SourceError('ACCESS_ERROR', 'Tencent response exceeds the size limit', metadata)
                    chunks, size = [], 0
                    for chunk in response.iter_content(chunk_size=65536):
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise SourceError('ACCESS_ERROR', 'Tencent response exceeds the size limit', metadata)
                        chunks.append(chunk)
                    text = b''.join(chunks).decode('utf-8-sig', errors='replace')
                    has_source_metadata = re.search(r'\bwindow\.(?:DATA|channelInfo)\s*=', text)
                    if (expected == 'html' and not has_source_metadata
                            and re.search(r'(?:login\s+required|access\s+denied|访问受限|安全验证|验证码)',
                                          text[:8192], re.I)):
                        raise SourceError('ACCESS_ERROR', 'Tencent returned an access restriction page', metadata)
                    if expected == 'json':
                        try:
                            return json.loads(text), metadata
                        except ValueError as exc:
                            raise SourceError('SECTION_CHANGED', 'Tencent returned invalid JSON', metadata) from exc
                    return text, metadata
                finally:
                    response.close()
            except requests.RequestException as exc:
                # Raw exception strings can contain proxy URLs or credentials.
                raise SourceError('NETWORK_ERROR', 'Tencent request failed',
                                  {'error_type': type(exc).__name__}) from None

    def _section(self, section):
        if (not isinstance(section, dict) or section.get('feed_kind') not in ('hot', 'pc')
                or not _url(section.get('page_url'))
                or not all(isinstance(section.get(key), str) and section[key].strip()
                           for key in ('channel_key', 'channel_id'))):
            raise ValueError('Tencent section requires channel_key, channel_id, page_url and feed_kind')
        return section

    def _feed(self, section, limit):
        if self._pac_uid is None:
            data, _ = self._request('GET', API_ROOT + 'web_backend/getWebPacUid', 'json')
            identity = data.get('data') if isinstance(data, dict) else None
            if (not isinstance(data, dict) or data.get('code') != 0 or not isinstance(identity, dict)
                    or not isinstance(identity.get('pac_uid'), str) or not identity['pac_uid'].strip()):
                raise _changed('Anonymous identity response requires code=0 and data.pac_uid')
            self._pac_uid = identity['pac_uid']
        body = {'base_req': {'from': 'pc'}, 'forward': '2', 'qimei36': self._pac_uid,
                'device_id': self._pac_uid, 'flush_num': 1, 'channel_id': section['channel_id'],
                'item_count': limit}
        endpoint = 'getHotModuleList' if section['feed_kind'] == 'hot' else 'getPCList'
        if section['feed_kind'] == 'pc':
            body['is_local_chlid'] = '0'
        raw, metadata = self._request('POST', API_ROOT + 'web_feed/' + endpoint, 'json', json=body)
        items = parse_feed(raw, section['feed_kind'])[:limit]
        metadata['items'] = [item.to_dict() for item in items]
        return Observation('json', raw, metadata)

    def collect(self, section: dict, limit: int = 12) -> list[SourceItem]:
        self._section(section)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError('Tencent collection limit must be between 1 and 100')
        return [SourceItem(**item) for item in self._feed(section, limit).metadata['items']]

    def _article(self, item):
        if item.get('metadata', {}).get('item_type', 'article') != 'article':
            raise SourceError('CHECK_CONFIG_ERROR', 'Only ordinary articles support article reading')
        raw, metadata = self._request('GET', item.get('url'), 'html')
        article = parse_article(raw, metadata['url'])
        metadata['article'] = article.to_dict()
        return Observation('html', raw, metadata)

    def read(self, item: dict) -> SourceItem:
        return SourceItem(**self._article(item).metadata['article'])

    def observe(self, section: dict, kind: str) -> Observation:
        if kind == 'article':
            if 'item' in section or 'url' in section:
                return self._article(section.get('item', section))
            items = self.collect(section, limit=1)
            if not items:
                raise SourceError('EMPTY_RESULT', 'Tencent feed has no ordinary article to sample')
            return self._article(items[0].to_dict())
        self._section(section)
        if kind == 'feed':
            return self._feed(section, 12)
        if kind == 'page':
            raw, metadata = self._request('GET', section['page_url'], 'html')
            metadata['channel_key'] = parse_page(raw, section['channel_key'])
            return Observation('html', raw, metadata)
        raise ValueError('Tencent observation kind must be page, feed or article')
