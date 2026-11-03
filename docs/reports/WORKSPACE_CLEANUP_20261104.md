# 工作区整理与分支收敛（2026-11-04）

本次按用户要求整理长期未提交内容、同步文档、提交并推送；不新增算法或仿真实验，不提升 Gate。

## 整理范围

- 入库当前 V2.2 设计正文、V2.1 原始快照、来源 hash 和路线验收报告；保留旧设计的历史入口说明。
- 归档此前留在工作树的官方 GUI smoke 修复、分层 reset 核验、接触读出/生命周期诊断及最小矩阵工具。接触专项入口是受控诊断工具，其旧包络、截图占位和边界字段限制见原审查；不得用它替代当前单环境动态评价默认入口。
- 归档旧冻结、pilot/失败版本、小型核验摘要与 GUI 截图，保持原路径、原始字节和原有状态。补提交不代表重新验收；运行时源码以各报告记录的 commit 与工作树差异/hash 为准。
- 新增 [当前状态索引](CURRENT_STATUS.md)，同步 README、PROJECT_PLAN、AGENTS 中的接手入口，避免将“感知完全未实现”与“感知 shadow 实验已实现但未达标”混淆。
- 文档审计新增 AGENTS 和当前状态索引的链接检查。Git 空白检查接受 Python、JSON/JSONL、Markdown 与文本摘录的 CRLF 行终止符，不改变源码、配置和证据的原始字节；V2.2 正文与原始快照 hash 保持不变。

## 历史冻结的使用边界

本次补入库的以下版本不替代各工作包的最终冻结：

| 历史文件组 | 使用说明 |
| --- | --- |
| `configs/perception/landmark_freeze_v1/v2/v3.json` | 旧迭代留档；原消费者交付使用 v4，后续独立评价另有冻结 |
| `configs/scenarios/contact_production_migration_pilot_v1.json`、`contact_production_migration_v2/v3.json` | 早期接入/pilot/修复版本，按对应报告识别，不套用当前默认入口 |
| `configs/scenarios/contact_production_migration_20_v1.json` | 20 场景评价历史版本，后续正式结果对应 v2 |
| `configs/scenarios/dynamic_default_equivalence_*_v1/v2.json` | 默认升级过程中的诊断/迭代版本；最终默认/显式等价结果使用 v3 |
| `configs/scenarios/dsh_contact_lifecycle_freeze_v1.json` | 专用最小新鲜度矩阵冻结，结合当时工作树和 readout hash 使用，不是通用默认动态冻结 |

未移动、重命名或改写这些历史文件来适配当前源码。归档时仍保留正式运行与 pilot、失败轮次、标签无效轮次的区别。

## 分支处理

用户要求取消 `codex/` 前缀；当前工作分支由 `codex/bb22-contact-envelope` 改名为 `feat/v2.2-simulation-perception`。在 `7a7001c` 基线上检查祖先关系后，以 `git branch -d` 删除 17 个已被该分支完整包含的本地历史分支，无独有提交分支被删除。

本地仅保留 `main` 和新的工作分支；远端 `p0-foundation` 保留。两个 detached 临时 worktree 未清理。分支改名/删除前后 HEAD 和 87 个修改/未跟踪文件的 hash 一致。此次推送选择新的工作分支，不强推、不合并到 main、不修改历史提交。

## 验证与保留项

- 现有解释器执行 `python -m pytest -q`：806 passed，exit 0；本轮验证的是单元测试，不是新 GUI/训练结果。
- `python scripts/planning/audit_documents.py`：PASS，31 文件、140 个本地链接；设计与来源 hash 检查通过。
- `git diff --check`：通过；提交前继续检查暂存区及文本/二进制文件完整性。
- 初始 86 个待整理文件约 5.6 MB，未发现超大文件；常见 token/私钥模式扫描无命中，该扫描不等同于全面安全审计。
- 原始大日志、图像集、权重、外部地图资产和本机配置保持在忽略目录或外部存储。原未提交文件的本地字节备份及分支清单位于忽略的 `tmp/workspace_cleanup_20261104/`，不作为唯一版本化结论来源。

本轮未运行 Isaac、模型训练、PX4、板端、SITL/HIL 或实机；未安装/升级环境、未清理用户进程。后续工作按当前状态索引推进，感知方法选型仍待实施。
