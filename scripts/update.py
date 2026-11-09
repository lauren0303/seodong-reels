#!/usr/bin/env python3
"""서동언니 릴스 데이터 갱신.

  python scripts/update.py --source graph     # Instagram Graph API (IG_ACCESS_TOKEN)
  python scripts/update.py --source windsor   # Windsor.ai REST (WINDSOR_API_KEY)
  python scripts/update.py --refresh-thumbs   # 최근 3개월 다시 조회 + 바뀐 썸네일 반영 (주 1회)
  python scripts/update.py --source none      # 수집 없이 재분류만 (keywords/overrides 수정 후)
  python scripts/update.py --source none --csv review.csv   # 검수용 분류표

순서: 새 게시물 수집 → data/raw.json 병합 → 키워드 분류 → overrides 적용
      → 썸네일 저장(images/) → data/reels.json 기록.
reels.json이 바뀌었으면 GITHUB_OUTPUT에 changed=true를 남긴다.
"""
import argparse, csv, json, os, re, sys, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
IMAGES = ROOT / "images"
START = "2024-10-01"
REFRESH_DAYS = 90  # --refresh-thumbs 때 썸네일을 다시 확인할 기간(최근 3개월)
IG_USER_ID = os.environ.get("IG_USER_ID", "17841453924057893")
GRAPH = "https://graph.facebook.com/v21.0"      # 페이스북 로그인 토큰(EAA…)
IG_GRAPH = "https://graph.instagram.com/v21.0"  # 인스타 로그인 토큰(IG…) — 페이스북 페이지 없이 무료


def load(path, default):
    return json.loads(path.read_text("utf-8")) if path.exists() else default


def get_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "seodong-reels-updater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # 오류 본문만 보여 준다 (주소에 키가 들어 있으므로 URL은 찍지 않음)
        sys.exit(f"요청 실패 HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")


# ---------- 수집 ----------
def fetch_graph(since):
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not token:
        sys.exit("IG_ACCESS_TOKEN 환경변수가 없습니다.")
    fields = "id,caption,media_type,media_product_type,permalink,timestamp,thumbnail_url"
    base = f"{IG_GRAPH}/me" if token.startswith("IG") else f"{GRAPH}/{IG_USER_ID}"
    url = f"{base}/media?" + urllib.parse.urlencode(
        {"fields": fields, "limit": 100, "access_token": token})
    out = []
    while url:
        page = get_json(url)
        if "error" in page:
            sys.exit(f"Graph API 오류: {page['error'].get('message')}")
        stop = False
        for m in page.get("data", []):
            d = m["timestamp"][:10]
            if d < since:
                stop = True  # 최신순이므로 여기부터는 이미 받은 기간
                break
            if m.get("media_product_type") == "REELS" and d >= START:
                out.append({"id": m["id"], "date": d, "permalink": m["permalink"],
                            "caption": m.get("caption", ""), "thumbnail_url": m.get("thumbnail_url")})
        url = None if stop else page.get("paging", {}).get("next")
    return out


def fetch_windsor(since):
    key = os.environ.get("WINDSOR_API_KEY")
    if not key:
        sys.exit("WINDSOR_API_KEY 환경변수가 없습니다.")
    fields = "date,media_id,media_caption,media_permalink,media_product_type,media_thumbnail_url"
    rows, start, today = [], date.fromisoformat(since), date.today()
    # 기간이 길면 응답이 커서 느리므로 한 달씩 나눠 받는다
    while start <= today:
        nxt = (start.replace(day=1) + timedelta(days=32)).replace(day=1)
        end = min(nxt - timedelta(days=1), today)
        url = "https://connectors.windsor.ai/instagram?" + urllib.parse.urlencode({
            "api_key": key, "fields": fields, "date_from": start.isoformat(),
            "date_to": end.isoformat(), "select_accounts": IG_USER_ID})
        part = get_json(url, timeout=300).get("data", [])
        print(f"  {start}~{end}: {len(part)}행", flush=True)
        rows += part
        start = nxt
    return [{"id": r["media_id"], "date": r["date"][:10], "permalink": r["media_permalink"],
             "caption": r.get("media_caption") or "", "thumbnail_url": r.get("media_thumbnail_url")}
            for r in rows if r.get("media_product_type") == "REELS" and r["date"][:10] >= START]


