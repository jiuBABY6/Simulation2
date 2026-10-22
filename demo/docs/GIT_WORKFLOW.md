# Git版本控制与团队协作使用说明

本文面向参与数据库、后端、前端和仿真扩展开发的成员，说明如何更新已经获取但不是最新的项目代码、创建姓名分支、提交代码并通过Pull Request合并到`main`。当前仓库地址为：

```text
https://github.com/jiuBABY6/Simulation2.git
```

## 一、基本原则

1. `main`只保存经过检查、可以交付的代码，成员不要直接在`main`上开发。
2. 每名成员使用自己的姓名分支开发，不直接在`main`上修改；每次提交和Pull Request只处理一项明确任务。
3. 提交前检查差异和敏感信息，不提交API密钥、本机绝对路径、缓存和临时文件。
4. 修改数据字段前先核对`DATA_CONTRACT.md`，修改仿真接口前先核对`SIMULATION_INTERFACE_SPEC.md`。
5. 通过GitHub Pull Request完成代码审查和合并，不使用聊天软件传递代码压缩包作为正式交付。
6. 成员必须先在本地完成本人模块测试；测试失败的版本不得推送为待合并版本。

## 二、首次获取或更新项目

确认本机已经安装Git，然后在准备存放项目的目录执行：

```powershell
git clone https://github.com/jiuBABY6/Simulation2.git
cd Simulation2
git switch main
git pull --ff-only origin main
```

检查仓库和当前分支：

```powershell
git remote -v
git branch --show-current
git status
```

正常情况下，远程仓库为`Simulation2.git`，当前分支为`main`，工作区没有未提交修改。

如果成员没有仓库写入权限，需要由仓库管理员先将其加入GitHub仓库协作者；也可以使用Fork方式开发，但团队内部优先使用协作者分支。

### 已经获取代码，但本地不是最新版本

先进入原有项目目录，并确认它是Git仓库：

```powershell
git status
git remote -v
```

如果工作区没有未提交修改，直接更新`main`，然后创建自己的姓名分支：

```powershell
git switch main
git pull --ff-only origin main
git switch -c zhangsan
```

如果本地已经存在姓名分支，则不重复创建：

```powershell
git switch zhangsan
git fetch origin
git merge origin/main
```

如果旧代码中已有本人尚未提交的修改，不要直接切换或覆盖。先在当前状态创建姓名分支，再按文件提交已有工作，最后合并远程`main`：

```powershell
git switch -c zhangsan
git status --short
git add <本人修改的文件路径>
git commit -m "chore: save existing local work"
git fetch origin
git merge origin/main
```

如果`git status`提示当前目录不是Git仓库，说明代码可能来自ZIP或文件复制。应保留原目录作为备份，重新克隆正式仓库，再把本人修改的文件复制到姓名分支中。

## 三、创建和使用姓名分支

第一次使用姓名分支前，先更新本地`main`：

```powershell
git switch main
git pull --ff-only origin main
```

然后创建并切换到自己的姓名分支。该命令只在首次创建时执行：

```powershell
git switch -c zhangsan
```

以后继续开发时直接切换，不再使用`-c`：

```powershell
git switch zhangsan
```

姓名分支统一使用姓名拼音，全部小写，不使用中文、空格或特殊符号：

| 情况 | 命名方式 | 示例 |
| --- | --- | --- |
| 普通姓名 | 姓名全拼 | `zhangsan` |
| 拼音重名 | 姓名全拼加职责 | `zhangsan-backend` |
| 名字较长 | 保持团队登记的统一拼音 | `ouyangming` |

每名成员只维护自己的分支，首次创建前应与负责人确认名称，避免同名。完成一个Pull Request并同步最新`main`后，再在同一姓名分支开始下一项工作。

## 四、编写和检查代码

开发过程中随时查看状态和差异：

```powershell
git status --short
git diff
```

当前项目的基础检查命令：

```powershell
python -m compileall -q demo
git diff --check
```

如果修改数据库、后端或前端，应继续执行该模块自己的最小测试。只有正式运行完整的“三个回应方案＋一组不回应基线”联调时，才把结果追加到`INTEGRATION_TEST_HISTORY.md`。

提交前必须确认：

- 没有真实的`DEEPSEEK_API_KEY`或其他密码；
- 没有本机用户名、个人目录和临时调试配置；
- 没有`__pycache__`、`.env`、编辑器缓存等文件；
- 没有无关的大型实验结果；正式实验结果只有在任务明确要求保留时才提交；
- 没有误改其他成员负责的模块。

