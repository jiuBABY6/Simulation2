# 项目交接说明（2026/10/22）

本文件记录当前可恢复工作现场。接手人必须先执行“Destination sentinel”；全部匹配后回复`HANDOFF VERIFIED`，任何一项不匹配则停止修改并回复`HANDOFF REGRESSION`及具体差异。

## 1. 项目总体目标

系统把微博用户数据转成Persona，在固定社交网络和个体可见信息约束下模拟Agent的情绪、官方态度、沉默/原创/转发行为与评论传播，并提供两类实验：

1. 三个可自定义回应方案与一组不回应基线的反事实对照，用于观察不同官方回应方案下的相对变化；
2. 条件化历史趋势复现，按真实时间线投入当时可知的客观事实、公众语境和官方通告，用于解释Agent在给定历史条件下的响应。

系统用于机制探索和方案比较，不等同于真实人口预测、因果识别或公安业务决策系统。

## 2. 已接受的验收标准

- Persona是长期倾向；情绪、官方态度和公开表达分别判断。
- Agent只读取个人可见信息，社交网络曝光、传播根、传播深度和权重衰减可审计。
- 三个回应方案与不回应基线共享事件、初始评论、固定网络、客观事实时间线和进场前状态；通告投入后各场景独立演化，禁止跨场景污染。
- 回应方案主路径为“状态判断→行为门控→按需原创/转发”；允许沉默、原创和转发，表达情绪允许`positive / neutral / negative`。
- 当前状态机制为`strategy_directional_utility_v3`：评论目标、证据角色和来源类型分流；权威证据按Persona渐进吸收；状态只做相邻变化；同一证据推动变化后不重复生效。
- 历史复现第1轮使用人工情绪比例校准初始公共环境；第2轮以后不注入真实评论或真实情绪比例，只投入当时可知的事实、公众语境和官方通告。
- 真实趋势只用于运行后对照，不进入Agent决策；拟合指标是探索性差异，不称为模型准确率。
- API Key只能从`DEEPSEEK_API_KEY`环境变量读取，不得写入源码、日志或交接文档。
- 旧实验数据不被新运行覆盖；新运行创建独立实验目录。

## 3. 当前架构与入口

| 范围 | 入口 | 说明 |
| --- | --- | --- |
| 回应方案对照 | `python demo\main.py` | 三方案＋不回应基线 |
| 历史复现 | `python demo\historical_replay\main.py --event-id <event_id>` | 单一条件化历史路线 |
| 历史事件列表 | `python demo\historical_replay\main.py --list-events` | 查看完整事件源 |
| 可视化 | `python visualization\app.py` | 历史、方案对照、共享网络三层只读界面 |
| Persona生成 | `python persona_pipeline\build_personas.py` | 从MongoDB读取并构建Persona |

关键结构：

- `demo/agents`：状态、证据、行为和表达；
- `demo/comments`：初始与增量评论生成；
- `demo/simulation`：网络、传播、状态和仿真执行；
- `demo/application`、`demo/domain`：应用编排和共享数据对象；
- `demo/historical_replay`：历史事件仓库、时间线和回放；
- `visualization/historical`、`visualization/strategy`、`visualization/shared`：两类业务视图与共享网络；
- `persona_pipeline`：用户与微博数据到Persona及分位数配置。

## 4. 北国事件冲突处理结论

- 当前可运行事件：`event_beiguo_xiantianxia_crash_20260920_002`，新数据三阶段版；
- 已移除的旧事件源：`event_beiguo_xiantianxia_crash_20260920_001`，不得恢复为当前运行入口；
- 保留`visualization/data/real_trends/event_beiguo_xiantianxia_crash_20260920_001.json`和引用旧编号的旧实验批次，只为历史结果兼容；
- 事件仓库、初始条件和当前真实趋势测试已经统一到`002`；
- `active_event.json`当前仍选择胡鑫宇事件，它只控制省略`--event-id`时的默认值，不代表北国事件版本。

## 5. 已验证内容

2026/10/22在Conda环境`persona_sim`完成以下离线验证：

```powershell
& 'D:\anaconda3\envs\persona_sim\python.exe' -m unittest discover -s demo/tests -p 'test_*.py'
# Ran 172 tests - OK

& 'D:\anaconda3\envs\persona_sim\python.exe' -m unittest discover -s persona_pipeline/tests -p 'test_*.py'
# Ran 4 tests - OK

& 'D:\anaconda3\envs\persona_sim\python.exe' -m unittest discover -s visualization/tests -p 'test_*.py'
# Ran 22 tests - OK (skipped=4)
```

