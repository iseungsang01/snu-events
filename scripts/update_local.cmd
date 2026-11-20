@echo off
rem Daily local refresh: fetch events and publish JSON plus subscription calendars.
rem GitHub-hosted runners get truncated responses from www.snu.ac.kr, so this runs on a PC instead.
cd /d "%~dp0.."
git pull --quiet --ff-only || exit /b 1
python scripts/fetch_events.py > "%TEMP%\snu-events-update.log" 2>&1 || exit /b 1
rem Enrichment failure must not prevent publishing the newly fetched rule data.
python scripts/enrich_with_codex.py >> "%TEMP%\snu-events-update.log" 2>&1
if errorlevel 1 echo Codex enrichment failed; publishing collected events with rule fallback. >> "%TEMP%\snu-events-update.log"
git add docs/events.json docs/calendar/ || exit /b 1
git diff --cached --quiet -- docs/events.json docs/calendar/ && exit /b 0
git commit --quiet -m "Update SNU calendar events"
git push --quiet
