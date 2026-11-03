# 官方 smoke GUI 元数据缺陷修复与前台复测

日期：2026-10-31（Asia/Shanghai）。分支 `codex/bb22-official-gui-smoke`，基于评价审计提交 `e177eb6`。本工作包只修复官方 smoke 的结果写出缺陷并验证，不修改评价边界、制导参数、项目物理执行链或历史产物。

## 结论

`scripts/check_official_quadcopter.py` 在 `bc169ea` 新增命令元数据 `' '.join(sys.argv)`，但未导入 `sys`。精确表达式的独立执行确认 `NameError: sys is not defined`；补充一行 `import sys` 后，前台可视 GUI、Vulkan、CUDA:0、USD 克隆的官方四旋翼 100 步完成，结果 JSON 和 PASS 标记均写出，进程退出 0。

修复前脚本也做了完整前台 GUI 对照：正常退出 0，却没有 PASS 标记和结果 JSON，复现了交接中的“后续 GUI 重跑无结果”。因此该问题至少包含一个确定的 Python 元数据缺陷，不能仅按退出码或窗口关闭判为成功。

本结论不将此前持续高占用、被停止的 GUI 运行全部归因于该缺陷；并行实例、启动方式及插桩影响仍保留原记录。项目 velocity/reach/compare/faults 的已核验 GUI 成果继续有效，不能因这个独立入口的问题概括为整个 Isaac GUI 物理不可用。

## 实际验证

现场 RTX 5080、驱动 581.80，现有 Isaac Sim 5.1 / Isaac Lab 环境。运行前没有其他 Python/Isaac 实例；每次只启动一个实例，启动窗口使用 `WindowStyle Normal`，未使用 `--headless`、未加入定时栈采集器。保留既有环境、缓存、驱动和用户配置。

| 检查 | 结果 | 边界 |
| --- | --- | --- |
| 修复前精确命令元数据表达式 | 预期 NameError，确认缺少 sys | 标准库表达式复现，不运行 Isaac |
| 修复后精确元数据表达式 | 返回字符串 | 一行导入补齐 |
| 修复后官方 GUI 100 步 | PASS，exit 0，gui_mode=true，实际 Vulkan | Creating window 日志、100 条连续样本、PASS 标记、JSON 同时存在 |
| 修复前脚本完整 GUI 对照 | exit 0、无 PASS、无 JSON，未触发 watchdog | 复现结果写出异常；不是运行成功 |
| pytest | 232 passed in 3.52s，exit 0 | 现有单元回归，未新增仅验证 import 的镜像测试 |

修复后日志无 `[Error]`、`Traceback` 或原生访问冲突；stderr 为空。存在 `IMemoryBudgetManagerFactory` 接口重复获取的性能 Warning，本轮未改其实现。100 条样本的步号为 0–99，奖励和位置有限；脚本同时检查每步观测和奖励有限。总进程耗时约 33 秒，包含启动，不解释为实时控制或稳定性性能指标。

修复前对照使用 `git show e177eb6:scripts/check_official_quadcopter.py` 的原字节，保存于仓库外独立目录，不回退当前源码。其前台运行约 75 秒后退出，仍无结果；不同启动耗时不作为导入修复的性能收益。

## 命令与证据

修复后实际命令（PowerShell，前台 GUI）：

```powershell
& 'E:\isaac\env_isaaclab\Scripts\python.exe' -u scripts/check_official_quadcopter.py --steps 100 --clone-in-usd --device cuda:0 --code-commit e177eb64f34d01b5152d087533dbcc196ebfc60b --output 'E:\isaac\boom_birds_storage\runs\official_gui_smoke_fix_20261031_214637\result.json'
```

`code_commit` 表示父提交，运行时工作树另有本次一行 import 修复；确切源码以脚本 hash 为准。实际 command 字段与 code_commit 以 [版本化核验摘要](verification_20261031.json) 及结果原件为准。仓库其他既有本地修改保留，不宣称整个工作树干净。

大日志、结果与响应采样在约定存储的 `runs/official_gui_smoke_fix_20261031_214637/`。版本化摘要包含修复前后进程结果、真实 API、GUI 模式及原始产物 hash。它不是仅从 status 标签复制结论，而是检查退出码、日志、100 条原始样本、无 headless 参数和结果字段。

| 产物 | SHA-256 |
| --- | --- |
| 修复后脚本（现场字节） | 48dbec15046b3b5e0f7eddf00ce51a169598722743cee2f0511e33a6fc87d8f7 |
| 修复前脚本（Git 原字节） | 090f7f911bf0823e487c478703af32e68f11cebd778e47d6d9344a47bf7024ad |
| 修复后 result.json | 3511db63d1d4808295873808a5419ae315ab8eedb4615bfa164b62236187d6da |
| 修复后 stdout.log | 4d383fc86120c323350421af18de30e67c0287f8194d2618b9f1bf26c7d1cf4d |
| verification_20261031.json | 3ba20e48a2eada5b4523f12834c9e140ad125aef358f7199bf167512de28af31 |

## 剩余限制与下一项

- 此次是一个前台 GUI 100 步的官方短例，不代表长时间稳定、训练收敛或实机验证。此前长时间未响应和诊断采集器崩溃不能全部归因于缺少 sys，仍按原始证据保留。
- 不以 headless 替代本工作包验收；修复前后两次 Isaac 运行均为前台 GUI。
- 本次只增加标准库导入，不改变共享 episode 边界或 layered 路径，无需因本次修改重跑 125 场景。
- 评价审计交接中的调参候选配置重建与调参集重验仍未执行；不提升任何 Gate，训练/板端/SITL/HIL/实机仍 NOT RUN。

## 当前分支的再次核验（2026-11-01 继续核对）

为澄清后续地图报告中“Vulkan 仍失败”的表述，对 f0ccfb1 工作树（仍保留本次未提交的 `import sys` 修复）再次做单实例前台官方 smoke。运行记录目录为 `runs/vulkan_current_verify_20261031_223123/`，保留其实际生成名称和时间，不改写为核验日期。

- 实际日志：驱动 581.80，Graphics API Vulkan，Creating window for environment，PASS steps=100。
- 真实结果：gui_mode=true，clone_in_fabric=false，100 条连续样本；奖励和位置有限；退出码 0，无超时、无 Error/Traceback/访问冲突，stderr 为空。
- 本次没有使用 `--headless` 或 D3D12 强制参数；原始命令使用 `--clone-in-usd --device cuda:0`，正常显示窗口。启动前没有其他 Python/Isaac 实例。
- 结果源码 SHA-256 仍为 `48dbec15046b3b5e0f7eddf00ce51a169598722743cee2f0511e33a6fc87d8f7`；code_commit 为 `f0ccfb19da6707b9938e8147620e8ae4340ccc78`，不宣称修复已在该提交内。
- 新结果 JSON SHA-256：`03951ee1652f201506d203be33046b34a26f25b76a87b96a180a75046e9be468`。
- [独立核验摘要](vulkan_current_verification.json) SHA-256：`1cdd3f311b9410261269ca1a4a268676db32796794e58895bed789f7ebdf13ed`。

前一轮及本轮共两次实际 Vulkan GUI 100 步通过，可确认此配置可运行；不等于默认 Fabric 克隆路径、地图评价的 Vulkan 后端或长时间稳定性已验收。历史失败与其全部根因仍保留，撤回“仅凭 D3D12 通过即可确认为后端根因”的推断。
