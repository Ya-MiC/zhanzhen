# 常见问题（FAQ）

> **上游依据**：`zhanzhen/cli.py`、`webapp.py`、`ocr.py`、`ai_assistant.py`、`store.py`、[LIMITATIONS.md](../../LIMITATIONS.md)、[INSTALL.md](INSTALL.md)、[CONFIG.md](CONFIG.md)。答案均对应 v0.1.0 真实代码行为，不臆测。
> **读者**：所有用户。按「安装 / OCR 与识别 / AI 助手 / 数据与存储 / Web 作业 / 合规」分类。
> **文档版本**：v0.1 · 更新日期：2026-08-25 · 状态：已有

---

## A. 安装与启动

### Q1 启动报错端口被占用（8710 已被其他程序使用）怎么办？

换端口即可，三种写法任选：

```bash
zhanzhen serve --port 9000              # 命令行覆盖（优先级最高）
ZZ_PORT=9000 zhanzhen serve             # bash 环境变量
# Docker 用户改 .env 里 ZZ_PORT=9000 后 docker compose up -d
```

注意 Docker 场景 `ZZ_PORT` 只改宿主机映射端口，容器内部恒为 8710（详见 CONFIG.md §3.4）。

### Q2 `zhanzhen serve` 提示「需要安装 Web 依赖」？

你只装了核心包。Web 服务是可选 extra：

```bash
pip install "zhanzhen[web]"             # 源码目录内
pip install "zhanzhen[all] @ git+https://github.com/Ya-MiC/zhanzhen.git"   # 直装用户
```

CLI 的 `demo`/`verify` 不需要这一步。

### Q3 Windows 下有绿色版 exe / 安装包吗？

没有。v0.1.0 只有 pip / 源码 / Docker 三种方式（INSTALL.md）；打包发布在路线图中。
Windows 用法：装 Python ≥3.10 → `pip install "zhanzhen[all] @ git+..."` → 一切照常。

### Q4 pip 安装很慢或超时？

国内网络加镜像源：

