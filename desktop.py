"""
桌面壳 v4：uvicorn 子线程 + Edge --app 窗口（应用层心跳守护生命周期）。

用法：python desktop.py（或双击快捷方式 → pythonw，零控制台）

演进（为何放弃 pywebview）：窗口图标需求在 pywebview 下被迫伸进 pythonnet/WinForms
底层，两版竞态翻车（UI 线程冻结/原生崩）。向上溯源后换壳——Edge 的 --app 模式
天生无地址栏独立窗口，且窗口图标 = 页面 favicon（六边形白送），
图标需求从清单里消失而不是被解决。

生命周期：窗口与服务分属两进程，页面每 5s ping /api/heartbeat，
服务侧超 HEARTBEAT_TIMEOUT 秒没收到心跳 → 退服务（关窗后约 15s 内退出）。
"""
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

HEARTBEAT_TIMEOUT = 15   # 秒；页面 5s 一 ping，3 次未达判离线

# ── 日志落盘（必须在任何 print 之前；pythonw 态 stdout=None，print 会炸）──
LOG_DIR = ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_log = open(LOG_DIR / f"desktop_{datetime.now():%Y%m%d}.log", "a", encoding="utf-8", buffering=1)
if sys.stdout is None:
    sys.stdout = _log
    sys.stderr = _log


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _open_app_window(url: str) -> None:
    """Edge --app 独立窗口（无地址栏，图标=favicon）；居中 1600x900；Edge 缺席退默认浏览器。"""
    W, H = 1600, 900
    # 居中：按主屏工作区算左上角（user32.SystemParametersInfo 取 SPI_GETWORKAREA）
    try:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
        x, y = max(0, (r.right - r.left - W) // 2 + r.left), max(0, (r.bottom - r.top - H) // 2 + r.top)
    except Exception:
        x, y = 60, 40   # 拿不到工作区时的保底位置
    edge = shutil.which("msedge") or r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    # 独立 profile：让窗口几何永远归 --window-size/--position 管——
    # 共享 profile 下 Edge 的"窗口记忆"会覆盖启动参数（实测 945x1020 盖掉 1600x900）
    profile = ROOT / "data" / "edge_profile"
    try:
        subprocess.Popen([edge, f"--app={url}",
                          f"--user-data-dir={profile}",
                          f"--window-size={W},{H}", f"--window-position={x},{y}",
                          "--no-first-run", "--no-default-browser-check"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[desktop] Edge app 窗口已拉起（{W}x{H} @ {x},{y}，独立profile）")
    except Exception:
        import webbrowser
        webbrowser.open(url)   # 兜底：普通浏览器标签页（图标同样是 favicon）
        print("[desktop] Edge 不可用，退默认浏览器")


def main():
    import uvicorn
    import web.app  # noqa: F401

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config("web.app:app", host="127.0.0.1", port=port,
                                           log_level="warning"))

    def _serve():
        import traceback
        try:
            server.run()
        except Exception:
            print("[desktop] 服务线程崩溃:\n" + traceback.format_exc())

    threading.Thread(target=_serve, daemon=True).start()

    url = f"http://127.0.0.1:{port}/"
    for _ in range(100):                      # 探活：就绪再开窗，防白屏
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                break
        except Exception:
            time.sleep(0.1)
    print(f"[desktop] 服务就绪 {url}")
    _open_app_window(url)

    # 心跳守护：页面活着就续命，窗口关了（心跳断）就收摊
    from web.app import last_heartbeat
    while True:
        time.sleep(2)
        if time.time() - last_heartbeat[0] > HEARTBEAT_TIMEOUT:
            who = _jobs_running()
            print(f"[desktop] 心跳超时（窗口已关闭）{'，任务仍在跑将随之终止: ' + who if who else ''}")
            break
    server.should_exit = True
    print("[desktop] 服务退出")


def _jobs_running() -> str:
    try:
        import web.routers.build as B
        import web.routers.run as R
        if not B.job["done"] and B.job["proc"] and B.job["proc"].poll() is None:
            return "主档商品库构建"
        if not R.job["done"] and R.job["proc"] and R.job["proc"].poll() is None:
            return "商品数据构建（跑批）"
    except Exception:
        pass
    return ""


if __name__ == "__main__":
    main()
