# 数据库迁移（Alembic）

把「运行时 `app.database.create_schema()` 建表」升级为可版本化的迁移。

> **定位**：这是**开发期/维护期工具**，不进 exe 打包产物
> （`packaging/mountainriverechoes.spec` 的 `excludes` 已排除 `alembic`）。
> 运行期建表入口**没有改动**，仍是 `app.database.create_schema()` —— 运行时行为不变。
> 本目录只服务于「以后要改表结构时，有一份可追溯、可回滚的版本历史」。

## 文件

| 文件 | 作用 |
| --- | --- |
| `../alembic.ini` | Alembic 配置；`script_location = migrations`，`sqlalchemy.url` **留空** |
| `env.py` | 从 `app.config.load_settings().db_path` 推导数据库地址，`target_metadata = Base.metadata` |
| `script.py.mako` | 新迁移脚本模板 |
| `versions/0001_baseline.py` | 基线：7 张表 + 13 个索引 + 2 个具名唯一约束 + FTS5 虚表与 3 个触发器 |

数据库地址**不写死**：`MRE_DB_PATH` / `MRE_DATA_DIR` 对 alembic 与运行时完全同效。

所有命令都在仓库根执行，Python 用仓库内解释器：

```bash
./venv/bin/python -m alembic <子命令>
```

---

## 一、新库怎么建

最简单：直接跑迁移。

```bash
MRE_DB_PATH=/tmp/mre_demo.db ./venv/bin/python -m alembic upgrade head
```

等价于运行时的 `create_schema()`：7 张表 + 全部索引 + `tracks_fts`（虚表）+ 3 个同步触发器
（`tracks_fts_ai` / `tracks_fts_ad` / `tracks_fts_au`）会全部就位。

新库其实也可以什么都不做 —— 应用首次启动会自己 `create_schema()` 建出来，
迁移只是让「建库」这件事变得可复现、可版本化。

---

## 二、已有库怎么对齐（**关键：只 stamp，不要 upgrade**）

已经有表、有数据的库（例如 `var/mountainriverechoes.db`）**绝不能**直接
`upgrade head` —— 那会因为 `CREATE TABLE` 已存在而失败，甚至留下半截状态。

正确做法是 `stamp`：只往 `alembic_version` 里写一行版本号，**不执行任何 DDL**。

```bash
# 1. 先备份（stamp 本身不动数据，但这是操作生产库的惯例）
cp var/mountainriverechoes.db var/mountainriverechoes.db.bak

# 2. 把基线版本写进版本表，即「声明：这个库已经处于 0001_baseline 之后的状态」
./venv/bin/python -m alembic stamp head

# 3. 确认没有真的去建表 / 改表
./venv/bin/python -m alembic current
sqlite3 var/mountainriverechoes.db "select * from alembic_version;"   # 应只有一行 0001_baseline
```

`stamp` 之后，这个库就被纳入版本管理了：以后新增的迁移（如 `0002_xxx`）才会对它生效。

> ⚠️ `var/mountainriverechoes.db` 是正式库（58008 首曲目）。
> 任何 `upgrade` / `downgrade` 都先在副本上验证过再动它。

**当前状态**：该库已于 2026-10-03 执行过 `stamp head`，`alembic current` 输出
`0001_baseline (head)`，无需重复执行。打标前后核对过：曲目数 58008 不变，
景颇族 e26=4587 / 傣族 e16=6649 / 汉族民间小调 han=2677 均不变。
后续新增 `0002_*` 迁移时，它就能直接 `upgrade head` 接上。

---

## 三、升级流程（以后要改表结构时）

1. **改 ORM**：编辑 `app/models/entities.py`（唯一权威定义）。
2. **生成迁移**：
   ```bash
   MRE_DB_PATH=/tmp/mre_alembic_dev.db ./venv/bin/python -m alembic revision --autogenerate -m "简述改了什么"
   ```
   （用一个**临时的、已 upgrade 到 head 的**库来对比，不要拿正式库跑 autogenerate。）
3. **人工校对**生成的脚本：
   - SQLite 无法真正 ALTER 的改动（改列类型、删列、改约束）需要改成
     `with op.batch_alter_table('表名') as batch_op:` 的批处理写法；
   - 默认的 `op.create_table()` / `op.drop_table()` 不需要批处理。
4. **验证**：临时库上跑一遍 `upgrade head` → `downgrade -1` → `upgrade head`。
5. **应用**：确认运行时也通（`MRE_DB_PATH=... ./venv/bin/python -m app`），再对正式库升级。

### 已知的 autogenerate 噪音（不是 bug，别照着改）

FTS5 虚表会在 `sqlite_master` 里留下 5 个物理条目：
`tracks_fts`、`tracks_fts_data`、`tracks_fts_idx`、`tracks_fts_docsize`、`tracks_fts_config`。
它们不在 SQLAlchemy 元数据里，所以 `alembic check` / `--autogenerate` **永远**会报
「remove_table: tracks_fts / _data / _idx / _docsize / _config」。

**看到这 5 条时直接忽略**，把它们从生成的脚本里删掉即可。
真正的判断标准是：**除了这 5 条之外没有别的差异**（业务表和索引都不该出现）。

```bash
MRE_DB_PATH=/tmp/mre_alembic_dev.db ./venv/bin/python -m alembic check
```

---

## 四、回退

```bash
MRE_DB_PATH=/tmp/mre_demo.db ./venv/bin/python -m alembic downgrade base
```

会把 7 张表、索引、FTS 虚表与触发器全部拆掉，只留下 alembic 自己的
`alembic_version` 空表（Alembic 保留它，仅清空其中的版本行）—— 这是预期行为，不是残留。

## 五、常见问题

**Q：为什么 `alembic.ini` 里 `sqlalchemy.url` 是空的？**
因为地址必须跟着 `app.config` 走。写死路径一换机器就错，也容易把本机绝对路径提交进仓库。

**Q：迁移建出来的库，和运行时 `create_schema()` 建出来的库一样吗？**
一样。已逐条比对过 `sqlite_master`：7 张表、13 个索引、2 个具名唯一约束、
`tracks_fts` 与 3 个触发器的 DDL 全部一致。
唯一差异是 `playlist_tracks` 的 `CREATE TABLE` 里 `UNIQUE` 与 `FOREIGN KEY`
子句的**书写顺序**不同（Alembic 先 FK 后 UNIQUE，SQLAlchemy 反过来），语义等价。

**Q：FTS 相关 SQL 为什么要手写？**
`tracks_fts` 是 SQLite 虚拟表、触发器也不是表/索引，SQLAlchemy 元数据里没有任何对应对象，
Alembic 无从生成，只能 `op.execute()`。SQL 与 `app/database.py::ensure_fts()` 一字不差，
包括 trigram / unicode61 分词器的选择判据（SQLite >= 3.34 用 trigram）。
