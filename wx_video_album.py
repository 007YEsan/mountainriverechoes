#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""微信公众号文章 -> 微信文章库入库条目 (含 mpvoice 音频 + mpvideo 视频 + 腾讯视频 vid 兜底)

三类微信内容都走同一份输出 schema, 跟主程序 mountainriverechoes 的自愈链路对齐:

  - 音频:  res.wx.qq.com/voice/getvoice?mediaid=...     (getvoice 直链免鉴权, 永久)
  - 视频:  mpvideo.qpic.cn/<base>.f10004.mp4?dis_k=...  (mpvideo 签名, 时效约 2 天)
                                                    主程序自愈(_weixin_video_self_heal)回文章页重取
  - 兜底: ugchsy.gtimg.com/B_... 或 v.qq.com 合集     (qqvideourl 取 fvkey 直链, 短时效)

三条路径都在输出 JSON 里带 article_url + voice_id/qqvid-xxx 字段, WebUI 试听直链过期时
由 mountainriverechoes 的自愈逻辑(_refresh_weixin_link / _refresh_song_link)按这些线索回源续期。

支持的输入形态:

  A. 单篇微信公众号文章 URL
       ./venv/bin/python wx_video_album.py --url "https://mp.weixin.qq.com/s/xxx" --out one.json
       输出该篇里的全部 mpvoice + mpvideo + qqvid 条目

  B. 微信视频专辑 (albumType=5, biz + album_id)
       ./venv/bin/python wx_video_album.py --biz MzIxNjM2MzMxNg== --album 2087959757599932418 \
           --out harvest_plan/raw/瑶族_我是瑶人视频专辑.json
       自动翻页 action=paging 接口拿全专辑, 逐篇解析 mpvoice/mpvideo/qqvid
       加 --resume 同名文件可断点续抓 (按 msgid 跳过); --limit N 先试跑 N 篇。

  C. 从 JSON 文件批量指定文章列表 (每项含 url + msgid + cover 等)
       ./venv/bin/python wx_video_album.py --articles-file article_list.json --out batch.json

  D. 微信公众号合集 URL (mp/appmsgalbum?action=getalbum&album_id=...)
       ./venv/bin/python wx_video_album.py --album-url \
           "https://mp.weixin.qq.com/mp/appmsgalbum?__biz=X&action=getalbum&album_id=Y" \
           --out album.json
       自动从 URL 拆 __biz + album_id, 走 action=paging 翻页接口拿全(每页 20 条)。
       与 --biz --album 同底, 只是少一步手抄参数。
