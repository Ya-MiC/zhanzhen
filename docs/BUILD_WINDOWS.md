# Windows 打包指南 —— 三步出 dist\zhanzhen.exe

湛箴提供 Windows 免安装单文件版：PyInstaller onefile 把 FastAPI 服务、前端页面、
内置规则参数全部打进一个 exe，双击即启动并自动打开浏览器。

## 前置要求

- Windows 10/11 x64
- Python **3.10+**（64 位；与 pyproject 的 `requires-python` 一致）
- 在仓库根目录操作（与 `zhanzhen.spec` 同级）

## 三步打包

```powershell
# 1) 安装运行依赖 + PyInstaller（已装过可跳过对应部分）
pip install -r requirements.txt pyinstaller

# 2) 按 spec 配置打包
pyinstaller zhanzhen.spec

# 3) 双击产物即用
dist\zhanzhen.exe
```

双击后：自动挑选空闲端口 → 后台起服务 → 默认浏览器打开工作台；
控制台窗口标题会显示访问地址，**Ctrl+C 或关闭窗口即退出**。

## 运行行为说明

| 项 | 行为 |
|---|---|
| 监听地址 | 仅 `127.0.0.1`，不向局域网暴露 |
| 端口 | 自动挑空闲端口；设环境变量 `ZZ_PORT=8710` 可固定 |
| 数据目录 | exe 同级 `data\`（不可写时退回 `~\.zhanzhen`）；`ZZ_DATA_DIR` 可覆盖 |
| 规则参数 | 打包内置 `rules_builtin.yaml`；`ZZ_RULES_YAML` 可指向外部文件 |
| OCR/PDF | PDF 文本层可用；图片 OCR（PaddleOCR）默认不打包，走 NEEDS_SERVER 提示 |

> 首次启动 onefile 要把资源解压到临时目录，会比后续启动慢几秒，属正常现象。

## 常见坑

### 1. Defender / SmartScreen 误报「已保护你的电脑」

未签名的 PyInstaller exe 是杀软误报重灾区。分发给自己人时的处理：

- SmartScreen 弹窗：点 **更多信息 → 仍要运行**；
- Windows Defender 隔离了文件：病毒防护 → 保护历史记录 → 还原，
  并把 `dist\` 目录加入排除项；
- 正式对外发行请申请代码签名证书签名 exe，可基本消除误报。

### 2. 端口被占用：`ZZ_PORT=xxx 已被占用`

- 报错信息里带了端口，用 `netstat -ano | findstr :<端口>` 找到占用进程关掉；
- 或换一个端口：PowerShell `$env:ZZ_PORT="8710"; .\zhanzhen.exe`
  （永久设置：系统属性 → 环境变量）。
- 自动选口模式下不会撞车；只有显式指定 `ZZ_PORT` 且被占用才会报错退出。

### 3. 杀毒软件（360/火绒等）拦截或报「可疑程序」

同误报问题：添加信任/白名单目录即可。不要下载来路不明的"绿色版"，自行从源码打包最稳妥。

### 4. 双击后闪退

- 先在 PowerShell 里运行 `.\dist\zhanzhen.exe` 看完整报错（控制台版保留了日志输出）；
- 多为构建机缺依赖：确认第 1 步的 `pip install -r requirements.txt` 装齐了再重新打包。

### 5. 构建机与目标机位数不一致

32 位 Python 只能打出 32 位 exe。构建机请装 **64 位 Python 3.10+**。

## 验证清单（发版前自测）

```powershell
dist\zhanzhen.exe          # 浏览器自动打开首页，上传一张凭证跑通全流程
$env:ZZ_PORT="8710"; dist\zhanzhen.exe   # 固定端口生效，标题显示 8710
# 再开第二个实例：自动换空闲端口，两个互不影响
```