4项跳过均依赖当前机器上可选的旧实验目录，不是断言失败。北国事件相关的事件仓库、初始条件、真实趋势和统一可视化定向回归共30项通过、4项按上述原因跳过。

当前交接保留8个完整批次：

| 类型 | 实验编号 | 状态 | 保留原因 |
| --- | --- | --- | --- |
| 历史复现 | `event_baoding_driving_school_crash_20261006_001_20261010_154112_520553` | `completed` | 保定事件完整样本 |
| 历史复现 | `event_beiguo_xiantianxia_crash_20260920_002_20261011_172334_394683` | `completed` | 北国新数据早期完整样本 |
| 历史复现 | `event_beiguo_xiantianxia_crash_20260920_002_20261013_122213_379538` | `completed` | 北国新数据后续完整样本 |
| 历史复现 | `event_huxinyu_2022_001_20261013_181206_806798` | `completed` | 文档明确引用的稳定机制样本 |
| 回应方案 | `event_gaoyang_assault_001_20260906_143939_040535` | `completed` | 可视化测试和第二十六次联调基线 |
| 回应方案 | `event_gaoyang_assault_001_20261015_204046_683644` | `completed` | 状态决策机制回退参照 |
| 回应方案 | `event_gaoyang_assault_001_20261019_112035_030498` | `completed` | `strategy_directional_utility_v1`验证样本 |
| 回应方案 | `event_gaoyang_assault_001_20261020_141414_286129` | `completed` | 当前保留的最近四场景完整样本 |

## 6. 未验证边界

- 未用最终`strategy_directional_utility_v3`完成新的DeepSeek四场景全量实验；不能声称最新机制已经改善拟合或现实性。
- 未运行DeepSeek完整历史复现；不能用离线测试替代自然语言输出质量验证。
- 未完成多事件、多随机种子、多批次统计稳定性验证。
- 未验证生产级数据库、后端API、任务队列、并发执行、权限和部署。
- 当前保留的8个批次均为完整结果，但产生于不同阶段的机制，不能直接混合作为同一版本的统计样本。最近四场景结果`event_gaoyang_assault_001_20261020_141414_286129`仍早于最终`strategy_directional_utility_v3`机制。

## 7. 当前P0风险

1. 工作区包含大量未提交的源码、文档、事件数据和实验结果；不得执行`git reset --hard`、`git clean`、批量覆盖或擅自stash。
2. 曾使用过的DeepSeek密钥必须在服务端撤销/轮换；当前源码已改为只读环境变量，但不能以源码无密钥推断旧密钥仍安全。
3. 最新机制缺少付费在线全量验证，效果结论必须标记为未验证。
4. 当前保留实验均已完成，但跨越不同机制版本；汇报或统计前必须说明实验日期、场景数量和机制边界，不能把不同阶段结果直接合并比较。
5. `decision_engine.py`、`incremental_generator.py`、`experiment_runner.py`和`metrics.py`仍较长；当前处于交接冻结期，不建议在在线基线未建立前继续大规模重构。

## 8. 推荐下一步顺序

1. 执行Destination sentinel并确认`HANDOFF VERIFIED`。
2. 接手人阅读`PROJECT_STATUS.md`、`RUNBOOK.md`、`ARCHITECTURE.md`和`DATA_CONTRACT.md`。
3. 在服务端确认旧密钥已轮换，在本机临时设置新的`DEEPSEEK_API_KEY`，不要写入文件。
4. 先运行一个小规模烟雾批次，再运行完整的三方案＋基线批次；首先检查四场景完整性、跨场景污染审计和证据生命周期，不先追求曲线拟合。
5. 固定输入、模型和随机种子，在至少三个事件上重复运行，评估稳定性和场景差异。
6. 在线基线稳定后再决定是否拆分超长模块或推进数据库、后端和前端工程化。

## 9. Git与工作区快照

| 项目 | 期望值 |
| --- | --- |
| 工作区 | `D:\Desktop\社会模拟已有代码` |
| 远端 | `origin https://github.com/jiuBABY6/Simulation2.git` |
| 分支 | `main` |
| HEAD | `f8c45ff2de36a2edf73926617d021e48da242354` |
| Git状态条目数 | `282`（使用`-uall`按未跟踪文件逐项统计） |
| Git状态SHA-256 | `676cf25000565487bb4cd522943ec2bd2f64072a0a80d6a356db335780217de2` |
| 跟踪差异SHA-256 | `6171fe0eb3d50b45e07916e12fe9389b0a26f537b1311f90e76813b3309bf19e` |

