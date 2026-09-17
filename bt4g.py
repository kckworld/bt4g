import feedparser
from feedgen.feed import FeedGenerator
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from email.utils import parsedate_to_datetime
import calendar
import re
import os
import socket
import time

socket.setdefaulttimeout(15)  # bt4gprx.com이 응답 없이 멈추면 run_all.sh 뒤 단계들까지 전부 밀리는 것 방지

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGDIR = os.path.join(SCRIPT_DIR, "logs")
os.makedirs(LOGDIR, exist_ok=True)
LOGFILE = os.path.join(LOGDIR, f"bt4g_{datetime.now().strftime('%Y%m%d')}.log")

def bt4g_ts():
    return f"[bt4g {datetime.now().strftime('%H:%M:%S')}]"

def log(msg):
    line = f"{bt4g_ts()} {msg}"
    with open(LOGFILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def extract_btih(link):
    m = re.search(r'btih:([a-fA-F0-9]+)', link)
    return m.group(1).lower() if m else link

def entry_pub_utc(entry):
    """feedparser가 이미 파싱해둔 published_parsed(UTC struct_time)를 재사용."""
    parsed = entry.get('published_parsed')
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)

def raw_pub_utc(published_str):
    """bt4gprx가 '-0000'(타임존 불명 표기)을 써서 feedparser 자체 파서가
    published_parsed를 못 채우는 경우가 있어, 원본 문자열을 직접 관대하게 파싱."""
    if not published_str:
        return None
    try:
        dt = parsedate_to_datetime(published_str)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

THREE_MONTHS_AGO = datetime.now(timezone.utc) - timedelta(days=90)

keyword_file = os.path.join(SCRIPT_DIR, "bt4g_keywords.txt")
with open(keyword_file, "r", encoding="utf-8") as f:
    all_keywords = [line.strip() for line in f if line.strip()]

# 현재 시간 기준 그룹 결정 (20분 단위: 0~19분=0, 20~39분=1, 40~59분=2)
# group_size는 전체 키워드 개수에 맞춰 매번 계산한다. 예전엔 10으로 고정돼
# 있어서 키워드가 30개를 넘으면 31번째부터는 어느 그룹에도 안 걸려 영원히
# 검색되지 않았음(웹에서 키워드를 자유롭게 추가/삭제하게 되면서 실제로 발생 가능).
import math
now = datetime.now()
slot = (now.minute // 20) % 3
group_size = max(1, math.ceil(len(all_keywords) / 3)) if all_keywords else 0
start = slot * group_size
keywords = all_keywords[start:start + group_size]
group_num = slot + 1

log(f"group={group_num} keywords={len(keywords)} ({start+1}~{start+len(keywords)})")

base_url = "https://bt4gprx.com/search?q={}&page=rss"

# 기존 merged_rss 로드 (있으면) → 없으면 새로 생성
xml_dir = os.path.join(SCRIPT_DIR, "xml")
os.makedirs(xml_dir, exist_ok=True)
rss_path = os.path.join(xml_dir, "bt4g_merged_rss.xml")

existing_hashes = set()  # btih 해시 기준 중복 체크
existing_entries = []

if os.path.exists(rss_path):
    try:
        parsed = feedparser.parse(rss_path)
        dropped = 0
        for entry in parsed.entries:
            if entry.get('link'):
                pub_utc = entry_pub_utc(entry)
                if pub_utc and pub_utc < THREE_MONTHS_AGO:
                    dropped += 1
                    continue
                if '720p' not in entry.get('title', '').lower():
                    dropped += 1
                    continue
                btih = extract_btih(entry.link)
                existing_hashes.add(btih)
                existing_entries.append(entry)
        log(f"기존 RSS 로드 완료: {len(existing_entries)}개 (3개월 초과 {dropped}개 정리)")
    except Exception as e:
        log(f"기존 RSS 로드 실패, 새로 생성: {e}")

fg = FeedGenerator()
fg.title("통합 BT4G 검색 RSS")
fg.link(href="https://bt4gprx.com", rel="alternate")
fg.description("키워드 기반 통합 RSS 피드")

# 기존 항목 먼저 추가
for entry in existing_entries:
    fe = fg.add_entry()
    fe.title(entry.get('title', ''))
    fe.link(href=entry.get('link', ''))
    fe.description(entry.get('description', entry.get('summary', '')))
    if entry.get('published'):
        fe.pubDate(entry.published)

new_count = 0
for keyword in keywords:
    url = base_url.format(quote(keyword))
    feed = feedparser.parse(url)
    count = len(feed.entries)
    if feed.bozo and count == 0:
        log(f"keyword={keyword!r} 요청/파싱 실패 가능성(bozo): {feed.get('bozo_exception')}")
    else:
        log(f"keyword={keyword!r} entries={count}")
    for entry in feed.entries:
        # 검색어가 2단어 이상(스페이스 2개 이상)이면 bt4g의 AND 검색이 깨져서
        # 쿼리에 720p를 못 붙이는 키워드들이 있음 → 결과를 받은 뒤 title로 직접 거름
        if '720p' not in entry.title.lower():
            continue

        # 오래된 재방송/모음 업로드가 검색에 계속 걸려서, 매 실행마다
        # "새 항목으로 추가됐다가 다음 로드 때 3개월 필터에 잘려나가는" 걸
        # 무한 반복하지 않도록 여기서도 미리 걸러낸다
        pub_utc = raw_pub_utc(entry.get('published'))
        if pub_utc and pub_utc < THREE_MONTHS_AGO:
            continue

        btih = extract_btih(entry.link)
        if btih in existing_hashes:
            continue
        existing_hashes.add(btih)

        desc = entry.get("description", "")
        split_desc = re.split(r'<br\s*/?>', desc, flags=re.IGNORECASE)
        size_str = f"[{split_desc[1].strip()}]" if len(split_desc) > 1 else ""

        fe = fg.add_entry()
        fe.title(f"{entry.title} {size_str}")
        fe.link(href=entry.link)
        fe.description(desc if desc else entry.title)
        pub_date = entry.get("published", datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000'))
        fe.pubDate(pub_date)
        new_count += 1
    time.sleep(2)

rss_str = fg.rss_str(pretty=True)
with open(rss_path, "w", encoding="utf-8") as f:
    f.write(rss_str.decode("utf-8"))

log(f"RSS 업데이트 완료: 그룹{group_num} 신규={new_count}개 전체={len(existing_hashes)}개")
print(f"{bt4g_ts()} RSS 업데이트 완료: 그룹{group_num} 신규={new_count}개")