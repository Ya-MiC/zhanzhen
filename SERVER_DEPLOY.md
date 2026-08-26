# 部署与调试指南（SERVER_DEPLOY）—— 服务器放哪 / 在哪调试

> 上游：docs/PRODUCT_TIERS.md（两档制）、ENGINEERING_SPEC §2/§10。读者：创始人/运维。

## 一、服务器放哪（分阶段决策）

### 现在（M0-M1，用户 ≤50）：一台国内轻量云即可
| 项目 | 建议 | 月成本 |
|---|---|---|
| 云商 | 阿里云/腾讯云 轻量应用服务器（**必须国内节点**——数据不出境，总纲 §23） | ¥40-100 |
| 配置 | 2核4G 起，Ubuntu 22.04 | — |
| 带宽 | 5Mbps 固定（凭证图片走内网 MinIO 时够用） | — |
| 备案 | **需要 ICP 备案**（对外提供 Web 服务），走云商代办约 1-2 周 | 免费 |
| 域名 | zhanzhen.cn 类，备案绑定 | ¥50/年 |

**为什么不在家里 NAS 起服务**：家庭宽带无备案无法绑域名、IP 不稳、断电断网=客户数据事故。

### 专业版上线后（M2+，事务所多租户）
- 同城主备两台 + 云数据库 RDS PostgreSQL（自动备份）+ 对象存储 OSS/COS
- 迁移路径已预留：zhanzhen/database.py 的 SQL 全部标准写法，换 psycopg2 连接串即可

### 永远不做
- 数据放境外服务器（违反《数据安全法》36 条与会计师数据管理办法）

## 二、三种部署形态

```bash
# A. 单机免费版（用户下载即用——根本不需要服务器）
pip install git+https://github.com/Ya-MiC/zhanzhen.git
zhanzhen serve            # http://localhost:8710 本机即服务

# B. 云服务器部署专业版（推荐 compose 一键）
git clone https://github.com/Ya-MiC/zhanzhen.git && cd zhanzhen
cp .env.example .env      # 改 ZZ_TENANT_ID / ZZ_USERS(发 API Key 给用户)
docker compose up -d      # 端口 8710；配 nginx 反代 + HTTPS(certbot)

# C. 生产加固
#   - uvicorn workers=2 或 gunicorn -k uvicorn.workers.UvicornWorker
#   - 每日 crontab: sqlite3 backup .backup 或 litestream 实时复制到 OSS
```

## 三、在哪调试

### 本地开发环（最快反馈）
```bash
git clone https://github.com/Ya-MiC/zhanzhen.git && cd zhanzhen
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q                     # 全量测试（当前 70 个）
zhanzhen demo ./out           # 一键跑通全管线看产物
uvicorn zhanzhen.webapp:app --reload --port 8710    # 改代码热重载
# 打开 http://localhost:8710 (用户端) / http://localhost:8710/admin (管理台)
```

### 调试三件套
1. **交互式 API 文档**：http://localhost:8710/docs （FastAPI 自动生成 Swagger，每个端点可点着试）
2. **数据库直查**：`sqlite3 .zzdata/zhanzhen.db ".tables"` / `SELECT * FROM subscriptions;`
3. **证据链校验**：`zhanzhen verify` —— 报错先跑这个判断是不是数据被手改过

### 多角色联调（模拟用户端 vs 管理端）
```bash
# .env 里配置两个账号：
ZZ_AUTH_MODE=users
ZZ_USERS=testkey-admin:boss:admin;testkey-user:xiaowang:accountant
# 用户端请求带 X-API-Key: testkey-user → 只能上传/做账/出报告
# 管理端带 X-API-Key: testkey-admin → 才能开 /admin 和订阅接口
curl -H "X-API-Key: testkey-user" localhost:8710/v1/vouchers          # ✅
curl -H "X-API-Key: testkey-user" localhost:8710/v1/admin/stats       # 403
curl -H "X-API-Key: testkey-admin" localhost:8710/v1/admin/stats      # ✅
```

### 手机采集端调试
- WebView 版：`adb install dist/*.apk` 后 `chrome://inspect` 远程调试页面
- 采集包联调：手机导出 json → 工作台「收手机采集包」→ 观察 `/v1/admin/stats` vouchers 数增长

## 四、升级与回滚
- 升级：`cd zhanzhen && git pull && docker compose up -d --build`（SQLite WAL 在线安全）
- 回滚：`git checkout <上一个tag> && docker compose up -d --build`
- 数据库迁移：database.py 有 schema_migrations 表；破坏性变更必须加迁移脚本+ADR（spec §12）
