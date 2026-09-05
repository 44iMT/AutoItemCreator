"""
创建/刷新桌面与项目内快捷方式（AutoItemCreator.lnk → pythonw desktop.py）。

覆盖式重建：每次运行都按当前位置重写——挪目录/换机器后双击 安装.bat 即自愈。
图标 = aic.ico（品红六边形）。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / ".venv" / "Scripts" / "pythonw.exe"
ICON = ROOT / "web" / "static" / "aic.ico"


def create(shortcut_path: Path) -> None:
    import win32com.client
    ws = win32com.client.Dispatch("WScript.Shell")
    lnk = ws.CreateShortcut(str(shortcut_path))
    lnk.TargetPath = str(TARGET)
    lnk.Arguments = "desktop.py"
    lnk.WorkingDirectory = str(ROOT)
    lnk.IconLocation = f"{ICON},0"
    lnk.Description = "AutoItemCreator 商品数据工作台"
    lnk.Save()


def main():
    if not TARGET.exists():
        sys.exit(f"pythonw 不存在: {TARGET}（先建 venv: python -m venv .venv）")
    # COM 的 SpecialFolders("Desktop") = 注册表真实桌面（防 OneDrive 重定向）
    import win32com.client
    desktop = Path(win32com.client.Dispatch("WScript.Shell").SpecialFolders("Desktop"))
    for p in (desktop / "AutoItemCreator.lnk", ROOT / "AutoItemCreator.lnk"):
        create(p)
        print(f"✓ {p}")
    print("完成，双击桌面图标即可启动")


if __name__ == "__main__":
    main()
