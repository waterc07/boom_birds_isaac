# 历史评价运行 episode 边界审计

检测方法：逐 step 记录中的出生位姿/零速度突变（辅助证据）；旧运行未记录 episode 计数或 terminated/truncated 标志，因此“未检测到”不等于“已证明没有”。
历史 velocity/reach CSV 的列表列未按 CSV 引号写出，使用括号感知的兼容解析器恢复逐 step 字段。

| 运行 | 状态 | 受影响/异常 | 方法与限制 |
| --- | --- | --- | --- |
| layered/final_run2 | CONFIRMED_POLLUTION | ['C_dynamic-8000-000', 'C_dynamic-8000-006', 'C_dynamic-8000-021', 'D_observation-9000-000', 'D_observation-9000-011', 'D_observation-9000-023', 'E_disturbance-10000-004', 'E_disturbance-10000-024'] | no episode counter/flags recorded in this historical run |
| layered/final_run3 | CONFIRMED_POLLUTION | ['C_dynamic-8000-000', 'C_dynamic-8000-006', 'C_dynamic-8000-021', 'D_observation-9000-000', 'D_observation-9000-011', 'D_observation-9000-023', 'E_disturbance-10000-004', 'E_disturbance-10000-022', 'E_disturbance-10000-024'] | no episode counter/flags recorded in this historical run |
| layered/final_run4 | CHECKED_NO_EVIDENCE | None | no episode counter/flags recorded in this historical run |
| velocity_chain/full | CHECKED_NO_EVIDENCE | None | no episode counter/flags recorded; spawn signature is auxiliary |
| reach/run1 | CHECKED_NO_EVIDENCE | None | no episode counter/flags recorded; spawn signature is auxiliary |
| reach/run2 | CHECKED_NO_EVIDENCE | None | no episode counter/flags recorded; spawn signature is auxiliary |
| compare/tuning_run1 | INSUFFICIENT_DATA | 16 | no per-step records; cannot prove or exclude a silent auto-reset. Run predates the evaluation-boundary fix, so its per-episode values are unverified. |
| compare/tuning_run2 | INSUFFICIENT_DATA | 16 | no per-step records; cannot prove or exclude a silent auto-reset. Run predates the evaluation-boundary fix, so its per-episode values are unverified. |
| compare/final_run1 | INSUFFICIENT_DATA | 60 | no per-step records; cannot prove or exclude a silent auto-reset. Run predates the evaluation-boundary fix, so its per-episode values are unverified. |
| compare/faults_run2 | INSUFFICIENT_DATA | 16 | no per-step records; cannot prove or exclude a silent auto-reset. Run predates the evaluation-boundary fix, so its per-episode values are unverified. |
| compare/faults_run4 | INSUFFICIENT_DATA | 16 | no per-step records; cannot prove or exclude a silent auto-reset. Run predates the evaluation-boundary fix, so its per-episode values are unverified. |
| c_diagnosis/legacy_original_r3 | CONFIRMED_POLLUTION | [{'scenario_id': 'C_dynamic-8000-021', 'outcome': 'INVALID', 'reason': 'ENV_TRUNCATED', 'steps': 31}, {'scenario_id': 'C_dynamic-8000-021', 'outcome': 'INVALID', 'reason': 'ENV_TRUNCATED', 'steps': 31}, {'scenario_id': 'C_dynamic-8000-021', 'outcome': 'INVALID', 'reason': 'ENV_TRUNCATED', 'steps': 31}] | intentionally reproduces the old defect for evidence |
