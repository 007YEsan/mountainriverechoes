'''
Function:
    Implementation of LizhiMusicClient: https://www.lizhi.fm/
Author:
    Zhenchao Jin
WeChat Official Account (微信公众号):
    Charles的皮卡丘
'''
import copy
from contextlib import suppress
from urllib.parse import urlencode
from rich.progress import Progress
from ..sources import BaseMusicClient
from datetime import datetime, timezone, timedelta
from ..utils import legalizestring, resp2json, seconds2hms, usesearchheaderscookies, safeextractfromdict, SongInfo


'''LizhiMusicClient'''
class LizhiMusicClient(BaseMusicClient):
    source = 'LizhiMusicClient'
    ALLOWED_SEARCH_TYPES = ['album', 'track'][1:]
    MUSIC_QUALITIES = ['_ud.mp3', '_hd.mp3', '_sd.m4a']
    def __init__(self, **kwargs):
        self.allowed_search_types = list(set(kwargs.pop('allowed_search_types', LizhiMusicClient.ALLOWED_SEARCH_TYPES)))
        super(LizhiMusicClient, self).__init__(**kwargs)
        self.default_search_headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 9_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 Mobile/13B143 Safari/601.1',
            'Referer': 'https://m.lizhi.fm',
        }
        self.default_download_headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 9_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 Mobile/13B143 Safari/601.1',
        }
        self.default_headers = self.default_search_headers
        self._initsession()
    '''_constructsearchurls'''
    def _constructsearchurls(self, keyword: str, rule: dict = None, request_overrides: dict = None):
        # init
        rule, request_overrides = rule or {}, request_overrides or {}
        self.search_size_per_page = min(self.search_size_per_page, 20)
        # construct search urls based on search rules
        search_urls, page_size = [], self.search_size_per_page
        for search_type in LizhiMusicClient.ALLOWED_SEARCH_TYPES:
            if search_type not in self.allowed_search_types: continue
            if search_type in {'track'}:
                default_rule = {'deviceId': "h5-b6ef91a9-3dbb-c716-1fdd-43ba08851150", "keywords": keyword, "page": 1, "receiptData": ""}
                default_rule.update(rule)
                base_url, count = 'https://m.lizhi.fm/vodapi/search/voice?', 0
                while self.search_size_per_source > count:
                    page_rule = copy.deepcopy(default_rule)
                    page_rule['page'] = str(int(count // page_size) + 1)
                    if count > 0:
                        with suppress(Exception): receipt_data = resp2json(self.get(search_urls[-1]['url'], **request_overrides)).get('receiptData', '')
                        page_rule['receiptData'] = receipt_data
                    search_urls.append({'url': base_url + urlencode(page_rule), 'type': search_type})
                    count += page_size
            elif search_type in ['album']:
                pass
        # return
        return search_urls
    '''_parsebytrack'''
    def _parsebytrack(self, search_results, song_infos: list = [], request_overrides: dict = None, progress: Progress = None):
        request_overrides = request_overrides or {}
        for search_result in search_results:
            if not isinstance(search_result, dict) or not safeextractfromdict(search_result, ['voiceInfo', 'voiceId'], ''): continue
            song_info, song_id = SongInfo(source=self.source), safeextractfromdict(search_result, ['voiceInfo', 'voiceId'], '')
            download_url = safeextractfromdict(search_result, ['voicePlayProperty', 'trackUrl'], '')
            if not download_url or not str(download_url).startswith('http'):
                create_time = safeextractfromdict(search_result, ['voiceInfo', 'createTime'], 0)
                if not create_time: continue
                download_url = f'http://cdn5.lizhi.fm/audio/{datetime.fromtimestamp(int(float(create_time)), tz=timezone(timedelta(hours=8))).strftime("%Y/%m/%d")}/{song_id}_sd.m4a'
            for quality in LizhiMusicClient.MUSIC_QUALITIES:
                download_url: str = download_url[:-7] + quality
                song_info = SongInfo(
                    raw_data={'search': search_result, 'download': {}, 'lyric': {}}, source=self.source, song_name=legalizestring(safeextractfromdict(search_result, ['voiceInfo', 'name'], '')),
                    singers=legalizestring(safeextractfromdict(search_result, ['userInfo', 'name'], '')), album='NULL', ext=download_url.split('?')[0].split('.')[-1], file_size='NULL', identifier=song_id, 
                    duration_s=safeextractfromdict(search_result, ['voiceInfo', 'duration'], ''), duration=seconds2hms(safeextractfromdict(search_result, ['voiceInfo', 'duration'], '')), lyric=None, 
                    cover_url=safeextractfromdict(search_result, ['voiceInfo', 'imageUrl'], None), download_url=download_url, download_url_status=self.audio_link_tester.test(download_url, request_overrides),
                )
                if song_info.with_valid_download_url: break
            if not song_info.with_valid_download_url: continue
            song_info.download_url_status['probe_status'] = self.audio_link_tester.probe(song_info.download_url, request_overrides)
            song_info.file_size = song_info.download_url_status['probe_status']['file_size']
            song_infos.append(song_info)
            if self.strict_limit_search_size_per_page and len(song_infos) >= self.search_size_per_page: break
        return song_infos
    '''_parsebyalbum'''
    def _parsebyalbum(self, search_results, song_infos: list = [], request_overrides: dict = None, progress: Progress = None):
        request_overrides, song_info = request_overrides or {}, SongInfo(source=self.source)
    '''_search'''
    @usesearchheaderscookies
    def _search(self, keyword: str = '', search_url: dict = '', request_overrides: dict = None, song_infos: list = [], progress: Progress = None, progress_id: int = 0):
        # init
        request_overrides = request_overrides or {}
        search_type, search_url = search_url['type'], search_url['url']
        # successful
        try:
            # --search results
            resp = self.get(search_url, **request_overrides)
            resp.raise_for_status()
            search_results = resp2json(resp)['data']
            # --parse based on search type
            parsers = {'album': self._parsebyalbum, 'track': self._parsebytrack}
            parsers[search_type](search_results, song_infos=song_infos, request_overrides=request_overrides, progress=progress)
            # --update progress
            progress.update(progress_id, description=f"{self.source}.search >>> {search_url} (Success)")
        # failure
        except Exception as err:
            progress.update(progress_id, description=f"{self.source}.search >>> {search_url} (Error: {err})")
        # return
        return song_infos