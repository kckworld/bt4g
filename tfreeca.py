"""티프리카 예능·드라마 게시판 → RSS (2026-10-26)

BT4G는 DHT 검색이라 NEXT 릴이 방송 후 몇 시간 뒤에야 잡히고, 키워드를 한꺼번에
검색하면 응답이 끊긴다. 티프리카 게시판에는 바로 올라오므로 목록 1~2쪽만 읽어서
키워드와 맞는 글의 마그넷을 RSS로 만든다. qBittorrent 규칙이 이 RSS를 읽어 받는다.

- 예능(b_id=tent): bt4g_keywords.txt, 720p-NEXT, 방송일 7일 이내 → "예능" 규칙
- 드라마(b_id=tdrama): drama_keywords.txt, 회차마다 하나만 → "드라마" 규칙.
  한 줄에 `키워드 | 릴` (예: `연애박사 | Sniper`, `닥터X | 720p-NEXT`, 릴 여러 개는 쉼표).
  릴을 안 적으면 1080p WEB-DL MrHulk·Marco(NF 원본, dramaday와 같은 릴)
- 영화(b_id=tmovie): 거르지 않고 전부 RSS로만 만든다 (자동 다운로드 규칙은 아직 없음).
  영화만 목록 주소가 mode=lists (mode=list는 빈 목록)

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

BASE = os.environ.get("TFREECA_BASE", "https://www.tfreeca22.com").rstrip("/")
PAGES = 2
MAX_AIR_AGE_DAYS = 7    # 예능: 방송일이 이보다 오래된 글(재업로드)은 받지 않음
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
KST = timezone(timedelta(hours=9))

MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:([A-Za-z0-9]{32,40})")
REGDATE_RE = re.compile(r"등록일:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
AIRDATE_RE = re.compile(r"\.(\d{6})\.720p")
# '100일의 거짓말.E06.1080p...' / '100일의 거짓말. S01E05.NF...'
EPISODE_RE = re.compile(r"(?:^|[.\s])(?:S\d{1,2})?E(\d{1,4})(?=[.\s]|$)", re.I)


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
    # 띄어쓰기·기호 무시 (폴더 이름 "닥터X 하얀 마피아의 시대" = 글 제목 "닥터X - 하얀 마피아의 시대")
    return re.sub(r"[\W_]+", "", s).lower()


def load_keywords(path):
    """path가 None이면 키워드로 거르지 않는다(영화).
    bt4g_keywords.txt의 ' 720p'는 BT4G 검색용이라 떼고, 공백 없이 비교한다
    ('나는SOLO 720p' → '나는solo'가 '나는 SOLO.E276...'과 맞음)."""
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            words = [re.sub(r"\s*720p\s*$", "", line.strip(), flags=re.I) for line in f]
    except FileNotFoundError:
        return []
    return [normalize(w) for w in words if w.strip()]


def load_drama_keywords(path):
    """'키워드 | 릴1, 릴2' → [(키워드, [릴...])]. 릴이 없으면 빈 목록(기본 MrHulk·Marco)"""
    try:
        with open(path, encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        name, _, rel = line.partition("|")
        if name.strip():
            out.append((normalize(name), [r.strip().lower() for r in rel.split(",") if r.strip()]))
    return out


def matched_keyword(title, keywords):
    if keywords is None:
        return "*"
    t = normalize(title)
    return next((k for k in keywords if k in t), None)


def variety_release_ok(title):
    if "720p-next" not in title.lower():
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


def drama_release_ok(title, releases):
    t = title.lower()
    if re.search(r"av1|x265|hevc|h\.?265", t):
        return False
    if releases:
        return any(r in t for r in releases)
    return "1080p" in t and "web-dl" in t and re.search(r"mrhulk|marco", t) is not None


def bt4g_hashes():
    """BT4G가 먼저 잡아서 이미 받은 토렌트. 받고 나면 qBittorrent 목록에서 지워지므로
    같은 해시를 티프리카 피드에 또 내면 다시 받는다 (BT4G를 켰을 때만 해당)."""
    path = os.path.join(XML_DIR, "bt4g_merged_rss.xml")
    try:
        with open(path, encoding="utf-8") as f:
            return {h.lower() for h in re.findall(r"btih:([0-9A-Fa-f]{40})", f.read())}
    except OSError:
        return set()


BOARDS = [
    {
        "b_id": "tent", "name": "예능",
        "keywords": os.path.join(SCRIPT_DIR, "bt4g_keywords.txt"),
        "rss": os.path.join(XML_DIR, "tfreeca_rss.xml"),
        "cache": os.path.join(XML_DIR, "tfreeca_items.json"),  # bt4g_sort.py도 읽음
        "feed_title": "티프리카 예능 720p-NEXT",
        "release_ok": variety_release_ok,
        "keep_days": 14,
        "skip_hashes": bt4g_hashes,
        "one_per_episode": False,
    },
    {
        "b_id": "tdrama", "name": "드라마",
        "keywords": os.path.join(SCRIPT_DIR, "drama_keywords.txt"),
        "load_keywords": load_drama_keywords,
        "rss": os.path.join(XML_DIR, "tfreeca_drama_rss.xml"),
        "cache": os.path.join(XML_DIR, "tfreeca_drama_items.json"),
        "feed_title": "티프리카 드라마 1080p WEB-DL",
        "release_ok": drama_release_ok,
        # MrHulk와 Marco가 같은 회차를 따로 올리므로, 받은 회차를 오래 기억해 둔다
        "keep_days": 90,
        "skip_hashes": set,
        "one_per_episode": True,
    },
    {
        "b_id": "tmovie", "name": "영화",
        "list_mode": "lists",
        "keywords": None,
        "rss": os.path.join(XML_DIR, "tfreeca_movie_rss.xml"),
        "cache": os.path.join(XML_DIR, "tfreeca_movie_items.json"),
        "feed_title": "티프리카 영화",
        "release_ok": lambda title: True,
        "keep_days": 14,
        "skip_hashes": set,
        "one_per_episode": False,
    },
]


def load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def episode_key(keyword, title):
    m = EPISODE_RE.search(title)
    return f"{keyword}#{int(m.group(1))}" if m else None


def run_board(board):
    b_id = board["b_id"]
    keywords = board.get("load_keywords", load_keywords)(board["keywords"])
    cache = load_cache(board["cache"])  # 글 id → {title, btih, pub[, ep, skip]}
    if keywords is not None and not keywords:
        log(f"[{board['name']}] 키워드 없음, 건너뜀")
        return

    posts = []
    for page in range(1, PAGES + 1):
        url = f"{BASE}/board.php?mode={board.get('list_mode', 'list')}&b_id={b_id}&page={page}"
        try:
            body = fetch(url)
        except Exception as e:
            log(f"[{board['name']}] 목록 {page}쪽 요청 실패: {type(e).__name__}: {e}")
            break
        row_re = re.compile(
            rf'mode=view&b_id={b_id}&id=(\d+)&page=\d+" class="stitle\d">\s*(.*?)\s*</a>', re.S)
        rows = [(i, html.unescape(t).strip()) for i, t in row_re.findall(body)]
        if not rows:
            log(f"[{board['name']}] 목록 {page}쪽에서 글을 못 찾음 (주소·구조 변경 확인 필요): {url}")
            break
        posts.extend(rows)
        time.sleep(1)

    skip_hashes = board["skip_hashes"]()
    taken_eps = {v["ep"] for v in cache.values() if v.get("ep") and not v.get("skip")}
    new_count = 0
    # 목록은 최신 글이 위 → 오래된 글부터 봐야 같은 회차 중 먼저 올라온 릴을 받는다
    for post_id, title in reversed(posts):
        if post_id in cache:
            continue
        if board.get("load_keywords"):
            # 드라마: 키워드마다 받을 릴이 다르다
            t = normalize(title)
            hit = next(((k, rels) for k, rels in keywords if k in t), None)
            if not hit or not board["release_ok"](title, hit[1]):
                continue
            keyword = hit[0]
        else:
            keyword = matched_keyword(title, keywords)
            if not keyword or not board["release_ok"](title):
                continue
        ep = episode_key(keyword, title) if board["one_per_episode"] else None
        if ep and ep in taken_eps:
            continue
        try:
            body = fetch(f"{BASE}/board.php?mode=view&b_id={b_id}&id={post_id}")
        except Exception as e:
            log(f"[{board['name']}] id={post_id} {title!r} 상세 요청 실패: {type(e).__name__}: {e}")
            continue
        m = MAGNET_RE.search(body)
        if not m:
            log(f"[{board['name']}] id={post_id} {title!r} 마그넷 없음, 건너뜀")
            continue
        btih = m.group(1).lower()
        if btih in skip_hashes:
            # 캐시에는 넣어서(RSS에는 안 냄) 다음 실행 때 상세 페이지를 또 읽지 않게 한다
            cache[post_id] = {"title": title, "btih": btih,
                              "pub": datetime.now(KST).isoformat(), "skip": "bt4g"}
            log(f"[{board['name']}] id={post_id} {title} BT4G로 이미 받음, 건너뜀")
            continue
        reg = REGDATE_RE.search(body)
        pub = (
            datetime.strptime(reg.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
            if reg else datetime.now(KST)
        )
        # seen: 처음 본 시각. 등록일이 오래된 글(영화 재등록 등)도 바로 지우지 않아야
        # 다음 실행 때 상세 페이지를 또 읽지 않는다
        cache[post_id] = {"title": title, "btih": btih, "pub": pub.isoformat(),
                          "seen": datetime.now(KST).isoformat()}
        if ep:
            cache[post_id]["ep"] = ep
            taken_eps.add(ep)
        new_count += 1
        log(f"[{board['name']}] 신규 id={post_id} {title} (등록 {pub.strftime('%m-%d %H:%M')})")
        time.sleep(1)

    cutoff = datetime.now(KST) - timedelta(days=board["keep_days"])
    cache = {k: v for k, v in cache.items()
             if datetime.fromisoformat(v.get("seen", v["pub"])) >= cutoff}

    fg = FeedGenerator()
    fg.title(board["feed_title"])
    fg.link(href=f"{BASE}/board.php?mode=list&b_id={b_id}", rel="alternate")
    fg.description(f"{os.path.basename(board['keywords'])} 키워드와 맞는 티프리카 {board['name']} 게시판 글"
                   if board["keywords"] else f"티프리카 {board['name']} 게시판 최신 글")
    # feedgen은 add_entry를 앞에 끼워 넣으므로 오래된 것부터 넣어야 최신이 위로 감
    for post_id, v in sorted(cache.items(), key=lambda kv: kv[1]["pub"]):
        if v.get("skip"):
            continue
        fe = fg.add_entry()
        fe.guid(f"tfreeca-{b_id}-{post_id}", permalink=False)
        fe.title(v["title"])
        fe.link(href=f"magnet:?xt=urn:btih:{v['btih']}&dn={urllib.request.quote(v['title'])}")
        fe.description(v["title"])
        fe.pubDate(datetime.fromisoformat(v["pub"]))

    tmp = board["rss"] + ".tmp"
    with open(tmp, "wb") as f:
        f.write(fg.rss_str(pretty=True))
    os.replace(tmp, board["rss"])
    tmp = board["cache"] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    os.replace(tmp, board["cache"])

    log(f"[{board['name']}] RSS 업데이트 완료: 목록 {len(posts)}개 확인, 신규 {new_count}개, 전체 {len(cache)}개")
    print(f"{ts()} [{board['name']}] RSS 업데이트 완료: 신규={new_count}개 전체={len(cache)}개")


def main():
    for board in BOARDS:
        if not board.get("enabled", True):
            continue
        try:
            run_board(board)
        except Exception as e:
            log(f"[{board['name']}] 처리 중 오류: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
