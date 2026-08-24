# 品牌：湛箴 · OctopusZhen 🐙（品牌备忘录）

> 缘起：创始人选定章鱼为品牌符号（对标 DeepSeek 🐋、Docker 🐳 的动物 IP 路线），
> 并要求与「湛箴 Zhanzhen」谐音融合。本文档是定名依据 + 图标设计提示词，供后续
> AI 生图 / 设计师执行时直接引用。

## 一、定名：OctopusZhen（缩写 OZ）

| 语言 | 写法 | 读法 | 用途 |
|---|---|---|---|
| 中文 | 湛箴 | zhàn zhēn | 正式产品名 |
| 英文 | **OctopusZhen** | ok-TO-pus-ZHEN | GitHub org/包名/域名 |
| 缩写 | **OZ** | — | logo 主字、命令前缀（`zz.*` 已呼应）|
| 拉丁/古雅体 | **Octozhen** (OCTOZHEN) | — | 印章式变体、徽标环字 |
| 阿拉伯语 | الأخطبوط جانجن (al-ukhtubūt Zhanjen) | — | 跨境版界面备用 |

**谐音逻辑**：Octo**Z**hen 尾音正落在「箴 Zhen」上——章鱼(Octo) + 箴(Zhen) 天然连读；
「湛」取清澈深蓝之意，正好对应深海章鱼的配色。「箴」= 规谏之言 = 审计的「规」与「证」，
章鱼八爪 = 多数据源触达（账/票/银/税/合同/物流/跨境/AI），每条触腕都能"抓证据"——
与总纲「Evidence Graph 证据链护城河」完美同构：**八爪抓证据，一脑管风险。**

## 二、图标设计提示词（Image Prompt）

> 使用场景：Midjourney / DALL·E / SDXL。基础提示词：

```
Minimalist flat vector logo of a friendly geometric octopus, deep ocean blue
(#0F4C81) body with gold-amber (#D9A406) accents, eight tentacles elegantly
curled around a glowing shield-shaped ledger document, one tentacle holding
a magnifying glass over a checkmark, round badge layout suitable for app icon,
clean white background, corporate fintech style, no text, centered composition
--v 6 --style raw
```

中文要点（给设计师）：
1. **主体**：几何扁平风小章鱼，圆润友好不惊悚；主色深海军蓝 `#0F4C81`（现有 README 同色系）
2. **点睛**：金琥珀色 `#D9A406` 用于吸盘与描边（呼应 audit-os-mobile 图标的暖金元素）
3. **道具**：一条触腕卷着一本**盾形账册**（审计+防护双关）；一条触腕持放大镜照着对勾（复核语义）
4. **构图**：圆形徽章布局，App icon 直接可用；留白干净，无文字
5. **禁忌**：不要写实照片风、不要恐怖触手、不要渐变紫（避开竞品感）

### 与现有图标的传承

audit-os-mobile 的 APK 图标（红金三峰「山」形定制图案，用户亲自选定的 v0.3 方案）
不含章鱼元素，但其**红金对比 + 几何硬朗**基因被继承为章鱼配色的点缀层。
新图标发布后，移动端 v0.4 同步换装。

## 三、应用规范速查

| 场景 | 用法 |
|---|---|
| README 头图 | `<h1>🐙 湛箴 OctopusZhen</h1>` |
| CLI 欢迎语 | `octozhen` ASCII banner（待 v0.2 加入）|
| 包名别名 | PyPI 候选 `octopuszhen`（zhanzhen 已占用的镜像名另议）|
| 命令空间 | DSH 插件命令保持 `zz.*`（OZ 双写呼应）|
