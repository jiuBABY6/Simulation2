# Persona 构建流水线说明

更新日期：2026-09-28

本目录用于把MongoDB中的微博用户与微博文本转换为当前仿真系统可读取的Agent Persona文件。最终结果写入项目根目录下的`output/personas`，五策略实验只读这些基础Persona，不会在仿真过程中覆盖它们。

## 一、整体流程

```text
MongoDB用户集合＋微博集合
        ↓
清洗正文并关联用户与微博
        ↓
DeepSeek分类主题、信息取向和情绪
        ↓
生成agent_<user_id>.json和policy_config.json
        ↓
DeepSeek补充五类评论派系偏好
        ↓
汇总全部Persona并更新情绪分位数
```

必须按下面的顺序执行：

```text
1. build_personas.py
2. build_faction_preferences.py
3. emotion.py
```

`build_personas.py`重新生成Persona时会覆盖对应的`agent_*.json`，其中不包含派系偏好。因此，只要重新运行第一步，就应再次执行第二步。

## 二、目录内文件说明

| 文件 | 是否调用LLM | 主要功能 | 主要输出 |
| --- | --- | --- | --- |
| `build_personas.py` | 是 | 读取MongoDB，清洗微博，分类主题、信息取向和情绪，生成基础Persona及全局规则 | `agent_*.json`、`policy_config.json`、`classification_progress.jsonl` |
| `build_faction_preferences.py` | 是 | 读取已有Persona和对应用户微博，分类五种评论派系，将概率写回Persona | 更新`agent_*.json`、生成`faction_classification_progress.json` |
| `emotion.py` | 否 | 汇总所有Persona的正面、中性和负面表达比例，计算P25、P50、P75 | 更新`policy_config.json`中的`emotion_quantiles` |
| `requirements.txt` | 否 | Persona流水线的最小Python依赖 | `pymongo`、`requests` |

## 三、运行前准备

### 3.1 Python环境

建议在项目现有Conda环境中运行：

```powershell
conda activate persona_sim
pip install -r persona_pipeline/requirements.txt
```

### 3.2 MongoDB

确认MongoDB服务已经启动，并准备好：

- 用户集合，默认名称为`user`；
- 微博集合，默认名称为`weibo`；
- 用户记录中的`id`能够与微博记录中的`user_id`对应。

默认数据库配置位于`build_personas.py`：

```python
MONGODB_URI = "mongodb://localhost:27017"
MONGODB_DATABASE = "weibo"
USERS_COLLECTION = "user"
POSTS_COLLECTION = "weibo"
```

第一步可以通过命令行参数临时覆盖这些值。第二步目前没有命令行参数，会直接读取`build_personas.py`中的默认MongoDB配置，因此执行派系分类前必须确认脚本顶部的默认配置与实际数据库一致。

### 3.3 DeepSeek配置

`build_personas.py`支持通过`--deepseek-api-key`临时传入Key。建议只在当前PowerShell窗口设置环境变量，不要把真实Key提交到代码仓库：

```powershell
$env:DEEPSEEK_API_KEY = "填写本机使用的API Key"
```

需要注意：`build_faction_preferences.py`当前没有命令行配置入口，它会导入`build_personas.py`中的`DEEPSEEK_API_KEY`、模型和接口地址。运行第二步前，需要在本地正确配置这些值；真实Key不得提交，运行结束后应恢复占位值。后续若重构该脚本，建议统一改为读取环境变量。

## 四、MongoDB数据结构要求

### 4.1 用户集合

用户记录至少需要包含`id`。流水线支持三种形式。

#### 平铺结构

```json
{
  "id": "10001",
  "gender": "f",
  "location": "河北",
  "verified": false,
  "followers_count": 1200
}
```

#### `user`嵌套结构

```json
{
  "user": {
    "id": "10001",
    "gender": "f",
    "location": "河北",
    "verified": false,
    "followers_count": 1200
  }
}
```

#### `wb.user`嵌套结构

```json
{
  "wb": {
    "user": {
      "id": "10001",
      "gender": "f",
      "location": "河北",
      "verified": false,
      "followers_count": 1200
    }
  }
}
```

除`id`外的身份字段缺失时会使用空字符串、`false`或`0`，但会降低Persona信息完整度。

### 4.2 微博集合

每条微博至少需要：

