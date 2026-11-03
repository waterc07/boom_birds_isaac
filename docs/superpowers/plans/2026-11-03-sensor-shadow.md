# V2.2 模拟传感器 shadow 链

- [x] 设计映射：OV9782 前视 RGB + 前向近场距离职责；所有未冻结参数标 PROPOSED；距离使用 SIM_RENDER_DEPTH，不冒充 ToF/双目。
- [x] 复用 v2 MessageHeader/Context，新增标准库 observation envelope/gate；记录时间、上下文、内外参、payload/hash、validity。
- [x] hard reset 后 camera/gate/sequence 重建；预热在任务 step 外；旧 generation 隔离；失败回归测试。
- [x] runner `--sensor-shadow`/`--sensor-shadow-config` shadow 接入，ORACLE 控制不变。
- [x] 6 个预冻结 GUI episode（static×2、route×2、reset×2）；1,728 records/1,336 accepted；两个已知 depth 参考。
- [x] 独立核验 43 checks PASS；迁移 4,230 行；pytest 793；文档审计；独立导出恢复。
- [x] 报告/交接/小样例/GUI 证据/hash；中文提交，不推送。

正式源码 commit `a623b4b`；最终交付只增加 freeze/expected/核验器/报告/证据。下一项：真实相机/ToF 参数、CSI/驱动、时间戳与 RK3576 采集标定，然后接入 shadow 感知消费者。