"""
import os
import re
import sys
import json
import time
import random
import argparse
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress

HERE = os.path.dirname(os.path.abspath(__file__))

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36')
SESS = requests.Session()
SESS.headers.update({'User-Agent': UA, 'Referer': 'https://mp.weixin.qq.com/'})


def _get(url, referer=None, timeout=(8, 30)):
    """会话级 GET。直链签名绑的是这个会话的 poc_sid cookie, 别处裸 requests 会 403。"""
    h = {}
    if referer:
        h['Referer'] = referer
    try:
        r = SESS.get(url, headers=h, timeout=timeout)
        return r.text or ''
    except Exception:
        return ''


# H.264 在前(浏览器 <audio> 可直接放), HEVC 只作兜底; 同族内小档在前(试听省流量)
FMT_PRIORITY = ('10004', '10002', '10104', '10102')

QQVIDEO_GETINFO_URL = ('https://vv.video.qq.com/getinfo?vids={vid}&otype=json&platform=11001&charge=0&defn=shd'
                       '&guid={guid}&sdtfrom=v1010&host=v.qq.com')


def qqvideourl(vid):
    """腾讯视频 vid -> (直链, 时长秒, 体积字节); getinfo 取 fvkey 拼直链(带签名时效, 靠自愈续命)。
    这是 WeixinMusicClient 时代同款路径: 部分老文章正文只挂 video_ids(如百色山歌), 没有 mpvideo。"""
    import uuid as _uuid
    u = QQVIDEO_GETINFO_URL.format(vid=vid, guid=_uuid.uuid4().hex.upper())
    body = _get(u, referer='https://v.qq.com/')
    if not body:
        return None
    text = (body or '').strip()
    m = re.search(r'QZOutputJson\s*=\s*(.*)', text, flags=re.S)
    if m:
        text = m.group(1).strip().rstrip(';')
    try:
        vi = json.loads(text)['vl']['vi'][0]
    except Exception:
        return None
    fn, fvkey = (vi.get('fn') or ''), (vi.get('fvkey') or '')
    base = (((vi.get('ul') or {}).get('ui') or [{}])[0].get('url') or '')
    if not (fn and fvkey and base):
        return None
    if not base.endswith('/'):
        base += '/'
    with suppress(Exception):
        dur = int(float(vi.get('td') or 0))
    with suppress(Exception):
        size = int(vi.get('filesize') or 0)
    return f'{base}{fn}?vkey={fvkey}', dur, size


def parse_qq_vids(body):
    """正文里的腾讯视频 vid: video_ids 数组 + v.qq.com iframe 两种形态"""
    vids = []
    for m in re.finditer(r'video_ids:\s*\[([^\]]*)\]', body):
        vids += re.findall(r"[\'\"]([A-Za-z0-9]{8,20})[\'\"]", m.group(1))
    for m in re.finditer(r'<iframe[^>]+(?:data-src|src)="([^"]*v\.qq\.com[^"]*)"', body):
        q = re.search(r'[?&]vid=([A-Za-z0-9]{8,20})', m.group(1))
        if q:
            vids.append(q.group(1))
        else:
            q2 = re.search(r'/([A-Za-z0-9]{8,20})\.html', m.group(1))
            if q2:
                vids.append(q2.group(1))
    out = []
    for v in vids:
        if v not in out:
            out.append(v)
    return out[:2]


def album_page_url(biz, album_id, begin_key=''):
    """视频专辑的翻页接口(action=paging, JSON): 每条自带 key, 下一页传上一批末条的 key。
    is_reverse=1 => 按 pos 正序(老->新)返回; 实测 begin_msg_id 会被忽略, 只有 begin_key 生效。"""
    u = (f'https://mp.weixin.qq.com/mp/appmsgalbum?action=paging&__biz={biz}'
         f'&album_id={album_id}&count=20&is_reverse=1')
    if begin_key:
        u += f'&begin_key={begin_key}'
    return u


def _decode(u):
    """正文里的直链是多层转义(\\x26amp; / &amp;), 逐层解回 &"""
    for _ in range(3):
        prev = u
        u = u.replace('\\x26amp;', '&').replace('\\x26', '&').replace('&amp;', '&')
        if u == prev:
            break
    return u


def fetch_album(biz, album_id, log=print):
    """翻页拿全专辑条目(JSON, 每页 20), 直到 continue_flag 断或无新条目
    返回 (条目列表, 专辑元信息 base_info: nickname/title/article_count)"""
    all_items, seen, begin = [], set(), ''
    meta = {}
    for page in range(30):
        try:
            r = SESS.get(album_page_url(biz, album_id, begin),
                         timeout=(8, 30), headers={'Referer': 'https://mp.weixin.qq.com/'})
            resp = json.loads(r.text).get('getalbum_resp') or {}
        except Exception:
            log(f'    第{page + 1}页非 JSON, 停止翻页')
            break
        meta = resp.get('base_info') or meta
        arts, cont = resp.get('article_list') or [], resp.get('continue_flag')
        fresh = []
        for a in arts:
            msgid = str(a.get('msgid') or '')
            if not msgid or msgid in seen:
                continue
            seen.add(msgid)
            fresh.append({'title': str(a.get('title') or '').strip(),
                          'url': _decode(str(a.get('url') or '')),
                          'vid': a.get('vid') or '', 'msgid': msgid,
                          'duration_s': int(a.get('video_duration') or 0),
                          'cover': _decode(str(a.get('video_cover') or '')),
                          'key': a.get('key') or '', 'pos': a.get('pos_num') or 0})
        log(f'    第{page + 1}页: +{len(fresh)} (累计 {len(all_items) + len(fresh)}, continue={cont})')
        all_items.extend(fresh)
        if not fresh or not cont or not fresh[-1]['key']:
            break
        begin = fresh[-1]['key']
        time.sleep(0.5 + random.random() * 0.5)
    # 专辑元信息(公众号名/专辑名): paging 接口的 base_info 不带, 要到专辑 HTML 页取
    with suppress(Exception):
        page = _get(f'https://mp.weixin.qq.com/mp/appmsgalbum?__biz={biz}&action=getalbum'
                    f'&album_id={album_id}&scene=126&count=1')
        m = re.search(r'nickname:\s*"([^"]+)"', page)
        if m:
            meta['nickname'] = m.group(1)
        m = re.search(r'article_count:\s*"(\d+)".{0,500}?title:\s*"([^"]+)"', page, re.S)
        if m:
            meta.setdefault('article_count', m.group(1))
            meta['title'] = m.group(2)
    return all_items, meta


def page_ctx(body):
    """从微信文章 HTML 里抽基础信息(msg_title / nickname / msg_cdn_url 封面等)。"""
    ctx = {'msg_title': '', 'nickname': '', 'msg_cdn_url': ''}
    m = re.search(r"msg_title\s*[:=]\s*['\"]([^'\"]+)['\"]", body)
    if m: ctx['msg_title'] = m.group(1)
    m = re.search(r"nickname\s*[:=]\s*['\"]([^'\"]+)['\"]", body)
    if m: ctx['nickname'] = m.group(1)
    m = re.search(r"msg_cdn_url\s*[:=]\s*['\"](https?://[^'\"]+?)['\"]", body)
    if m: ctx['msg_cdn_url'] = m.group(1)
    return ctx


def parse_voices(body):
    """正文里的 mpvoice 音频: voice_encode_fileid + 紧邻的 title/singer_name 等。
    返回 [{voice_id, name, singers, duration_s, ...}]"""
    out = []
    for m in re.finditer(
            r"voice_encode_fileid\s*=\s*\"([^\"]+)\".{0,2000}?"
            r"title\s*=\s*\"([^\"]*)\".{0,2000}?singer_name\s*=\s*\"([^\"]*)\""
            r".{0,2000}?(?P<dur>voice_duration\s*=\s*\"(\d+)\")?",
            body, re.S):
        voice_id = m.group(1)
        title = m.group(2).strip()
        singer = m.group(3).strip()
        with suppress(Exception):
            dur = int(m.group(5))
        out.append({'voice_id': voice_id, 'name': title or voice_id, 'singers': singer,
                    'duration_s': dur if 'dur' in locals() else 0, 'kind': 'audio'})
    return out


def parse_mp_videos(body):
    """正文 mp_video_trans_info -> [{base, formats{fmt->(url,dur,size,w,h)}}]
    同一视频的 4 档直链共享同一路径基名, 按基名分组。
    注意: 路径形如 <videoid>.f10004.mp4 —— 必须剥掉 .fXXXXX 档位后缀, 否则一个视频的
    4 档会被当成 4 个独立视频(多视频文章里后续视频全部取不到)。"""
    groups = {}
    for m in re.finditer(r"format_id:\s*'(\d+)'[^{}]*?url:\s*'(http://mpvideo[^']+)'", body, re.S):
        fmt, raw = m.group(1), m.group(2)
        block = m.group(0)
        base = re.match(r'https?://mpvideo\.qpic\.cn/([^/?]+)\.', raw).group(1)
        base = re.sub(r'\.f\d+$', '', base)
        dur = re.search(r"duration:\s*'([\d.]+)'", block)
        size = re.search(r"filesize:\s*'(\d+)'", block)
        w = re.search(r"width:\s*'(\d*)'", block)
        g = groups.setdefault(base, {'formats': {}})
        g['formats'][fmt] = {
            'url': _decode(raw),
            'duration_s': int(float(dur.group(1))) if dur else 0,
            'file_size_bytes': int(size.group(1)) if size and size.group(1) else 0,
            'width': int(w.group(1)) if w and w.group(1) else 0,
        }
    return groups


def pick_video(groups):
    """按 FMT_PRIORITY 选一个视频组与档位"""
    for fmt in FMT_PRIORITY:
        for base in sorted(groups):
            f = groups[base]['formats'].get(fmt)
            if f and f['url']:
                return base, fmt, f
    return None, None, None


LABEL_BAD = {'歌曲', '音乐', 'MV', '视频', '国外', '外国', '中国', '国内', '泰国', '越南',
             '瑶族', '瑶', '作品展播', '《盘王歌》', '《盘王歌》'.replace('《', '').replace('》', '')}


def clean_label(s):
    """首个｜段(地名/系列名)做歌手标签的清洗: 去行业后缀, 挡无意义词"""
    if s.startswith('老科'):
        return '老科（赵成科）'          # 专辑内另一篇标题自带注释: 老科(赵成科)
    t = re.sub(r'(瑶语|瑶族|瑶)?(经典|新歌|原创|流行)?(歌曲|歌剧|音乐|MV|民谣)$', '', str(s or '')).strip()
    return '' if (not t or t in LABEL_BAD) else t


def parse_title(title):
    """'天籁之音｜盘梅燕演唱：瑶韵深牌' -> ('瑶韵深牌', '盘梅燕')
    歌手只认「XXX演唱：」与「XXX（YYY）」两种明确形态, 宁缺毋滥;
    没有明确歌手时用首个｜段(地名/系列名)做分组标签, 同族曲库早有此用法。"""
    t = re.sub(r'\s+', ' ', str(title or '')).strip()
    singer = ''
    m = re.search(r'([\u4e00-\u9fa5A-Za-z0-9·]{2,12})\s*演唱\s*[：:]', t)
    if m:
        singer = m.group(1)
    if not singer:
        m = re.search(r'[（(]([\u4e00-\u9fa5A-Za-z·]{2,12})[)）]', t)
        if m:
            singer = m.group(1)
    parts = [p.strip() for p in re.split(r'[｜|]', t) if p.strip()]
    name = parts[-1] if len(parts) > 1 else t
    name = re.sub(r'^.*?演唱\s*[：:]\s*', '', name)
    if not singer and len(parts) > 1:
        singer = clean_label(parts[0])
    return name or t, singer


def _normalize_audio(it, article_title, article_url, article_msgid, nickname, cover, album_of_site):
    """mpvoice -> 统一 schema 条目。download_url 是 res.wx.qq.com 直链(免鉴权)。"""
    return {
        'name': it.get('name') or article_title,
        'singers': it.get('singers') or '',
        'voice_id': it.get('voice_id') or '',
        'download_url': f'https://res.wx.qq.com/voice/getvoice?mediaid={it.get("voice_id", "")}',
        'duration_s': int(it.get('duration_s') or 0),
        'file_size_bytes': 0,
        'ext': 'mp3',
        'kind': 'audio',
        'article_title': article_title,
        'article_url': article_url,
        'article_msgid': article_msgid,
        'nickname': nickname,
        'cover_url': cover,
        'album_of_site': album_of_site,
    }


def _normalize_video_mp(f, fmt, vid, article_title, article_url, article_msgid,
                        nickname, cover, album_of_site, album_title=''):
    """mpvideo -> 统一 schema 条目。download_url 是 mpvideo.qpic.cn 签名直链(短效, 自愈续命)。"""
    name, singer = parse_title(article_title)
    return {
        'name': name,
        'singers': singer,
        'voice_id': vid or '',
        'download_url': f['url'],
        'duration_s': int(f['duration_s'] or 0),
        'file_size_bytes': int(f['file_size_bytes'] or 0),
        'ext': 'mp4',
        'kind': 'video',
        'article_title': article_title,
        'article_url': article_url,
        'article_msgid': article_msgid,
        'nickname': nickname,
        'cover_url': cover,
        'album_of_site': album_of_site,
        'album_title': album_title,
        'vid': vid,
        'format_id': fmt,
    }


def _normalize_video_qq(url, dur, size, vid, article_title, article_url, article_msgid,
                        nickname, cover, album_of_site, album_title=''):
    """qqvideourl 兜底 -> 统一 schema 条目。voice_id 带 'qqvid-' 前缀, 自愈时按它走 getinfo 重签。"""
    return {
        'name': article_title,
        'singers': '',
        'voice_id': f'qqvid-{vid}',
        'download_url': url,
        'duration_s': int(dur or 0),
        'file_size_bytes': int(size or 0),
        'ext': 'mp4',
        'kind': 'video',
        'article_title': article_title,
        'article_url': article_url,
        'article_msgid': article_msgid,
        'nickname': nickname,
        'cover_url': cover,
        'album_of_site': album_of_site,
        'album_title': album_title,
        'vid': vid,
    }


_WXM = None
_NORM_STR = lambda s: re.sub(r'[\s\-—·,，.。\'"()（）【】\[\]~～!！?？:：;；&+、]', '', str(s or '').lower())


def _get_weixin_client():
    """懒加载 musicdl 的 WeixinMusicClient(它走搜狗→微信文章 绕过 mp.weixin.qq.com 直连的 ret=-2 反爬)。
    单次进程只构造一次, 内部已维护会话和冷却。"""
    global _WXM
    if _WXM is not None:
        return _WXM
    with suppress(Exception):
        from musicdl import musicdl
        mc = musicdl.MusicClient(music_sources=['WeixinMusicClient'],
                                 init_music_clients_cfg={'WeixinMusicClient':
                                     {'work_dir': 'downloads', 'search_size_per_source': 10, 'max_retries': 1}})
        _WXM = mc.music_clients['WeixinMusicClient']
    return _WXM


def _search_fallback(entry, album_of_site, album_title, nickname):
    """直接 hit mp.weixin.qq.com 拿到 ret=-2 空壳时, 走搜狗找候选 SongInfo -> 还原入库条目。
    mpvoice 直链(免鉴权)能直接拿到; mpvideo 与 qqvid 走不了(它们在文章正文字面量里), 只能拿到音频。
    返回 [入库条目]。"""
    wmc = _get_weixin_client()
    if wmc is None:
        return []
    title_hint = (entry.get('title') or '').strip()
    if not title_hint:
        return []
    nick_hint = nickname or entry.get('nickname') or ''
    kw_candidates = [f'{nick_hint} {title_hint}'.strip(), title_hint]
    candidates = []
    for kw in kw_candidates:
        try:
            ss = wmc.search(keyword=kw, num_threadings=2, request_overrides={}, rule={}) or []
        except Exception:
            ss = []
        candidates.extend(ss)
        if ss:
            break

    def _hit(s):
        n = _NORM_STR(s.get('singers') or '')
        t = _NORM_STR(s.get('song_name') or '')
        if nick_hint and _NORM_STR(nick_hint) in n:
            return True
        if title_hint and (_NORM_STR(title_hint) in t or t in _NORM_STR(title_hint)):
            return True
        return False
    hits = [s for s in candidates if _hit(s)]
    if not hits:
        return []
    out = []
    for s in hits[:3]:
        u = str(s.download_url or '')
        if not u.startswith('http'):
            continue
        voice_id = str(s.identifier or '')
        if voice_id.startswith('wxvoice-'):
            voice_id = voice_id[len('wxvoice-'):]
        cover = str(s.cover_url or '')
        singer = str(s.singers or '') or nickname or '微信公众号'
        out.append({
            'name': str(s.song_name or title_hint),
            'singers': singer,
            'voice_id': voice_id,
            'download_url': u,
            'duration_s': int(getattr(s, 'duration_s', 0) or 0),
            'file_size_bytes': int(getattr(s, 'file_size_bytes', 0) or 0),
            'ext': str(s.ext or 'mp3'),
            'kind': 'audio',
            'article_title': title_hint,
            'article_url': entry['url'],
            'article_msgid': entry['msgid'],
            'nickname': singer,
            'cover_url': cover,
            'album_of_site': album_of_site,
            'album_title': album_title,
        })
    return out


def harvest_article(entry, album_of_site, album_title=''):
    """单条微信文章(entry 含 url/title/vid/msgid/cover) -> [入库条目]
    抽取顺序:
      1. 直接 hit mp.weixin.qq.com 拿正文(早期公众号 / 部分合集仍走通)
      2. 若服务端返 ret=-2 空壳(body < 60k 或不含 mpvoice/mpvideo 字段), 自动转走搜狗反向拿候选
         (mpvoice 走通; mpvideo/qqvid 走不通, 因为它们在文章正文字面量里)
    直链过期不要紧, 自愈靠 article_url + voice_id(主程序 mountainriverechoes 续期)。"""
    url = entry['url'].replace('http://mp.weixin.qq.com', 'https://mp.weixin.qq.com')
    body = _get(url)
    nickname_hint = entry.get('nickname') or ''
    if len(body) < 60000 or 'ret = -2' in body[:6000] or "var ret = '-2'" in body[:6000]:
        items = _search_fallback(entry, album_of_site, album_title, nickname_hint)
        if items:
            return items
        if len(body) < 60000:
            return []
    ctx = page_ctx(body)
    article_title = ctx.get('msg_title') or entry['title']
    nickname = ctx.get('nickname') or nickname_hint or '微信公众号'
    cover = entry.get('cover') or ctx.get('msg_cdn_url') or ''
    out = []
    for it in parse_voices(body):
        out.append(_normalize_audio(it, article_title, entry['url'], entry['msgid'],
                                    nickname, cover, album_of_site))
    groups = parse_mp_videos(body)
    base, fmt, f = pick_video(groups)
    if f:
        out.append(_normalize_video_mp(f, fmt, entry.get('vid', ''), article_title,
                                       entry['url'], entry['msgid'], nickname, cover,
                                       album_of_site, album_title))
    if not out:
        for vid in parse_qq_vids(body):
            parsed = qqvideourl(vid)
            if not parsed:
                continue
            u, dur, size = parsed
            out.append(_normalize_video_qq(u, dur, size, vid, article_title, entry['url'],
                                           entry['msgid'], nickname, cover,
                                           album_of_site, album_title))
            break
    return out


def harvest_single_url(url, album_of_site='', album_title='', nickname='', msgid=''):
    """单篇 URL 入口: 抓完返回 [(统一 schema 条目), ...]。直接调 harvest_article 包装一下。
    msgid 缺省时用 url 的 hash 末段保证不重复。"""
    if not msgid:
        m = re.search(r'(?:mid|__biz)=([^&]+)', url) or re.search(r'/([^/?]+)(?:\?|$)', url)
        msgid = (m.group(1) if m else '')[:48]
    entry = {'url': url, 'title': '', 'vid': '', 'msgid': msgid,
             'cover': '', 'nickname': nickname}
    items = harvest_article(entry, album_of_site, album_title)
    if not items:
        # 至少留一条"已抓但未抽到音频视频"的痕迹, 方便排查
        return [{'name': url, 'singers': '', 'voice_id': '',
                 'download_url': '', 'duration_s': 0, 'file_size_bytes': 0,
                 'ext': '', 'kind': 'empty',
                 'article_title': '', 'article_url': url, 'article_msgid': msgid,
                 'nickname': nickname, 'cover_url': '',
                 'album_of_site': album_of_site}]
    return items


# ======================= CLI =======================

def _parse_album_url(url):
    """从 mp.weixin.qq.com/mp/appmsgalbum?... 这种合集页 URL 抠 __biz + album_id。
    兼容 query 里夹 #wechat_redirect / &scene 等尾巴。"""
    from urllib.parse import urlparse, parse_qs
    p = urlparse(url.strip())
    qs = parse_qs(p.query)
    biz = (qs.get('__biz') or [''])[0]
    aid = (qs.get('album_id') or [''])[0]
    if not biz or not aid:
        raise SystemExit(f'无法从 URL 拆出 __biz 与 album_id: {url}')
    return biz, aid


