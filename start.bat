@echo off
rem 创建/修复快捷方式（挪目录换机器后双击自愈）并直接启动
cd /d "%~dp0"
.venv\Scripts\python.exe create_shortcut.py
explorer.exe "%USERPROFILE%\Desktop\AutoItemCreator.lnk"
