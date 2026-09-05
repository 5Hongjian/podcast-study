# 播客精读工作流程

[返回项目首页](../README.md)

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
