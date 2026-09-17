#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
BT4G_SCRIPT="$SCRIPT_DIR/bt4g.py"
BT4G_SORT_SCRIPT="$SCRIPT_DIR/bt4g_sort.py"

bt4g_ts() { echo "[bt4g $(date '+%H:%M:%S')]"; }

cd "$SCRIPT_DIR"

# 30일 지난 로그 자동 정리 (media-router/run_all.sh와 동일한 방식, 삭제 없이는 무기한 누적됨)
find "$SCRIPT_DIR/logs" -maxdepth 1 -name "*.log" -mtime +30 -delete 2>/dev/null || true

if [ ! -d "$VENV_DIR" ]; then
    echo "$(bt4g_ts) venv 없음, 생성 중..."
    python3 -m venv "$VENV_DIR"
    . "$VENV_DIR/bin/activate"
    pip install --quiet --upgrade pip
    if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
        pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
    else
        pip install --quiet feedparser feedgen
    fi
    echo "$(bt4g_ts) venv 생성 및 패키지 설치 완료"
else
    . "$VENV_DIR/bin/activate"
fi

echo "$(bt4g_ts) BT4G RSS 통합 시작"
# bt4gprx.com 요청이 gluetun(PIA VPN)의 내장 HTTP 프록시를 거쳐 나가도록 설정.
# feedparser(urllib 기반)는 http_proxy/https_proxy 환경변수를 자동으로 따른다.
if [ -f "$SCRIPT_DIR/.env" ]; then
    . "$SCRIPT_DIR/.env"
    export http_proxy="http://${HTTPPROXY_USER}:${HTTPPROXY_PASSWORD}@${HTTPPROXY_HOST}:${HTTPPROXY_PORT}"
    export https_proxy="$http_proxy"
else
    echo "$(bt4g_ts) 경고: .env 없음, VPN 프록시 없이 직접 접속함"
fi
python "$BT4G_SCRIPT" || echo "$(bt4g_ts) bt4g.py 실행 중 오류 발생"
unset http_proxy https_proxy

echo "$(bt4g_ts) BT4G RSS 정렬 및 필터링 시작"
python "$BT4G_SORT_SCRIPT" || echo "$(bt4g_ts) bt4g_sort.py 실행 중 오류 발생"