'''
Function:
    Implementation of DeezerMusicClient Utils
Author:
    Zhenchao Jin
WeChat Official Account (微信公众号):
    Charles的皮卡丘
'''
import re
import hashlib
import binascii
import functools
from Cryptodome.Cipher import AES, Blowfish


'''DeezerMusicClientUtils'''
class DeezerMusicClientUtils():
    BLOWFISH_SECRET = "g4el58wc0zvf9na1"
    MUSIC_QUALITIES = ('FLAC', 'MP3_320', 'MP3_128')
    IS_ENCRYPTED_RPATTERN = re.compile("/m(?:obile|edia)/")
    '''decryptchunk'''
    @staticmethod
    def decryptchunk(key, data):
        return Blowfish.new(key, Blowfish.MODE_CBC, b"\x00\x01\x02\x03\x04\x05\x06\x07").decrypt(data)
    '''generateblowfishkey'''
    @staticmethod
    def generateblowfishkey(track_id: str) -> bytes:
        md5_hash = hashlib.md5(track_id.encode()).hexdigest()
        return "".join(chr(functools.reduce(lambda x, y: x ^ y, map(ord, t))) for t in zip(md5_hash[:16], md5_hash[16:], DeezerMusicClientUtils.BLOWFISH_SECRET)).encode()
    '''getencryptedfileurl'''
    @staticmethod
    def getencryptedfileurl(meta_id: str, track_hash: str, media_version: str, format_number: int = 1):
        url_bytes = b"\xa4".join((track_hash.encode(), str(format_number).encode(), str(meta_id).encode(), str(media_version).encode()))
        info_bytes = bytearray(hashlib.md5(url_bytes).hexdigest().encode())
        info_bytes.extend(b"\xa4"); info_bytes.extend(url_bytes); info_bytes.extend(b"\xa4")
        padding_len = 16 - (len(info_bytes) % 16); info_bytes.extend(b"." * padding_len)
        path = binascii.hexlify(AES.new(b"jo6aey6haid2Teih", AES.MODE_ECB).encrypt(info_bytes)).decode("utf-8")
        return f"https://e-cdns-proxy-{track_hash[0]}.dzcdn.net/mobile/1/{path}"
    '''getcoverurl'''
    @staticmethod
    def getcoverurl(pic_id: str):
        if not pic_id: return None
        return f"https://e-cdns-images.dzcdn.net/images/cover/{pic_id}/1200x1200.jpg"
    '''covert2lrclyrics'''
    @staticmethod
    def covert2lrclyrics(lyrics_node: dict):
        lrc_lines = []; lyrics_node.get("writers") and lrc_lines.append(f"[ar:{lyrics_node['writers']}]")
        if (sync_lines := lyrics_node.get("synchronizedLines")):
            for item in sync_lines: lrc_lines.append(f"{item.get('lrcTimestamp', '')}{item.get('line', '')}") if item.get("lrcTimestamp", "") else (lrc_lines.append(f"[{int(item['milliseconds']) // 60000:02d}:{(int(item['milliseconds']) % 60000) / 1000:05.2f}]{item.get('line', '')}") if "milliseconds" in item else None)
            return "\n".join(lrc_lines)
        else:
            return lyrics_node.get("text")