| 字段 | 必需 | 用途 |
| --- | --- | --- |
| `id` | 建议提供 | 生成稳定的分类任务编号；缺失时使用临时行号 |
| `user_id` | 是 | 与用户集合中的`id`关联 |
| `text` | 是 | 用户本人的微博正文或转发附言 |
| `retweet` | 否 | 转发的原微博对象，其中可包含`text` |

支持单条微博文档：

```json
{
  "id": "post_001",
  "user_id": "10001",
  "text": "这件事还需要更多事实说明",
  "retweet": null
}
```

也支持微博列表存放在`weibo`或`wb.weibo`中：

```json
{
  "wb": {
    "weibo": [
      {
        "id": "post_001",
        "user_id": "10001",
        "text": "这件事还需要更多事实说明"
      }
    ]
  }
}
```

用户ID会统一转换为字符串后关联。正文会去除HTML标签、合并多余空白，并跳过空正文或“转发微博”等占位文本。存在`retweet`对象时，主题分类优先使用原微博正文，信息取向和情绪分类使用当前用户自己的正文或转发附言。

## 五、执行步骤

以下命令均在项目根目录执行。

### 5.1 生成基础Persona

先用少量用户验证数据库结构和LLM输出：

```powershell
python persona_pipeline/build_personas.py `
  --mongo-uri "mongodb://localhost:27017" `
  --database "weibo" `
  --users-collection "user" `
  --posts-collection "weibo" `
  --deepseek-api-key $env:DEEPSEEK_API_KEY `
  --limit-users 10 `
  --output-dir "output/personas"
```

验证成功后处理全部用户：

```powershell
python persona_pipeline/build_personas.py `
  --mongo-uri "mongodb://localhost:27017" `
  --database "weibo" `
  --users-collection "user" `
  --posts-collection "weibo" `
  --deepseek-api-key $env:DEEPSEEK_API_KEY `
  --limit-users 0 `
  --output-dir "output/personas"
```

常用参数：

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--mongo-uri` | `mongodb://localhost:27017` | MongoDB连接地址 |
| `--database` | `weibo` | 数据库名称 |
| `--users-collection` | `user` | 用户集合名称 |
| `--posts-collection` | `weibo` | 微博集合名称 |
| `--deepseek-api-key` | 脚本配置值 | DeepSeek API Key |
| `--deepseek-model` | `deepseek-v4-flash` | 分类模型 |
| `--deepseek-endpoint` | DeepSeek Chat Completions地址 | API地址 |
| `--limit-users` | `16` | 处理用户数量，`0`表示全部 |
| `--batch-size` | `10` | 每次分类的微博文本数量 |
| `--max-text-chars` | `800` | 单条文本送入模型的最大字符数 |
| `--output-dir` | `output/personas` | 输出目录 |

脚本依次执行：读取用户、关联微博、拆分分类文本、调用DeepSeek分类、计算各类比例、生成个人Persona，并汇总生成全局策略配置。比例计算使用拉普拉斯平滑，避免小样本直接出现`0`或`1`。

### 5.2 补充评论派系偏好

确认`output/personas`已经存在`agent_*.json`，并确认`build_personas.py`顶部的MongoDB和DeepSeek默认配置正确，然后执行：

```powershell
python persona_pipeline/build_faction_preferences.py
```

脚本会把历史表达分类为：

- 观点输出派；
- 表态判断派；
- 情绪激进派；
- 矛盾激化派；
- 吃瓜派。

分类结果经过拉普拉斯平滑后写入每个Persona的`comment_faction_preference`，样本数量写入`data_info.faction_sample_count`。

### 5.3 更新情绪分位数

最后执行：

```powershell
python persona_pipeline/emotion.py
```

该脚本不访问MongoDB，也不调用LLM。它读取全部`agent_*.json`中的`emotion_expression`，计算正面、中性和负面比例的P25、P50、P75，并写入`policy_config.json`的`emotion_quantiles`。

## 六、输出文件说明

### 6.1 `agent_<user_id>.json`

每个有效用户生成一份Persona，核心结构如下：

