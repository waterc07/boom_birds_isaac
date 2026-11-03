# 单环境动态评价默认升级

- [x] 评审默认升级：单环境、reset/握手、接触/几何/UNKNOWN 分层、旧冻结核验、旧 bbox/max 混用、进程释放、失败/Kit exit 0。
- [x] 审查 LF/CRLF 冻结：v2 记录 hash algorithm/scope/effective config/sources；v1 raw 显式兼容；失败测试后最小修复。
- [x] 实施默认升级与 legacy 显式迁移；旧 freeze 明确拒绝；混合策略拒绝；completion marker。
- [x] 预冻结 default/explicit 等价运行：A_south_0 + C_south_0 × follow_only/supervisor = 8 GUI episode。
- [x] 独立等价核验 52 checks PASS；迁移/raw 核验；786 pytest；文档审计；独立导出恢复。
- [x] 报告/交接/版本化证据/hash；仅提交审查文件，不推送。

正式运行源码 commit：`fc82d5a`；最终交付 commit 只增加 freeze/文档/证据。默认升级仅限单环境动态评价，不扩散到其他入口。报告见 `docs/reports/map_eval/contact_envelope/DSH_DYNAMIC_DEFAULT_UPGRADE_20261103.md`。
