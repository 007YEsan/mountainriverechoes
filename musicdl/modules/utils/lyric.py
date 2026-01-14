'''
Function:
    Implementation of WhisperLRC
Author:
    Zhenchao Jin
WeChat Official Account (微信公众号):
    Charles的皮卡丘
'''
import os
import re
import tempfile
import requests
from typing import Optional, Union, Dict, Any, List


'''settings'''
_TIME_RE = re.compile(r"\[(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")
cleanlrc = lambda text: "\n".join(line for raw in re.sub(r"\r\n?", "\n", text).split("\n") if (line := raw.strip("\ufeff\u200b\u200c\u200d\u2060\u00a0 \t").strip()) and not re.fullmatch(r"\[(\d{2}:)?\d{2}:\d{2}(?:\.\d{1,3})?\]", line))


'''fractoseconds'''
def fractoseconds(frac: str | None) -> float:
    if not frac: return 0.0
    scale = 10 ** len(frac)
    return int(frac) / scale


'''extractdurationsecondsfromlrc'''
def extractdurationsecondsfromlrc(lrc: str) -> Optional[float]:
    max_t = None
    for h, m, s, frac in _TIME_RE.findall(lrc):
        hh = int(h) if h else 0
        mm = int(m)
        ss = int(s)
        t = hh * 3600 + mm * 60 + ss + fractoseconds(frac)
        max_t = t if (max_t is None or t > max_t) else max_t
    return max_t


'''sectolrcts'''
def sectolrcts(t: Union[str, float, int], centis: int = 2) -> str:
    try: sec = float(t)
    except (TypeError, ValueError): sec = 0.0
    if sec < 0: sec = 0.0
    if centis == 3: return f"{(cs:=int(round(sec*1000)))//60000:02d}:{(cs//1000)%60:02d}.{cs%1000:03d}"
    else: return f"{(cs:=int(round(sec*100)))//6000:02d}:{(cs//100)%60:02d}.{cs%100:02d}"


'''lyricslisttolrc'''
def lyricslisttolrc(items: List[Dict[str, Any]], *, time_key: str = "time", lyric_key: str = "lineLyric", centis: int = 2, offset: float = 0.0, skip_empty: bool = True, dedup_same_time: bool = False, join_sep: str = " / ") -> str:
    norm = []
    for x in items:
        lyric = str(x.get(lyric_key, "")).strip()
        if skip_empty and not lyric: continue
        try: t = float(x.get(time_key, 0.0)) + float(offset)
        except (TypeError, ValueError): t = 0.0
        if t < 0: t = 0.0
        norm.append((t, lyric))
    norm.sort(key=lambda z: z[0])
    if dedup_same_time:
        merged = []
        for t, lyric in norm:
            if merged and abs(merged[-1][0] - t) < 1e-6: merged[-1] = (merged[-1][0], merged[-1][1] + join_sep + lyric)
            else: merged.append((t, lyric))
        norm = merged
    lines = [f"[{sectolrcts(t, centis=centis)}]{lyric}" for t, lyric in norm]
    return "\n".join(lines)


'''WhisperLRC'''
class WhisperLRC:
    def __init__(self, model_size_or_path="small", device="auto", compute_type="int8", cpu_threads=4, num_workers=1, **kwargs):
        try:
            from faster_whisper import WhisperModel
            self.whisper_model = WhisperModel(model_size_or_path, device=device, compute_type=compute_type, cpu_threads=cpu_threads, num_workers=num_workers, **kwargs)
        except:
            self.whisper_model = None
    '''downloadtotmpdir'''
    @staticmethod
    def downloadtotmpdir(url: str, headers: dict = None, timeout: int = 300, cookies: dict = None, request_overrides: dict = None):
        headers, cookies, request_overrides = headers or {}, cookies or {}, request_overrides or {}
        if 'headers' not in request_overrides: request_overrides['headers'] = headers
        if 'timeout' not in request_overrides: request_overrides['timeout'] = timeout
        if 'cookies' not in request_overrides: request_overrides['cookies'] = cookies
        resp = requests.get(url, stream=True, **request_overrides)
        resp.raise_for_status()
        m = re.search(r"\.([a-z0-9]{2,5})(?:\?|$)", url, re.I)
        fd, path = tempfile.mkstemp(suffix="."+(m.group(1).lower() if m else "bin"))
        with os.fdopen(fd, "wb") as fp:
            for ch in resp.iter_content(32768):
                if ch: fp.write(ch)
        return path
    '''timestamp'''
    @staticmethod
    def timestamp(t):
        t = max(0.0, float(t)); mm = int(t//60); ss = t - mm*60
        return f"[{mm:02d}:{ss:05.2f}]"
    '''fromurl'''
    def fromurl(self, url: str, transcribe_overrides: dict = None, headers: dict = None, timeout: int = 300, cookies: dict = None, request_overrides: dict = None):
        assert self.whisper_model is not None, 'faster_whisper should be installed via "pip install "faster_whisper"'
        transcribe_overrides, headers, cookies, request_overrides = transcribe_overrides or {}, headers or {}, cookies or {}, request_overrides or {}
        tmp_file_path = ''
        try:
            tmp_file_path = self.downloadtotmpdir(url, headers=headers, timeout=timeout, cookies=cookies, request_overrides=request_overrides)
            default_transcribe_settings = {'language': None, 'vad_filter': True, 'vad_parameters': dict(min_silence_duration_ms=300), 'chunk_length': 30, 'beam_size': 5}
            default_transcribe_settings.update(transcribe_overrides)
            segs, info = self.whisper_model.transcribe(tmp_file_path, **default_transcribe_settings)
            lrc = "\n".join(f"{self.timestamp(s.start)}{s.text.strip()}" for s in segs)
            result = {"language": info.language, "prob": info.language_probability, "duration": getattr(info, "duration", None), 'lyric': lrc}
            return result
        finally:
            if tmp_file_path and os.path.exists(tmp_file_path): os.remove(tmp_file_path)
    '''fromfilepath'''
    def fromfilepath(self, file_path: str, transcribe_overrides: dict = None):
        assert self.whisper_model is not None, 'faster_whisper should be installed via "pip install "faster_whisper"'
        transcribe_overrides = transcribe_overrides or {}
        default_transcribe_settings = {'language': None, 'vad_filter': True, 'vad_parameters': dict(min_silence_duration_ms=300), 'chunk_length': 30, 'beam_size': 5}
        default_transcribe_settings.update(transcribe_overrides)
        segs, info = self.whisper_model.transcribe(file_path, **default_transcribe_settings)
        lrc = "\n".join(f"{self.timestamp(s.start)}{s.text.strip()}" for s in segs)
        result = {"language": info.language, "prob": info.language_probability, "duration": getattr(info, "duration", None), 'lyric': lrc}
        return result