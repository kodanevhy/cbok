import json
from pathlib import Path
import unittest

import requests

from cbok.alert.sources import create_source, register_source
from cbok.alert.sources.base import Observation, SourceError, SourceItem
from cbok.alert.sources.tencent import TencentSource, parse_article, parse_feed, parse_page


FIXTURES = Path(__file__).parent / 'fixtures' / 'tencent'
SECTION = {'channel_key': 'finance', 'channel_id': 'news_news_finance',
           'page_url': 'https://news.qq.com/ch/finance/', 'feed_kind': 'pc'}


def fixture(name):
    return (FIXTURES / name).read_text()


class Response:
    def __init__(self, body='', status=200, content_type='application/json', url=None, headers=None):
        self.body = body.encode()
        self.status_code = status
        self.headers = {'Content-Type': content_type, **(headers or {})}
        self.url = url
        self.closed = False

    def iter_content(self, chunk_size):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]

    def close(self):
        self.closed = True


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.trust_env = True

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        response.url = response.url or url
        return response


class SourceValuesTests(unittest.TestCase):
    def test_values_are_json_serializable_and_metadata_not_shared(self):
        item = SourceItem('id')
        other = SourceItem('other')
        item.metadata['x'] = 1
        self.assertEqual(other.metadata, {})
        self.assertEqual(json.loads(json.dumps(item.to_dict()))['external_id'], 'id')
        self.assertEqual(Observation('json', {'a': 1}).to_dict()['data'], {'a': 1})

    def test_registry_instantiates_custom_source(self):
        register_source('fixture_source', lambda config: ('custom', config))
        self.assertEqual(create_source('fixture_source', {'k': 1}), ('custom', {'k': 1}))
        with self.assertRaises(ValueError):
            register_source('fixture_source', lambda config: config)
        self.assertIsInstance(create_source('tencent', {}), TencentSource)


class TencentParsingTests(unittest.TestCase):
    def assert_changed(self, operation):
        with self.assertRaises(SourceError) as caught:
            operation()
        self.assertEqual(caught.exception.code, 'SECTION_CHANGED')

    def test_empty_react_root_page_shell_is_valid(self):
        self.assertEqual(parse_page(fixture('page.html'), 'finance'), 'finance')

    def test_page_missing_wrong_or_invalid_channel_is_contract_failure(self):
        for body in ('<div id="root"></div>', 'window.channelInfo = nope;',
                     'window.channelInfo = {"channelKey":"tech"};'):
            with self.subTest(body=body):
                self.assert_changed(lambda: parse_page(body, 'finance'))

    def test_pc_feed_expands_wrapper_and_ignores_nonarticle_modules(self):
        items = parse_feed(json.loads(fixture('pc.json')), 'pc')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].external_id, 'TEST202610230001')
        self.assertEqual(items[0].metadata['item_type'], 'article')
        self.assertEqual(items[0].published_at, '2026-10-23 12:00:00')

    def test_hot_feed_does_not_require_code(self):
        self.assertEqual(len(parse_feed(json.loads(fixture('hot.json')), 'hot')), 1)
        self.assertEqual(parse_feed({'data': []}, 'hot'), [])
        self.assertEqual(parse_feed({'code': 0, 'data': []}, 'pc'), [])

    def test_feed_invalid_envelope_and_required_article_fields_fail(self):
        for payload in ({'data': []}, {'code': 1, 'data': []}, {'code': 0, 'data': {}},
                        {'code': 0, 'data': [None]},
                        {'code': 0, 'data': [{'articletype': '525'}]}):
            with self.subTest(payload=payload):
                self.assert_changed(lambda: parse_feed(payload, 'pc'))
        original = json.loads(fixture('hot.json'))['data'][0]
        for field in ('id', 'title', 'link_info'):
            broken = dict(original)
            del broken[field]
            self.assert_changed(lambda: parse_feed({'data': [broken]}, 'hot'))
        broken = dict(original, link_info={'url': 'javascript:alert(1)'})
        self.assert_changed(lambda: parse_feed({'data': [broken]}, 'hot'))
        broken = dict(original, link_info={'url': 'https://new.qq.com:bad/rain/a/id'})
        self.assert_changed(lambda: parse_feed({'data': [broken]}, 'hot'))

    def test_article_extracts_body_metadata_and_canonical_response_url(self):
        item = parse_article(fixture('article.html'), 'https://news.qq.com/rain/a/TEST202610230001')
        self.assertEqual(item.external_id, 'TEST202610230001')
        self.assertEqual(item.url, 'https://news.qq.com/rain/a/TEST202610230001')
        self.assertEqual(item.content, 'First paragraph.\nSecond paragraph.')

    def test_article_missing_title_body_or_data_fails(self):
        body = fixture('article.html')
        for changed in (body.replace('article-title', 'removed-title'),
                        body.replace('article-content', 'removed-content'),
                        body.replace('window.DATA', 'window.OTHER')):
            self.assert_changed(lambda: parse_article(changed, 'https://news.qq.com/rain/a/id'))


