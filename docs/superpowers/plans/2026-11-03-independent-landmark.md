# 地标消费者独立评价与有限改进

- [x] 审计旧数据：四个旧路线 case 同 waypoints/相机轨迹；旧 36 帧降级为开发/历史；旧 TP presence-level、bearing bbox-center 未验证。
- [x] 建立新独立数据集：reverse_south/north/static_test_oblique/static_test_away；开发 south_new/static_dev；前台 GUI；label/split 固定。
- [x] 新标签：presence/visibility/bbox/绿灯参考点；9 个 localization 子集；IoU .3、bearing 5° 为 PROPOSED；代理人标注限制记录。
- [x] 两项改进：development-only 多视角模板库 + 模板 anchor bearing；阈值 .65 仅 dev 选择；baseline 旧模板同测试配对。
- [x] 正式评价：baseline presence TP12/FP0/FN15，P1/R.444，localization TP0；improved TP0/FP2/FN27，P0/R0；无改善。
- [x] 独立核验 30 checks PASS；801 tests；文档审计。
- [x] 旧数据审计/报告/交接/证据；失败样例；结论：不具备区域/地标关联 shadow 条件。
- [x] 中文提交（不推送），保留用户修改。

下一项：真实相机/镜头/CSI/时间同步 + 地标数据库/区域拓扑 + 更多独立视角/标注，不接控制。
