#!/data/data/com.termux/files/usr/bin/bash
# 5분(±30초)마다 watcher.py 를 반복 실행합니다.
cd "$(dirname "$0")" || exit 1
termux-wake-lock 2>/dev/null   # 화면이 꺼져도 CPU가 잠들지 않게
while true; do
  python watcher.py >> watcher.log 2>&1
  tail -n 300 watcher.log > watcher.log.tmp && mv watcher.log.tmp watcher.log   # 로그 300줄만 유지
  sleep $((270 + RANDOM % 61))
done