# ---------- 분류 ----------
def norm(s):
    return re.sub(r"\s+", "", s)


def flat(s):
    # 띄어쓰기는 살려서 비교한다 (붙이면 "자세가 평소"가 "가평"으로 잡힘)
    return re.sub(r"\s+", " ", s).lower()


def clean_caption(caption, kw):
    # "…가 궁금하다면 / @seodong_love 팔로우" 같은 매번 붙는 문구는 분류에서 뺀다
    lines = caption.splitlines()
    drop = set()
    for i, l in enumerate(lines):
        if any(w in l for w in kw["ignore_lines_with"]):
            drop.add(i)
            if i > 0 and lines[i - 1].rstrip().endswith("면"):
                drop.add(i - 1)
    return "\n".join(l for i, l in enumerate(lines) if i not in drop)


def title_of(caption):
    first = next((l.strip() for l in caption.splitlines() if l.strip()), "")
    first = re.sub(r"^(\(공유\)\s*)", "", first)
    first = re.sub(r"(^|\s)#\S+", " ", first)  # 앞뒤 해시태그(#광고 등) 제거
    return re.sub(r"\s+", " ", first).strip() or "(제목 없음)"


def ad_label(caption, kw):
    for label in kw["ad_labels"]:
        if re.search(rf"[#\[(]\s*{re.escape(label)}(?![가-힣])", caption):
            return label
    return None


def blank(text, words):
    for w in sorted(words, key=len, reverse=True):
        text = text.replace(flat(w), " ")
    return text


def match(text, table, ignore=()):
    """사전 단어를 긴 것부터 찾고, 찾은 자리는 지워서 '남양주' 안의 '양주'처럼 겹쳐 잡히지 않게 한다."""
    text = blank(flat(text), ignore)
    pairs = sorted(((flat(w), name) for name, words in table.items() for w in words),
                   key=lambda p: len(p[0]), reverse=True)
    found = []
    for w, name in pairs:
        if w in text:
            text = text.replace(w, " ")
            if name not in found:
                found.append(name)
    order = list(table)
    return sorted(found, key=order.index)


def pin_lines(caption, kw):
    return [l for l in caption.splitlines()
            if "📍" in l and not any(w in l for w in kw.get("pin_ignore", []))
            and len(l.replace("📍", "").strip()) > 1]


def classify(item, kw):
    text = clean_caption(item["caption"], kw)
    title = title_of(item["caption"])
    pins = pin_lines(item["caption"], kw)
    strong = "\n".join([title, *pins])  # 제목과 📍 줄이 그 릴스의 주제
    ign = kw.get("ignore_words", [])

    types = match(strong, kw["types"], ign)
    regions = match(strong, kw["regions"], ign)
    goods_title = match(title, kw["goods"], ign)
    goods_body = match(text, kw["goods"], ign)

    gb = kw["groupbuy"]
    t, nt = flat(text), norm(title)
    mentions = any(w in t for w in gb["strong"])
    # 공구 글: 제목에 공구가 있거나, 공구가·일정 같은 공구 안내가 있거나,
    # 공구 언급만 있고 장소 내용은 없을 때. (여행 릴스 끝의 "공구 예정" 홍보는 장소로 둔다)
    is_gb = (any(w in nt for w in gb["strong"])
             or any(flat(w) in t for w in gb["details"])
             or (mentions and not types and not pins))
    if is_gb:
        category = "공구"
    elif types or pins:
        category = "장소"
    elif goods_title:
        category = "용품"
    else:
        body_types = match(text, kw["types"], ign)
        if body_types and not goods_body:
            category, types = "장소", body_types
        elif goods_body:
            category = "용품"
        else:
            category = "일상"
    info = [w for w in kw.get("info_words", []) if w in flat(strong + " " + text)]
    if info and category in ("용품", "일상"):
        category = "정보"  # 레시피 같은 정보성 릴스
    if category == "장소":
        if not types:
            types = match(text, kw["types"], ign)
        if not regions:
            regions = match(text, kw["regions"], ign)
    goods = (goods_title or goods_body) if category in ("용품", "공구", "정보") else []
    if category != "장소":
        regions, types = [], []
    # 검색 키워드: 지역 + 캡션에 나온 동네 이름(잠실·묵호 등) + 종류 + 구분
    zone = blank(flat(strong if regions else text), ign)
    areas = [w for name in regions for w in kw["regions"].get(name, [])
             if w != name and flat(w) in zone]
    keywords = list(dict.fromkeys(regions + areas + types + goods + [category] + info
                                  + (["용품"] if category == "공구" else [])))
    tags = {"region": regions, "type": types, "goods": goods,
            "category": category, "keywords": keywords}
    ad = ad_label(item["caption"], kw)  # 카드 배지용 (검색 키워드에는 넣지 않음)
    if ad:
        tags["ad"] = ad
    return tags


