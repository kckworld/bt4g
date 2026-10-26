"""티프리카 예능 게시판 → RSS (2026-10-26)

BT4G는 DHT 검색이라 NEXT 릴이 방송 후 몇 시간 뒤에야 잡히고, 키워드를 한꺼번에
검색하면 응답이 끊긴다. 티프리카 예능 게시판(b_id=tent)은 NEXT가 바로 올라오므로
목록 1~2쪽만 읽어서 bt4g_keywords.txt 키워드와 맞는 720p-NEXT 글을 RSS로 만든다.
qBittorrent "예능" 규칙이 이 RSS를 읽어 자동으로 받는다.

티프리카 주소가 바뀌면 .env에 TFREECA_BASE=https://www.tfreecaNN.com 을 넣는다.
"""
import html
import json
import os
import re
import socket
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from feedgen.feed import FeedGenerator

socket.setdefaulttimeout(15)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGDIR = os.path.join(SCRIPT_DIR, "logs")
XML_DIR = os.path.join(SCRIPT_DIR, "xml")
os.makedirs(LOGDIR, exist_ok=True)
os.makedirs(XML_DIR, exist_ok=True)
LOGFILE = os.path.join(LOGDIR, f"tfreeca_{datetime.now().strftime('%Y%m%d')}.log")
RSS_PATH = os.path.join(XML_DIR, "tfreeca_rss.xml")
CACHE_PATH = os.path.join(XML_DIR, "tfreeca_items.json")
KEYWORD_FILE = os.path.join(SCRIPT_DIR, "bt4g_keywords.txt")

BASE = os.environ.get("TFREECA_BASE", "https://www.tfreeca22.com").rstrip("/")
PAGES = 2
KEEP_DAYS = 14          # 캐시/RSS에 남겨 둘 기간
MAX_AIR_AGE_DAYS = 7    # 방송일이 이보다 오래된 글(재업로드)은 받지 않음
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
KST = timezone(timedelta(hours=9))

ROW_RE = re.compile(
    r'mode=view&b_id=tent&id=(\d+)&page=\d+" class="stitle\d">\s*(.*?)\s*</a>',
    re.S,
)
MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:([A-Za-z0-9]{32,40})")
REGDATE_RE = re.compile(r"등록일:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
AIRDATE_RE = re.compile(r"\.(\d{6})\.720p")


def ts():
    return f"[tfreeca {datetime.now().strftime('%H:%M:%S')}]"


def log(msg):
    line = f"{ts()} {msg}"
    with open(LOGFILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": BASE + "/"})
    with urllib.request.urlopen(req) as r:
        return r.read().decode("utf-8", errors="replace")


def normalize(s):
    return re.sub(r"\s+", "", s).lower()


def load_keywords():
    """bt4g_keywords.txt의 ' 720p'는 BT4G 검색용이라 떼고, 공백 없이 비교한다
    ('나는SOLO 720p' → '나는solo'가 '나는 SOLO.E276...'과 맞음)."""
    with open(KEYWORD_FILE, encoding="utf-8") as f:
        words = [re.sub(r"\s*720p\s*$", "", line.strip(), flags=re.I) for line in f]
    return [normalize(w) for w in words if w.strip()]


def wanted(title, keywords):
    if "720p-next" not in title.lower():
        return False
    t = normalize(title)
    if not any(k in t for k in keywords):
        return False
    m = AIRDATE_RE.search(title)
    if m:
        try:
            air = datetime.strptime(m.group(1), "%y%m%d")
        except ValueError:
            return True
        if datetime.now() - air > timedelta(days=MAX_AIR_AGE_DAYS):
            return False
    return True


def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main():
    keywords = load_keywords()
    cache = load_cache()  # 글 id → {title, btih, pub}

    posts = []
    for page in range(1, PAGES + 1):
        url = f"{BASE}/board.php?mode=list&b_id=tent&page={page}"
        try:
            body = fetch(url)
        except Exception as e:
            log(f"목록 {page}쪽 요청 실패: {type(e).__name__}: {e}")
            break
        rows = [(i, html.unescape(t).strip()) for i, t in ROW_RE.findall(body)]
        if not rows:
            log(f"목록 {page}쪽에서 글을 못 찾음 (주소·구조 변경 확인 필요): {url}")
            break
        posts.extend(rows)
        time.sleep(1)

    new_count = 0
    for post_id, title in posts:
        if post_id in cache or not wanted(title, keywords):
            continue
        try:
            body = fetch(f"{BASE}/board.php?mode=view&b_id=tent&id={post_id}")
        except Exception as e:
            log(f"id={post_id} {title!r} 상세 요청 실패: {type(e).__name__}: {e}")
            continue
        m = MAGNET_RE.search(body)
        if not m:
            log(f"id={post_id} {title!r} 마그넷 없음, 건너뜀")
            continue
        reg = REGDATE_RE.search(body)
        pub = (
            datetime.strptime(reg.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
            if reg else datetime.now(KST)
        )
        cache[post_id] = {"title": title, "btih": m.group(1).lower(), "pub": pub.isoformat()}
        new_count += 1
        log(f"신규 id={post_id} {title} (등록 {pub.strftime('%m-%d %H:%M')})")
        time.sleep(1)

    cutoff = datetime.now(KST) - timedelta(days=KEEP_DAYS)
    cache = {k: v for k, v in cache.items() if datetime.fromisoformat(v["pub"]) >= cutoff}

    fg = FeedGenerator()
    fg.title("티프리카 예능 720p-NEXT")
    fg.link(href=f"{BASE}/board.php?mode=list&b_id=tent", rel="alternate")
    fg.description("bt4g_keywords.txt 키워드와 맞는 티프리카 예능 게시판 글")
    # feedgen은 add_entry를 앞에 끼워 넣으므로 오래된 것부터 넣어야 최신이 위로 감
    for post_id, v in sorted(cache.items(), key=lambda kv: kv[1]["pub"]):
        fe = fg.add_entry()
        fe.guid(f"tfreeca-tent-{post_id}", permalink=False)
        fe.title(v["title"])
        fe.link(href=f"magnet:?xt=urn:btih:{v['btih']}&dn={urllib.request.quote(v['title'])}")
        fe.description(v["title"])
        fe.pubDate(datetime.fromisoformat(v["pub"]))

    tmp = RSS_PATH + ".tmp"
    with open(tmp, "wb") as f:
        f.write(fg.rss_str(pretty=True))
    os.replace(tmp, RSS_PATH)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CACHE_PATH)

    log(f"RSS 업데이트 완료: 목록 {len(posts)}개 확인, 신규 {new_count}개, 전체 {len(cache)}개")
    print(f"{ts()} RSS 업데이트 완료: 신규={new_count}개 전체={len(cache)}개")


if __name__ == "__main__":
    main()
