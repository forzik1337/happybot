@echo off
chcp 65001 >nul

:: БОТ
start cmd /k py -3.11 bot.py

:: ВТОРОЙ САЙТ (плеер)
start cmd /k py -3.11 player.py

pause