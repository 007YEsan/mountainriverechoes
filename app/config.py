'''
Function:
    集中配置 —— 全部来自环境变量 / 运行环境推导，启动时统一校验，缺参或非法值即快速失败。
    约定:
      - 真实密钥/路径不写死在代码里, 一律 .env 或环境变量
      - 打包后(exe)数据落在用户数据目录; 开发态落在仓库内 var/ 目录
'''
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = 'MountainRiverEchoes'
APP_TITLE = '山河回响'
VERSION = '1.0.0'
# 发行者 / 数据目录厂商名。与 README 里的「课程建设方」是两件事, 改这里只会影响
# 安装包的发布者显示与用户数据目录路径, 不影响曲库内容。
PUBLISHER = '李大光'
DATA_DIR_VENDOR = '李大光'

_REPO_ROOT = Path(__file__).resolve().parents[1]


def is_frozen() -> bool:
    '''是否运行在 PyInstaller 打包产物中'''
    return bool(getattr(sys, 'frozen', False))


def _app_root() -> Path:
    '''打包态: exe 所在目录(_MEIPASS 里只读资源, 这里取 exe 旁目录); 开发态: 仓库根'''
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _REPO_ROOT


def _env_str(name: str, default: str = '') -> str:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f'[配置错误] 环境变量 {name} 必须是整数, 当前值={raw!r}') from exc


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _default_data_dir() -> Path:
    '''用户数据目录: 数据库 / 下载产物 / 日志都落在里面, exe 卸载时不误删'''
    if v := _env_str('MRE_DATA_DIR'):
        return Path(v).expanduser()
    if is_frozen():
        from platformdirs import user_data_dir
        # 第二参数是「厂商名」, 会进数据目录路径:
        #   Windows: C:\Users\<你>\AppData\Local\李大光\MountainRiverEchoes
        #   macOS:   ~/Library/Application Support/MountainRiverEchoes
        # 改这个值 = 换数据目录。可用 MRE_DATA_DIR 覆盖, 老数据不会丢, 只是要手动搬。
        return Path(user_data_dir(APP_NAME, DATA_DIR_VENDOR))
    return _REPO_ROOT / 'var'


@dataclass(frozen=True)
class Settings:
    '''运行期只读配置快照'''
    app_name: str = APP_NAME
    app_title: str = APP_TITLE
    version: str = VERSION
    env: str = 'development'
    host: str = '127.0.0.1'
    port: int = 8766
    debug: bool = False

    app_root: Path = field(default_factory=_app_root)
    data_dir: Path = field(default_factory=_default_data_dir)
    db_path: Path = Path()
    download_dir: Path = Path()
    log_dir: Path = Path()

    # 迁移来源: 旧版 webui/ethnos_cache 的 JSON 缓存目录
    legacy_cache_dir: Path = Path()
    legacy_ui_state: Path = Path()

    log_level: str = 'INFO'
    log_json: bool = True
    cors_origins: tuple[str, ...] = ()

    # 非本机绑定时必须提供访问口令, 避免局域网裸奔
    api_token: str = ''
    require_token: bool = False

    library_index_ttl: int = 300
    search_page_size: int = 60
    search_max_limit: int = 200
    search_min_query: int = 2
    max_download_workers: int = 4

    def __post_init__(self) -> None:
        return None

    def as_public_dict(self) -> dict:
        '''可安全打印的配置(不含口令), 用于启动日志'''
        return {
            'env': self.env, 'host': self.host, 'port': self.port, 'debug': self.debug,
            'app_root': str(self.app_root), 'data_dir': str(self.data_dir),
            'db_path': str(self.db_path), 'download_dir': str(self.download_dir),
            'log_dir': str(self.log_dir), 'log_level': self.log_level,
            'cors_origins': list(self.cors_origins),
            'require_token': self.require_token,
        }


def load_settings() -> Settings:
    '''读取并校验全部配置。任何非法项直接 SystemExit, 不做带病上线'''
    data_dir = _default_data_dir()
    db_path = Path(_env_str('MRE_DB_PATH', str(data_dir / 'mountainriverechoes.db'))).expanduser()
    download_dir = Path(_env_str('MRE_DOWNLOAD_DIR', str(data_dir / 'downloads'))).expanduser()
    log_dir = Path(_env_str('MRE_LOG_DIR', str(data_dir / 'logs'))).expanduser()

    host = _env_str('MRE_HOST', '127.0.0.1')
    port = _env_int('MRE_PORT', 8766)
    if not 1 <= port <= 65535:
        raise SystemExit(f'[配置错误] MRE_PORT 超出合法范围(1-65535): {port}')

    cors_raw = _env_str('MRE_CORS_ORIGINS', '')
    cors_origins = tuple(x.strip() for x in cors_raw.split(',') if x.strip())
    if '*' in cors_origins:
        raise SystemExit('[配置错误] MRE_CORS_ORIGINS 不允许使用通配符 *, 请显式列出来源')

    api_token = _env_str('MRE_API_TOKEN', '')
    # 非回环地址绑定 = 暴露到局域网, 必须配口令
    loopback = host in {'127.0.0.1', 'localhost', '::1'}
    if not loopback and not api_token:
        raise SystemExit(
            f'[配置错误] MRE_HOST={host} 会监听非本机地址, 必须同时设置 MRE_API_TOKEN; '
            f'仅本机使用请显式指定 MRE_HOST=127.0.0.1'
        )

    return Settings(
        env=_env_str('MRE_ENV', 'development'),
        host=host,
        port=port,
        debug=_env_bool('MRE_DEBUG', False),
        app_root=_app_root(),
        data_dir=data_dir,
        db_path=db_path,
        download_dir=download_dir,
        log_dir=log_dir,
        legacy_cache_dir=Path(_env_str('MRE_LEGACY_CACHE_DIR', str(_REPO_ROOT / 'webui' / 'ethnos_cache'))).expanduser(),
        legacy_ui_state=Path(_env_str('MRE_LEGACY_UI_STATE', str(_REPO_ROOT / 'webui' / 'ui_state.json'))).expanduser(),
        log_level=_env_str('MRE_LOG_LEVEL', 'INFO').upper(),
        log_json=_env_bool('MRE_LOG_JSON', True),
        cors_origins=cors_origins,
        api_token=api_token,
        require_token=bool(api_token),
        library_index_ttl=_env_int('MRE_INDEX_TTL', 300),
        search_page_size=_env_int('MRE_SEARCH_PAGE', 60),
        search_max_limit=_env_int('MRE_SEARCH_MAX', 200),
        search_min_query=_env_int('MRE_SEARCH_MIN_Q', 2),
        max_download_workers=_env_int('MRE_DOWNLOAD_WORKERS', 4),
    )
