'''
Function:
    生命周期管理 —— 优雅停机与就绪状态。
    停机时依次: 停收新任务 -> 收尾线程池 -> 关闭数据库连接, 避免 WAL 留下脏页。
'''
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class LifecycleService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.shutting_down = False

    @property
    def is_shutting_down(self) -> bool:
        with self._lock:
            return self.shutting_down

    def register(self, **resources: object) -> None:
        '''登记需要在停机时释放的资源: executor(thread pool) / log_stream(file handle)'''
        for name, value in resources.items():
            setattr(self, name, value)

    def shutdown(self) -> None:
        with self._lock:
            if self.shutting_down:
                return
            self.shutting_down = True
        logger.info('开始优雅停机')

        executor = getattr(self, 'executor', None)
        if executor is not None:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:                                   # Python<3.9 无 cancel_futures
                executor.shutdown(wait=False)

        try:
            from app.extensions import dispose_engine
            dispose_engine()
        except Exception as exc:                                # noqa: BLE001
            logger.debug('释放数据库引擎时出错: %s', exc)

        stream = getattr(self, 'log_stream', None)
        if hasattr(stream, 'close'):
            try:
                stream.close()
            except Exception:                                   # noqa: BLE001
                pass
        logger.info('停机完成')
