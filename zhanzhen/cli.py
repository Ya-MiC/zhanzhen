"""湛箴命令行入口。

  zhanzhen demo <dir>   跑通全管线并生成报告（零配置即可用）
  zhanzhen serve        启动 Web 工作台（需 zhanzhen[web]）
  zhanzhen verify       校验数据目录事件链完整性
"""

from __future__ import annotations

import argparse
import os
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="zhanzhen", description="湛箴 Audit OS")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="一键演示：示例账套→OCR→分录→规则→报告")
    d.add_argument("outdir", nargs="?", default="./zz-demo-out")

    s = sub.add_parser("serve", help="启动 Web 工作台")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    v = sub.add_parser("verify", help="校验事件哈希链完整性")

    args = ap.parse_args(argv)

    if args.cmd == "demo":
        return _demo(args.outdir)
    if args.cmd == "serve":
        return _serve(args.host, args.port)
    if args.cmd == "verify":
        return _verify()
    return 1


def _demo(outdir: str) -> int:
    from .service import AuditService
    svc = AuditService(tenant_id="demo", data_dir=os.path.join(outdir, "data"))
    print("== 1. 载入示例账套（6张凭证，含重复/金额异常样本）==")
    ids = svc.load_demo_data()
    for vid in ids:
        print("  凭证:", vid[:8])
    print("== 2. 全部进入覆核通过态 ==")
    for vid, rec in list(svc.store.vouchers.items()):
        if rec["state"] == "NEEDS_REVIEW":
            svc.review(vid, {}, reviewer="demo-human")
    print("== 3. 生成分录草稿并确认 ==")
    for vid, rec in list(svc.store.vouchers.items()):
        if rec["state"] == "REVIEWED":
            try:
                svc.draft_journal(vid)
                svc.confirm_journal(vid, actor="demo-human")
            except Exception as e:
                print(f"  [跳过] {vid[:8]}: {e}")
    print("== 4. 规则引擎 ==")
    findings = svc.run_rules()
    for f in findings:
        print(f"  [{f['severity']}] {f['rule_id']} → {f['explanation'][:60]}")
    print(f"  共 {len(findings)} 条命中")
    print("== 5. 导出 ==")
    html_path = svc.export_report(out_dir=outdir)
    print("  报告:", html_path)
    try:
        xl = svc.export_journal_excel(out_dir=outdir)
        print("  序时账:", xl)
    except Exception as e:
        print("  序时账导出失败:", e)
    iv = svc.verify_integrity()
    print("== 6. 证据链校验 ==", "✔ 完整" if iv["chain_ok"] else f"✘ {iv['errors']}")
    print(f"\n打开报告查看: {os.path.abspath(html_path)}")
    return 0


def _serve(host: str, port: int) -> int:
    try:
        import uvicorn
    except ImportError:
        print("需要安装 Web 依赖: pip install 'zhanzhen[web]'")
        return 1
    uvicorn.run("zhanzhen.webapp:app", host=host, port=port)
    return 0


def _verify() -> int:
    from .store import TenantStore
    from .events import EventLog
    tenant = os.environ.get("ZZ_TENANT_ID", "default")
    data_dir = os.environ.get("ZZ_DATA_DIR", ".zzdata")
    snap = os.path.join(data_dir, "tenants", tenant, f"snapshot-{tenant}.json")
    if not os.path.exists(snap):
        print(f"未找到快照: {snap}")
        return 1
    import json
    with open(snap, encoding="utf-8") as f:
        events = EventLog(json.load(f).get("events", []))
    ok, errors = events.verify_chain()
    n = len(events.all())
    print(("✔" if ok else "✘"), f"{n} 条事件，链{'完整' if ok else '损坏'}")
    for e in errors:
        print(" -", e)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
