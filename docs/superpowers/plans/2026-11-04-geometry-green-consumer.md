# 塔体几何＋绿灯参考点消费者

- [x] 核对根因/草稿/旧 freeze；确认 49 帧已暴露；复核 B 复现/bbox≠绿灯/anchor 未验证。
- [x] 资产先验：目标绿灯可见于 8/9 参考帧；north s181 无参考；存在相似绿色负例；绿灯仅为当前资产视觉先验。
- [x] 实现绿光种子 + 饱和结构 bbox + 空间/尺度/边缘验证 + 多候选拒绝；不读 truth/标签/目标位置，不输出距离/概率。
- [x] 开发计划/条件先冻结；开发集（49 已暴露 + 30 development）满足 presence P1/R.963、bbox7/9、anchor8/8；一次有界 min_green_area 8→10 后冻结。
- [x] 冻结新 4 episode 采集/抽样/标签计划；前台 GUI 采集成功；30 test frames、18 正/12 负、9 localization。
- [x] v1 标签参考点错误保留为 INVALID_LABEL_REFERENCE；v2 仅修正 3 个 route refs，算法/参数不变。
- [x] 正式 v2：presence TP13/FP0/FN5/TN12、bbox TP3/9、joint TP3/18；static A 0/3；C 停止此启发式。
- [x] 独立核验 PASS17；单元测试；报告/交接/证据/hash；中文提交不推送。

最终决策 C：不进入地标关联 shadow；下一候选需目标专用轻量分割/实例模型、200–400 帧标注、独立 sealed test，未在本包启动训练。
