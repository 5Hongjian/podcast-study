# Podcast Study · 播客精读

把播客或访谈的标题、链接整理成有理解深度、能回听的 Google Docs 笔记。

完整原生字幕优先；确实无法获取时才下载音频，用 Buzz 和本地模型转录。文档完成并读回核验之后，最后才把本期产生的音频、字幕和转录副本移入系统废纸篓。

这是一个可调用的 Codex 技能，附带工作流、默认设置和空白任务模板。它需要当前环境提供浏览器、文件工具和 Google Docs 写入连接；安装技能本身不会部署后台服务、登录 Google 或自动下载模型。

## 默认文档

1. **个人 takeaway**：本期对自己意味着什么、依据和可执行动作。
2. **一句话主线 + 思维导图**：核心内容与重点段落导航；连接正文解释和对应播放器时间位置。
3. **把关键问题讲明白**：回答、推理、案例、前提与适用条件。
4. **来源与必要说明**：只保留确有必要的出处和限制。

开头不放发布日期、整理日期和处理工具等元数据。导图节点不能直接点击时，用导图和同编号链接表；播放器不支持精确跳转时明确提供节目链接与时间。

这是默认值，用户可以更改。完整规则在 [默认文档结构](skills/podcast-study/references/document-format.md)。

## 安装与调用

可以直接把下面的话发给 Codex：

> 请从 https://github.com/5Hongjian/podcast-study 安装 skills/podcast-study。保留我已有的个人偏好、文档结构覆盖和单期任务记录。

也可以在本机使用 Python 3.10+ 和 Git：

```sh
git clone https://github.com/5Hongjian/podcast-study.git
cd podcast-study
python3 scripts/install.py
```

安装器默认使用 `~/.agents/skills/podcast-study`。如果这里已有指向旧安装的符号链接，会保留链接并更新其目标；也可用 `--skills-dir` 指定位置。Codex 的用户级技能目录见 [官方技能文档](https://learn.chatgpt.com/docs/build-skills)。如果技能未出现，重启 Codex。

调用示例：

> 使用 $podcast-study 整理这个播客：〈标题或链接〉。完成 Google Docs 并核验后，再清理本期临时音频和转录文件。

新用户只有在确实需要本地转录时，才按 [Buzz 安装指引](skills/podcast-study/references/buzz-setup.md) 检查设备、安装缺少的 Buzz 与合适模型。已有完整字幕时不下载这些组件。

## 三部分存储

| 部分 | 位置 | 如何维护 |
| --- | --- | --- |
| 通用技能、文档默认值、偏好默认值、空白记录模板 | 本仓库 `skills/podcast-study/` | 随版本升级 |
| 用户自己的偏好与文档结构覆盖 | 状态目录的 `preferences.md`、`document-format.md` | 用户可编辑，升级保留 |
| 当前用户自己的每期任务记录 | 状态目录的 `runs/` | 首次运行才创建，留在本地 |

状态目录依次取 `PODCAST_STUDY_HOME`、`$CODEX_HOME/podcast-study`，最后回退到 `~/.codex/podcast-study`。安装器的 `--state-dir` 可以覆盖本次安装位置；使用自定义位置时，后续运行也需设置同一个 `PODCAST_STUDY_HOME`。状态目录必须在仓库之外。

配置优先级：**本次用户要求 → 用户本地覆盖 → 仓库默认值**。安装器只在文件不存在时创建空白覆盖文件，不把作者的个人资料或历史授权当作新用户默认值。

- 想改语言、深度或应用角度：编辑自己的 `preferences.md`。
- 想把导图放最前、减少章节或换导航形式：编辑自己的 `document-format.md`，写出需要覆盖的项目即可。
- 想固定整套自定义结构：把随附默认结构复制到本地 `document-format.md` 后修改。
- 只想改这一次：在当次请求中说明，不必改全局文件。

仓库不包含任何人的真实播客记录、私人文档地址、个人路径、账号凭证、音频或转录稿。`.gitignore` 与发布检查用于防止意外提交；它们不能替代上传前阅读差异。

## 更新与持续迭代

```sh
git pull --ff-only
python3 scripts/install.py
```

更新仅替换技能，已有本地配置与 `runs/` 保持原样。内容变化时，旧技能会备份到本地状态目录的 `backups/`；重复安装相同内容不会反复备份。安装替换失败会尝试恢复旧技能。默认值的新版本只影响用户未覆盖的部分，更新不会改写已有 Google Docs。

`main` 保存通过检查的版本，发布点使用 `vX.Y.Z` 标签。要固定或回退技能，可检出明确的版本标签后重新运行安装器；这不会倒退或重写任务记录。切回 `main` 后才使用上面的拉取命令。有本地代码改动时先保存到分支，安装器不会处理 Git 合并冲突。

每轮维护走“具体反馈 → 独立分支 → 修改 → 检查 → 合并 → 版本标签”。参见 [维护规则](CONTRIBUTING.md)、[变更记录](CHANGELOG.md) 与 [后续任务](docs/iteration-plan.md)。

## 检查

```sh
python3 scripts/validate.py
python3 -m unittest discover -s tests -v
```

自动检查覆盖发布文件、空白模板及安装升级的数据保留。字幕判断、内容解释和 Google Docs 实际呈现仍需按 [行为评估场景](docs/evaluation-cases.md) 验证，不能用静态检查冒充端到端运行成功。