class TencentRequestTests(unittest.TestCase):
    def pac(self):
        return Response('{"code":0,"data":{"pac_uid":"anonymous-fixture"}}')

    def test_collect_prepares_anonymous_identity_and_correct_pc_request(self):
        session = Session(self.pac(), Response(fixture('pc.json')))
        source = TencentSource({'timeout': 8, 'trust_env': False}, session=session)
        self.assertEqual(len(source.collect(SECTION, limit=1)), 1)
        method, url, kwargs = session.calls[1]
        self.assertEqual(method, 'POST')
        self.assertTrue(url.endswith('/getPCList'))
        self.assertEqual(kwargs['json'], {'base_req': {'from': 'pc'}, 'forward': '2',
                         'qimei36': 'anonymous-fixture', 'device_id': 'anonymous-fixture',
                         'flush_num': 1, 'channel_id': 'news_news_finance',
                         'item_count': 1, 'is_local_chlid': '0'})
        self.assertEqual(kwargs['timeout'], 8)
        self.assertTrue(kwargs['verify'])
        self.assertTrue(kwargs['stream'])
        self.assertFalse(kwargs['allow_redirects'])
        self.assertFalse(session.trust_env)

    def test_hot_request_and_observation_preserve_raw_json(self):
        session = Session(self.pac(), Response(fixture('hot.json')))
        source = TencentSource({}, session=session)
        obs = source.observe(dict(SECTION, feed_kind='hot', channel_id='news_news_top'), 'feed')
        self.assertEqual(obs.data, json.loads(fixture('hot.json')))
        self.assertEqual(len(obs.metadata['items']), 1)
        self.assertEqual(obs.metadata['status_code'], 200)
        self.assertTrue(session.calls[1][1].endswith('/getHotModuleList'))
        self.assertNotIn('is_local_chlid', session.calls[1][2]['json'])

    def test_page_observation_keeps_html_and_parsed_channel(self):
        source = TencentSource({}, session=Session(Response(fixture('page.html'), content_type='text/html')))
        obs = source.observe(SECTION, 'page')
        self.assertEqual(obs.data, fixture('page.html'))
        self.assertEqual(obs.metadata['channel_key'], 'finance')
        self.assertEqual(obs.metadata['url'], SECTION['page_url'])

    def test_normal_page_text_mentioning_captcha_is_not_an_access_failure(self):
        html = fixture('page.html').replace('</body>', '<p>新闻报道：验证码行业发展</p></body>')
        source = TencentSource({}, session=Session(Response(html, content_type='text/html')))
        self.assertEqual(source.observe(SECTION, 'page').metadata['channel_key'], 'finance')

    def test_article_observation_preserves_raw_html(self):
        source = TencentSource({}, session=Session(Response(fixture('article.html'), content_type='text/html')))
        obs = source.observe({'item': {'url': 'https://new.qq.com/rain/a/TEST202610230001'}}, 'article')
        self.assertEqual(obs.data, fixture('article.html'))
        self.assertEqual(obs.metadata['article']['external_id'], 'TEST202610230001')

    def test_section_article_observation_collects_one_ordinary_sample(self):
        session = Session(self.pac(), Response(fixture('pc.json')),
                          Response(fixture('article.html'), content_type='text/html'))
        obs = TencentSource({}, session=session).observe(SECTION, 'article')
        self.assertEqual(obs.metadata['article']['external_id'], 'TEST202610230001')
        self.assertEqual(obs.data, fixture('article.html'))
        self.assertEqual(session.calls[1][2]['json']['item_count'], 1)
        self.assertEqual(session.calls[2][1], 'https://new.qq.com/rain/a/TEST202610230001')

    def test_section_article_without_ordinary_items_is_empty_result(self):
        for payload in ({'code': 0, 'data': []},
                        {'code': 0, 'data': [{'articletype': '56', 'title': 'Video'}]}):
            session = Session(self.pac(), Response(json.dumps(payload)))
            with self.subTest(payload=payload), self.assertRaises(SourceError) as caught:
                TencentSource({}, session=session).observe(SECTION, 'article')
            self.assertEqual(caught.exception.code, 'EMPTY_RESULT')
            self.assertEqual(len(session.calls), 2)

    def test_redirect_chain_and_stream_network_errors_remain_bounded(self):
        responses = [Response(status=302, headers={'Location': f'https://news.qq.com/{i}'}) for i in range(5)]
        session = Session(*responses)
        with self.assertRaises(SourceError) as caught:
            TencentSource({}, session=session).observe(SECTION, 'page')
        self.assertEqual(caught.exception.code, 'ACCESS_ERROR')
        self.assertEqual(len(session.calls), 4)
        self.assertTrue(all(response.closed for response in responses[:4]))

        class InterruptedResponse(Response):
            def iter_content(self, chunk_size):
                yield b'partial'
                raise requests.ConnectionError('secret')

        response = InterruptedResponse(content_type='text/html')
        with self.assertRaises(SourceError) as caught:
            TencentSource({}, session=Session(response)).observe(SECTION, 'page')
        self.assertEqual(caught.exception.code, 'NETWORK_ERROR')
        self.assertTrue(response.closed)

    def test_article_follows_limited_tencent_redirect(self):
        session = Session(Response(status=302, headers={'Location': 'https://news.qq.com/rain/a/TEST202610230001'}),
                          Response(fixture('article.html'), content_type='text/html'))
        item = TencentSource({}, session=session).read({'external_id': 'TEST202610230001',
                    'url': 'https://new.qq.com/rain/a/TEST202610230001'})
        self.assertEqual(item.url, 'https://news.qq.com/rain/a/TEST202610230001')
        self.assertEqual(len(session.calls), 2)

    def test_nonarticle_read_does_not_apply_article_contract(self):
        session = Session()
        with self.assertRaises(SourceError) as caught:
            TencentSource({}, session=session).read({'external_id': 'video', 'title': 'Video',
                           'metadata': {'item_type': 'video'}})
        self.assertEqual(caught.exception.code, 'CHECK_CONFIG_ERROR')
        self.assertEqual(session.calls, [])

    def test_network_errors_have_no_raw_exception_secrets(self):
        session = Session(requests.Timeout('secret-proxy-password'))
        with self.assertRaises(SourceError) as caught:
            TencentSource({}, session=session).observe(SECTION, 'page')
        self.assertEqual(caught.exception.code, 'NETWORK_ERROR')
        self.assertNotIn('secret-proxy-password', str(caught.exception))
        self.assertNotIn('secret-proxy-password', str(caught.exception.evidence))

    def test_access_statuses_are_not_structural_failures_and_close_response(self):
        for status in (401, 403, 429, 500, 503):
            response = Response('blocked', status=status)
            with self.subTest(status=status), self.assertRaises(SourceError) as caught:
                TencentSource({}, session=Session(response)).observe(SECTION, 'page')
            self.assertEqual(caught.exception.code, 'ACCESS_ERROR')
            self.assertTrue(response.closed)

    def test_invalid_json_mime_identity_and_page_contract_are_classified(self):
        for responses, kind, code in (([Response('bad json')], 'feed', 'SECTION_CHANGED'),
             ([Response('{}', content_type='text/html')], 'feed', 'ACCESS_ERROR'),
             ([Response('{"code":0,"data":{}}')], 'feed', 'SECTION_CHANGED'),
             ([Response('login required', content_type='text/html')], 'page', 'ACCESS_ERROR')):
            with self.subTest(kind=kind, responses=responses), self.assertRaises(SourceError) as caught:
                TencentSource({}, session=Session(*responses)).observe(SECTION, kind)
            self.assertEqual(caught.exception.code, code)

    def test_large_response_and_foreign_redirect_are_rejected(self):
        for response in (Response('x' * (2 * 1024 * 1024 + 1), content_type='text/html'),
                         Response(status=302, headers={'Location': 'https://example.org/private'})):
            with self.subTest(response=response), self.assertRaises(SourceError) as caught:
                TencentSource({}, session=Session(response)).observe(SECTION, 'page')
            self.assertEqual(caught.exception.code, 'ACCESS_ERROR')
            self.assertTrue(response.closed)

    def test_invalid_configuration_is_rejected_before_network(self):
        for config in ({'timeout': 0}, {'timeout': 61}, {'trust_env': 'false'}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                TencentSource(config)
        session = Session()
        source = TencentSource({}, session=session)
        for section in (dict(SECTION, feed_kind='unknown'), dict(SECTION, page_url='https://example.org/')):
            with self.subTest(section=section), self.assertRaises(ValueError):
                source.observe(section, 'page')
        self.assertEqual(session.calls, [])


if __name__ == '__main__':
    unittest.main()
