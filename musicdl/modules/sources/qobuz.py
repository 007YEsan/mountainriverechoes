'''
Function:
    Implementation of QobuzMusicClient: https://play.qobuz.com/discover
Author:
    Zhenchao Jin
WeChat Official Account (微信公众号):
    Charles的皮卡丘
'''
import os
import re
import time
import copy
import base64
import hashlib
import requests
from itertools import product
from contextlib import suppress
from .base import BaseMusicClient
from collections import OrderedDict
from pathvalidate import sanitize_filepath
from ..utils.hosts import QOBUZ_MUSIC_HOSTS
from urllib.parse import urlencode, urlparse, urljoin, parse_qs
from rich.progress import Progress, TextColumn, BarColumn, TimeRemainingColumn, MofNCompleteColumn
from ..utils import legalizestring, resp2json, usesearchheaderscookies, safeextractfromdict, hostmatchessuffix, obtainhostname, useparseheaderscookies, SongInfo, AudioLinkTester, LyricSearchClient, IOUtils, SongInfoUtils


'''QobuzMusicClient'''
class QobuzMusicClient(BaseMusicClient):
    source = 'QobuzMusicClient'
    APP_ID = None
    SECRETS = None
    MUSIC_QUALITIES = (27, 7, 6, 5)
    get_token_func = lambda cookies, *keys: next((cookies.get(k) for k in keys if cookies.get(k)), None)
    def __init__(self, **kwargs):
        super(QobuzMusicClient, self).__init__(**kwargs)
        if self.default_search_cookies: assert QobuzMusicClient.get_token_func(self.default_search_cookies, "user_auth_token", "X-User-Auth-Token", "x-user-auth-token"), '"x-user-auth-token" should be configured, refer to https://musicdl.readthedocs.io/en/latest/Quickstart.html#qobuz-music-download'
        if self.default_parse_cookies: assert QobuzMusicClient.get_token_func(self.default_parse_cookies, "user_auth_token", "X-User-Auth-Token", "x-user-auth-token"), '"x-user-auth-token" should be configured, refer to https://musicdl.readthedocs.io/en/latest/Quickstart.html#qobuz-music-download'
        if self.default_download_cookies: assert QobuzMusicClient.get_token_func(self.default_download_cookies, "user_auth_token", "X-User-Auth-Token", "x-user-auth-token"), '"x-user-auth-token" should be configured, refer to https://musicdl.readthedocs.io/en/latest/Quickstart.html#qobuz-music-download'
        self.default_search_headers = {
            "accept": "*/*", "accept-encoding": "gzip, deflate, br, zstd", "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7", "origin": "https://play.qobuz.com", "priority": "u=1, i", "referer": "https://play.qobuz.com/", "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"', "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-site", "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36", 
        }
        self.default_parse_headers = {
            "accept": "*/*", "accept-encoding": "gzip, deflate, br, zstd", "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7", "origin": "https://play.qobuz.com", "priority": "u=1, i", "referer": "https://play.qobuz.com/", "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"', "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-site", "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        }
        self.default_download_headers = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"}
        if self.default_search_cookies: self.default_search_headers.update({'X-User-Auth-Token': QobuzMusicClient.get_token_func(self.default_search_cookies, "user_auth_token", "X-User-Auth-Token", "x-user-auth-token")})
        if self.default_parse_cookies: self.default_parse_headers.update({'X-User-Auth-Token': QobuzMusicClient.get_token_func(self.default_parse_cookies, "user_auth_token", "X-User-Auth-Token", "x-user-auth-token")})
        if self.default_download_cookies: self.default_download_headers.update({'X-User-Auth-Token': QobuzMusicClient.get_token_func(self.default_download_cookies, "user_auth_token", "X-User-Auth-Token", "x-user-auth-token")})
        self.default_headers = self.default_search_headers; self.default_search_cookies = {}; self.default_parse_cookies = {}; self.default_download_cookies = {}
        self._initsession()
    '''_setappidandsecrets'''
    def _setappidandsecrets(self, request_overrides: dict = None) -> tuple[str, list[str]]:
        if (QobuzMusicClient.APP_ID is not None) and (QobuzMusicClient.SECRETS is not None): self.default_headers.update({"X-App-Id": QobuzMusicClient.APP_ID}); return
        (resp := self.get("https://play.qobuz.com/login", **(request_overrides := request_overrides or {}))).raise_for_status()
        bundle_url = re.search(r'<script src="(/resources/\d+\.\d+\.\d+-[a-z]\d{3}/bundle\.js)"></script>', resp.text).group(1)
        (resp := self.get(urljoin("https://play.qobuz.com", bundle_url), **request_overrides)).raise_for_status()
        app_id = str(re.search(r'production:{api:{appId:"(?P<app_id>\d{9})",appSecret:"(\w{32})', resp.text).group("app_id"))
        seed_matches, secrets = re.finditer(r'[a-z]\.initialSeed\("(?P<seed>[\w=]+)",window\.utimezone\.(?P<timezone>[a-z]+)\)', resp.text), OrderedDict()
        secrets.update({timezone: [seed] for match in seed_matches for seed, timezone in [match.group("seed", "timezone")]}); secrets.move_to_end(list(secrets.items())[1][0], last=False)
        info_extras_regex = r'name:"\w+/(?P<timezone>{timezones})",info:"(?P<info>[\w=]+)",extras:"(?P<extras>[\w=]+)"'.format(timezones="|".join(str(timezone).capitalize() for timezone in secrets))
        for match in re.finditer(info_extras_regex, resp.text): timezone, info, extras = match.group("timezone", "info", "extras"); secrets[timezone.lower()] += [info, extras]
        for secret_pair in secrets: secrets[secret_pair] = base64.standard_b64decode("".join(secrets[secret_pair])[:-44]).decode("utf-8")
        QobuzMusicClient.APP_ID, QobuzMusicClient.SECRETS = app_id, [v for v in secrets.values() if v != ""]
        self.default_headers.update({"X-App-Id": QobuzMusicClient.APP_ID})
        return QobuzMusicClient.APP_ID, QobuzMusicClient.SECRETS
    '''_constructsearchurls'''
    def _constructsearchurls(self, keyword: str, rule: dict = None, request_overrides: dict = None):
        # init
        rule, request_overrides = rule or {}, request_overrides or {}; self._setappidandsecrets(request_overrides=request_overrides)
        (default_rule := {'query': keyword, 'offset': 0, 'limit': 10}).update(rule)
        # construct search urls
        search_urls, page_size, count, base_url = [], self.search_size_per_page, 0, 'https://www.qobuz.com/api.json/0.2/catalog/search?'
        while self.search_size_per_source > count:
            (page_rule := copy.deepcopy(default_rule))['limit'] = page_size
            page_rule['offset'] = count
            search_urls.append(base_url + urlencode(page_rule))
            count += page_size
        # return
        return search_urls
    '''_parsewithdabyeetsuapi'''
    def _parsewithdabyeetsuapi(self, search_result: dict, request_overrides: dict = None):
        # init
        request_overrides, song_id, headers = request_overrides or {}, str(search_result['id']), {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",}
        # parse
        for music_quality in QobuzMusicClient.MUSIC_QUALITIES:
            (resp := requests.get(f"https://dab.yeet.su/api/stream?trackId={song_id}&quality={music_quality}", headers=headers, timeout=10, **request_overrides)).raise_for_status()
            if not (download_url := safeextractfromdict((download_result := resp2json(resp=resp)), ['url'], '')) or not str(download_url).startswith('http'): continue
            real_music_quality = real_music_quality[0] if isinstance((real_music_quality := parse_qs(urlparse(str(download_url)).query, keep_blank_values=True).get('fmt') or music_quality), list) else real_music_quality
            download_url_status: dict = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
            song_info = SongInfo(
                raw_data={'search': search_result, 'download': download_result, 'lyric': {}, 'quality': real_music_quality}, source=self.source, song_name=legalizestring(search_result.get('title')), singers=legalizestring(safeextractfromdict(search_result, ['performer', 'name'], None)), album=legalizestring(safeextractfromdict(search_result, ['album', 'title'], None)), ext=download_url_status['ext'], file_size_bytes=download_url_status['file_size_bytes'], 
                file_size=download_url_status['file_size'], identifier=song_id, duration_s=int(float(search_result.get('duration') or 0)), duration=SongInfoUtils.seconds2hms(int(float(search_result.get('duration') or 0))), lyric=None, cover_url=safeextractfromdict(search_result, ['album', 'image', 'large'], None), download_url=download_url_status['download_url'], download_url_status=download_url_status, 
            )
            if song_info.with_valid_download_url and song_info.ext in AudioLinkTester.VALID_AUDIO_EXTS: break
        # return
        return song_info
    '''_parsewithdabmusicapi'''
    def _parsewithdabmusicapi(self, search_result: dict, request_overrides: dict = None):
        # init
        request_overrides, song_id, headers = request_overrides or {}, str(search_result['id']), {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",}
        # parse
        for music_quality in QobuzMusicClient.MUSIC_QUALITIES:
            (resp := requests.get(f"https://dabmusic.xyz/api/stream?trackId={song_id}&quality={music_quality}", headers=headers, timeout=10, **request_overrides)).raise_for_status()
            if not (download_url := safeextractfromdict((download_result := resp2json(resp=resp)), ['url'], '')) or not str(download_url).startswith('http'): continue
            real_music_quality = real_music_quality[0] if isinstance((real_music_quality := parse_qs(urlparse(str(download_url)).query, keep_blank_values=True).get('fmt') or music_quality), list) else real_music_quality
            download_url_status: dict = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
            song_info = SongInfo(
                raw_data={'search': search_result, 'download': download_result, 'lyric': {}, 'quality': real_music_quality}, source=self.source, song_name=legalizestring(search_result.get('title')), singers=legalizestring(safeextractfromdict(search_result, ['performer', 'name'], None)), album=legalizestring(safeextractfromdict(search_result, ['album', 'title'], None)), ext=download_url_status['ext'], file_size_bytes=download_url_status['file_size_bytes'], 
                file_size=download_url_status['file_size'], identifier=song_id, duration_s=int(float(search_result.get('duration') or 0)), duration=SongInfoUtils.seconds2hms(int(float(search_result.get('duration') or 0))), lyric=None, cover_url=safeextractfromdict(search_result, ['album', 'image', 'large'], None), download_url=download_url_status['download_url'], download_url_status=download_url_status, 
            )
            if song_info.with_valid_download_url and song_info.ext in AudioLinkTester.VALID_AUDIO_EXTS: break
        # return
        return song_info
    '''_parsewithafkarxyzapi'''
    def _parsewithafkarxyzapi(self, search_result: dict, request_overrides: dict = None):
        # init
        request_overrides, song_id, headers = request_overrides or {}, str(search_result['id']), {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",}
        song_info = SongInfo(source=self.source, raw_data={'search': search_result, 'download': {}, 'lyric': {}, 'quality': QobuzMusicClient.MUSIC_QUALITIES[-1]})
        # parse
        (resp := requests.get(f"https://qbz.afkarxyz.qzz.io/api/track/{song_id}", headers=headers, timeout=10, **request_overrides)).raise_for_status()
        if not (download_url := safeextractfromdict((download_result := resp2json(resp=resp)), ['url'], '')) or not str(download_url).startswith('http'): return song_info
        real_music_quality = real_music_quality[0] if isinstance((real_music_quality := parse_qs(urlparse(str(download_url)).query, keep_blank_values=True).get('fmt') or QobuzMusicClient.MUSIC_QUALITIES[-1]), list) else real_music_quality
        download_url_status: dict = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
        song_info = SongInfo(
            raw_data={'search': search_result, 'download': download_result, 'lyric': {}, 'quality': real_music_quality}, source=self.source, song_name=legalizestring(search_result.get('title')), singers=legalizestring(safeextractfromdict(search_result, ['performer', 'name'], None)), album=legalizestring(safeextractfromdict(search_result, ['album', 'title'], None)), ext=download_url_status['ext'], file_size_bytes=download_url_status['file_size_bytes'], 
            file_size=download_url_status['file_size'], identifier=song_id, duration_s=int(float(search_result.get('duration') or 0)), duration=SongInfoUtils.seconds2hms(int(float(search_result.get('duration') or 0))), lyric=None, cover_url=safeextractfromdict(search_result, ['album', 'image', 'large'], None), download_url=download_url_status['download_url'], download_url_status=download_url_status, 
        )
        # return
        return song_info
    '''_parsewiththirdpartapis'''
    def _parsewiththirdpartapis(self, search_result: dict, request_overrides: dict = None):
        if QobuzMusicClient.get_token_func(self.default_headers, "X-User-Auth-Token", "x-user-auth-token"): return SongInfo(source=self.source, raw_data={'quality': QobuzMusicClient.MUSIC_QUALITIES[-1]})
        for parser_func in [self._parsewithdabmusicapi, self._parsewithdabyeetsuapi, self._parsewithafkarxyzapi]:
            song_info_flac = SongInfo(source=self.source, raw_data={'search': search_result, 'download': {}, 'lyric': {}, 'quality': QobuzMusicClient.MUSIC_QUALITIES[-1]})
            with suppress(Exception): song_info_flac = parser_func(search_result, request_overrides)
            if song_info_flac.with_valid_download_url and song_info_flac.ext in AudioLinkTester.VALID_AUDIO_EXTS: break
        return song_info_flac
    '''_parsewithofficialapiv1'''
    def _parsewithofficialapiv1(self, search_result: dict, song_info_flac: SongInfo = None, lossless_quality_is_sufficient: bool = True, lossless_quality_definitions: set | list | tuple = {'flac'}, request_overrides: dict = None) -> "SongInfo":
        # init
        song_info = SongInfo(source=self.source, raw_data={'search': search_result, 'download': {}, 'lyric': {}, 'quality': QobuzMusicClient.MUSIC_QUALITIES[-1]})
        request_overrides, song_info_flac = request_overrides or {}, song_info_flac or copy.deepcopy(song_info); self._setappidandsecrets(request_overrides=request_overrides)
        if (not isinstance(search_result, dict)) or (not (song_id := search_result.get('id'))): return song_info
        # parse download url based on arguments
        if lossless_quality_is_sufficient and song_info_flac.with_valid_download_url and (song_info_flac.ext in lossless_quality_definitions): song_info = song_info_flac
        else:
            for (music_quality, secret) in list(product(QobuzMusicClient.MUSIC_QUALITIES, QobuzMusicClient.SECRETS)):
                if song_info_flac.with_valid_download_url and QobuzMusicClient.MUSIC_QUALITIES.index(music_quality) >= QobuzMusicClient.MUSIC_QUALITIES.index(song_info_flac.raw_data.get('quality', QobuzMusicClient.MUSIC_QUALITIES[-1])): song_info = song_info_flac; break
                r_sig = f"trackgetFileUrlformat_id{music_quality}intentstreamtrack_id{song_id}{(unix_ts := time.time())}{secret}"
                params = {"request_ts": unix_ts, "request_sig": hashlib.md5(r_sig.encode("utf-8")).hexdigest(), "track_id": song_id, "format_id": music_quality, "intent": "stream"}
                with suppress(Exception): resp = None; (resp := self.get('https://www.qobuz.com/api.json/0.2/track/getFileUrl', params=params, **request_overrides)).raise_for_status()
                if not locals().get('resp') or not hasattr(locals().get('resp'), 'text'): continue
                if not (download_url := safeextractfromdict((download_result := resp2json(resp=resp)), ['url'], None)) or not str(download_url).startswith('http'): continue
                download_url_status: dict = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
                song_info = SongInfo(
                    raw_data={'search': search_result, 'download': download_result, 'lyric': {}, 'quality': music_quality}, source=self.source, song_name=legalizestring(search_result.get('title')), singers=legalizestring(safeextractfromdict(search_result, ['performer', 'name'], None)), album=legalizestring(safeextractfromdict(search_result, ['album', 'title'], None)), ext=download_url_status['ext'], file_size_bytes=download_url_status['file_size_bytes'], 
                    file_size=download_url_status['file_size'], identifier=song_id, duration_s=int(float(download_result.get('duration') or 0)), duration=SongInfoUtils.seconds2hms(int(float(download_result.get('duration') or 0))), lyric=None, cover_url=safeextractfromdict(search_result, ['album', 'image', 'large'], None), download_url=download_url_status['download_url'], download_url_status=download_url_status, 
                )
                if song_info_flac.with_valid_download_url and song_info_flac.largerthan(song_info): song_info = song_info_flac
                if song_info_flac.with_valid_download_url and song_info_flac.ext in AudioLinkTester.VALID_AUDIO_EXTS: break
        if not (song_info := song_info if song_info.with_valid_download_url else song_info_flac).with_valid_download_url or song_info.ext not in AudioLinkTester.VALID_AUDIO_EXTS: return song_info
        # supplement lyric results
        lyric_result, lyric = LyricSearchClient().search(artist_name=song_info.singers, track_name=song_info.song_name, request_overrides=request_overrides)
        song_info.raw_data['lyric'] = lyric_result if lyric_result else song_info.raw_data['lyric']
        song_info.lyric = lyric if (lyric and (lyric not in {'NULL'})) else song_info.lyric
        # return
        return song_info
    '''_search'''
    @usesearchheaderscookies
    def _search(self, keyword: str = '', search_url: str = '', request_overrides: dict = None, song_infos: list = [], progress: Progress = None, progress_id: int = 0):
        # init
        request_overrides, lossless_quality_is_sufficient = request_overrides or {}, False if QobuzMusicClient.get_token_func(self.default_headers, "X-User-Auth-Token", "x-user-auth-token") else True; self._setappidandsecrets(request_overrides=request_overrides)
        # successful
        try:
            # --search results
            (resp := self.get(search_url, **request_overrides)).raise_for_status()
            for search_result in resp2json(resp)['tracks']['items']:
                song_info = SongInfo(source=self.source, raw_data={'search': search_result, 'download': {}, 'lyric': {}, 'quality': QobuzMusicClient.MUSIC_QUALITIES[-1]})
                # --parse with third part apis
                song_info_flac = self._parsewiththirdpartapis(search_result=search_result, request_overrides=request_overrides)
                # --parse with official apis
                with suppress(Exception): song_info = self._parsewithofficialapiv1(search_result=search_result, song_info_flac=song_info_flac, lossless_quality_is_sufficient=lossless_quality_is_sufficient, request_overrides=request_overrides)
                # --append to song_infos
                if (song_info := song_info if song_info.with_valid_download_url else song_info_flac).with_valid_download_url: song_infos.append(song_info)
                # --judgement for search_size
                if self.strict_limit_search_size_per_page and len(song_infos) >= self.search_size_per_page: break
            # --update progress
            progress.update(progress_id, description=f"{self.source}._search >>> {search_url} (Success)")
        # failure
        except Exception as err:
            progress.update(progress_id, description=f"{self.source}._search >>> {search_url} (Error: {err})")
            self.logger_handle.error(f"{self.source}._search >>> {search_url} (Error: {err})", disable_print=self.disable_print)
        # return
        return song_infos
    '''parseplaylist'''
    @useparseheaderscookies
    def parseplaylist(self, playlist_url: str, request_overrides: dict = None):
        # init
        playlist_url = self.session.head(playlist_url, allow_redirects=True, **(request_overrides := dict(request_overrides or {}))).url
        playlist_id, song_infos = urlparse(playlist_url).path.strip('/').split('/')[-1].removesuffix('.html').removesuffix('.htm'), []
        if (not (hostname := obtainhostname(url=playlist_url))) or (not hostmatchessuffix(hostname, QOBUZ_MUSIC_HOSTS)): return song_infos
        # get tracks in playlist
        tracks_in_playlist, page, page_size, playlist_result_first = [], 1, 500, {}; self._setappidandsecrets()
        while True:
            with suppress(Exception): (resp := self.get("https://www.qobuz.com/api.json/0.2/playlist/get?", params={"playlist_id": playlist_id, "extra": 'tracks', "offset": (page-1)*page_size, 'limit': page_size}, **request_overrides)).raise_for_status()
            if not locals().get('resp') or not hasattr(locals().get('resp'), 'text') or (not safeextractfromdict((playlist_result := resp2json(resp=resp)), ['tracks', 'items'], [])): break
            tracks_in_playlist.extend(safeextractfromdict(playlist_result, ['tracks', 'items'], [])); page += 1; del resp
            if not playlist_result_first: playlist_result_first = copy.deepcopy(playlist_result)
            if (float(safeextractfromdict(playlist_result, ['tracks', 'total'], 0)) <= len(tracks_in_playlist)): break
        tracks_in_playlist = list({d["id"]: d for d in tracks_in_playlist}.values())
        # parse track by track in playlist
        with Progress(TextColumn("{task.description}"), BarColumn(bar_width=None), MofNCompleteColumn(), TimeRemainingColumn(), refresh_per_second=10) as main_process_context:
            main_progress_id = main_process_context.add_task(f"{len(tracks_in_playlist)} Songs Found in Playlist {playlist_id} >>> Completed (0/{len(tracks_in_playlist)}) SongInfo", total=len(tracks_in_playlist))
            for idx, track_info in enumerate(tracks_in_playlist):
                if idx > 0: main_process_context.advance(main_progress_id, 1); main_process_context.update(main_progress_id, description=f"{len(tracks_in_playlist)} Songs Found in Playlist {playlist_id} >>> Completed ({idx}/{len(tracks_in_playlist)}) SongInfo")
                song_info = SongInfo(source=self.source, raw_data={'search': track_info, 'download': {}, 'lyric': {}, 'quality': QobuzMusicClient.MUSIC_QUALITIES[-1]})
                song_info_flac = self._parsewiththirdpartapis(search_result=track_info, request_overrides=request_overrides)
                lossless_quality_is_sufficient = False if self.default_cookies or request_overrides.get('cookies') else True
                with suppress(Exception): song_info = self._parsewithofficialapiv1(search_result=track_info, song_info_flac=song_info_flac, lossless_quality_is_sufficient=lossless_quality_is_sufficient, request_overrides=request_overrides)
                if (song_info := song_info if song_info.with_valid_download_url else song_info_flac).with_valid_download_url: song_infos.append(song_info)
            main_process_context.advance(main_progress_id, 1); main_process_context.update(main_progress_id, description=f"{len(tracks_in_playlist)} Songs Found in Playlist {playlist_id} >>> Completed ({idx+1}/{len(tracks_in_playlist)}) SongInfo")
        # post processing
        playlist_name = legalizestring(safeextractfromdict(playlist_result_first, ['name'], None) or f"playlist-{playlist_id}")
        song_infos, work_dir = self._removeduplicates(song_infos=song_infos), self._constructuniqueworkdir(keyword=playlist_name)
        for song_info in song_infos:
            song_info.work_dir, episodes = work_dir, song_info.episodes if isinstance(song_info.episodes, list) else []
            for eps_info in episodes: eps_info.work_dir = sanitize_filepath(os.path.join(work_dir, f"{song_info.song_name} - {song_info.singers}")); IOUtils.touchdir(eps_info.work_dir)
        # return results
        return song_infos