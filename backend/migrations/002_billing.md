# 共用仪器阶梯计费表（002）

新增四张表，SQLAlchemy 启动时 `Base.metadata.create_all` 自动创建，不影响既有表：

- `billing_contracts`：固定合同与边际阶梯价（tiers JSON），按 合同编号+版本 唯一，只新增不覆盖。
- `billing_usages`：用量区间（start_at/end_at/quantity，数量 Numeric(30,10)），`backfilled` 标记补录。
- `billing_jobs`：重算作业，`seq` 全局递增作为 FIFO 与“旧账不顶新账”护栏；保存合同用量冻结快照与 SHA256。
- `billing_ledgers`：合同-月版本化台账，`is_current` 标记现行版本；发布时单事务行锁（`with_for_update`）切换，每月仅一条现行行，历史版本保留可查。

升级已有数据库：直接启动后端即自动建表；无需数据回填。回滚：删除上述四张表即可，不影响成本归集簿原模块。计费队列使用 Redis key `billing-jobs`，与原 `report-jobs` 隔离。
