'''
Function:
    应用工厂 —— 组装配置/日志/数据库/服务/控制器, 产出可直接运行的 Flask 实例。
    所有横切关注点(request_id、访问日志、错误规范、安全头、CORS、优雅停机)集中在此,
    业务蓝图里不再重复这些逻辑。
'''
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from flask import Flask, jsonify, request

from app import __version__
from app.api import system as system_bp
from app.config import Settings, load_settings
from app.database import create_schema
from app.errors import AppError
from app.extensions import init_engine
from app.logging_setup import set_request_id, setup_logging
from app.services.download_service import DownloadService
from app.services.files_service import FilesService
from app.services.library_service import LibraryService
from app.services.lifecycle_service import LifecycleService
from app.services.media_service import MediaService
from app.services.online_search_service import OnlineSearchService
from app.services.playlist_service import PlaylistService
from app.services.session_service import session_service
from app.services.ui_state_service import UiStateService
from app.util_paths import static_dir, template_dir

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    setup_logging(
        level=settings.log_level, json_format=settings.log_json,
        log_dir=settings.log_dir, console=True,
    )

    app = Flask(
        __name__,
        template_folder=str(template_dir()),
        static_folder=str(static_dir()),
        static_url_path='/static',
    )
    app.json.ensure_ascii = False                 # 中文不被转义成 \uXXXX
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

    # ------------------------------------------------------------ 数据层
    # 首次启动: 从安装目录的母本复制出用户工作副本(详见 app/bootstrap.py)
    try:
        from app.bootstrap import ensure_database
        ensure_database(settings.db_path)
    except Exception as exc:                                       # noqa: BLE001
        logger.warning('曲库初始化失败, 以现有库启动: %s', exc)
    engine = init_engine(settings.db_path, echo=settings.debug)
    create_schema(engine)

    # ------------------------------------------------------------ 服务层
    lifecycle = LifecycleService()
    services: dict[str, Any] = {
        'lifecycle': lifecycle,
        'sessions': session_service,
        'library': LibraryService(settings=settings),
        'playlists': PlaylistService(),
        'curation': _curation_service(engine),
        'ui_state': UiStateService(),
        'files': FilesService(download_dir=settings.download_dir),
        'online': OnlineSearchService(download_dir=settings.download_dir),
        'media': MediaService(),
        'download': DownloadService(
            download_dir=settings.download_dir, workers=settings.max_download_workers,
        ),
    }
    app.extensions['settings'] = settings
    app.extensions['services'] = services

    # ------------------------------------------------------------ 控制器
    for blueprint in (
        system_bp.bp,
        _safe_import('app.api.compat', 'bp'),
        _safe_import('app.api.library', 'bp'),
        _safe_import('app.api.playlists', 'bp'),
        _safe_import('app.api.ui', 'bp'),
        _safe_import('app.api.files', 'bp'),
        _safe_import('app.api.online', 'bp'),
        _safe_import('app.api.curation', 'bp'),
    ):
        if blueprint is not None:
            app.register_blueprint(blueprint)

    _register_error_handlers(app)
    _register_middleware(app, settings)

    @app.teardown_appcontext
    def _teardown(_exc: BaseException | None) -> None:
        return None

    logger.info(
        '山河回响启动完成 version=%s env=%s', __version__, settings.env,
        extra={'mre_settings': settings.as_public_dict()},
    )
    return app


def _curation_service(engine: Any) -> Any:
    '''策展编辑服务。构造失败时返回 None, 对应蓝图也会被跳过, 其余功能不受影响'''
    try:
        from app.services.curation_service import CurationService
        return CurationService()
    except Exception as exc:                                       # noqa: BLE001
        logger.warning('策展编辑服务未启用: %s', exc)
        return None


