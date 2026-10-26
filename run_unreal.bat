@echo off
title GarudaOS - Unreal Engine 5.7.4 Copilot
color 0b
echo ========================================================
echo       Starting GarudaOS Unreal Engine 5.7.4 Copilot
echo ========================================================
if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe scripts\run_unreal_pilot.py
) else (
    python scripts\run_unreal_pilot.py
)
pause