def _run_album(a):
    print(f'[视频专辑] {a.biz} / {a.album}')
    entries, meta = fetch_album(a.biz, a.album)
    album_title = a.album_title or str(meta.get('title') or '')
    nickname = a.nickname or str(meta.get('nickname') or '')
    print(f'    专辑「{album_title}」/ {meta.get("nickname", "")} / 声明 {meta.get("article_count", "?")} 条, 实拿 {len(entries)} 篇')

    done_msgs = set()
    if a.resume and os.path.exists(a.resume):
        with suppress(Exception):
            done_msgs = {it.get('article_msgid') for it in json.load(open(a.resume, encoding='utf-8'))
                         if it.get('article_msgid')}
        print(f'    断点续抓: 已有 {len(done_msgs)} 篇')
    todo = [e for e in entries if e['msgid'] not in done_msgs]
    if a.limit:
        todo = todo[:a.limit]

    results, lock, n = [], threading.Lock(), [0]

    def one(e):
        e = dict(e, nickname=nickname)
        items = []
        for attempt in range(2):
            items = harvest_article(e, a.album, album_title)
            if items:
                break
            time.sleep(1.0 + random.random())
        with lock:
            n[0] += 1
            results.extend(items)
            kinds = ''.join('音' if i.get('kind') == 'audio' else '视' for i in items) or '-'
            print(f'  [{n[0]}/{len(todo)}] {kinds} {e["title"][:44]}', flush=True)
        time.sleep(a.sleep)

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = [pool.submit(one, e) for e in todo]
        for f in as_completed(futs):
            with suppress(Exception):
                f.result()

    merged = []
    if a.resume and os.path.exists(a.resume):
        with suppress(Exception):
            merged = json.load(open(a.resume, encoding='utf-8'))
    merged.extend(results)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)
    json.dump(merged, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    na = sum(1 for x in results if x.get('kind') == 'audio')
    nv = sum(1 for x in results if x.get('kind') == 'video')
    print(f'\n[完成] 本次 音频 {na} + 视频 {nv}, 文件共 {len(merged)} 条 -> {a.out}')
    for x in results[:6]:
        print(f"    {x.get('nickname', '')[:10]:12} {x['name'][:36]:38} {x.get('duration_s', 0)}s {x.get('ext')}")


def _run_single(a):
    print(f'[单篇] {a.url}')
    items = harvest_single_url(a.url, album_of_site=a.album or '', album_title=a.album_title or '',
                               nickname=a.nickname or '', msgid=a.msgid or '')
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)
    json.dump(items, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    na = sum(1 for x in items if x.get('kind') == 'audio')
    nv = sum(1 for x in items if x.get('kind') == 'video')
    print(f'[完成] 音频 {na} + 视频 {nv} -> {a.out}')
    for x in items:
        print(f"    {x.get('nickname', '')[:10]:12} {x['name'][:36]:38} {x.get('duration_s', 0)}s {x.get('ext')}")


def _run_articles_file(a):
    print(f'[批量] 读 {a.articles_file}')
    with open(a.articles_file, encoding='utf-8') as f:
        items_in = json.load(f)
    if not isinstance(items_in, list):
        print('  期望 JSON 数组(每项含 url/msgid/title/cover)')
        sys.exit(2)
    print(f'  共 {len(items_in)} 篇')
    todo = items_in
    if a.limit:
        todo = todo[:a.limit]
    results, lock, n = [], threading.Lock(), [0]

    def one(e):
        entry = {'url': e.get('url') or '', 'title': e.get('title') or '', 'vid': e.get('vid') or '',
                 'msgid': str(e.get('msgid') or ''), 'cover': e.get('cover') or '',
                 'nickname': e.get('nickname') or a.nickname or ''}
        items = []
        for attempt in range(2):
            items = harvest_article(entry, a.album or '', a.album_title or '')
            if items:
                break
            time.sleep(1.0 + random.random())
        with lock:
            n[0] += 1
            results.extend(items)
            kinds = ''.join('音' if i.get('kind') == 'audio' else '视' for i in items) or '-'
            print(f'  [{n[0]}/{len(todo)}] {kinds} {entry["title"][:44]}', flush=True)
        time.sleep(a.sleep)

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = [pool.submit(one, e) for e in todo]
        for f in as_completed(futs):
            with suppress(Exception):
                f.result()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)
    json.dump(results, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    na = sum(1 for x in results if x.get('kind') == 'audio')
    nv = sum(1 for x in results if x.get('kind') == 'video')
    print(f'\n[完成] 音频 {na} + 视频 {nv} -> {a.out}')


def main():
    ap = argparse.ArgumentParser(description='微信公众号文章/专辑 -> 微信文章库入库条目')
    # 四选一
    ap.add_argument('--url', help='单篇微信公众号文章 URL (与其他入口互斥)')
    ap.add_argument('--biz', help='视频专辑 __biz (与 --url/--articles-file/--album-url 互斥)')
    ap.add_argument('--album', help='视频专辑 album_id (与 --url/--articles-file/--album-url 互斥)')
    ap.add_argument('--album-url', help='微信公众号合集页 URL (mp/appmsgalbum?__biz=...&album_id=...), 与 --url/--biz/--articles-file 互斥')
    ap.add_argument('--articles-file', help='JSON 数组文件, 每项含 url/msgid/title/cover')
    # 公用
    ap.add_argument('--out', required=True, help='输出 JSON 路径')
    ap.add_argument('--album-title', default='', help='专辑名(默认取专辑 base_info.title)')
    ap.add_argument('--nickname', default='', help='覆盖公众号名(默认取文章 HTML)')
    ap.add_argument('--msgid', default='', help='仅 --url 模式: 显式指定 msgid 用于断点续抓')
    ap.add_argument('--resume', default='', help='仅专辑模式: 已有结果 JSON, 其中的 msgid 会跳过')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--sleep', type=float, default=0.7)
    ap.add_argument('--limit', type=int, default=0, help='只抓前 N 篇(试跑)')
    a = ap.parse_args()

    modes = sum(bool(x) for x in (a.url, a.biz, a.articles_file, a.album_url))
    if modes == 0:
        ap.error('必须传 --url 或 (--biz + --album) 或 --album-url 或 --articles-file 之一')
    if modes > 1:
        ap.error('--url / (--biz + --album) / --album-url / --articles-file 互斥')
    if a.biz and not a.album:
        ap.error('--biz 必须配合 --album')

    if a.url:
        _run_single(a)
    elif a.album_url:
        biz, album_id = _parse_album_url(a.album_url)
        # 复用 --biz --album 通道: 在 a 上覆盖两个字段再走 _run_album
        a.biz, a.album = biz, album_id
        _run_album(a)
    elif a.biz:
        _run_album(a)
    else:
        _run_articles_file(a)


if __name__ == '__main__':
    main()
