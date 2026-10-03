'''
Function:
    策展编辑控制器。
      POST /api/ethnos/edit  民族歌单协作编辑(12 个 action 的单一入口)
'''
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.api.deps import svc
from app.errors import AppError

logger = logging.getLogger(__name__)

bp = Blueprint('curation', __name__)


@bp.post('/api/ethnos/edit')
def api_ethnos_edit() -> tuple[dict, int]:
    '''协作编辑: 增删歌手/曲目、改署名、搬库、置顶排序。

    请求体(公共字段): {group, editor, action}
      add_artist        {name}
      remove_artist     {name, kill_tracks?}                kill_tracks=true 连名下曲目硬删
      save_artist_order {names:[], pinned:[]}               只存名单+置顶, 不存位置索引
      save_track_order  {keys:[{song_name,singers,source}], pinned:[同结构]}
      add_to_artist     {dst, artist, sid, tid}             会话曲目挂到目标民族的歌手名下
      add_tracks        {tracks:[{song_name,...}]}          批量灌入, 按歌名指纹去重
      reassign_singer   {tname, tsingers, tsource, new_singers}
      remove_track      {tname, tsingers?, tsource?}        缺省歌手/音源时只删第一条同名
      remove_tracks     {keys:[{song_name,singers,source}]}
      move_tracks       {dst, keys:[...], mode: move|copy}
      move_artist       {dst, name}
      remove_collection {name, restore?|kill_tracks?}
      move_collection   {dst, name}

    group / dst 为民族歌单 key(e00..e54 / han), 也接受「景颇族」这类族名。
    响应: {'ok': true, 'count': 该民族现有曲目数, ...各动作的附加统计}
    '''
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        return {'error': '需要 JSON 对象'}, 400

    service = svc('curation')
    if service is None:
        return {'error': '策展编辑服务未启用'}, 503

    try:
        result = service.apply(body, invalidate=svc('library').invalidate)
    except AppError as err:
        # 旧版该端点回的是 {'error': '文本'}: 前端 api() 直接把 d.error 当消息弹 toast,
        # 这里维持老契约, 不让结构化错误体变成 "[object Object]"
        # 注意取 to_dict()['message'] —— err.message 是类属性的默认值, 不是本次的具体提示
        return {'error': err.to_dict()['message']}, err.http_status
    return jsonify(result), 200
