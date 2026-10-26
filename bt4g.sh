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

# 티프리카 예능 게시판 → xml/tfreeca_rss.xml (qBittorrent "예능" 규칙이 읽음, 2026-10-26)
# 국내 사이트라 VPN 프록시 없이 직접 접속한다. 주소가 바뀌면 .env에 TFREECA_BASE=...
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a; . "$SCRIPT_DIR/.env"; set +a
fi
echo "$(bt4g_ts) 티프리카 RSS 시작"
python "$SCRIPT_DIR/tfreeca.py" || echo "$(bt4g_ts) tfreeca.py 실행 중 오류 발생"

# BT4G는 같은 NEXT 토렌트를 몇 시간 늦게 잡고, 대량 검색 시 응답이 끊겨서 기본은 끔.
# Media Router "예능 키워드" 화면의 스위치가 아래 파일을 만들고 qBittorrent 규칙에 BT4G 피드를 넣는다.
BT4G_FLAG="/volume1/docker/media-router/data/bt4g_enabled"
if [ ! -f "$BT4G_FLAG" ] && [ "${BT4G_ENABLE:-0}" != "1" ]; then
    echo "$(bt4g_ts) BT4G 꺼짐 (Media Router 예능 키워드 화면에서 켤 수 있음)"
    exit 0
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