```bash
pip install "zhanzhen[all] @ git+https://github.com/Ya-MiC/zhanzhen.git" \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

公司内网请配置代理后再试。PaddleOCR（`[ocr]` extra）体积约 2 GB，非必需先不装。

---

## B. OCR 与识别

### Q5 上传 PDF 后 OCR 报 `no_text_layer_needs_ocr` 是什么意思？

这份 PDF 是**扫描件**——只有图片像素、没有文字层。程序诚实拒绝并转人工，绝不编造内容。
处理路径：① 换文字型 PDF（电子原件最佳）；② 图片/扫描件 OCR 等 v0.2.0-alpha 的 PaddleOCR
adapter（LIMITATIONS.md #1 的诚实声明）；③ 在覆核页手工补录字段。

### Q6 能上传照片/JPG/PNG 吗？

v0.1.0 工作台上传入口只接受 `.pdf`。手机拍的照片走采集包通道可以入库留证
（服务端重算 SHA-256），但自动字段提取仍受上述限制；入库本身不丢证据，
后续版本解锁识别后可直接补跑。

### Q7 装了 `[ocr]` extra 为什么还是不能识别图片？

诚实回答：v0.1.0 只预留了 PaddleOCR 探测位，adapter 在 Week3 批次提供（代码里会明确提示
「PaddleOCR adapter 将在 Week3 提供」）。装了 extra 不会破坏任何功能，只是提前备好依赖。

### Q8 有些字段 OCR 结果是空的（显示 `-`）？

关键词未命中该版面。设计上抽不到就留空等人工，不猜数。到覆核页对照原件补填后批准即可；
补填动作会以 `voucher.field_corrected` 事件永久留痕。

---

## C. AI 助手

### Q9 点「AI 解释选中风险」报 `ai_disabled_or_invalid`？

AI 助手**默认关闭**，这是安全设计不是故障。需要同时配置三个环境变量才会开启：

```bash
export ZZ_AI_BASE_URL=https://integrate.api.nvidia.com/v1
export ZZ_AI_API_KEY=nvapi-xxxx
export ZZ_AI_MODEL=<端点支持的模型名>
```

三者缺一即视为关闭（CONFIG.md §3.5）。另外：所选凭证必须确有风险命中，无命中的凭证
会拒绝解释（「该凭证无风险命中，无需解释」）。

### Q10 配好了 AI 又报「LLM 调用失败」？

依次检查：Key 是否有效/欠费；`BASE_URL` 是否为 OpenAI 兼容根路径（以 `/v1` 结尾，
程序自动拼 `/chat/completions`）；网络能否出访该端点。调用失败不会影响账务数据——
AI 层只读已确认数据，失败即降级人工。

### Q11 AI 会替我改账或出审计意见吗？

永远不会。权威守则（ENGINEERING_SPEC §8.2）：AI 只把已确认结构化数据解释成会计语言、
给科目候选、起草问题清单；输出强制过 schema 校验，校验不过直接丢弃转人工；
每次调用留痕。它没有任何写数据的通道。执业边界详见 CPA_COMPLIANCE.md。

---

## D. 数据与存储

### Q12 我的数据存在哪里？怎么备份？

全部在 `ZZ_DATA_DIR` 一个目录里：原始文件对象库 `objects-root/` + 租户快照
`tenants/<ID>/snapshot-<ID>.json`。备份=停机后整目录复制；迁移=复制到新机同名位置。
默认值因入口而异（`.zzdata` / `./data` / 容器 `/data`），生产环境务必显式设置——见 CONFIG.md。

### Q13 快照 JSON 能手改吗？

不要。快照里的 `events` 是哈希链，任何手工改动都会被 `zhanzhen verify` 判定链损坏
（退出码 2）。程序检测到快照损坏时会拒绝静默清空、抛 RuntimeError 保留现场让人决策。
修数据走正常业务路径（覆核修正/红字冲销），让链来记录。

### Q14 两个人能同时用同一个账套吗？

不建议。MVP 存储是单机内存+JSON 快照，**并发写入未加锁**（LIMITATIONS.md #3），
后保存者可能覆盖前者的进度。单人串行使用；多人协作等多租户/PostgreSQL 版本（v0.3.0-alpha）。

### Q15 怎么彻底删除我的数据？

停止服务 → 删除 `$ZZ_DATA_DIR` 整个目录（Docker 用户删挂载的 `./data`）→ 完成，
本地模式没有第二份副本。导出的报告/Excel 属于你自己，自行处置。完整清单与承诺见 PRIVACY.md。

---

## E. Web 作业

### Q16 demo 运行时第 3 步出现 `[跳过] xxx` 正常吗？

正常且刻意。示例账套第 6 张凭证三角不平（含税 ≠ 未税 + 税额），被质量门拦进
`NEEDS_REVIEW`，demo 把它覆核放行但**保留错误数据**，就是为了演示规则引擎必须命中它
（R-AMT-001）。这是特性展示，不是安装坏了。

### Q17 分录页「确认」按钮一直是灰的？

按钮文案会告诉你原因：借贷不平衡时显示差额且禁用。把某行金额改成借贷相等即可；
若怎么都调不平，回查覆核页的含税/未税/税额三兄弟是否自洽。

### Q18 分录确认后发现金额错了，怎么改？

改不了——确认分录不可变（只能红字冲销），这是审计铁律。当前 Web 界面尚未暴露冲销按钮
（路线图 v0.5-beta 批次），可用 Python API：
`AuditService(...).reverse_journal("<voucher_id>", reason="录入错误")`。
系统会生成一笔方向相反的平衡分录并与原分录关联，两笔永久并存。

### Q19 手机采集包导入弹「不是湛箴采集包」？

包不符合契约：顶层需含 `app: "zhanzhen-capture"` 标识与 `items[]` 数组，照片字段名为
`content_b64`。逐项对照 MOBILE_WORKFLOW_CHECKLIST.md §3 的最小样例重打包。

### Q20 导出序时账得到的是 CSV 而不是 Excel？

未安装 openpyxl 时的**自动降级**，CSV 永远可用、不算故障。要 XLSX 就补装：
`pip install "zhanzhen[excel]"`。HTML 报告不受此影响（零模板依赖内置生成）。

### Q20b 页头「事件链 ✘ 损坏」还能继续干活吗？

立即停止作业。说明快照被绕过程序改动过或磁盘损坏。先备份现场目录，跑
`zhanzhen verify` 收集错误明细，从最近一次可信备份恢复快照。带病记账会让全部历史结论
的可信度归零——这正是链式校验存在的意义。

---

## F. 合规与边界

### Q21 我上传的凭证会被传到网上吗？

本地模式下**不会**。唯一出网场景是你主动配置 `ZZ_AI_*` 开启助手后，发送的是已确认的
结构化字段摘要（不是原始文件全文）到你指定的端点。逐字段清单与承诺见 PRIVACY.md；
程序本身无遥测、无自动更新回连。

### Q22 报告能直接交给客户当审计报告吗？

不能。输出物定位是**分析初稿**：审计报告的法定效力仅来源于注册会计师亲笔签名盖章
（《注册会计师法》第 25 条口径）。软件不出具审计意见、不替代职业判断。
红线全文与免责声明见 CPA_COMPLIANCE.md。

### Q23 发票是真的还是假的，软件能验吗？

不能。国家税务系统无公开验真接口，湛箴只做格式、金额平衡与重复检测，**不做联网验真**
（LIMITATIONS.md #4）。真伪核验请走官方线下渠道。

### Q24 遇到这里没写的问题怎么办？

- 先查 [INSTALL.md](INSTALL.md) §5 故障排查表与本文；
- 行为与文档不符？请开 GitHub Issue 附统一错误信封里的 `trace_id`
  （格式 `{code, message, details, trace_id}`）；
- 安全类问题**不要**开公开 Issue，走 SECURITY.md 的私下报告渠道。
