'''
Function:
    本地下载库服务 —— 列出/删除已下载文件、打开所在目录。
    安全约束: 所有路径必须先规约到 download_dir 之内, 挡住 ../ 穿越。
'''
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

from app.errors import ValidationError

logger = logging.getLogger(__name__)

AUDIO_EXTS = {'.mp3', '.flac', '.wav', '.m4a', '.ape', '.ogg', '.oga', '.wma', '.aac', '.opus'}
IGNORE_SUFFIX = {'.pkl'}
MAX_LIST = 400


class FilesService:
    def __init__(self, *, download_dir: Path) -> None:
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- 列举
    def list_files(self) -> list[dict]:
        files: list[dict] = []
        for path in self.download_dir.rglob('*'):
            if not path.is_file() or path.name.startswith('.'):
                continue
            if path.suffix.lower() in IGNORE_SUFFIX:
                continue
            st = path.stat()
            size = st.st_size
            files.append({
                'name': path.stem,
                'file': path.name,
                'path': str(path.relative_to(self.download_dir)),
                'ext': path.suffix.lstrip('.').upper(),
                'size': f'{size / 1024 / 1024:.1f}MB' if size > 1024 * 1024 else f'{size / 1024:.0f}KB',
                'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime)),
                'mtime_ts': st.st_mtime,
                'playable': path.suffix.lower() in AUDIO_EXTS,
            })
        files.sort(key=lambda x: x['mtime_ts'], reverse=True)
        return files[:MAX_LIST]

    # ---------------------------------------------------------------- 操作
    def resolve_safe(self, relative: str) -> Path:
        '''把相对路径解析为安全绝对路径; 越界一律拒绝'''
        target = (self.download_dir / (relative or '')).resolve()
        root = self.download_dir.resolve()
        if target != root and not str(target).startswith(str(root) + os.sep):
            raise ValidationError('非法路径')
        return target

    def delete(self, relative: str) -> None:
        import shutil
        target = self.resolve_safe(relative)
        if target.is_file():
            target.unlink()
            with_target = target.with_suffix('.pkl')
            if with_target.is_dir():
                shutil.rmtree(with_target, ignore_errors=True)
            logger.info('已删除文件 %s', relative)

    def open_folder(self, relative: str = '') -> None:
        '''在文件管理器中定位文件/目录。跨平台: macOS open / Windows explorer / Linux xdg-open'''
        target = self.resolve_safe(relative)
        folder = target if target.is_dir() else target.parent
        if os.name == 'nt':
            args: list[str] = ['explorer', str(folder)]
        elif os.name == 'posix' and _is_macos():
            args = ['open', str(folder)]
        else:
            args = ['xdg-open', str(folder)]
        try:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            logger.warning('打开目录失败: %s', exc)
            raise ValidationError('无法打开文件管理器') from exc


def _is_macos() -> bool:
    import sys
    return sys.platform == 'darwin'
