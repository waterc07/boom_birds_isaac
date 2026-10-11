# Execution ledger — plan: docs/superpowers/plans/2026-10-11-p0-p1-foundation.md

2026-10-11，按已接受 v1.2 推进。当前执行范围：Task 1 环境核查和Task 2标准库合同；Task 3–6仍待推进。

- Pre-flight: Task 1资产接口→Task 3执行器；官方四维为推力/力矩，与速度合同不同，必须实现外环适配。
- Pre-flight: Task 2时效/坐标→Task 3/4/6；共用标准库合同，reset必须清理epoch/动作。
- Pre-flight: Task 4 terminated/truncated→Task 5统计/Task 6 PPO；碰撞优先，超时不成功。
- Ruling: 在用户指定主工作区新建独立Git仓库及p0-foundation分支，保留原资料基线，不创建额外worktree — 符合当前工作区指定与W00授权 — 代价是并行编辑仍需协调。
- Ruling: P0诊断脚本以真实环境运行、日志和JSON核验，不为低影响诊断工具构造镜像实现的单元测试 — 当前任务是现场核查，业务合同仍按Task 2先测试 — 风险是诊断工具覆盖有限，不用于飞行验收。
- Task 1: complete (scoped W00 evidence)；既有解释器/启动器核实、包快照、固定上游SHA/许可、官方100步exit 0、官方RSL-RL 1迭代exit 0生成checkpoint；pip check的4项冲突明确保留，整体依赖一致性未通过。
- Ruling: 关闭scene.clone_in_fabric解决官方最小例克隆Error，保持PhysX/Fabric I/O — 单因素复测100步和8环境短PPO运行无Error/Traceback — 扩规模后仍需验资源和克隆隔离。
- Ruling: VelocityCommand增加origin_epoch/clock_id/schema_id — 原点重置及时钟域切换必须可拒绝旧动作 — 未来适配器必须显式携带这些字段。
- Task 2: complete；pytest RED因缺少boom_birds包，GREEN全套31 passed；标准库隔离在子进程验证，未安装项目包或新依赖。
- Task 3–6: NOT RUN。

- Final review: independent read-only review of Task 1/2 snapshot; no Critical findings.
- Final: regraded mutable velocity container and nonstring clock equality from Minor to Important — public contract bypasses immutability/clock-domain guarantees, despite decode_action normal path being safe.
- Final: fixed both findings — test_public_command_rejects_mutable_velocity_container and test_nonstring_clocks_never_match_by_python_coercion RED→GREEN; full suite 33/33 passed on both Isaac and default system Python.
- Final: deferred minors: none.
- Final: Ruling on review scope — Task 3–6 are the next unexecuted work, not missing functionality in the current P0 checkpoint; no G1/P1 completion claim — cost: full flight/PPO comparison still requires future execution.
- Verification: pinned upstream/source hashes, official 100 samples and checkpoint hash matched; document audit PASS; outputs/weights/external ignored; no merge or push.
