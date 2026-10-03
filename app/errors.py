'''
Function:
    类型化错误体系 —— 服务层只抛领域错误, 全局处理器统一转成规范 JSON。
    客户端永远看不到堆栈/内部细节, 只拿到 {error:{code,message,details}}。
'''
from __future__ import annotations

from typing import Any


class AppError(Exception):
    '''所有领域错误的基类'''

    code: str = 'internal_error'
    http_status: int = 500
    # 面向用户的默认提示, 子类覆盖
    message: str = '服务内部错误，请稍后重试'

    def __init__(self, message: str | None = None, *, details: Any = None, cause: Exception | None = None):
        self._message = message or self.message
        self.details = details
        self.__cause__ = cause
        super().__init__(self._message)

    def to_dict(self) -> dict:
        payload = {'code': self.code, 'message': self._message}
        if self.details is not None:
            payload['details'] = self.details
        return payload


class ValidationError(AppError):
    '''入参不合法 / 校验失败'''
    code, http_status, message = 'validation_error', 400, '请求参数不合法'


class NotFoundError(AppError):
    '''资源不存在'''
    code, http_status, message = 'not_found', 404, '请求的资源不存在'


class ConflictError(AppError):
    '''资源冲突 / 重复'''
    code, http_status, message = 'conflict', 409, '资源已存在或状态冲突'


class UnauthorizedError(AppError):
    '''未认证 / 口令错误'''
    code, http_status, message = 'unauthorized', 401, '未通过身份验证'


class RateLimitedError(AppError):
    '''被上游限流'''
    code, http_status, message = 'rate_limited', 429, '上游服务限流，请稍后再试'


class UpstreamError(AppError):
    '''外部音源 / 网络依赖失败'''
    code, http_status, message = 'upstream_error', 502, '外部音源服务不可用'


class DatabaseUnavailableError(AppError):
    '''数据库不可用(未迁移 / 连接失败)'''
    code, http_status, message = 'database_unavailable', 503, '本地曲库尚未就绪'


class PayloadTooLargeError(AppError):
    '''上传/请求体过大'''
    code, http_status, message = 'payload_too_large', 413, '请求数据过大'