```json
{
  "agent_id": "agent_10001",
  "source_user_id": "10001",
  "identity": {
    "gender": "f",
    "location": "河北",
    "verified": false,
    "followers_count": 1200
  },
  "action_preference": {
    "original_preference": 0.6,
    "repost_preference": 0.4
  },
  "topic_preference": {
    "社会事件": 0.4,
    "新闻时事": 0.3,
    "娱乐": 0.1,
    "其他": 0.2
  },
  "information_orientation": {
    "fact_rate": 0.3,
    "opinion_rate": 0.4,
    "questioning_rate": 0.3
  },
  "emotion_expression": {
    "positive_rate": 0.2,
    "neutral_rate": 0.5,
    "negative_rate": 0.3
  },
  "comment_faction_preference": {
    "观点输出派": 0.3,
    "表态判断派": 0.25,
    "情绪激进派": 0.2,
    "矛盾激化派": 0.1,
    "吃瓜派": 0.15
  },
  "data_info": {
    "total_posts": 20,
    "topic_sample_count": 18,
    "expression_sample_count": 18,
    "faction_sample_count": 18
  }
}
```

这些比例描述用户历史表达倾向，不代表Agent在某个具体事件中的固定情绪或固定立场。

### 6.2 `policy_config.json`

保存全部Persona统计得到的全局规则，包括：

- 参考用户数量；
- 主题偏好分位数；
- 信息取向分位数；
- 情绪表达分位数；
- 原创与转发偏好的区分阈值；
- Agent决策使用的候选状态规则。

### 6.3 断点文件

| 文件 | 用途 |
| --- | --- |
| `classification_progress.jsonl` | 保存主题、信息取向和情绪分类结果，第一步中断后可继续运行 |
| `faction_classification_progress.json` | 保存派系分类成功项和跳过项，第二步中断后可继续运行 |

断点续跑依赖稳定的用户ID和微博ID。如果MongoDB内容、分类规则或模型发生变化，旧断点可能不再适用。需要完全重新分类时，应先备份旧输出目录，再在新的空目录或清理后的受控目录中重建，避免新旧用户和旧分类缓存混合。

## 七、运行后检查

至少检查以下内容：

1. `output/personas`中的`agent_*.json`数量是否符合预期；
2. 每个Persona是否具有非空`agent_id`和`source_user_id`；
3. 三组比例字段是否存在且数值位于`0～1`；
4. 执行第二步后是否出现`comment_faction_preference`；
5. `policy_config.json.reference_population_size`是否等于本次基础Persona数量；
6. 执行第三步后是否存在`emotion_quantiles`；
7. 两个断点文件中是否有大量`skipped`记录；
8. 终端是否出现MongoDB连接失败、HTTP 400、JSON解析失败或余额不足等错误。

生成完成后，当前Demo通过`demo/agents/persona_repository.py`只读加载`output/personas/agent_*.json`，通过`policy_config.json`读取全局分位数与候选规则。

## 八、注意事项

- 必须从项目根目录执行命令，避免相对输出路径写到其他位置；
- 不要提交真实DeepSeek API Key、MongoDB账号或包含敏感个人信息的原始数据；
- 不建议直接批量手工修改生成后的Persona，应修改流水线后重新生成；
- `--limit-users`只限制本轮生成数量，不会自动删除输出目录中以前的其他Persona；
- 切换数据集时应使用独立输出目录或先备份并隔离旧结果，避免不同人群混合；
- 重新运行第一步会覆盖对应Persona，因此必须在之后重新执行派系分类；
- 基础Persona是长期历史特征，当前事件中的情绪和官方态度由仿真决策模块逐轮判断；
- 当前适应性画像与跨事件长期更新尚未实现，不属于本流水线。

## 九、常见问题

### MongoDB连接失败

检查MongoDB服务、连接地址、端口、认证信息和网络权限。脚本启动时会执行`ping`，连接失败不会继续生成文件。

### 提示没有用户数据

检查数据库名、用户集合名，以及用户记录中是否存在`id`或受支持的嵌套结构。

### Persona存在但微博数量为0

检查微博记录的`user_id`是否能够与用户`id`匹配，以及正文是否为空或占位文本。

### DeepSeek返回HTTP 400或无法解析JSON

脚本会重试，并在批次异常时逐条定位。仍然失败的文本会写入断点文件的跳过记录。需要同时检查模型名称、接口地址、Key、余额和输入长度。

### 第二步没有找到Persona

必须先执行`build_personas.py`，并确保结果保存在项目根目录的`output/personas`。

### 修改了分类规则但结果没有变化

可能仍在复用旧断点分类结果。先备份旧输出和断点文件，再使用隔离的新输出重新生成，不能直接混用不同分类规则的缓存。
