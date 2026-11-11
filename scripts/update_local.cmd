@echo off
rem Daily local refresh: fetch the SNU calendar and push docs/events.json when it changed.
rem GitHub-hosted runners get truncated responses from www.snu.ac.kr, so this runs on a PC instead.
cd /d "%~dp0.."
git pull --quiet --ff-only || exit /b 1
python scriptsetch_events.py > "%TEMP%\snu-events-update.log" 2>&1 || exit /b 1
git diff --quiet -- docs/events.json && exit /b 0
git add docs/events.json
git commit --quiet -m "Update SNU calendar events"
git push --quiet
