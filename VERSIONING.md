# 版本与发布节奏（VERSIONING）

> 依据：[语义化版本 SemVer 2.0.0](https://semver.org/lang/zh-CN/) × 《ENGINEERING_SPEC》§11 八周计划 × 总纲 §27 Phase 0-6。
> 规则：破坏契约（specs 三件套）变更 = 升主版本；新增功能 = 升次版本；修复 = 升修订号。

## 当前版本

**v0.1.0 · Phase-0 单机参考实现**（2026-08-24）

| 已交付 | 说明 |
|---|---|
| 核心域零依赖包 | canonical JSON / 事件哈希链 / 12态状态机 / VoucherJSON v1 校验归一化 |
| OCR 协议层 | PDF 文本层提取（可用）+ 确定性 Stub + PaddleOCR 探测位 |
| 三条 MVP 规则 | R-AMT-001 金额一致性 / R-DUP-001 疑似重复 / R-CMP-001 完整性 |
| 分录引擎 | 科目建议模板 + 借贷平衡硬校验 + 确认不可变 + 红字冲销 |
| 可追溯导出 | HTML 报告（SHA-256 全索引）+ 序时账 XLSX/CSV（导出前强制平衡校验）|
| Web 工作台 | FastAPI 子集端点 + Vue3 单页（上传/覆核/分录/风险/AI助手面板）|
| AI 助手 | OpenAI 兼容端点，schema 约束 + model_runs 留痕，默认关闭 |
| DSH 插件 | dsh-plugin/ 一切皆插件接入（zz.* 七命令）|
| 质量 | 31 个单测/端到端全绿（CI 矩阵 3.10/3.12）；demo 账套全管线人工验证 |

对应总纲阶段：**Phase 0 技术原型完成**；对应规范周：Week 1 内容 + W5/W6 核心语义提前落地。

## 发布路线（预发布节奏）

| 版本 | 预计 | 内容 | 对应 |
|---|---|---|---|
| **v0.2.0-alpha** | W+1~2 | PaddleOCR adapter 正式接入 + 90张去敏金标数据集框架 + 字段级评估脚本 | spec Week 3 |
| **v0.3.0-alpha** | W+3~4 | PostgreSQL 迁移（RLS 实验）+ 多租户上下文 + 对象存储 MinIO + 认证 stub | spec Week 2 |
| **v0.5.0-beta** | W+5~7 | RBAC + 审计日志完备 + rate limit + 备份恢复文档 + Flutter Windows 操作台启动 | spec Week 4/7 |
| **v1.0.0** | M0 出口 | 50-100 张真实去敏凭证全闭环验收：字段准确率/误报率/处理时长达标 + Demo walkthrough | spec Week 8 / 总纲 M0→M1 |

v1.0.0 之后按总纲 Phase 2-6：审计项目管理 → 事务所版 → 连接器 → 行业模型 → 跨境。

## 版本号怎么读

```
v0.x.y   x=能力代际（0=单机原型） y=增量
v0.2.0-alpha   预发布标签：API 可能变，勿用于生产
```
