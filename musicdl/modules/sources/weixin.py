'''
Function:
    Implementation of WeixinMusicClient: 微信公众号音乐(音频/视频 -> 音频)
    - 检索: 搜狗微信搜索(type=2, 文章) -> 解析 mp.weixin.qq.com 正文
    - 音频: 正文 <mpvoice> -> res.wx.qq.com/voice/getvoice?mediaid=<voice_encode_fileid> (裸 MP3, 免鉴权)
    - 视频: 正文腾讯视频 iframe -> vv.video.qq.com/getinfo(platform=11001) 取 fvkey -> 直链(m4a)
    注意: 搜狗的 /link 跳转页有反爬, 普通 requests 会被打到 antispider 页; 必须先用带浏览器的 TLS
         指纹访问首页拿到 SUID/SNUID cookie, 再带着同一会话去解析跳转。
Author:
    Zhenchao Jin ( base ) / wk-hours ( weixin adapter )
WeChat Official Account (微信公众号):
    Charles的皮卡丘
'''
import re
import html
import json
import copy
import time
import uuid
import random
import threading
from collections import OrderedDict
from contextlib import suppress
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing_extensions import Unpack
from urllib.parse import quote_plus, urlparse, parse_qs
from rich.progress import Progress
from .base import BaseMusicClient, BaseMusicClientKwargs
from ..utils import legalizestring, usesearchheaderscookies, optionalimport, AudioLinkTester, SongInfo, SongInfoUtils


'''常量'''
SOGOU_HOME_URL = 'https://weixin.sogou.com/'
SOGOU_SEARCH_URL = 'https://weixin.sogou.com/weixin?type=2&query={keyword}&ie=utf8'
VOICE_URL = 'https://res.wx.qq.com/voice/getvoice?mediaid={mediaid}'
QQVIDEO_GETINFO_URL = ('https://vv.video.qq.com/getinfo?vids={vid}&otype=json&platform=11001&charge=0&defn=shd'
                       '&guid={guid}&sdtfrom=v1010&host=v.qq.com')
CHROME_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/134.0.0.0 Safari/537.36")
# 标题含这些词 => 正文大概率有可听内容, 加权前置
AUDIO_HINT_WORDS = ('演唱', '演奏', '弹唱', '合唱', '清唱', '示范', '听听', '欣赏', '有声', '音频', '声音', '原声', '翻唱', '伴奏', '弹拨', '独奏')
# 标题含这些词 => 多为歌词/谱例/公告类文章, 没有可解析的音频, 直接降权到末尾
AUDIO_BLOCK_WORDS = ('歌词', '简谱', '歌谱', '曲谱', '歌单', '报名', '招生', '培训', '通知', '纪要', '综述', '征文', '征集', '论文', '招聘', '方案', '课例')


'''WeixinSogouBlocked: 搜狗反爬/限流, 需要对外可见(前端会显示红色 ! 而不是假装 0 条结果)'''
class WeixinSogouBlocked(Exception):
    pass


