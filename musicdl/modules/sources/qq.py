'''
Function:
    Implementation of QQMusicClient: https://y.qq.com/
Author:
    Zhenchao Jin
WeChat Official Account (微信公众号):
    Charles的皮卡丘
'''
import copy
import json
import time
import base64
import random
from .base import BaseMusicClient
from rich.progress import Progress
from ..utils.qqutils import QQMusicClientUtils, Device, DEFAULT_VIP_QUALITIES, DEFAULT_QUALITIES
from ..utils import byte2mb, resp2json, seconds2hms, legalizestring, safeextractfromdict, usesearchheaderscookies, SongInfo


'''QQMusicClient'''
class QQMusicClient(BaseMusicClient):
    source = 'QQMusicClient'
    def __init__(self, **kwargs):
        super(QQMusicClient, self).__init__(**kwargs)
        self.uid = '3931641530'
        self.version_info = dict(
            version="13.2.5.8", version_code=13020508,
        )
        self.device = Device()
        self.qimei_info = QQMusicClientUtils.obtainqimei(version=self.version_info['version'], device=self.device)
        self.default_search_headers = {
            'Referer': 'https://y.qq.com/',
            'Origin': 'https://y.qq.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        }
        self.default_download_headers = {
            'Referer': 'http://y.qq.com',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        }
        self.default_headers = self.default_search_headers
        self._initsession()
    '''_randomsearchid'''
    def _randomsearchid(self):
        e = random.randint(1, 20)
        t = e * 18014398509481984
        n = random.randint(0, 4194304) * 4294967296
        a = time.time()
        r = round(a * 1000) % (24 * 60 * 60 * 1000)
        return str(t + n + r)
    '''_randomguid'''
    def _randomguid(self):
        return "".join(random.choices("abcdef1234567890", k=32))
    '''_constructsearchurls'''
    def _constructsearchurls(self, keyword: str, rule: dict = None, request_overrides: dict = None):
        # init
        rule, request_overrides = rule or {}, request_overrides or {}
        # search rules
        default_rule = {
            'comm': {
                'cv': self.version_info['version_code'], 'v': self.version_info['version_code'], 'QIMEI36': self.qimei_info['q36'], 'ct': '11', 
                'tmeAppID': 'qqmusic', 'format': 'json', 'inCharset': 'utf-8', 'outCharset': 'utf-8', 'uid': self.uid,
            }, 
            'music.search.SearchCgiService.DoSearchForQQMusicMobile': {
                'module': 'music.search.SearchCgiService', 'method': 'DoSearchForQQMusicMobile', 
                'param': {'searchid': self._randomsearchid(), 'query': keyword, 'search_type': 0, 'num_per_page': 10, 'page_num': 1, 'highlight': 1, 'grp': 1}
            }
        }
        default_rule.update(rule)
        # construct search urls based on search rules
        base_url = 'https://u.y.qq.com/cgi-bin/musicu.fcg'
        search_urls, page_size, count = [], self.search_size_per_page, 0
        while self.search_size_per_source > count:
            page_rule = copy.deepcopy(default_rule)
            page_rule['music.search.SearchCgiService.DoSearchForQQMusicMobile']['param']['num_per_page'] = page_size
            page_rule['music.search.SearchCgiService.DoSearchForQQMusicMobile']['param']['page_num'] = int(count // page_size) + 1
            search_urls.append({'url': base_url, 'json': page_rule})
            count += page_size
        # return
        return search_urls
    '''_search'''
    @usesearchheaderscookies
    def _search(self, keyword: str = '', search_url: dict = {}, request_overrides: dict = None, song_infos: list = [], progress: Progress = None, progress_id: int = 0):
        # init
        search_meta, request_overrides = copy.deepcopy(search_url), request_overrides or {}
        search_url = search_meta.pop('url')
        # successful
        try:
            # --search results
            resp = self.post(search_url, **search_meta, **request_overrides)
            resp.raise_for_status()
            search_results = resp2json(resp)['music.search.SearchCgiService.DoSearchForQQMusicMobile']['data']['body']['item_song']
            for search_result in search_results:
                # --download results
                if not isinstance(search_result, dict) or ('mid' not in search_result):
                    continue
                # ----init
                file_size_infos, song_info = dict(
                    size_new=safeextractfromdict(search_result, ['file', 'size_new'], ['0', '0', '0', '0', '0']), size_flac=safeextractfromdict(search_result, ['file', 'size_flac'], '0'),
                    size_192ogg=safeextractfromdict(search_result, ['file', 'size_192ogg'], '0'), size_96ogg=safeextractfromdict(search_result, ['file', 'size_96ogg'], '0'),
                    size_320mp3=safeextractfromdict(search_result, ['file', 'size_320mp3'], '0'), size_128mp3=safeextractfromdict(search_result, ['file', 'size_128mp3'], '0'),
                    size_192aac=safeextractfromdict(search_result, ['file', 'size_192aac'], '0'), size_96aac=safeextractfromdict(search_result, ['file', 'size_96aac'], '0'),
                    size_48aac=safeextractfromdict(search_result, ['file', 'size_48aac'], '0'),
                ), SongInfo(source=self.source)
                # ----if cookies exits, assume user with vip first
                if self.default_cookies or request_overrides.get('cookies', {}):
                    default_vip_rule = {
                        'comm': {
                            'cv': self.version_info['version_code'], 'v': self.version_info['version_code'], 'QIMEI36': self.qimei_info['q36'], 'ct': '11', 
                            'tmeAppID': 'qqmusic', 'format': 'json',  'inCharset': 'utf-8', 'outCharset': 'utf-8', 'uid': self.uid,
                        }, 
                        'music.vkey.GetEVkey.CgiGetEVkey': {
                            'module': 'music.vkey.GetEVkey', 'method': 'CgiGetEVkey', 
                            'param': {'filename': [], 'guid': self._randomguid(), 'songmid': [search_result['mid']], 'songtype': [0]}
                        },
                    }
                    default_file_sizes = [
                        file_size_infos['size_new'][0], file_size_infos['size_new'][1], file_size_infos['size_new'][2], file_size_infos['size_flac'], file_size_infos['size_new'][5], 
                        file_size_infos['size_new'][3], file_size_infos['size_192ogg'], file_size_infos['size_96ogg'],
                    ]
                    for quality, default_file_size in zip(list(DEFAULT_VIP_QUALITIES.values()), default_file_sizes):
                        song_info = SongInfo(source=self.source)
                        try:
                            current_rule = copy.deepcopy(default_vip_rule)
                            current_rule['music.vkey.GetEVkey.CgiGetEVkey']['param']['filename'] = [f"{quality[0]}{search_result['mid']}{search_result['mid']}{quality[1]}"]
                            resp = self.post('https://u.y.qq.com/cgi-bin/musicu.fcg', json=current_rule, **request_overrides)
                            resp.raise_for_status()
                            download_result: dict = resp2json(resp)
                            if download_result.get('code', 'NULL') not in [0] or safeextractfromdict(download_result, ['music.vkey.GetEVkey.CgiGetEVkey', 'code'], 'NULL') not in [0]: continue
                            download_url = safeextractfromdict(download_result, ['music.vkey.GetEVkey.CgiGetEVkey', 'data', "midurlinfo", 0, "wifiurl"], "")
                            if not download_url: continue
                            download_url, ext, file_size = "https://isure.stream.qqmusic.qq.com/" + download_url, quality[1][1:], default_file_size
                            download_url_status = self.audio_link_tester.test(download_url, request_overrides)
                            song_info.update(dict(
                                download_url=download_url, download_url_status=download_url_status, ext=ext, file_size_bytes=file_size, file_size=byte2mb(file_size),
                                raw_data={'search': search_result, 'download': download_result},
                            ))
                            if song_info.with_valid_download_url: break
                        except:
                            continue
                # ----common user in post try
                if not song_info.with_valid_download_url:
                    default_rule = {
                        'comm': {
                            'cv': self.version_info['version_code'], 'v': self.version_info['version_code'], 'QIMEI36': self.qimei_info['q36'], 'ct': '11', 
                            'tmeAppID': 'qqmusic', 'format': 'json', 'inCharset': 'utf-8', 'outCharset': 'utf-8', 'uid': self.uid,
                        }, 
                        'music.vkey.GetVkey.UrlGetVkey': {
                            'module': 'music.vkey.GetVkey', 'method': 'UrlGetVkey', 
                            'param': {'filename': [], 'guid': self._randomguid(), 'songmid': [search_result['mid']], 'songtype': [0]}
                        },
                    }
                    default_file_sizes = [
                        file_size_infos['size_new'][0], file_size_infos['size_new'][1], file_size_infos['size_new'][2], file_size_infos['size_flac'], file_size_infos['size_new'][5], file_size_infos['size_new'][3],
                        file_size_infos['size_192ogg'], file_size_infos['size_96ogg'], file_size_infos['size_320mp3'], file_size_infos['size_128mp3'], file_size_infos['size_192aac'], file_size_infos['size_96aac'],
                        file_size_infos['size_48aac'],
                    ]
                    for quality, default_file_size in zip(list(DEFAULT_QUALITIES.values()), default_file_sizes):
                        song_info = SongInfo(source=self.source)
                        try:
                            current_rule = copy.deepcopy(default_rule)
                            current_rule['music.vkey.GetVkey.UrlGetVkey']['param']['filename'] = [f"{quality[0]}{search_result['mid']}{search_result['mid']}{quality[1]}"]
                            resp = self.post('https://u.y.qq.com/cgi-bin/musicu.fcg', json=current_rule, **request_overrides)
                            resp.raise_for_status()
                            download_result: dict = resp2json(resp)
                            if download_result.get('code', 'NULL') not in [0] or safeextractfromdict(download_result, ['music.vkey.GetVkey.UrlGetVkey', 'code'], 'NULL') not in [0]: continue
                            download_url = safeextractfromdict(download_result, ['music.vkey.GetVkey.UrlGetVkey', 'data', "midurlinfo", 0, "wifiurl"], "")
                            if not download_url: continue
                            download_url, ext, file_size = "https://isure.stream.qqmusic.qq.com/" + download_url, quality[1][1:], default_file_size
                            download_url_status = self.audio_link_tester.test(download_url, request_overrides)
                            song_info.update(dict(
                                download_url=download_url, download_url_status=download_url_status, ext=ext, file_size_bytes=file_size, file_size=byte2mb(file_size),
                                raw_data={'search': search_result, 'download': download_result},
                            ))
                            if song_info.with_valid_download_url: break
                        except:
                            continue
                # ----common user in get try
                if not song_info.with_valid_download_url:
                    params = {
                        'data': json.dumps({
                            "req_0": {
                                "module": 'vkey.GetVkeyServer', "method": 'CgiGetVkey', 
                                "param": {
                                    "filename": [f"M500{search_result['mid']}{search_result['mid']}.mp3"], "guid": "10000", "songmid": [search_result['mid']], 
                                    "songtype": [0], "uin": "0", "loginflag": 1, "platform": "20"
                                }
                            },
                            "loginUin": "0",
                            "comm": {"uin": "0", "format": "json", "ct": 24, "cv": 0}
                        }, ensure_ascii=False).encode('utf-8'),
                        'format': 'json',
                    }
                    song_info = SongInfo(source=self.source)
                    try:
                        resp = self.get('https://u.y.qq.com/cgi-bin/musicu.fcg', params=params, **request_overrides)
                        resp.raise_for_status()
                        download_result: dict = resp2json(resp)
                        if download_result.get('code', 'NULL') not in [0] or safeextractfromdict(download_result, ['req_0', 'code'], 'NULL') not in [0]: continue
                        download_url = safeextractfromdict(download_result, ['req_0', 'data', "midurlinfo", 0, "purl"], "")
                        if not download_url: continue
                        download_url, ext, file_size = 'http://ws.stream.qqmusic.qq.com/' + download_url, "mp3", file_size_infos['size_128mp3']
                        download_url_status = self.audio_link_tester.test(download_url, request_overrides)
                        song_info.update(dict(
                            download_url=download_url, download_url_status=download_url_status, ext=ext, file_size_bytes=file_size, file_size=byte2mb(file_size),
                            raw_data={'search': search_result, 'download': download_result},
                        ))
                    except:
                        continue
                # ----parse more infos
                if not song_info.with_valid_download_url: continue
                song_info.update(dict(
                    duration_s=search_result.get('interval', 0), duration=seconds2hms(search_result.get('interval', 0)),
                    song_name=legalizestring(search_result.get('title', 'NULL'), replace_null_string='NULL'),
                    singers=legalizestring(', '.join([singer.get('name', 'NULL') for singer in search_result.get('singer', [])]), replace_null_string='NULL'), 
                    album=legalizestring(safeextractfromdict(search_result, ['album', 'title'], 'NULL'), replace_null_string='NULL'),
                    identifier=search_result['mid'],
                ))
                # --lyric results
                params = {
                    'songmid': str(search_result['mid']), 'g_tk': '5381', 'loginUin': '0', 'hostUin': '0', 'format': 'json',
                    'inCharset': 'utf8', 'outCharset': 'utf-8', 'platform': 'yqq'
                }
                request_overrides = copy.deepcopy(request_overrides)
                request_overrides.pop('headers', {})
                try:
                    resp = self.get('https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg', headers={'Referer': 'https://y.qq.com/portal/player.html'}, params=params, **request_overrides)
                    lyric_result: dict = resp2json(resp) or {'lyric': ''}
                    lyric = lyric_result.get('lyric', '')
                    if not lyric: lyric = 'NULL'
                    else: lyric = base64.b64decode(lyric).decode('utf-8')
                except:
                    lyric_result, lyric = {}, "NULL"
                song_info.raw_data['lyric'], song_info.lyric = lyric_result, lyric
                # --append to song_infos
                song_infos.append(song_info)
                # --judgement for search_size
                if self.strict_limit_search_size_per_page and len(song_infos) >= self.search_size_per_page: break
            # --update progress
            progress.advance(progress_id, 1)
            progress.update(progress_id, description=f"{self.source}.search >>> {search_url} (Success)")
        # failure
        except Exception as err:
            progress.update(progress_id, description=f"{self.source}.search >>> {search_url} (Error: {err})")
        # return
        return song_infos