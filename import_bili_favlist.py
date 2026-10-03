# -*- coding: utf-8 -*-
"""
导入 B站收藏夹到指定民族歌单(门巴 e52 / 珞巴 e53)。
- 抓取收藏夹全部视频
- 用 BilibiliMusicClient._parsewithofficialapiv1 把每个 bvid 解析为带可播放直链的 SongInfo
- 复用 mountainriverechoes 的 _ethnos_payload / _dedup_key / _atomic_write_json 严格匹配现有缓存格式
- 增量并入: 已有曲目(warm)优先, 不重复, 原子写回(自动归档旧版本)
"""
import importlib.util, os, json, sys, time, threading
import urllib.request as urllib_request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "webui", "ethnos_cache")

# ---- 导入 mountainriverechoes 复用序列化辅助(不会触发 app.run) ----
spec = importlib.util.spec_from_file_location("cam", os.path.join(HERE, "webui", "mountainriverechoes.py"))
cam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cam)

from musicdl.modules.sources import bilibili as bili_mod
from musicdl.modules import SongInfo

ETHNIC_BY_KEY = cam.ETHNIC_BY_KEY
_cache_path = cam._cache_path
_dedup_key = cam._dedup_key
_ethnos_payload = cam._ethnos_payload
_atomic_write_json = cam._atomic_write_json

# 收藏夹 -> 民族 key 映射 (来自用户提供的两个 space.bilibili.com/22526049/favlist)
FAVLIST_MAP = {
    4133785249: "e52",   # 门巴
    4144803649: "e53",   # 珞巴
}
UP_UID = 22526049

_lock = threading.Lock()

def fetch_favlist(media_id, ps=20, max_pages=20):
    items = []
    for pn in range(1, max_pages + 1):
        url = (f"https://api.bilibili.com/x/v3/fav/resource/list?media_id={media_id}"
               f"&pn={pn}&ps={ps}&keyword=&order=mtime&type=0&tid=0&platform=web")
        req = urllib_request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            "Referer": f"https://space.bilibili.com/{UP_UID}/favlist",
        })
        with urllib_request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d.get("code") != 0:
            print(f"  [warn] favlist {media_id} pn{pn} code={d.get('code')} msg={d.get('message')}")
            break
        medias = d.get("data", {}).get("medias") or []
        if not medias:
            break
        items.extend(medias)
        total = d.get("data", {}).get("info", {}).get("media_count") or 0
        if len(items) >= total:
            break
        time.sleep(0.4)
    return items


# 每个视频独立解析(避免共用单例客户端被连续请求打坏)
def parse_one(media):
    bvid = media.get("bvid")
    if not bvid:
        return None
    try:
        bili = bili_mod.BilibiliMusicClient()   # 每次 fresh, 规避单例损坏
        sr = {
            "id": media.get("id"),
            "bvid": bvid,
            "title": media.get("title"),
            "author": (media.get("upper") or {}).get("name"),
            "pic": media.get("cover"),
        }
        si = bili._parsewithofficialapiv1(
            search_result=sr, song_info_flac=None,
            lossless_quality_is_sufficient=False, request_overrides={})
    except Exception as e:
        return (bvid, None, f"err:{e}")
    if isinstance(si, list):
        si = si[0] if si else None
    if isinstance(si, SongInfo) and si.with_valid_download_url:
        return (bvid, si, media.get("title", "")[:40])
    return (bvid, None, "no_valid_url")


def merge_into(group_key, new_songs):
    path = _cache_path(group_key)
    info = ETHNIC_BY_KEY[group_key]
    merged = {}
    warm_keys = set()
    if path.exists():
        d = json.loads(path.read_text(encoding="utf-8"))
        if d.get("v") == cam.ETHNOS_SCHEMA:
            for t in d.get("tracks") or []:
                s = SongInfo.fromdict(t.get("_song") or {})
                if s.song_name:
                    k = _dedup_key(s)
                    merged[k] = (s, 1000)    # 老歌 warm 优先
                    warm_keys.add(k)
    added = 0
    for s, _score in new_songs:
        if s is None:
            continue
        k = _dedup_key(s)
        if k in warm_keys:
            continue
        merged[k] = (s, 800)    # B站补充分(低于 warm)
        warm_keys.add(k)
        added += 1
    songs = [v[0] for v in sorted(merged.values(), key=lambda x: -x[1])]
    payload = _ethnos_payload(info, group_key, songs, partial=False)
    _atomic_write_json(path, payload)
    return added, len(songs)


def main():
    summary = {}
    for media_id, group_key in FAVLIST_MAP.items():
        gname = ETHNIC_BY_KEY[group_key]["name"]
        print(f"\n=== 抓取收藏夹 {media_id} -> {gname}({group_key}) ===")
        items = fetch_favlist(media_id)
        print(f"  共 {len(items)} 条视频")
        good, bad = [], 0
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(parse_one, m): m.get("bvid") for m in items}
            done = 0
            for fut in as_completed(futs):
                bvid, si, note = fut.result()
                done += 1
                if si is not None:
                    good.append((si, 800))
                else:
                    bad += 1
                if done % 20 == 0 or done == len(items):
                    print(f"  解析进度 {done}/{len(items)}  可用{len(good)} 失败{bad}")
        added, total = merge_into(group_key, good)
        summary[group_key] = (gname, len(items), len(good), bad, added, total)
        print(f"  >>> {gname}: 收藏夹{len(items)} / 解析可用{len(good)} / 失败{bad} / 新增{added} / 现有总计{total}")

    print("\n==== 汇总 ====")
    for k, (n, tot, ok, bad, added, total) in summary.items():
        print(f"  {n}({k}): 收藏夹{tot} 可用{ok} 失败{bad} 新增{added} 总计{total}")


if __name__ == "__main__":
    main()
