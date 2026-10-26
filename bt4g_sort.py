import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
XML_DIR = os.path.join(SCRIPT_DIR, "xml")

INPUT_FILE = os.path.join(XML_DIR, 'bt4g_merged_rss.xml')
OUTPUT_FILE = os.path.join(XML_DIR, 'bt4g_filtered_sorted_rss.xml')

THREE_MONTHS_AGO = datetime.now(timezone.utc) - timedelta(days=90)

def bt4g_ts():
    return f"[bt4g {datetime.now().strftime('%H:%M:%S')}]"

def parse_pubdate(pubdate_str):
    # 고정 포맷 strptime 대신 표준 RFC822 파서 사용: bt4gprx가 날짜 표기를
    # 조금 바꿔도(요일/타임존 표기 변형 등) 조용히 항목이 누락되는 것 방지
    try:
        dt = parsedate_to_datetime(pubdate_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def extract_btih(link):
    m = re.search(r'btih:([a-fA-F0-9]+)', link)
    return m.group(1).lower() if m else link

MAX_AIR_AGE_DAYS = 7
AIRDATE_RE = re.compile(r'\.(\d{6})\.720p')
TFREECA_CACHE = os.path.join(XML_DIR, 'tfreeca_items.json')


def tfreeca_hashes():
    """티프리카 피드로 이미 받은 토렌트. 받고 나면 qBittorrent 목록에서 지워지므로
    몇 시간 늦게 BT4G에 같은 해시가 나오면 다시 받게 된다 → 빼고 낸다."""
    try:
        with open(TFREECA_CACHE, encoding='utf-8') as f:
            return {v['btih'] for v in json.load(f).values() if not v.get('skip')}
    except (OSError, ValueError):
        return set()


def too_old_airdate(title):
    """'미운 우리 새끼.E509.260823.720p-NEXT'처럼 옛날 회차가 다시 올라온 것"""
    m = AIRDATE_RE.search(title)
    if not m:
        return False
    try:
        air = datetime.strptime(m.group(1), '%y%m%d')
    except ValueError:
        return False
    return datetime.now() - air > timedelta(days=MAX_AIR_AGE_DAYS)


def filter_and_sort_recent_items(input_path, output_path):
    tree = ET.parse(input_path)
    root = tree.getroot()

    channel = root.find('channel')
    items = channel.findall('item')

    seen_hashes = tfreeca_hashes()
    recent_items = []
    for item in items:
        pubdate_text = item.findtext('pubDate', default='')
        pubdate = parse_pubdate(pubdate_text)
        if pubdate and pubdate >= THREE_MONTHS_AGO:
            link = item.findtext('link', '')
            btih = extract_btih(link)
            if btih in seen_hashes or too_old_airdate(item.findtext('title', '')):
                continue
            seen_hashes.add(btih)
            recent_items.append((pubdate, item))

    recent_items.sort(key=lambda x: x[0], reverse=True)

    for item in items:
        channel.remove(item)

    for _, item in recent_items:
        channel.append(item)

    tree.write(output_path, encoding='utf-8', xml_declaration=True)
    print(f'{bt4g_ts()} 생성 완료: {output_path} ({len(recent_items)} 항목)')

if __name__ == '__main__':
    if not os.path.exists(INPUT_FILE):
        print(f'{bt4g_ts()} 입력 파일 없음: {INPUT_FILE}')
    else:
        filter_and_sort_recent_items(INPUT_FILE, OUTPUT_FILE)