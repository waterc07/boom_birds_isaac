# Codex 接触读取层修复交接（2026-11-02）

## 状态与并行边界

本轮得到用户授权，与 DSH 分工推进。Codex 只修改读取适配与测试，不启动 Isaac、不占 GPU、不切分支、不提交；DSH 负责独立 GUI 生命周期探针与闭环重放配置。用户和其他工作包既有修改保留。

源码审计依据见 [审计与方案](CONTACT_REVIEW_CODE_AUDIT_20261102.md)。本轮不能宣称真实 PhysX 接触生命周期、单进程多 episode 或旧案例闭环重放已经修复。

## 修改文件

- `src/boom_birds/evaluation/contact_readout.py`：新增标准库读取适配，接受 Torch `.tolist()` 或嵌套序列；严格验证 `(N,B,3)` / `(N,B,M,3)` 的所选环境数据、有限值、body/filter 数量与显式 target 顺序。
- `tests/evaluation/test_contact_readout.py`：25 条针对性回归。
- `scripts/run_contact_verification.py`：接入读取适配，原始每 sensor 结果/异常写入 steps，修正无根据的 summary 无接触/旧案例一致性升级。

## 实际修复

1. 单 filter 三维向量不再误取成二维列表；多 body/filter 不再把绝对值总和复制为假三维向量。
2. 所有力使用欧氏模长；每 target 保留最大模长的真实 body 向量，明确不是 body 总和或时间窗最大值。
3. 一次读取完整验证后才返回，避免异常前部分更新；错误保留类型/消息，不再静默转为零。
4. 传感器每次更新 `force_recompute=True`；这只确保本次请求更新，不证明底层 contact view 或覆盖健康。
5. 原始成功零值保留在 `contact_readout.reads`；没有独立覆盖验证时，v2 证据与 episode 判 UNKNOWN/UNDECIDABLE，不写 NO_CONTACT。
6. net force 不赋予 target prim；filtered 映射计数不一致显式失败。调用方仍须验证实际 PhysX filter 顺序与 target_paths 对应，不能只因数量相等就假定真实对象绑定正确。
7. 明确 `event` 为 force threshold 派生，非独立 PhysX callback；force window 使用物理步长，不再用策略步长冒充观测窗口。v2 旧 sampling 描述仍沿用旧合同，新增 readout/manifest 明确有效采样为最后物理步；尚未实现所有物理子步的时间窗最大值。
8. 几何探针不再证明旧闭环结果 CONSISTENT，即使本次探针测力也仍为 UNDECIDABLE；本次接触观测单独保留。
9. run_plan 新增 readout schema/source hash。旧 freeze 缺少该项会在 GUI 启动前拒绝，必须新建预运行冻结，不能套用旧预期制造新 PASS。

## 已执行验证

解释器：`E:\isaac\env_isaaclab\Scripts\python.exe`。

- 新测试先因缺失模块/接口失败，再实现通过；episode 判定新增六项在实现前失败、实现后通过。
- `-m pytest tests/evaluation/test_contact_readout.py -q`：25 passed。
- `-m pytest -q`：750 passed，exit 0，81.51 s。
- `-m py_compile scripts/run_contact_verification.py src/boom_birds/evaluation/contact_readout.py`：exit 0。
- 文档审计：PASS，119 links，exit 0；执行后恢复原有 planning_audit.json 字节，避免覆盖用户已有报告修改。
- 真实 CPU Torch `(1,1,1,3)` 张量：filtered `[0.03,0,0]` 正确读取；net `[0.01,0.01,0.01]` 欧氏模长约 0.0173205 N，低于 0.02 N，而原 L1 为 0.03 N。
- 仅本轮运行代码 diff 空白检查通过。

## DSH 后续必须完成

1. 不重写本轮适配；先阅读新增代码和测试。旧 verifier 对 C/D 要求有效零/NO_CONTACT 的口径不再成立，新 verifier 和 expected 必须版本化，不能修改旧冻结。
2. 冻结生成器需写入与运行入口相同的 `contact_readout` 字段；冻结应追踪 helper 源码 hash。全套源码/工作树的真实一致性仍依原工作包规则核查，本轮不宣称已补齐整个冻结器的所有防篡改检查。
3. 独立 GUI 探针验证实际 body/filter 路径、更新时间、shape、reporter、生命周期。先固定 sensor 连续三次接触，再逐项测试 reset/view 重建，不能直接认定只能首 episode 有效。
4. 已知同进程读零问题未解决前，独立进程只能作为临时运行模式，必须标注。新代码会诚实地产生 UNKNOWN，不能把这当作需要放宽判据的障碍。
5. 旧案例从原始初始条件、策略、轨迹、时钟和边界闭环复现；当前 replay 模式仍只做局部几何探针。
6. 生产 `run_dynamic_eval.py` 的中心偏移包络迁移另做明确差异审查，本轮未改，不能宣称已集成。

## 另发现、未改动的证据风险

- 原运行器仍以常量写入 `episode_boundary.no_silent_reset=True` 等字段，`step_hover` 未检查环境返回的 terminated/truncated；不能把这些声明字段当独立边界证据，生命周期探针应记录实际计数与 done 信号。
- 原运行器末尾会写入空字节 `screenshots/final.png`；该文件不是有效截图，不能用存在性证明 GUI 可视。本轮未触碰该逻辑；现有其他真实截图需逐个独立核查，不能据此否定所有历史截图。
- wall 诊断存在高度偏离时重新写机器人 pose 的逻辑，属于受控诊断干预，不可冒称完全无干预的闭环飞行。

以上风险记录给下一步处理，不在本轮顺带改动。当前接触问题尚未总体关闭，不提升 Gate。
