# dsh-plugin-zhanzhen-audit

湛箴审计 OS 的 **DeepSeek Harness 插件**——「一切皆插件」架构的审计能力接入。

## 安装

前置：湛箴服务在本地跑着：

```bash
pip install "zhanzhen[web]"
zhanzhen serve            # http://127.0.0.1:8710（ZZ_PORT 可改）
```

然后把本目录作为 DSH 插件装入 Harness。

## 命令

| 命令 | 说明 |
|---|---|
| `zz.vouchers` | 凭证箱总览 |
| `zz.ocr <id>` | OCR 识别指定凭证 |
| `zz.review <id> field=value` | 覆核修正字段（留痕进哈希链） |
| `zz.journal <id>` | 生成分录草稿并确认 |
| `zz.rules` | 运行三条审计规则 |
| `zz.report` | 导出可追溯 HTML 报告 |
| `zz.integrity` | 校验证据链完整性 |

## 配置

```ts
export default {
  plugins: {
    'zhanzhen-audit': {
      baseUrl: 'http://127.0.0.1:8710',
      // token: '...'
    }
  }
}
```

环境变量 `ZHANZHEN_BASE_URL` 亦可。