'''WeixinMusicClient'''
class WeixinMusicClient(BaseMusicClient):
    source = 'WeixinMusicClient'
    # 单次搜索最多抓取的文章数(每篇正文 1~4MB, 这是耗时的主要来源)
    MAX_ARTICLES = 6
    # 单篇文章最多提取的音频条目
    MAX_AUDIO_PER_ARTICLE = 3
    # 单篇文章最多走"视频->音频"通道的条目
    MAX_VIDEO_PER_ARTICLE = 2
    ARTICLE_WORKERS = 3
    # 搜狗反爬: 同 IP 连续高频请求会被打到 antispider 页, 必须串行 + 抖动 + 冷却
    SOGOU_COOLDOWN_SEC = 45
    SOGOU_CACHE_TTL_SEC = 6 * 3600
    # 类级共享状态: 限流是按 IP 计的, 同一进程里的多个实例应当共同退让
    _sogou_lock = threading.Lock()
    _sogou_cooldown_until = 0.0
    _search_page_cache = OrderedDict()
    _link_cache = OrderedDict()

    def __init__(self, **kwargs: Unpack[BaseMusicClientKwargs]):
        super(WeixinMusicClient, self).__init__(**kwargs)
        self.default_search_headers = {
            "User-Agent": CHROME_UA, "Referer": "https://weixin.sogou.com/",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        }
        self.default_download_headers = {
            "User-Agent": CHROME_UA, "Referer": "https://mp.weixin.qq.com/",
            "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self.default_headers = self.default_search_headers
        self.default_search_cookies = self.default_search_cookies or {}
        self.default_download_cookies = self.default_download_cookies or {}
        self.default_cookies = self.default_search_cookies
        self._initsession()
        # 自带会话: 走浏览器 TLS 指纹, 与 base 的 session 分开维护; 会话不带锁, 按线程隔离
        self._tls = threading.local()
    '''_clean'''
    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r'\s+', ' ', html.unescape(str(text or '')).replace('\xa0', ' ')).strip()
    '''_wxsession'''
    def _wxsession(self):
        """构造带浏览器 TLS 指纹的会话(按线程隔离); curl_cffi 不可用时退回普通 requests(搜狗跳转大概率失败)"""
        session = getattr(self._tls, 'session', None)
        if session is not None:
            return session
        session = None
        curl_cffi = optionalimport('curl_cffi')
        if curl_cffi is not None:
            with suppress(Exception):
                session = curl_cffi.requests.Session(impersonate='chrome')
        if session is None:
            import requests
            session = requests.Session()
        session.headers.update({
            'User-Agent': CHROME_UA, 'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': 'https://weixin.sogou.com/',
        })
        self._tls.session, self._tls.warmed = session, False
        return session
    '''_warmup'''
    def _warmup(self, session):
        """首次访问首页拿 SUID/SNUID; 缺了它, /link 跳转会被判定为爬虫"""
        if getattr(self._tls, 'warmed', False):
            return
        self._tls.warmed = True
        with suppress(Exception):
            session.get(SOGOU_HOME_URL, timeout=(6, 15))
    '''_wxget'''
    def _wxget(self, url: str, referer: str = '', allow_redirects: bool = True, timeout=(8, 25)):
        session = self._wxsession()
        self._warmup(session)
        headers = {'Referer': referer} if referer else None
        for attempt in range(2):
            if attempt:
                time.sleep(0.4 + random.random() * 0.6)
                # 重建会话: 清掉过期 cookie 后重新到首页取票
                self._tls.session = None
                session = self._wxsession(); self._warmup(session)
            try:
                resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=allow_redirects)
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            page = (resp.text or '')[:4000]
            if 'antispider' in str(getattr(resp, 'url', '') or '') or 'antispider' in page or '请输入验证码' in page:
                continue
            return resp
        return None
    '''_sogouget'''
    def _sogouget(self, url: str, referer: str = 'https://weixin.sogou.com/', cache_key: str = None, timeout=(8, 25)):
        """所有打向搜狗的请求都要过这里: 串行 + 抖动 + 冷却 + 短时缓存, 少触发反爬"""
        cls = WeixinMusicClient
        cached = cls._search_page_cache.get(cache_key) if cache_key else None
        if cached and time.time() - cached[0] < self.SOGOU_CACHE_TTL_SEC:
            return cached[1]
        wait = cls._sogou_cooldown_until - time.time()
        if wait > 0:
            raise WeixinSogouBlocked(f'搜狗微信检索限流中, 请 {int(wait) + 1} 秒后再试')
        with cls._sogou_lock:
            time.sleep(0.15 + random.random() * 0.35)
            resp = self._wxget(url, referer=referer, timeout=timeout)
        if resp is None:
            # 触发反爬: 设冷却, 明确抛出而不是静默返回空
            cls._sogou_cooldown_until = time.time() + self.SOGOU_COOLDOWN_SEC
            raise WeixinSogouBlocked('搜狗微信检索触发反爬校验, 已冷却 45 秒')
        if cache_key:
            cls._search_page_cache[cache_key] = (time.time(), resp.text)
            while len(cls._search_page_cache) > 200:
                cls._search_page_cache.popitem(last=False)
        return resp.text
    '''_constructsearchurls'''
    def _constructsearchurls(self, keyword: str, rule: dict = None, request_overrides: dict = None):
        # init
        rule, request_overrides = rule or {}, request_overrides or {}
        (default_rule := {'page': 1}).update(rule)
        page = max(int(default_rule.get('page', 1) or 1), 1)
        # 搜狗微信搜索的文章结果质量远高于翻页产出, 只取第一页
        return [SOGOU_SEARCH_URL.format(keyword=quote_plus(str(keyword)))] if page == 1 else []
    '''_parsesearchpage'''
    def _parsesearchpage(self, search_page: str) -> list:
        """搜狗结果页 -> [(标题, 中转链接)]; 含音频线索词的排前面, 歌词/公告类降到最后"""
        scored = []
        pattern = r'<h3>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
        if not re.search(pattern, search_page or '', flags=re.S):
            pattern = r'<a[^>]+href="(/link\?url=[^"]+)"[^>]*>(.*?)</a>'
        for href, raw_title in re.findall(pattern, search_page or '', flags=re.S):
            title = self._clean(re.sub(r'<[^>]+>', '', raw_title))
            if not title:
                continue
            link = href if href.startswith('http') else 'https://weixin.sogou.com' + href.replace('&amp;', '&')
            score = 0
            if any(w in title for w in AUDIO_HINT_WORDS): score += 10
            if any(w in title for w in ('歌', '曲', '音乐', '民谣', '调', '朗诵', '唱')): score += 2
            if any(w in title for w in AUDIO_BLOCK_WORDS): score -= 20
            scored.append((score, title, link))
        scored.sort(key=lambda x: -x[0])
        return [(title, link) for _, title, link in scored]
    '''_resolvesogoulink'''
    def _resolvesogoulink(self, link: str, referer: str = '') -> str:
        """搜狗中转页是 JS 拼接地址, 需要把片段拼回来才是真实 mp.weixin.qq.com 链接(结果按链接缓存)"""
        if 'weixin.sogou.com' not in link:
            return link
        cls = WeixinMusicClient
        if link in cls._link_cache:
            return cls._link_cache[link]
        page = self._sogouget(link, referer=referer or 'https://weixin.sogou.com/')
        parts = re.findall(r"url \+= '([^']*)'", page or '')
        article_url = ''.join(parts).replace('@', '') if parts else ''
        if article_url:
            cls._link_cache[link] = article_url
            while len(cls._link_cache) > 400:
                cls._link_cache.popitem(last=False)
        return article_url
    '''_extractpagectx'''
    def _extractpagectx(self, article_html: str) -> dict:
        ctx = {}
        for key in ('nickname', 'msg_title', 'msg_cdn_url', 'round_head_img', 'biz', 'mid', 'idx'):
            matched = re.search(rf'var {key} = ([\'"])(.*?)\1', article_html)
            if matched:
                ctx[key] = matched.group(2)
            elif key == 'nickname':
                matched = re.search(r'var nickname = htmlDecode\(([\'"])(.*?)\1\)', article_html)
                if matched: ctx[key] = matched.group(2)
        for key in ('msg_title', 'nickname'):
            if ctx.get(key): ctx[key] = self._clean(ctx[key])
        return ctx
    '''_parseaudiotags'''
    def _parseaudiotags(self, article_html: str) -> list:
        """<mpvoice> 原生音频标签 -> 条目列表"""
        items = []
        for tag in re.findall(r'<mpvoice[^>]*>', article_html)[:self.MAX_AUDIO_PER_ARTICLE]:
            attrs = dict(re.findall(r'([a-z_]+)="([^"]*)"', tag))
            mediaid = (attrs.get('voice_encode_fileid') or '').strip()
            if not mediaid:
                continue
            name = self._clean(attrs.get('name', ''))
            try: duration_ms = int(float(attrs.get('play_length', '0') or 0))
            except Exception: duration_ms = 0
            size_kb = 0.0
            for key in ('high_size', 'source_size', 'low_size'):
                try:
                    if attrs.get(key): size_kb = float(attrs[key]); break
                except Exception: continue
            items.append({
                'kind': 'audio', 'name': name, 'duration_s': int(duration_ms / 1000),
                'file_size_bytes': int(size_kb * 1024), 'identifier': 'wxvoice-' + mediaid,
                'download_url': VOICE_URL.format(mediaid=mediaid), 'ext': 'mp3',
            })
        return items
    '''_parsevideoids'''
    def _parsevideoids(self, article_html: str) -> list:
        """正文里的腾讯视频 vid -> [vid]"""
        vids, seen = [], []
        patterns = [
            r'<iframe[^>]+(?:data-src|src)="([^"]*v\.qq\.com[^"]*)"',
            r'https?://v\.qq\.com/(?:txp/iframe/player\.html|iframe/preview\.html|x/cover/[^/]+/)([A-Za-z0-9]+)\.html',
        ]
        candidates = []
        for pattern in patterns:
            candidates.extend(re.findall(pattern, article_html, flags=re.S))
        for candidate in candidates:
            candidate = html.unescape(candidate)
            vid = ''
            if candidate.startswith('http'):
                query = parse_qs(urlparse(candidate).query or '')
                vid = ((query.get('vid') or [''])[0] or '').strip()
                if not vid:
                    matched = re.search(r'/([A-Za-z0-9]{8,})\.html', candidate)
                    vid = matched.group(1) if matched else ''
            elif re.fullmatch(r'[A-Za-z0-9]{8,}', candidate):
                vid = candidate
            if vid and vid not in seen:
                seen.append(vid)
            if len(seen) >= self.MAX_VIDEO_PER_ARTICLE:
                break
        return seen
    '''_qqvideourl'''
    def _qqvideourl(self, vid: str):
        """腾讯视频 vid -> (直链, 标题, 时长秒); fvkey 只有在带 guid/sdtfrom/host 时才返回, 缺了会 client not auth"""
        resp = self._wxget(QQVIDEO_GETINFO_URL.format(vid=vid, guid=uuid.uuid4().hex.upper()),
                           referer='https://v.qq.com/')
        if resp is None:
            return None
        text = (resp.text or '').strip()
        matched = re.search(r'QZOutputJson\s*=\s*(.*)', text, flags=re.S)
        if matched:
            text = matched.group(1).strip().rstrip(';')
        try:
            video_info = json.loads(text)['vl']['vi'][0]
        except Exception:
            return None
        filename, fvkey = (video_info.get('fn') or ''), (video_info.get('fvkey') or '')
        ui_list = (video_info.get('ul') or {}).get('ui') or [{}]
        base_url = (ui_list[0] or {}).get('url') or ''
        if not (filename and fvkey and base_url):
            return None
        if not base_url.endswith('/'):
            base_url += '/'
        try: duration_s = int(float(video_info.get('td') or 0))
        except Exception: duration_s = 0
        return f'{base_url}{filename}?vkey={fvkey}', self._clean(video_info.get('ti') or ''), duration_s
    '''_harvestarticle'''
    def _harvestarticle(self, title: str, article_url: str) -> list:
        """单篇文章正文 -> [{音频条目}], 原生音频不足时用视频通道补齐"""
        if 'mp.weixin.qq.com' not in (article_url or ''):
            return []
        resp = self._wxget(article_url, referer='https://weixin.sogou.com/', timeout=(8, 30))
        if resp is None:
            return []
        article_html = resp.text or ''
        ctx = self._extractpagectx(article_html)
        nickname = ctx.get('nickname') or '微信公众号'
        article_title = ctx.get('msg_title') or title
        cover_url = ctx.get('msg_cdn_url') or ctx.get('round_head_img') or ''
        items = []
        for item in self._parseaudiotags(article_html):
            items.append(dict(item, singers=nickname, album=article_title, cover_url=cover_url, article_url=article_url))
        # 视频 -> 音频: 仅在原生音频不足时启用, 避免主结果里混入大量视频
        if not items:
            for vid in self._parsevideoids(article_html):
                parsed = self._qqvideourl(vid)
                if not parsed:
                    continue
                download_url, video_title, duration_s = parsed
                items.append({
                    'kind': 'video', 'name': video_title or article_title, 'duration_s': duration_s, 'file_size_bytes': 0,
                    'identifier': f'wxvideo-{vid}', 'download_url': download_url, 'ext': 'm4a',
                    'singers': nickname, 'album': article_title, 'cover_url': cover_url, 'article_url': article_url,
                })
        return items
    '''_search'''
    @usesearchheaderscookies
    def _search(self, keyword: str = '', search_url: str = '', request_overrides: dict = None, song_infos: list = [], progress: Progress = None, progress_id: int = 0):
        # init
        request_overrides, want = dict(request_overrides or {}), max(self.search_size_per_source, 1)
        # 搜狗结果页(带短时缓存: 同一关键词重复搜索不再重复请求, 有效降低被风控的概率)
        search_page = self._sogouget(search_url, referer='https://weixin.sogou.com/', cache_key='page:' + search_url)
        candidates = self._parsesearchpage(search_page or '')
        if not candidates:
            return []
        # 阶段一: 串行解析搜狗中转链接(只有这部分打搜狗), 拿到真实文章地址
        articles = []
        for title, link in candidates[:self.MAX_ARTICLES]:
            try:
                article_url = self._resolvesogoulink(link, referer=search_url)
            except WeixinSogouBlocked:
                if not articles: raise
                break
            if 'mp.weixin.qq.com' in (article_url or ''):
                articles.append((title, article_url))
        if not articles:
            return []
        # 阶段二: 正文抓取(mp.weixin 域, 不占搜狗配额) -> 并行
        raw = []
        with ThreadPoolExecutor(max_workers=self.ARTICLE_WORKERS) as pool:
            futures = [pool.submit(self._harvestarticle, title, article_url) for title, article_url in articles]
            for future in as_completed(futures):
                try: raw.extend(future.result() or [])
                except Exception: continue
        # 原生音频优先, 视频 -> 音频作补充
        audio_items = [item for item in raw if item.get('kind') == 'audio']
        video_items = [item for item in raw if item.get('kind') != 'audio']
        collected, seen = [], set()
        for item in audio_items + video_items:
            if len(collected) >= want:
                break
            downloaded_url = (item.get('download_url') or '').strip()
            identifier = item.get('identifier') or ''
            if not downloaded_url or identifier in seen:
                continue
            seen.add(identifier)
            song_name = legalizestring(item.get('name') or '') or legalizestring(item.get('album') or '') or '未知曲目'
            duration_s = int(item.get('duration_s') or 0)
            file_size_bytes = int(item.get('file_size_bytes') or 0)
            ext = item.get('ext') or 'mp3'
            file_size = AudioLinkTester.byte2mb(file_size_bytes) if file_size_bytes else 'NULL'
            song_info = SongInfo(
                raw_data={'search': {'title': item.get('name'), 'article': item.get('album'), 'url': item.get('article_url')},
                          'download': {}, 'lyric': {}},
                source=self.source, song_name=song_name, singers=legalizestring(item.get('singers') or '') or '微信公众号',
                album=legalizestring(item.get('album') or '') or 'NULL', ext=ext, file_size_bytes=file_size_bytes,
                file_size=file_size, identifier=identifier, duration_s=duration_s,
                duration=SongInfoUtils.seconds2hms(duration_s) if duration_s else None, lyric='NULL',
                cover_url=item.get('cover_url') or '', download_url=downloaded_url,
                download_url_status={'ok': True, 'ext': ext, 'file_size_bytes': file_size_bytes,
                                     'file_size': file_size, 'download_url': downloaded_url},
                default_download_headers=copy.deepcopy(self.default_download_headers),
            )
            if song_info.with_valid_download_url:
                collected.append(song_info)
        song_infos.extend(collected)
        return collected
