@echo off
title GarudaOS - City Pedestrian Spawner
color 0a
echo ========================================================
echo     GarudaOS — Dynamic City Pedestrian Spawner
echo ========================================================
echo.
echo Connecting to CityEnviron.exe on port 41451...
echo Spawning dynamic pedestrians on sidewalks in front of launchpad...
echo.

if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe scripts\spawn_pedestrians.py --count 3 --speed 1.4
) else (
    python scripts\spawn_pedestrians.py --count 3 --speed 1.4
)
pause