当前删除的旧北国`001`六个事件源文件、已确认不保留的旧实验文件，以及被Git误跟踪的`.pyc`删除记录均为预期变更，不应恢复。第5节表中的8个实验目录属于保留的实验现场，不在后续清理范围。

## 10. 关键文件SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `demo/project_config.py` | `aedb23518179df9208f3de8beb845bcd82fc1ffd47c4068eb04b9bdd36ea75e1` |
| `demo/experiment_runner.py` | `46f7f178a6d4c364c7995ce8434301d384ac7356efc32ded5c2087f260782bc9` |
| `demo/agents/decision_engine.py` | `493d6f90458046bd0a86eede00e128276e8d7bcfacf54262e1b75238d5844761` |
| `demo/historical_replay/event_repository.py` | `b1ae7425ad3ac406aff7cc295ae5a086b3903c884a4ae373e181056f86bdf09b` |
| `visualization/app.py` | `5c637600575b8c3614268b7cb0b1ea858c2d70f606058781d568e86d3ad760ba` |
| `persona_pipeline/build_personas.py` | `4b8efdb7f6238ac7b16f8874ac94aff10c8705a08114342642ebe2c5b43cec62` |

## 11. Destination sentinel

在项目根目录、`persona_sim`环境中执行以下只读命令。不要在检查前修改、清理、重置、stash或提交。

```powershell
$expectedRoot = 'D:\Desktop\社会模拟已有代码'
$actualRoot = (Resolve-Path -LiteralPath '.').Path
$remote = git remote get-url origin
$branch = git branch --show-current
$head = git rev-parse HEAD

$statusLines = @(git status --porcelain=v1 -uall)
$statusText = $statusLines -join "`n"

function Get-TextSha256([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return -join (
            $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)) |
                ForEach-Object { $_.ToString('x2') }
        )
    }
    finally {
        $sha.Dispose()
    }
}

$statusHash = Get-TextSha256 $statusText

$diffLines = @(git diff HEAD --no-ext-diff --text 2>$null)
$diffText = $diffLines -join "`n"
$diffHash = Get-TextSha256 $diffText

[pscustomobject]@{
    Workspace = $actualRoot
    WorkspaceMatches = ($actualRoot -eq $expectedRoot)
    Remote = $remote
    Branch = $branch
    HEAD = $head
    StatusCount = $statusLines.Count
    StatusSHA256 = $statusHash
    TrackedDiffSHA256 = $diffHash
} | Format-List

Get-FileHash -Algorithm SHA256 -LiteralPath @(
    'demo\project_config.py',
    'demo\experiment_runner.py',
    'demo\agents\decision_engine.py',
    'demo\historical_replay\event_repository.py',
    'visualization\app.py',
    'persona_pipeline\build_personas.py'
) | Select-Object Path,Hash

$env:PYTHONDONTWRITEBYTECODE = '1'
& 'D:\anaconda3\envs\persona_sim\python.exe' -c "from pathlib import Path; roots=[Path('demo'),Path('persona_pipeline'),Path('visualization')]; files=[p for r in roots for p in r.rglob('*.py')]; [compile(p.read_text(encoding='utf-8-sig'), str(p), 'exec') for p in files]; print(f'SYNTAX_OK {len(files)} files')"
& 'D:\anaconda3\envs\persona_sim\python.exe' -c "import sys; sys.path.insert(0, 'demo'); import project_config, experiment_runner, historical_replay.event_repository; import persona_pipeline.build_personas, visualization.app; print('IMPORT_OK')"
git diff --check 2>$null
```

判断规则：

- 工作区、远端、分支、HEAD、状态数量、两个状态哈希和全部关键文件哈希必须与本文件一致；
- 语法命令必须输出`SYNTAX_OK`，导入命令必须输出`IMPORT_OK`；
- `git diff --check`必须无输出且退出码为0；
- 全部匹配后回复`HANDOFF VERIFIED`，再按第8节继续；
- 任一项不匹配则回复`HANDOFF REGRESSION`，逐项列出差异并停止修改。

## 12. 禁止事项

- 不要恢复旧北国`001`为当前事件源；
- 不要把API Key写回源码；
- 不要用旧实验结果证明最新机制有效；
- 不要在未确认保留策略前删除实验、Persona、MongoDB导出或真实趋势数据；
- 不要为了让测试通过而降低校验强度或跳过跨场景污染审计。
