# RMUC2027 场地安装与 Isaac 预览核查

2026-10-28。范围仅为用户提供便携包的本地解压、场景加载、渲染与静态碰撞射线检查，不改变 P0/P1 工作包或飞行验收状态。

## 存放与来源

采用 `docs/design/05_WORKSPACE.md` 的仓库外大资产约定，存放在 `boom_birds_storage/assets/RMUC2027_IsaacSim/`，保留原始目录、来源归档、许可证和转换记录。入口为 `rmuc2027_preview.usda`；复用场地为 `assets/rmuc2027_terrain.usdc`。未执行压缩包内工具或修改原始资产。

- 压缩包 SHA256：`fb1d5aabfb3a4933ab5233098f481bea2c32cb08d97820f78626f23c34665a3f`。
- 场地 SHA256：`f5f55c6633d6f138c434664e73903fe96859a98b99f9fab63690e58d38694baa`。
- 包内记录的上游提交：`ffd1eb7d1d1a2d1654125d8f316fdb0fdac6d001`，来源 `CosmosMount/rmuc2027_mjarena`；本次未联网复核上游。
- `source/LICENSE` 与资产权属记录保留在资产目录；本次只做本地预览，未复制上游实现到项目包或再分发资产。

## 实际验证

使用现有 Isaac 环境的 `Scripts/python.exe` 执行仓库外的 `runs/map_preview_20261028/preview_map.py`，通过 `SimulationApp` 打开场景。未安装或升级依赖。

| 检查 | 实际结果 |
| --- | --- |
| 解压与完整性 | 11 个文件解压；`SHA256SUMS.txt` 所列 10 个文件全部匹配 |
| USD 依赖与组合 | 无未解析依赖；遍历 prim 的组合错误为空 |
| 网格与材质 | 80 个网格，46 个视觉网格、34 个碰撞网格；顶点有限、索引与面计数合法；视觉/物理用途材质绑定可解析 |
| 单位与轴 | 米，Z-up |
| 可见几何范围 | 约 x=[-14.0005,14.0005]、y=[-8.0016,8.0016]、z=[-0.3010,3.4977] 米 |
| RTX 预览 | DirectX 后端成功渲染；已人工检查输出截图，界面保留 `/World/Overview` 相机 |
| PhysX 射线 | 从 (0,0,20) 向下 100 米，命中 `collision_018`，距离约 17.4885 米 |
| 动态接触与飞行 | NOT RUN；120 次应用 update 后时间线仅约 1e-7 秒，不作为有效物理步进证据 |

首次默认 Vulkan 启动在地图加载前崩溃，涉及 RTX 场景数据库与材质预加载调用栈；仅清空材质库目录的复测仍失败。单独使用 `extra_args=['--/app/vulkan=false']` 后成功；这是本次启动参数，不修改安装或全局配置，也不将后端差异推断为已确认的驱动根因。初版检查脚本的 USD API 与材质用途查询问题已修正。

## 外部证据与复现

证据目录为 `boom_birds_storage/runs/map_preview_20261028/`，含脚本、默认后端失败日志、最终日志、原始和复核后 JSON、截图。最终日志标记 `RMUC_PREVIEW_READY`；原始 JSON 的时间线检查范围过宽，复核后 `validation.json` 明确缩小为场景、渲染和碰撞射线检查。

- `overview.png` SHA256：`dd4f1df9a9971cb234a11dbfdd5f010812f955113c44c3ef4908c1fac9e695db`。
- `validation.json` SHA256：`546de72eec18720701bdd3cbc03a86665b029eee422921cede51bc28e3fd7566`。
- 修正范围说明后的 `preview_map.py` SHA256：`974bddcbe95f280d7ac2d401ccd19678bb9f2763ddd37a50cb287511c154136a`。

复现时使用本机配置中的既有解释器执行该脚本；会重写该证据目录下的输出，应先保留重要历史记录。手工打开原始场景时也需要本次验证成功的 DirectX 启动设置。

本次没有机器人、落球或全面接触测试，没有项目训练或实机验证；不代表正式赛场尺寸或资产与赛季规则一致。场地最低点低于零，不应额外用 z=0 地平面填平。下一技术工作包仍为 Task 3 速度控制物理执行器。
