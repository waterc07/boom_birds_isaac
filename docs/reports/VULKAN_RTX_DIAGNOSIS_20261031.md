# Vulkan/RTX 启动崩溃定位

> 2026-11-01 最新核对：581.80、单实例、正常显示窗口、USD 克隆的官方 Vulkan GUI 100 步已再次 PASS。当前源码仍含未提交的 `import sys` 元数据修复。见 [核验摘要](official_gui_smoke/vulkan_current_verification.json)。本文件后续各节为按时间保留的诊断历史，不把其阶段性失败概括为当前所有 Vulkan 配置不可运行；地图评价本身的正式证据仍为 D3D12。

> 最新核对（同日 21:47 起）：评价审计中的 velocity/reach/compare/faults 已有独立核验通过的前台 GUI 证据。另发现官方 smoke 元数据缺少 `sys` 导入并修复；单实例、正常显示窗口、Vulkan、CUDA:0 的官方 100 步已完成，结果与 PASS 标记齐全。修复前原脚本 GUI 对照复现 exit 0 却无结果。详见 [后续修复报告](official_gui_smoke/OFFICIAL_GUI_SMOKE_FIX_20261031.md)。下方“GUI 尚未通过”等均为各次诊断时的历史状态，不能扩大为整个项目 GUI 物理不可用；历史持续挂起的全部根因仍未确证。

日期：2026-10-31（Asia/Shanghai）。本轮仅诊断和启动对照，未升级、回退驱动、修改全局配置、删除缓存或修改项目代码。保留并行运行的项目仿真。本文补充 `RMUC2027_ASSET_PREVIEW_20261028.md` 的未确认问题。

> 最新状态：用户回退至 **591.74** 后，Vulkan GUI 空场和 RMUC2027 地图加载均通过，原启动崩溃未复现；D3D12 无界面官方物理 smoke 亦通过。但后续带物理的 GUI 复测出现持续未响应和 CPU 高占用，Vulkan、D3D12 均未完成，详见末节。不能将前面的短例通过扩大为 GUI 仿真全面可用。

> 后续驱动更新：用户又回退至 **581.80**。无界面 GPU 物理 100 步通过；不带栈采集的 Vulkan GUI 物理仍 90 秒未完成，本轮有另一个 Isaac GUI 实例并行，须保留资源争用限制，见末节。

## 结论

已定位直接故障：Isaac Sim 5.1 / Kit 107.3.3 的 Vulkan GUI 路径在 `SimulationApp` 构造期间初始化 RTX/Hydra 引擎时，`rtx.scenedb.plugin.dll + 0xE533B` 对空基址执行原子读改写，触发 Windows `0xC0000005`。空指针如何形成尚未确认，不能将直接故障位置等同于驱动根因。

当前最有价值的进一步实验是驱动版本对照；不是继续运行现有 D3D12 仿真的必要条件。未实施驱动变更。

## 现场与实测

- 现有解释器；Isaac Sim 5.1.0，Kit 107.3.3，RTX 5080，驱动 630.20。
- Windows 11 专业工作站版 Insider Preview，Build 28120；驱动与 OS/Kit 组合兼容性均未单独验证。
- 2026-10-28 失败及成功日志均报告驱动 630.20，因此不是历史与当前驱动不同导致的假对照。
- 本轮 GUI 探针固定 RaytracedLighting、单 GPU 和原预览窗口尺寸，关闭持久配置写入；在应用构造成功后才创建 Cube 或打开地图。

| 实际运行 | 结果 | 范围 |
| --- | --- | --- |
| Vulkan，未打开任何场景 | exit -1073741819（0xC0000005），无 APP_READY 标记 | 地图和项目控制代码不是复现的必要条件 |
| D3D12，打开 RMUC2027 地图，120 次 update | exit 0，PASS，实际 Graphics API 为 D3D12 | GUI 初始化、地图打开及渲染更新；不代表动态物理或视觉质量验收 |
| Vulkan，另加 `--reset-user` | exit -1073741819，同一故障 | 跳过持久用户配置仍复现；不排除全部配置或缓存因素 |
| 前一轮官方四旋翼 headless，100 步 | exit 0，PASS；日志 Graphics API 为 D3D12 | CUDA/PhysX 入口可用，不验证 Vulkan |