SHORTCODE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def post_order(reel):
    """게시 순서. 릴스 주소의 코드(shortcode)는 올린 시각 순으로 커지므로 같은 날 안에서도 순서를 알 수 있다."""
    code = reel["permalink"].rstrip("/").split("/")[-1][:11]
    n = 0
    for ch in code:
        n = n * 64 + SHORTCODE.index(ch) if ch in SHORTCODE else n
    return (reel["date"], n)


def dedupe_key(caption):
    first = next((l for l in caption.splitlines() if l.strip()), "")
    first = re.sub(r"\((공구 마감|\+?\+?추가[^)]*|공유[^)]*)\)", "", first)
    return re.sub(r"[^가-힣a-zA-Z0-9]", "", first)[:25]


def drop_pilots(reels, days=3):
    """같은 첫 줄로 3일 안에 여러 번 올린 릴스(파일럿)는 가장 나중 것만 남긴다.
    overrides에 "keep": true가 있으면 묶음과 상관없이 남긴다."""
    groups = {}
    for r in reels:
        groups.setdefault(dedupe_key(r["caption"]), []).append(r)
    drop = set()
    for g in groups.values():
        g.sort(key=post_order)
        for a, b in zip(g, g[1:]):
            if (date.fromisoformat(b["date"]) - date.fromisoformat(a["date"])).days <= days and not a.get("keep"):
                drop.add(a["id"])  # 3일 안에 같은 글이 또 올라왔으면 앞의 것은 파일럿
    return [r for r in reels if r["id"] not in drop], len(drop)


def add_nationwide(tags, n=3):
    """지역이 3곳 이상인 모음 릴스는 '전국'으로도 찾히게 한다."""
    regions = [r for r in tags.get("region", []) if r != "전국"]
    if len(regions) >= n and "전국" not in tags.get("region", []):
        tags["region"] = ["전국"] + tags["region"]
        kws = tags.get("keywords")
        if kws is not None and "전국" not in kws:
            tags["keywords"] = ["전국"] + kws


def apply_override(reel, ov):
    if not ov:
        return reel
    for k in ("title", "date", "hide", "keep"):
        if k in ov:
            reel[k] = ov[k]
    for k, v in ov.get("tags", {}).items():
        if v is None:
            reel["tags"].pop(k, None)
        else:
            reel["tags"][k] = v
    return reel


# ---------- 썸네일 ----------
def thumb_key(url):
    """CDN 주소의 파일 이름. 서명(?뒤)은 매번 바뀌지만 파일 이름은 커버를 바꿀 때만 바뀐다."""
    return Path(urllib.parse.urlparse(url).path).name if url else None


def same_picture(a, b):
    """두 이미지가 눈으로 보기에 같은지. Pillow가 없으면 바이트가 같은지만 본다."""
    if a == b:
        return True
    try:
        from io import BytesIO
        from PIL import Image
    except ImportError:
        return False
    def sig(data):
        im = Image.open(BytesIO(data)).convert("L").resize((16, 20))
        px = list(im.getdata())
        avg = sum(px) / len(px)
        return [p > avg for p in px], px
    try:
        (ha, pa), (hb, pb) = sig(a), sig(b)
    except Exception:
        return False
    # 같은 커버를 다른 화질로 받은 경우는 밝기 패턴이 거의 그대로다
    diff_bits = sum(x != y for x, y in zip(ha, hb))
    diff_px = sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)
    return diff_bits <= 12 and diff_px <= 12


