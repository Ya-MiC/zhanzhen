"""桌面单文件入口 —— Windows 免安装 exe（PyInstaller onefile）的启动器。

流程：找空闲端口（或 ZZ_PORT 指定）→ 后台线程内嵌 uvicorn 跑 webapp
→ 服务就绪后自动打开浏览器 → 控制台窗口标题显示访问地址；
Ctrl+C（或直接关闭窗口）退出。

设计约束（ENGINEERING_SPEC §12 诚实原则）：
- 只监听 127.0.0.1，不向局域网/外网暴露端口；
- 冻结（PyInstaller）环境下把 rules_builtin.yaml 指到解包目录，
  数据目录默认落在 exe 同级 data\，可用 ZZ_DATA_DIR / ZZ_PORT 环境变量覆盖；
- ZZ_PORT 指定的端口被占用时明确报错退出，不静默换口。

源码模式同样可用：python -m zhanzhen.desktop
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser

APP_TITLE = "湛箴 ZhanZhen Audit OS"
HOST = "127.0.0.1"
READY_TIMEOUT = 15.0  # 秒，等 uvicorn 完成绑定的最长时间


def find_free_port() -> int:
    """让操作系统发一个当前空闲的 TCP 端口（bind 到 0）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return int(s.getsockname()[1])


def resolve_port() -> int:
    """ZZ_PORT 环境变量优先；未设置则自动挑空闲端口。"""
    raw = (os.environ.get("ZZ_PORT") or "").strip()
    if not raw:
        return find_free_port()
    try:
        port = int(raw)
    except ValueError:
        raise SystemExit(f"[湛箴] ZZ_PORT={raw!r} 不是合法端口号") from None
    if not (1 <= port <= 65535):
        raise SystemExit(f"[湛箴] ZZ_PORT={port} 超出范围 1-65535")
    if port_is_taken(port):
        raise SystemExit(
            f"[湛箴] 端口 {port} 已被占用。请关闭占用程序，"
            f"或设置环境变量 ZZ_PORT 为其他端口后重试。")
    return port


def port_is_taken(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, port)) == 0


def setup_frozen_paths() -> None:
    """PyInstaller onefile 下修正资源与数据路径。

    - 解包根目录是 sys._MEIPASS（spec 已把 rules_builtin.yaml 与 web/ 放进去）；
    - 规则参数默认取解包目录里的 rules_builtin.yaml（rules.py 按 CWD 找不到时退回内置值）;
    - 数据目录默认放 exe 同级 data\\（双击启动时 CWD 可能不在 exe 目录），
      目录不可写（如 Program Files）则退回 ~/.zhanzhen。
    """
    if not getattr(sys, "frozen", False):
        return
    base = getattr(sys, "_MEIPASS", None)
    if base:
        os.environ.setdefault(
            "ZZ_RULES_YAML", os.path.join(base, "rules_builtin.yaml"))
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    candidates = [
        os.path.join(exe_dir, "data"),
        os.path.join(os.path.expanduser("~"), ".zhanzhen"),
    ]
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            os.environ.setdefault("ZZ_DATA_DIR", d)
            break
        except OSError:
            continue


def set_console_title(text: str) -> None:
    """Windows 控制台窗口标题显示访问地址；其他平台静默跳过。"""
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(text)  # 仅 Windows
    except Exception:
        pass


def wait_until_ready(port: int, timeout: float = READY_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_is_taken(port):
            time.sleep(0.15)
            continue
        return True
    return False


def ensure_importable() -> None:
    """源码模式直跑本文件时（python zhanzhen/desktop.py），把仓库根加进 sys.path。

    冻结模式下包已在 PYZ 里，无需处理。
    """
    if getattr(sys, "frozen", False):
        return
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> int:
    setup_frozen_paths()
    ensure_importable()
    port = resolve_port()
    url = f"http://{HOST}:{port}/"

    # 延迟导入：保证 --help 类快速失败路径不被拖慢，也便于单测替换
    try:
        import uvicorn
        from zhanzhen.webapp import app
    except ImportError as e:
        print(f"[湛箴] 缺少 Web 依赖：{e}\n"
              f"       请先安装：pip install -r requirements.txt", file=sys.stderr)
        return 1

    server = uvicorn.Server(uvicorn.Config(
        app, host=HOST, port=port, log_level="info"))
    thread = threading.Thread(target=server.run, name="zz-uvicorn", daemon=True)
    thread.start()

    if not wait_until_ready(port):
        print(f"[湛箴] 服务在 {READY_TIMEOUT}s 内未就绪（端口 {port}），退出。",
              file=sys.stderr)
        server.should_exit = True
        thread.join(timeout=5)
        return 1

    set_console_title(f"{APP_TITLE} — {url}")
    print("=" * 52)
    print(f"  {APP_TITLE} 已启动")
    print(f"  访问地址: {url}   （浏览器已自动打开）")
    print(f"  数据目录: {os.environ.get('ZZ_DATA_DIR', '.zzdata')}")
    print("  退出方式: 按 Ctrl+C 或直接关闭本窗口")
    print("=" * 52)

    try:
        webbrowser.open(url)
    except Exception as e:  # 无默认浏览器的机器上给出兜底提示
        print(f"[湛箴] 自动打开浏览器失败（{e}），请手动访问 {url}")

    try:
        while thread.is_alive():
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n[湛箴] 收到 Ctrl+C，正在退出……")
        server.should_exit = True
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