本轮未重复历史的清空材质库路径实验：历史该实验仍崩溃，不能将 Python 线程栈中的材质预加载认定为根因。

## 转储证据

使用标准库读取 MINIDUMP 的 ExceptionStream、AMD64 Context 和 ModuleList；未安装调试器或解析私有符号。核对安装 DLL 的 PE 时间戳与四份 dump 的模块时间戳一致。

四份 dump（两份历史、两份本轮）的共同结果：

- exception code：`0xC0000005`。
- ExceptionInformation：`[1, 0x3380]`，即向 `0x3380` 写入时发生访问冲突。
- faulting module：`rtx.scenedb.plugin.dll`，RVA `0xE533B`。
- `RDI=0`，`RAX=0x10000`。
- 当前安装 DLL 对应字节：`F0 0F C1 87 80 33 00 00`，按 x86-64 指令编码为 `lock xadd dword ptr [rdi+0x3380], eax`。
- 直接原因是该指令使用空基址；未获得空指针形成前的完整对象生命周期和私有符号。
- dump 模块列表未发现 Steam/Fossilize/RTSS 模块；注册表存在 Steam Vulkan layer 清单本身不能证明其注入或导致崩溃。`rtx.reshade.plugin.dll` 是本机 NVIDIA RTX 扩展声明的组件，不据其名称判断外部 ReShade 注入。

| dump ID | SHA-256 |
| --- | --- |
| 07697fbe-f7c2-44ea-b017-ed9b1fe0eefc | 996f41f807c74bff0310ba1383bee7afcbdd32f3b9528bc5dccce94c9ef593b9 |
| f6096db4-7495-47d8-b239-0ca22cfaa5e5 | e16060fbf1b42013072cfd472ed0b36ea82bc31ef46d4ea8929a672a22ccb84f |
| d471beca-9466-4af6-a049-c0ae46f030b1 | 7676bacac986fbd4f9d9b9859f74881c6bdb5de485560ffe83c65858ab74ceed |
| 9a06fdc3-8988-4038-9489-c3c5a2355e5e | 87c1e00c2af229784cbc13839c92b27437c71934959e6cbcc4ce143bcbb17160 |

## 证据与复现

仓库外产物位于约定的大资产存储目录 `runs/vulkan_diagnosis_20261031/`，未覆盖原预览记录。复现会重写指定结果与日志，应使用新的输出名。

```powershell
$bbPython = 'E:\isaac\env_isaaclab\Scripts\python.exe'
$bbDiag = 'E:\isaac\boom_birds_storage\runs\vulkan_diagnosis_20261031'
& $bbPython -u "$bbDiag/probe.py" --backend vulkan --result "$bbDiag/recheck_vulkan.json"
& $bbPython -u "$bbDiag/probe.py" --backend vulkan --reset-user --result "$bbDiag/recheck_reset.json"
& $bbPython -u "$bbDiag/probe.py" --backend d3d12 --result "$bbDiag/recheck_d3d12.json" --scene 'E:\isaac\boom_birds_storage\assets\RMUC2027_IsaacSim\rmuc2027_preview.usda'
& $bbPython "$bbDiag/analyze_dumps.py"
```

`analyze_dumps.py` 仅解析现场已生成的 dump，并重写 `dump_analysis.json`；其 DLL SHA 为当前安装文件 hash，不是从 dump 恢复的完整映像 hash。

| 产物 | SHA-256 |
| --- | --- |
| probe.py | f6873ef957114b7310911692ff7f148558d73033eaafa7be144ad97e1ba87ca5 |
| analyze_dumps.py | 0ad273c7ae8890373b8ba6ce75f94d48c1545a1a3a85e9c25bc45667cf571f8f |
| dump_analysis.json | 2163807f8cdb94a5fc26a4488db4c3681debe44cffd751193d7ab8c7201511bc |
| vulkan_existing.log | 2cafc17ac6de45f98fc68f07ce11dcdcf3aa52ca632479ec2317581d376ac72b |
| vulkan_reset.log | 930e4503269688321c7b875e3f5f0e95ab254cea1974d494e464ce36d4cd1f9e |
| d3d12_existing.log | 7d94df266978a312d23b2bafef5bbdd4e146ddc159f4bf835403efb337d00c34 |
| d3d12_existing.json | 9082f0a7cd74c2a63e6eaa195c7aa13991219899beead198474deaaec035914f |
| 当前 rtx.scenedb.plugin.dll | f9d85bf25abb089d9c762e0edcbdcbff269fba713a00c35eef2fb4455f401996 |

