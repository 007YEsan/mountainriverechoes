'''
Function:
    仓储层 —— 唯一允许直接写 SQL / 碰 ORM 实体的地方。
    服务层只面对这里返回的纯数据结构, 不碰 Session。
'''
