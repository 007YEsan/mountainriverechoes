'''
Function:
    Implementation of QingtingMusicClient: https://m.qingting.fm/
Author:
    Zhenchao Jin
WeChat Official Account (微信公众号):
    Charles的皮卡丘
'''
import re
import copy
from contextlib import suppress
from urllib.parse import urlencode
from rich.progress import Progress
from ..sources import BaseMusicClient
from ..utils import legalizestring, resp2json, seconds2hms, usesearchheaderscookies, safeextractfromdict, SongInfo


'''QingtingMusicClient'''
class QingtingMusicClient(BaseMusicClient):
    source = 'QingtingMusicClient'
    ALLOWED_SEARCH_TYPES = ['album', 'track']
    def __init__(self, **kwargs):
        self.allowed_search_types = list(set(kwargs.pop('allowed_search_types', QingtingMusicClient.ALLOWED_SEARCH_TYPES)))
        super(QingtingMusicClient, self).__init__(**kwargs)
        self.default_search_headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 9_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 Mobile/13B143 Safari/601.1',
        }
        self.default_download_headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 9_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 Mobile/13B143 Safari/601.1',
        }
        self.default_headers = self.default_search_headers
        self._initsession()