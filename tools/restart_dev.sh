#!/bin/sh
# Restart a local Django dev server (Windows / Git Bash).  Usage: sh tools/restart_dev.sh [port]
# Pair with SST_DJ_URL=http://127.0.0.1:<port> for tools/visual/*.py.
PORT="${1:-8000}"
cd "$(dirname "$0")/.."
for pid in $(netstat -ano | grep "127.0.0.1:$PORT " | grep LISTENING | awk '{print $5}' | sort -u); do taskkill //PID "$pid" //F >/dev/null 2>&1; done
LOG="${TMPDIR:-/tmp}/sst_runserver_$PORT.log"
nohup .venv/Scripts/python manage.py runserver "127.0.0.1:$PORT" --noreload > "$LOG" 2>&1 &
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do sleep 1; curl -s -o /dev/null "http://127.0.0.1:$PORT/robots.txt" && break; done
echo "dev server up on $PORT (log: $LOG)"