def save_thumb(item, refresh=False):
    """썸네일을 images/에 저장한다.
    refresh=True면 이미 있는 썸네일도 인스타의 현재 커버와 비교해, 바뀌었을 때만 덮어쓴다."""
    path = IMAGES / f"{item['id']}.jpg"
    rel = f"images/{path.name}"
    url = item.get("thumbnail_url")
    key = thumb_key(url)
    if path.exists():
        if not (refresh and url):
            return rel
        if key and key == item.get("thumb_key"):
            return rel  # 지난번과 같은 파일 — 다시 받을 필요 없음
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except Exception as e:  # 만료된 URL 등: 있던 썸네일은 그대로, 없으면 카드에서 대체 이미지
        print(f"썸네일 실패 {item['id']}: {e}", file=sys.stderr)
        return rel if path.exists() else None
    item["thumb_key"] = key
    if path.exists() and same_picture(path.read_bytes(), data):
        return rel
    if path.exists():
        print(f"썸네일 바뀜 {item['id']} {item.get('permalink', '')}")
    IMAGES.mkdir(exist_ok=True)
    path.write_bytes(data)
    return rel


# ---------- 공구 상태 ----------
PERIOD = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일(?:\s*\([^)]*\))?\s*[~\-–]\s*"
                    r"(?:(\d{1,2})\s*월\s*)?(\d{1,2})\s*일")
CLOSED = re.compile(r"조기\s*마감|마감되었|품절")


def parse_period(caption, posted):
    """'10월 13일(화) ~ 16일(금)' → (date(…13), date(…16)). 없으면 None."""
    m = PERIOD.search(caption)
    if not m:
        return None
    m1, d1, m2, d2 = int(m[1]), int(m[2]), int(m[3] or m[1]), int(m[4])
    y = posted.year + (1 if m1 < posted.month - 6 else 0)  # 12월에 올린 1월 공구
    try:
        start = date(y, m1, d1)
        end = date(y + (1 if m2 < m1 else 0), m2, d2)
    except ValueError:
        return None
    return start, end


