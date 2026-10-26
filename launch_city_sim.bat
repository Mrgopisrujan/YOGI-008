@echo off
title GarudaOS - Unreal City Simulation
color 0a
echo ========================================================
echo       Launching Unreal Engine CityEnviron Simulation
echo ========================================================
echo Navigating to simulation directory...
cd /d "D:\Aatonovaz\Garuda\CityEnviron\WindowsNoEditor"
echo Starting CityEnviron.exe in windowed mode...
start "" "CityEnviron.exe" -windowed -ResX=1280 -ResY=720