## 五、暂存和提交

优先按文件暂存，不建议直接运行`git add .`：

```powershell
git add demo/docs/DATABASE_DESIGN.md
git add database/schema.sql
```

检查准备提交的内容：

```powershell
git diff --cached
git status --short
```

确认无误后提交：

```powershell
git commit -m "feat: add initial database schema"
```

推荐提交信息格式：

```text
类型: 简短说明
```

常用类型包括`feat`、`fix`、`docs`、`refactor`、`test`和`chore`。一次提交应保持目标单一，避免使用“修改代码”“更新文件”等无法说明目的的信息。

如果文件被误加入暂存区，但仍需保留本地修改，可以执行：

```powershell
git restore --staged <文件路径>
```

## 六、同步主分支

开发期间如果`main`已经更新，在自己的姓名分支执行：

```powershell
git fetch origin
git merge origin/main
```

如果没有冲突，继续完成测试。如果出现冲突：

1. 打开Git标记的冲突文件；
2. 与相关负责人确认需要保留的内容；
3. 删除`<<<<<<<`、`=======`、`>>>>>>>`标记；
4. 重新执行模块测试；
5. 暂存解决后的文件并完成合并提交。

```powershell
git add <已解决的文件路径>
git commit -m "merge: resolve main branch conflicts"
```

不要使用`git reset --hard`或强制覆盖远程分支解决冲突，这可能丢失本人或他人的工作。

## 七、推送姓名分支

只有前一节检查和本人模块的本地测试全部通过后，才能执行本节命令。数据库、后端和前端的具体本地验收项见`demo/docs/dev`中的对应任务文档。

第一次推送该分支：

```powershell
git push -u origin zhangsan
```

后续继续提交后，只需执行：

```powershell
git push
```

如果GitHub要求登录，按照浏览器授权或Personal Access Token提示完成认证，不要把令牌写入代码和文档。

## 八、创建Pull Request

推送成功后，在GitHub仓库页面选择`Compare & pull request`：

- Base分支选择`main`；
- Compare分支选择本人的姓名分支；
- 标题说明本次功能；
- 描述修改内容、影响范围、验证命令和验证结果；
- 指定至少一名相关模块负责人进行审查。

Pull Request描述建议使用：

```markdown
## 修改内容
- 完成了什么功能

## 影响范围
- 修改了哪些模块和数据字段

## 验证结果
- 执行了哪些命令
- 验证是否通过

## 未完成内容
- 本次明确没有处理什么
```

审查人提出修改意见后，继续在本人姓名分支修改、提交并执行`git push`，Pull Request会自动更新，不需要重新创建。姓名分支会重复使用，建议仓库合并方式采用`Create a merge commit`，保持个人分支和`main`的提交关系清晰。

## 九、合并后的本地处理

Pull Request合并后，姓名分支通常不删除。先更新本地`main`，然后把最新`main`同步回姓名分支：

```powershell
git switch main
git pull --ff-only origin main
git switch zhangsan
git merge origin/main
git push
```

确认同步完成后，再在该姓名分支开始下一项任务。如果团队决定停用某名成员的分支，应由仓库管理员在确认代码全部合并后统一处理，不要求成员自行删除。

## 十、姓名分支和负责范围登记

以下名称只是示例，实际使用时替换为成员自己的姓名拼音：

| 成员示例 | 姓名分支 | 主要负责范围 |
| --- | --- | --- |
| 张三 | `zhangsan` | 数据库目录、导入工具和数据文档 |
| 李四 | `lisi` | 后端目录和API文档 |
| 王五 | `wangwu` | 前端目录和页面文档 |
| 赵六 | `zhaoliu` | 仿真核心或可视化指定模块 |

数据库、后端和前端可以在各自姓名分支并行开发。仿真原始文件字段以`DATA_CONTRACT.md`为准，三端API字段以`dev/SHARED_INTERFACE_CONTRACT.md`为准。需要更改公共接口时，先由负责成员提交契约Pull Request，合并后其他成员再同步`main`。

## 十一、最短日常工作流程

```powershell
git switch zhangsan
git fetch origin
git merge origin/main

# 编写并检查代码
git status --short
git diff
python -m compileall -q demo
git diff --check

# 按文件提交
git add <文件路径>
git diff --cached
git commit -m "feat: describe the feature"

# 推送并创建Pull Request；首次推送使用-u，后续只需git push
git push -u origin zhangsan
```

完成以上步骤后，在GitHub上发起Pull Request，由负责人审查并合并到`main`。