## 驱动回退判断与剩余问题

后续在线核验发现高度相关的第一手报告，进一步提高了驱动版本对照的优先级：

- [IsaacSim issue #537](https://github.com/isaac-sim/IsaacSim/issues/537)：报告者的结构化环境为 Isaac Sim 5.1、Windows 11、RTX 5080 Laptop、595.79；回退到 580 后恢复。其 RTX/Hydra 栈 000–015 的模块、符号及偏移与本机一致，包括 `rtx.scenedb.plugin.dll!carbOnPluginStartup+0x252db`。报告正文另有一处写 6.0，与结构化字段不一致，不能忽略该来源瑕疵；但公开栈仍可直接比较。回复支持使用 580/581 已测试分支。
- [RTX 5070 Ti 用户报告](https://forums.developer.nvidia.com/t/isaac-sim-5-1-gui-crash-access-violation-on-rtx-5070-ti-blackwell-fixed-by-driver-downgrade-to-591-74/365335)：Windows 11、Isaac Sim 5.1、595.79 下 GUI 崩溃而 headless D3D12 可用；回退 591.74 后恢复。它是不同显卡的用户实测，不能当成本机保证。
- [RTX 5060 Ti 线程回复](https://forums.developer.nvidia.com/t/isaac-sim-5-1-crashes-on-startup-with-rtx-5060-ti-blackwell-sm-120-rtx-scenedb-plugin-crash/366252/2)明确将 Blackwell 上 595.xx 的类似故障称为已知问题。其结论不能直接外推为本机 630.20 已被确认存在同一个回归。

因此建议优先做一次受控的驱动回退验证。优先考虑官方 5.1 测试基线、再考虑社区明确恢复的版本；仅回退到“任意较旧版本”证据较弱。是否在本机修复仍须 A/B 实验。

[Isaac Sim 5.1 官方要求](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/requirements.html)列出的 Windows 已测试驱动是 580.88，显卡表包含 RTX 5080。这说明 630.20 与发行版已测试组合不同，不证明它必然不兼容，也不证明回退到任何更旧版本必然修复。

用户截图提供的先前驱动为 610.62，可作相邻版本 A/B；本轮未核实其对当前 OS 的支持，亦未发现本机该版本的 Isaac Vulkan 成功记录。若后续回退，应保持 Isaac/脚本不变，在空场 Vulkan、地图 Vulkan、D3D12 对照和官方物理 smoke 上复测；不要同时清缓存、改 Isaac 或改配置，否则失去单变量判断力。580.88 是官方测试基线，但距当前驱动较远，需另外核对当前系统兼容性。

[Kit 官方配置说明](https://docs.omniverse.nvidia.com/kit/docs/kit-manual/latest/guide/configuring.html)说明 `--reset-user` 跳过持久配置。本轮仍复现，故不优先采用删除全局用户配置的做法。

仍未确认：驱动回归、Kit 内部缺陷、缓存因素、Insider OS 兼容性及更早的初始化失败如何导致空指针。未做驱动 A/B、缓存隔离、OS A/B、符号调试或厂商确认；不能宣布 Vulkan 已修复。当前可用办法仍是每次启动设置 `--/app/vulkan=false`，以实际日志确认 D3D12。

## 用户回退至 610.62 后的复测（同日 20:39–20:41）

用户自行回退驱动后授权验证，现场 `nvidia-smi` 及四项测试的 Graphics API 日志均确认驱动为 **610.62**。本轮代理未修改驱动、Isaac、配置或主动清理缓存；开始时未发现其他 Python/Kit 仿真进程。驱动安装、重启本身可能改变驱动缓存等状态，本实验不能将所有系统状态视为严格不变。

沿用原 `probe.py`，SHA-256 仍为 `f6873ef957114b7310911692ff7f148558d73033eaafa7be144ad97e1ba87ca5`。复测独立保存至约定存储的 `runs/driver_61062_verify_20261031_203915/`，不覆盖上一轮证据。

| 测试 | 实际 Graphics API | 退出码 | 结果 |
| --- | --- | --- | --- |
| Vulkan 空场启动（成功后才创建 Cube） | Vulkan | -1073741819 | FAIL，应用构造期间崩溃，尚未创建 Cube |
| Vulkan 地图启动（成功后才打开地图） | Vulkan | -1073741819 | FAIL，应用构造期间崩溃，尚未打开地图 |
| D3D12 地图加载及 120 次 update | D3D12 | 0 | PASS |
| 官方四旋翼，单环境、USD 克隆、cuda:0、100 步 | D3D12 | 0 | PASS，100 条逐步记录；观测及奖励有限 |

两项成功运行的日志未检出 `[Error]`、`Traceback` 或原生访问冲突。两项 Vulkan 的 `PROBE_APP_READY` 均未出现；因此第二项不是地图加载失败，而是计划加载地图前已经崩溃。两次失败应视为同一初始化故障的重复复现。

新转储与原故障一致：`0xC0000005`、写地址 `0x3380`、`RDI=0`、`rtx.scenedb.plugin.dll + 0xE533B`，安装 DLL 的 SHA-256 和模块时间戳亦保持一致：

| dump ID | SHA-256 |
| --- | --- |
| 313fe81e-e5e9-4226-8a44-1d1b526a78a2 | e9011dcaafd1d7db27592ebb242aec3ca3c60c280ae8e8203124829d78a17472 |
| 5a137424-18b1-4eb4-8225-4a8974c4dc11 | 79263a8b45fa9a9c887fde928e5177a3da7fb840bb0e41b88358de83a6e34249 |

`summary.json` 汇总真实退出码、实际 API、两份新转储及本轮各产物 hash，SHA-256 为 `7ae6ef3822cb471d29f5d005553ff2a0cd302bf738367faee82ad640a7f468dd`。独立证据断言返回 `DRIVER_ROLLBACK_EVIDENCE_CHECK_PASS`：确认四个进程退出码、两项成功 JSON/日志、100 条物理样本、实际驱动/API 和两份新转储的一致故障字段。原 dump 解析脚本复制到本轮目录执行，仅重写本轮 `dump_analysis.json`，原诊断摘要保持不变。

结论：**630.20 → 610.62 未修复本机 Vulkan 启动崩溃；D3D12 地图与官方物理 smoke 在 610.62 下仍可用。** 结果削弱“仅 630.20 引入故障”的假设，但没有排除多个新驱动分支共同存在兼容问题。610.62 不是前述官方 580.88 测试基线或社区 591.74 成功版本，本轮未验证后二者。未进行板端、训练或实机验证。

## 用户回退至 591.74 后的复测（同日 20:50 起）

现场 GPU 查询和六次实际运行日志均确认驱动为 **591.74**。原 GUI 探针 SHA-256 不变，未修改 Isaac、项目代码或全局配置，未主动清理缓存；开始时未发现其他 Python/Kit 仿真进程。所有运行退出码为 0，日志未检出 `[Error]`、`Traceback` 或原生访问冲突。

| 测试 | 实际 Graphics API | 结果与范围 |
| --- | --- | --- |
| 原探针 Vulkan 空场 | Vulkan | PASS，应用构造成功，创建 Cube，120 次 update |
| 原探针 Vulkan 地图 | Vulkan | PASS，应用构造成功，打开 RMUC2027 地图，120 次 update |
| 原探针 D3D12 地图对照 | D3D12 | PASS，打开同一地图，120 次 update |
| 官方四旋翼原命令，100 步 | D3D12 | PASS，单环境、USD 克隆、cuda:0；100 条样本，观测和奖励有限 |
| 官方入口另传 `--kit_args=--/app/vulkan=true`，100 步 | D3D12 | PASS，但实际没有切换为 Vulkan |
| 官方入口另传 `--kit_args=--vulkan`，100 步 | D3D12 | PASS，但实际没有切换为 Vulkan |

后两项是为补充 Vulkan 物理证据而做的参数对照；必须按日志将其归为 D3D12，不能根据请求参数或结果文件名声称 Vulkan 物理已验证。为何 headless 入口仍选择 D3D12 本轮未进一步追踪；Vulkan GUI 与地图启动已经由独立探针的真实 API 日志确认。

结论：**591.74 下，原先在 630.20 和 610.62 上稳定复现的 Vulkan GUI 初始化崩溃，本轮空场和地图两次均未复现。** 这是驱动/Kit 组合兼容性的重要实测证据；驱动安装和重启可能同时改变驱动缓存等状态，仍不足以确认 NVIDIA 内部具体缺陷。建议当前保持 591.74，在此基础上继续项目工作。

证据保存于约定存储的 `runs/driver_59174_verify_20261031_205034/`，包含各次 JSON、日志、退出码和 GPU 记录。`summary.json` 含各产物 SHA-256，文件自身 SHA-256 为 `87bb84424732904d58797b4c5ca7bb6490c5846a5446dfc7f085a9a829f624e3`。证据断言返回 `DRIVER_59174_EVIDENCE_CHECK_PASS`，检查六个退出码、六份 PASS JSON、实际驱动/API、三次各 100 条物理样本、原探针 hash 以及日志错误情况。

验证边界：Vulkan GUI 初始化、地图打开和更新；D3D12 官方短物理步进。未做截图质量审查、Vulkan 动态物理、长时间稳定性、项目训练、板端或实机验证。未覆盖历史失败证据。

## GUI 未响应与 CPU 高占用跟进（同日 21:00 起）

用户反馈 DSH 打开的前台窗口显示未响应后被关闭；随后本轮窗口也被用户观察到未响应、一度恢复。本轮不将 Windows 的短暂“未响应”直接判为原生崩溃，也不将短暂恢复判为整个仿真通过。

现场初查没有存活的 Isaac/Python 仿真进程。最近 DSH 对应日志 `kit_20261031_205838.log` 的参数为 `--steps 20 --output outputs/eval_audit/smoke_gui1/result.json --device cuda:0`，未带 `--clone-in-usd`。其记录包含视口等待超时、`Failed to clone in Fabric`；约 23 秒启动完成，约 32 秒进入 `SimulationApp.close`。结果 JSON 虽为 PASS，但 Fabric 错误意味着不能按日志无错的 GUI 验收通过；该关闭记录本身无法区分用户关窗或脚本收尾。

本轮独立诊断记录在约定存储的 `runs/gui_response_20261031_210147/`：

| 对照 | 实际结果 |
| --- | --- |
| GUI、CUDA:0、USD 克隆、100 步，默认 Vulkan | 92 秒监测结束时进程仍存活，无结果 JSON；之后检查仍停在仿真启动、CPU 累计时间持续增长。已停止本轮自建进程 |
| 相同官方入口，显式 D3D12，加入 faulthandler | 环境初始化完成，步进阶段持续未响应；定时 Python 栈停在 `DirectRLEnv.step` → `SimulationContext.render` → `self._app.update()`，未生成结果。已停止本轮自建进程 |
| 相同 D3D12 入口，仅另设 `cfg.sim.use_fabric=False` | 仍在步进渲染更新处未完成；40 秒 faulthandler 记录同一 Python 调用位置，无结果。已停止本轮自建进程 |

后两项通过仓库外诊断包装器执行原官方检查脚本；第二项只增加定时栈记录，第三项另改变 Fabric I/O 开关。项目源文件未改。关闭 Fabric I/O 与 `--clone-in-usd` 是不同变量，后者只关闭 Fabric 克隆。本轮关闭 Fabric I/O 的负面对照说明它不是已经证实的修复。

Windows 响应采样共有 32 条含窗口记录：3 条响应、29 条未响应；约 24、26、36 秒曾响应，其后至约 90 秒的样本持续未响应。CPU 为相关 Python 子进程累计 CPU 时间，不能直接把其秒数当作墙钟耗时。单次现场 GPU 采样约 0% 利用率、约 4.3 GiB 显存占用；这些是瞬时值，不表示整个过程中 GPU 从未工作。

已确认：测试一直使用 `--device cuda:0`，PhysX 也报告 CUDA 设备 0；没有证据表明是误用了 CPU 仿真。CPU 忙碌集中在 GUI 的原生更新调用期间；Python 调用栈不能解释 C++ 内部具体在等待什么或证明死锁。Kit 自带 py-spy 无法定位当前解释器，返回错误，未将其当成有效栈；后续采用进程内 faulthandler 成功取栈。

因此，当前边界是：静态 GUI 和无界面 GPU 物理入口可通过；带物理的 GUI 更新路径仍有未解决的长时间未响应。两种渲染后端都出现，不能继续把它直接等同于最初 Vulkan 原生访问冲突，也不能承诺仅更换 GPU/CPU 设备或关闭 Fabric 即可修复。后续若继续深入，需要原生线程/渲染更新层的证据，而不是继续重复短启动测试。

`summary.json` 记录未完成状态及本轮日志、包装器、响应采样等产物的 SHA-256；自身 SHA-256 为 `c4f9f4691ebd444925e00b9a00fef096ae2b1799789399c8f15582ed760ebded`。三个 GUI 物理实验均未产生成功结果，未将外部停止进程记为正常退出。保留原失败、成功及本轮未完成证据；未全局修改环境、驱动或依赖。

## 用户回退至 581.80 后的复测（同日 21:12–21:17）

GPU 查询及实际运行日志确认 **581.80**。重点改为带物理的 GUI，而不是重复静态空场。未修改驱动、Isaac、项目脚本或依赖，继续使用 `--device cuda:0 --clone-in-usd --steps 100`。

| 运行 | 结果 | 证据限制 |
| --- | --- | --- |
| 原检查入口，无界面 | PASS，exit 0，100 条样本，实际 D3D12，观测/奖励有限 | 证明 GPU 物理短例可运行 |
| 原检查入口，GUI，完全不加载 faulthandler 包装器 | 约 90.58 秒仍未退出，无结果 JSON；实际 Vulkan，环境设置完成后未完成步进 | 监测期内窗口未响应；有另一 GUI 仿真并行，不能单独归因于驱动 |
| GUI Vulkan，带 40 秒定时栈采集 | exit -1073741819，访问冲突栈顶为 `python311.dll!Py_DumpTraceback` | 与最初 RTX 空指针位置不同，发生在采集栈期间，可能受诊断工具影响，排除其作为驱动回归结论的依据 |
| GUI D3D12，带定时栈采集 | 90 秒未完成，被本轮 watchdog 停止 | 有并行实例，亦非原始无插桩对照 |

发现栈采集访问冲突后，补跑不带采集器的原脚本，不将采集器崩溃当作原 RTX 故障复现。不带采集器的 GUI 未出现立即访问冲突，但仍未生成成功结果。脚本 SHA-256 为 `db6b321999e2a2dceea3c01864a680b699fb9d533b969eb47952c30d351bb54e`。

本轮开始时未发现其他 Python/Isaac 实例；后来 DSH 启动了 GUI 速度链，之后又运行 GUI 制导比较。原脚本 GUI 对照开始时记录的 2 个 Python 进程是同一外部仿真的 venv 启动器和子进程，并非两个外部仿真实例。本轮仅停止超时且命令行匹配本轮独立输出目录的自建进程，保留 DSH 仿真。

目前结论：581.80 已生效，无界面 GPU 物理可用；本轮 GUI 物理仍出现未响应，尚未验收通过。由于并行实例和插桩影响，不能据此确证 581.80 的驱动缺陷或判定继续回退必然有效。下一项应在其他 GUI 仿真正常结束后，用原始命令做单实例、带物理 GUI 复测。

证据目录为约定存储的 `runs/driver_58180_verify_20261031_211213/`。`summary.json` 包含真实退出/超时状态、插桩限制及各产物 SHA-256，自身 SHA-256 为 `f3fab3a1dc272ee3b0367f90df4cdd6a85359bf85c4087c4e2a90fc4a6827d19`。证据断言 `DRIVER_58180_EVIDENCE_CHECK_PASS` 仅表示结果记录自洽，不是 GUI 运行通过。
