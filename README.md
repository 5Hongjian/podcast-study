# Podcast Study · 播客精读

把播客或访谈的标题、链接整理成有理解深度、能回听的 Google Docs 笔记。

完整原生字幕优先；确实无法获取时才下载音频，用 Buzz 和本地模型转录。文档完成并读回核验之后，最后才把本期产生的音频、字幕和转录副本移入系统废纸篓。

这是一个可调用的 Codex 技能，附带工作流、默认设置和空白任务模板。它需要当前环境提供浏览器、文件工具和 Google Docs 写入连接；安装技能本身不会部署后台服务、登录 Google 或自动下载模型。

## 工作流程

```mermaid
flowchart TD
    START["提供播客标题或链接"] --> PREP["确认单集与媒体版本<br/>读取用户偏好、已有进度并检查 Docs 连接"]
    PREP --> SEARCH["查找原播放页面、官方字幕或全文"]
    SEARCH --> CAPTIONS{"原生文本是否完整？"}

    CAPTIONS -->|完整且带时间| INPUT_QA
    CAPTIONS -->|完整但无时间| ALIGN["寻找官方章节与定位依据<br/>无法精确定位时明确标注"]
    ALIGN --> INPUT_QA
    CAPTIONS -->|部分、不可用或访问失败| RETRY["检查同一期其他官方渠道<br/>补齐缺段或进行有限重试"]
    RETRY --> FOUND{"获得完整文本？"}
    FOUND -->|是| CAPTIONS
    FOUND -->|否| REASON["记录检查结果与限制<br/>确认合法音频来源及所需范围"]
    REASON --> LOCAL{"Buzz 和本地模型可用？"}
    LOCAL -->|缺少组件| SETUP["按设备安装缺少的 Buzz 或模型"]
    SETUP --> TRANSCRIBE
    LOCAL -->|已具备| TRANSCRIBE["获取所需音频并用本地模型转录<br/>新环境先试转；仅缺段时尽量只补录缺段"]
    TRANSCRIBE --> INPUT_QA{"输入检查通过？<br/>完整性、识别质量与时间对应"}
    INPUT_QA -->|否| FIX_INPUT["补齐缺段或校正识别<br/>只处理有问题的部分"]
    FIX_INPUT --> INPUT_QA

    INPUT_QA -->|是| UNDERSTAND["理解全期，建立带出处的内容底稿<br/>长节目分段处理后统一主线"]
    UNDERSTAND --> COMPOSE["讲清关键问题 → 组织导图与回听导航<br/>再提炼个人 takeaway"]
    COMPOSE --> REVIEW["依据原文审阅并修订<br/>核对观点、论证、启示与来源"]
    REVIEW --> WRITE["按用户选择的文档结构<br/>创建或更新 Google Docs"]
    WRITE --> VERIFY{"文档读回核验通过？<br/>正文、导图、链接与版式"}
    VERIFY -->|否| FIX_DOC["先读回定位问题，再修复对应内容<br/>保留素材，不盲目重复创建或追加"]
    FIX_DOC --> VERIFY
    VERIFY -->|是| TRASH["文档完成后，最后按本期文件清单<br/>将临时音频、字幕及转录副本移入废纸篓"]
    TRASH --> CLEAN{"清理成功？"}
    CLEAN -->|否| PENDING["记录清理待办与已完成的 Docs<br/>恢复时只继续清理"]
    CLEAN -->|是| FINISH["记录清理结果<br/>返回 Docs 链接与本期处理结果"]
```

- 已完成且无需更新的单集直接返回已有文档；中断任务从未完成阶段恢复，修改旧笔记时从现有 Docs 开始。
- 访问失败不等于没有字幕；完整文本缺少时间戳，也不会因此重新转录整期。
- 任一阶段受阻时保存进度并说明限制；文档未完成或重要核验未通过时保留素材。清理只涉及本期临时文件，保留 Buzz、本地模型及用户原有素材，不永久删除或清空废纸篓。

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

## 检查

```sh
python3 scripts/validate.py
python3 -m unittest discover -s tests -v
```

自动检查覆盖发布文件、空白模板及安装升级的数据保留。字幕判断、内容解释和 Google Docs 实际呈现仍需按 [行为评估场景](docs/evaluation-cases.md) 验证，不能用静态检查冒充端到端运行成功。