def _safe_import(module: str, attr: str) -> Any:
    '''导入蓝图; 缺失时降级为「未启用」而不是整个应用起不来'''
    from importlib import import_module
    try:
        return getattr(import_module(module), attr)
    except Exception as exc:                                       # noqa: BLE001
        logger.warning('蓝图 %s 未启用: %s', module, exc)
        return None


def _register_error_handlers(app: Flask) -> None:
    '''错误体统一为 {'error': '可直接展示的文本', 'code': '机器可读码'}。

    error 必须是字符串: 前端普遍写 `new Error(d.error || ...)` 后直接 toast,
    给成对象会在界面上弹出 "[object Object]"。code 供程序分支使用。
    '''
    def _body(code: str, message: str, *, detail: str | None = None) -> dict:
        payload: dict[str, Any] = {'error': message, 'code': code}
        if detail is not None:
            payload['detail'] = detail
        return payload

    @app.errorhandler(AppError)
    def _handle_app_error(err: AppError) -> tuple[Any, int]:
        detail = None
        if err.details is not None:
            detail = err.details if isinstance(err.details, str) else json.dumps(
                err.details, ensure_ascii=False, default=str)
        return jsonify(_body(err.code, str(err), detail=detail)), err.http_status

    @app.errorhandler(404)
    def _handle_404(_err: Any) -> tuple[Any, int]:
        return jsonify(_body('not_found', '接口不存在')), 404

    @app.errorhandler(405)
    def _handle_405(_err: Any) -> tuple[Any, int]:
        return jsonify(_body('method_not_allowed', '请求方法不被支持')), 405

    @app.errorhandler(413)
    def _handle_413(_err: Any) -> tuple[Any, int]:
        return jsonify(_body('payload_too_large', '请求体过大')), 413

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception) -> tuple[Any, int]:
        '''兜底: 记录堆栈用于排障, 但只把规范化错误体回给客户端, 绝不泄漏内部细节'''
        logger.exception('未处理异常: %s', err)
        settings = app.extensions.get('settings')
        detail = str(err)[:500] if settings is not None and settings.debug else None
        return jsonify(_body('internal_error', '服务内部错误，请稍后重试', detail=detail)), 500


def _register_middleware(app: Flask, settings: Settings) -> None:
    @app.before_request
    def _assign_request_id() -> None:
        set_request_id(uuid.uuid4().hex[:16])

    @app.before_request
    def _guard_token() -> Any | None:
        '''非本机绑定时的口令校验(配置层已保证此时必有 MRE_API_TOKEN)'''
        if not settings.require_token:
            return None
        if request.path.startswith(('/health', '/ready', '/static')):
            return None
        provided = request.headers.get('X-Api-Token') or request.args.get('token')
        if provided != settings.api_token:
            from app.errors import UnauthorizedError
            raise UnauthorizedError('访问口令不正确')
        return None

    @app.after_request
    def _security_and_log(resp: Any) -> Any:
        from app.logging_setup import get_request_id
        resp.headers['X-Request-Id'] = get_request_id()
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['X-Frame-Options'] = 'SAMEORIGIN'
        resp.headers['Referrer-Policy'] = 'no-referrer'
        # 桌面端默认同源访问; 显式列出来源, 绝不使用通配符
        if settings.cors_origins and request.headers.get('Origin') in settings.cors_origins:
            origin = request.headers['Origin']
            resp.headers['Access-Control-Allow-Origin'] = origin
            resp.headers['Vary'] = 'Origin'
            resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Api-Token'
            resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
        return resp

    @app.after_request
    def _access_log(resp: Any) -> Any:
        from app.logging_setup import get_request_id
        status = int(getattr(resp, 'status_code', 0) or 0)
        level = logging.ERROR if status >= 500 else logging.INFO
        logger.log(
            level, '%s %s -> %d', request.method, request.path, status,
            extra={
                'mre_http_method': request.method, 'mre_http_path': request.path,
                'mre_http_status': status, 'mre_request_id': get_request_id(),
            },
        )
        return resp
