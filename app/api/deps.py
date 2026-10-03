'''
Function:
    控制器依赖注入入口 —— 从 Flask 扩展槽里取服务实例。
    控制器不自己 new 服务对象, 也不读全局配置: 全部由工厂注入, 便于测试替换。
'''
from __future__ import annotations

from typing import Any

from flask import current_app


def svc(name: str) -> Any:
    services = current_app.extensions.get('services')
    if services is None or name not in services:
        raise RuntimeError(f'服务未注册: {name}')
    return services[name]


def settings() -> Any:
    return current_app.extensions['settings']


def all_services() -> dict[str, Any]:
    return current_app.extensions.get('services') or {}