def groupbuy_status(reels, today):
    """캡션의 공구 기간으로 '지금' 칸 상태를 정한다: active / upcoming / recent / none."""
    gb = [r for r in reels if r["tags"].get("category") == "공구" and r["date"] <= today.isoformat()]
    periods = {}
    for r in gb:
        posted = date.fromisoformat(r["date"])
        if (today - posted).days > 90:
            continue
        pr = parse_period(r["caption"], posted)
        if not pr:
            continue
        g = periods.setdefault(pr, {"reels": [], "closed": False})
        g["reels"].append(r)
        if CLOSED.search(r["caption"]):
            g["closed"] = True
    best = None
    for (start, end), g in periods.items():
        if g["closed"] or end < today:
            continue
        status = "active" if start <= today else "upcoming"
        cand = (0 if status == "active" else 1, start, status, end, g["reels"])
        if best is None or cand[:2] < best[:2]:
            best = cand
    if best:
        _, start, status, end, rs = best
        r = max(rs, key=lambda x: x["date"])  # 가장 최근에 올린 안내 릴스
        return {"status": status, "start": start.isoformat(), "end": end.isoformat(),
                "title": r["title"], "permalink": r["permalink"]}
    recent = [r for r in gb if (today - date.fromisoformat(r["date"])).days <= 14
              and not parse_period(r["caption"], date.fromisoformat(r["date"]))
              and not CLOSED.search(r["caption"])]
    if recent:
        r = max(recent, key=lambda x: x["date"])
        return {"status": "recent", "title": r["title"], "permalink": r["permalink"], "date": r["date"]}
    return {"status": "none"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["graph", "windsor", "none"], default="graph")
    ap.add_argument("--full", action="store_true", help="2024-10-01부터 전부 다시 받기")
    ap.add_argument("--refresh-thumbs", action="store_true",
                    help="최근 3개월 릴스를 다시 조회해 인스타에서 바꾼 썸네일(커버)을 반영")
    ap.add_argument("--csv", help="검수용 분류표 CSV 경로")
    args = ap.parse_args()

    kw = load(DATA / "keywords.json", {})
    overrides = load(DATA / "overrides.json", {})
    raw = {r["id"]: r for r in load(DATA / "raw.json", [])}

    if args.source != "none":
        last = max((r["date"] for r in raw.values()), default=START)
        # 하루 겹쳐서 받아 시간대 경계 누락을 막는다
        since = START if args.full else max(START, (date.fromisoformat(last) - timedelta(days=1)).isoformat())
        if args.refresh_thumbs and not args.full:  # 썸네일 확인은 최근 3개월 릴스만
            since = min(since, max(START, (date.today() - timedelta(days=REFRESH_DAYS)).isoformat()))
        new = fetch_graph(since) if args.source == "graph" else fetch_windsor(since)
        # 받는 곳이 바뀌어 id가 달라도 같은 릴스(같은 주소)는 기존 id로 묶는다
        by_link = {r["permalink"].rstrip("/"): k for k, r in raw.items()}
        for n in new:
            n["id"] = by_link.get(n["permalink"].rstrip("/"), n["id"])
        added = sum(1 for n in new if n["id"] not in raw)
        for n in new:
            raw[n["id"]] = {**raw.get(n["id"], {}), **n}
        print(f"{since} 이후 릴스 {len(new)}개 조회, 새 릴스 {added}개")

    reels = []
    for item in sorted(raw.values(), key=lambda r: (r["date"], r["id"]), reverse=True):
        if item["date"] < START:
            continue
        reel = {"id": item["id"], "permalink": item["permalink"], "date": item["date"],
                "title": title_of(item["caption"]), "caption": item["caption"],
                "thumb": save_thumb(item, refresh=args.refresh_thumbs), "tags": classify(item, kw)}
        reel = apply_override(reel, overrides.get(item["id"]))
        add_nationwide(reel["tags"])
        if not reel.pop("hide", False):
            reels.append(reel)
    reels, pilots = drop_pilots(reels)
    for r in reels:
        r.pop("keep", None)
    print(f"파일럿(중복) 릴스 {pilots}개 숨김")

    # 원본 보관(썸네일 URL은 만료되므로 저장하지 않음)
    raw_out = [{k: v for k, v in r.items() if k != "thumbnail_url"}
               for r in sorted(raw.values(), key=lambda r: r["date"], reverse=True)]
    (DATA / "raw.json").write_text(json.dumps(raw_out, ensure_ascii=False, indent=1) + "\n", "utf-8")

    out = DATA / "reels.json"
    new_text = json.dumps(reels, ensure_ascii=False, indent=1) + "\n"
    changed = not out.exists() or out.read_text("utf-8") != new_text
    if changed:
        out.write_text(new_text, "utf-8")
    print(f"reels.json: {len(reels)}개, {'변경됨' if changed else '변경 없음'}")
    today_kst = (datetime.now(timezone.utc) + timedelta(hours=9)).date()
    gb = groupbuy_status(reels, today_kst)
    (DATA / "groupbuy.json").write_text(json.dumps(gb, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"공구 상태: {gb['status']}")
    if gh := os.environ.get("GITHUB_OUTPUT"):
        with open(gh, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:  # 엑셀에서 한글 깨짐 방지
            w = csv.writer(f)
            w.writerow(["날짜", "캡션 첫 줄", "구분", "지역", "장소 유형", "제품 종류", "검색 키워드", "광고표시", "링크", "id"])
            for r in reels:
                t = r["tags"]
                w.writerow([r["date"], r["title"], t["category"], ", ".join(t.get("region", [])),
                            ", ".join(t.get("type", [])), ", ".join(t.get("goods", [])),
                            ", ".join(t.get("keywords", [])), t.get("ad", ""), r["permalink"], r["id"]])
        print(f"분류표: {args.csv}")


if __name__ == "__main__":
    main()
