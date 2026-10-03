'''
Function:
    歌名/歌手/专辑的归一化 —— 曲库去重与检索打分的地基。
    这些规则是从旧版 webui 单文件里逐字搬过来的, 不可随意改动:
    一旦归一化口径变了, dedup_key 就会漂移, 表现为「同一首歌突然变成两首」或反之。
'''
from __future__ import annotations

import re

# 归一化时剔除的标点/空白
_PUNCT_RE = re.compile(r'[\s\-—·,，.。\'"()（）【】\[\]~～!！?？:：;；&+]')
# 括号注记: (Live版) 【现场】 之类
_BRACKET_RE = re.compile(r'[（(\[【][^)）\]】]*[)）\]】]')
# 版本后缀
_SUFFIX_RE = re.compile(r'(现场版?|live版?|伴奏版?|纯音乐版?|翻唱版?|remix|dj版?|cover版?|卡拉ok版?)$')
# 主名与副名分隔符: A-B 与 B-A 视为同名
_DASH_RE = re.compile(r'[-—]')
# 多歌手分隔符(用于歌手续一化/归属)
_SINGER_SPLIT_RE = re.compile(r'[/,、&+]')
_PLACEHOLDER = {'NULL', 'NONE', '未知歌手'}


def norm_str(value: object) -> str:
    '''去标点/空白并转小写'''
    return _PUNCT_RE.sub('', str(value or '').lower())


def core_name(name: object) -> str:
    '''主匹配键: 去括号注记与版本后缀, A-B 与 B-A 归一'''
    raw = str(name or '')
    n = _BRACKET_RE.sub('', raw)
    n = _SUFFIX_RE.sub('', n.strip().lower())
    n = norm_str(n)
    parts = sorted(p for p in (norm_str(x) for x in _DASH_RE.split(raw)) if p)
    if len(parts) >= 2 and n == ''.join(parts):
        n = ''.join(sorted(parts))
    return n or norm_str(raw)


def split_singers(value: object) -> list[str]:
    '''拆分多歌手: 合作曲同时归属每位歌手'''
    parts = [x.strip() for x in _SINGER_SPLIT_RE.split(str(value or '')) if x.strip()]
    cleaned = [x for x in parts if x and x.upper() not in _PLACEHOLDER]
    if cleaned:
        return cleaned
    single = str(value or '').strip()
    return [single] if single else []


def first_singer(value: object) -> str:
    '''首位歌手: 用于 dedup_key, 避免「歌手字段排序不同」造成同一首歌重复。

    注意这里刻意不含 '&': 与 split_singers 口径不同, 是沿袭旧版行为。
    "&" 连接的合作曲在旧版里首位歌手是整串(如 "Laurent Jeanneau&施坦丁"),
    贸然收紧会让 dedup_key 漂移, 表现为曲库条目数在迁移后对不上。
    '''
    s = str(value or '')
    for sep in ('/', ',', '、'):
        s = s.split(sep)[0]
    return s.strip()


def dedup_key(*, song_name: object, singers: object) -> str:
    '''逻辑归并键: 主名 + 首位歌手(检索结果去重口径)'''
    return core_name(song_name) + '|' + norm_str(first_singer(singers))


def recording_key(
    *, song_name: object, singers: object, source: object = '', duration_s: object = 0, size_bytes: object = 0,
) -> str:
    '''物理行唯一键: 归并键 + 音源 + 时长 + 字节数。

    与 dedup_key 分开是因为曲库里确实存在「同一歌单内同歌名+首歌手的多个不同录音」
    (例如汉族民间小调 507 条、傣族 313 条)。若用 dedup_key 做物理主键, 迁移会在
    学生看不到的情况下删掉这些条目, 各民族歌单显示的曲目数就和策展时对不上了。
    '''
    return '|'.join((
        dedup_key(song_name=song_name, singers=singers),
        str(source or ''), str(duration_s or 0), str(size_bytes or 0),
    ))
