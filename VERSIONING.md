# 版本与发布节奏（VERSIONING）

> 依据：[语义化版本 SemVer 2.0.0](https://semver.org/lang/zh-CN/) × 《ENGINEERING_SPEC》§11 八周计划 × 总纲 §27 Phase 0-6。
> 规则：破坏契约（specs 三件套）变更 = 升主版本；新增功能 = 升次版本；修复 = 升修订号。
> 预-1.0 补充：0.x 阶段的 breaking-level 变更（含视觉契约，如本轮 Web 工作台 UI 全面改版）按惯例升**次版本号**。

## 当前版本

**v0.3.0 · 平台化与多受众交付轮**（2026-08-25）

| 已交付 | 说明 |
|---|---|
| 五受众报告引擎 | bank / gov / boss / firm / cross 五受众模板 + jinja2 缺失时纯 Python 兜底；注册会计师免责声明强制；`POST /v1/exports/report-v2` 按 audience 出稿并接入管线 |
| OCR 三级路由 | OcrRouter 三级降级链：文字型 PDF→文本层 / txt→Stub / 图片→Tesseract(chi_sim)→PaddleOCR→引擎全缺返回明确 NEEDS_SERVER 信封；`router=auto` 回显 engine 与 fallback_chain；14 个路由用例 |
| 加密层 + 数据库双后端 | PBKDF2-HMAC-SHA256（200k 轮）派生密钥 → Fernet 加解密，可选依赖懒加载可读报错；`ZZ_DATABASE_URL`→PostgreSQL(psycopg2 懒加载) / 否则 SQLite 双后端 + ?↔%s 占位符翻译层；report_assets 报告资产先加密再落库；新增 `[server]` extra |
| DSH 工作流插件分支 | dsh-plugin 分支承载审计行业 n8n 式七节点工作流引擎（TypeScript）+ 基础工作流模板 JSON + zz.workflow.list / zz.workflow.run 工具 |
| 安卓直传双轨 | 免费轨：采集包 `POST /v1/vouchers/capture-batch` 逐张服务端重算 SHA-256 + 工作台导入按钮；专业轨：对象存储预签名 URL 直传（分片），口径见 docs/MOBILE_WORKFLOW.md |
| Windows 免安装 exe | desktop.py 启动器 + PyInstaller 单文件打包（zhanzhen.spec）：双击启动并自动开浏览器、自动挑空闲端口、数据落 exe 同级 data\ 目录；构建指南 docs/BUILD_WINDOWS.md |
| UI 全面改版 | 正式产品形态：登录横幅（Key→localStorage→X-API-Key）、按角色显隐页签（viewer 仅报告 / admin 增管理台）、顶栏本月报告额度 x/3 或 ∞、品牌色 #0F4C81 + #C9A063；配套免费/专业订阅计费与管理台端点 |

对应总纲阶段：Phase 0 收尾 → 平台化起步；质量基线 **97 测试绿**（可选依赖缺失的 13 例自动跳过）；main 85 文件 + dsh-plugin 分支同步演进。

## 发布路线（预发布节奏）

| 版本 | 预计 | 内容 | 对应 |
|---|---|---|---|
| 原 v0.2.x / v0.3.0-alpha 计划项 | 已并入 v0.3.0 | PostgreSQL 双后端、认证/角色 stub、OCR 软件化三级路由随本轮交付；MinIO 直传仅落地接口层，PaddleOCR 服务端正式接入顺延至下轮 | spec Week 2/3 |
| **v0.4.0-alpha** | W+1~3 | PaddleOCR 服务端正式接入 + 金标数据集框架 + 字段级评估脚本 | spec Week 3 |
| **v0.5.0-beta** | W+5~7 | RBAC 完备 + 审计日志完备 + rate limit + 备份恢复文档 + Flutter Windows 操作台启动 | spec Week 4/7 |
| **v1.0.0** | M0 出口 | 50-100 张真实去敏凭证全闭环验收：字段准确率/误报率/处理时长达标 + Demo walkthrough | spec Week 8 / 总纲 M0→M1 |

v1.0.0 之后按总纲 Phase 2-6：审计项目管理 → 事务所版 → 连接器 → 行业模型 → 跨境。

## 版本号怎么读

```
v0.x.y   x=能力代际（0=单机原型） y=增量
v0.3.0   预-1.0：API 与界面仍可能变，勿用于生产
```
