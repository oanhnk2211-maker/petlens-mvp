# PetLens 查询结果持久化表设计

数据库：SQLite  
数据库文件：项目根目录 `petlens.db`  
数据表：`history`

## 字段设计

| 字段 | SQLite 类型 | 约束 | 数据来源 | 用途 |
|---|---|---|---|---|
| `id` | `INTEGER` | 主键、自增 | SQLite 自动生成 | 唯一标识一条查询记录 |
| `created_at` | `TEXT` | 非空 | UTC 时间的 ISO 8601 字符串 | 记录查询时间 |
| `item_name` | `TEXT` | 非空 | `SafetyResult.normalized_item` | 保存标准化物品名称 |
| `species` | `TEXT` | 非空 | `PetProfile.species` | 保存关联宠物的物种 |
| `risk_level` | `TEXT` | 非空 | `SafetyResult.risk_level` | 保存风险等级 |
| `confidence` | `INTEGER` | 非空 | `SafetyResult.confidence` | 保存 0–100 的置信度 |
| `result_json` | `TEXT` | 非空 | `SafetyResult.model_dump_json()` | 保存完整结构化分析结果 |
| `profile_json` | `TEXT` | 非空 | `PetProfile.model_dump_json()` | 保存本次查询使用的宠物画像 |

## 建表 SQL

```sql
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    item_name TEXT NOT NULL,
    species TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    confidence INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    profile_json TEXT NOT NULL
);
```

## 写入关系

```text
SafetyResult.normalized_item ──> history.item_name
PetProfile.species          ──> history.species
SafetyResult.risk_level     ──> history.risk_level
SafetyResult.confidence     ──> history.confidence
SafetyResult（完整 JSON）    ──> history.result_json
PetProfile（完整 JSON）      ──> history.profile_json
```

每次查询完成后写入一行。界面中的最近查询按 `id DESC` 排序，默认读取最近 30 条记录。

## 数据与隐私说明

- SQLite 的 `TEXT` 字段用于保存 JSON；读取完整历史时，由 Pydantic 还原并校验为 `SafetyResult` 和 `PetProfile`。
- 当前表中没有图片或图片路径字段，上传的原始图片不会写入该表。
- `profile_json` 可能包含宠物名字、年龄、体重和健康备注。
- `petlens.db` 是未加密的本地文件，已写入 `.gitignore`，不应提交到公开仓库。

## 实现位置

- 数据库路径、建表、写入和读取：`app/storage.py`
- 应用启动初始化与查询结果保存：`streamlit_app.py`
- 数据模型与历史反序列化校验：`app/models.py`
- 数据库忽略规则：`.gitignore`
