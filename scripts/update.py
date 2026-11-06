#!/usr/bin/env python3
"""서동언니 릴스 데이터 갱신.

  python scripts/update.py --source graph     # Instagram Graph API (IG_ACCESS_TOKEN)
  python scripts/update.py --source windsor   # Windsor.ai REST (WINDSOR_API_KEY)
  python scripts/update.py --source none      # 수집 없이 재분류만 (keywords/overrides 수정 후)
  python scripts/update.py --source none --csv review.csv   # 검수용 분류표

순서: 새 게시물 수집 → data/raw.json 병합 → 키워드 분류 → overrides 적용
      → 썸네일 저장(images/) → data/reels.json 기록.
reels.json이 바뀌었으면 GITHUB_OUTPUT에 changed=true를 남긴다.
"""
import argparse, csv, json, os, re, sys, urllib.parse, urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
IMAGES = ROOT / "images"
START = "2024-10-01"
IG_USER_ID = os.environ.get("IG_USER_ID", "17841453924057893")
GRAPH = "https://graph.facebook.com/v21.0"


def load(path, default):
    return json.loads(path.read_text("utf-8")) if path.exists() else default


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "seodong-reels-updater"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


# ---------- 수집 ----------
def fetch_graph(since):
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not token:
        sys.exit("IG_ACCESS_TOKEN 환경변수가 없습니다.")
    fields = "id,caption,media_type,media_product_type,permalink,timestamp,thumbnail_url"
    url = f"{GRAPH}/{IG_USER_ID}/media?" + urllib.parse.urlencode(
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
            if m.get("media_product_type") == "REELS":
                out.append({"id": m["id"], "date": d, "permalink": m["permalink"],
                            "caption": m.get("caption", ""), "thumbnail_url": m.get("thumbnail_url")})
        url = None if stop else page.get("paging", {}).get("next")
    return out


def fetch_windsor(since):
    key = os.environ.get("WINDSOR_API_KEY")
    if not key:
        sys.exit("WINDSOR_API_KEY 환경변수가 없습니다.")
    fields = "date,media_id,media_caption,media_permalink,media_product_type,media_thumbnail_url"
    url = "https://connectors.windsor.ai/instagram?" + urllib.parse.urlencode({
        "api_key": key, "fields": fields, "date_from": since, "date_to": date.today().isoformat(),
        "select_accounts": IG_USER_ID})
    rows = get_json(url).get("data", [])
    return [{"id": r["media_id"], "date": r["date"][:10], "permalink": r["media_permalink"],
             "caption": r.get("media_caption") or "", "thumbnail_url": r.get("media_thumbnail_url")}
            for r in rows if r.get("media_product_type") == "REELS" and r["date"][:10] >= START]


# ---------- 분류 ----------
def norm(s):
    return re.sub(r"\s+", "", s)


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


def match(text, table):
    t = norm(text)
    return [name for name, words in table.items() if any(norm(w) in t for w in words)]


def classify(item, kw):
    text = clean_caption(item["caption"], kw)
    regions = match(text, kw["regions"])
    types = match(text, kw["types"])
    goods = match(text, kw["goods"])
    gb = kw["groupbuy"]
    t = norm(text)
    is_gb = any(w in t for w in gb["strong"]) or (
        any(w in t for w in gb["weak"]) and any(w in t for w in gb["weak_needs_any"]))
    if is_gb:
        category = "공구"
    elif types:
        category = "장소"
    elif goods:
        category = "용품"
    else:
        category = "일상"
    tags = {"region": regions if category == "장소" else [],
            "type": types if category == "장소" else [],
            "goods": goods if category in ("용품", "공구") else [],
            "category": category}
    ad = ad_label(item["caption"], kw)
    if ad:
        tags["ad"] = ad
    return tags


def apply_override(reel, ov):
    if not ov:
        return reel
    for k in ("title", "date", "hide"):
        if k in ov:
            reel[k] = ov[k]
    for k, v in ov.get("tags", {}).items():
        if v is None:
            reel["tags"].pop(k, None)
        else:
            reel["tags"][k] = v
    return reel


# ---------- 썸네일 ----------
def save_thumb(item):
    path = IMAGES / f"{item['id']}.jpg"
    if path.exists():
        return f"images/{path.name}"
    url = item.get("thumbnail_url")
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        IMAGES.mkdir(exist_ok=True)
        path.write_bytes(data)
        return f"images/{path.name}"
    except Exception as e:  # 만료된 URL 등: 카드에서 대체 이미지 사용
        print(f"썸네일 실패 {item['id']}: {e}", file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["graph", "windsor", "none"], default="graph")
    ap.add_argument("--full", action="store_true", help="2024-10-01부터 전부 다시 받기")
    ap.add_argument("--csv", help="검수용 분류표 CSV 경로")
    args = ap.parse_args()

    kw = load(DATA / "keywords.json", {})
    overrides = load(DATA / "overrides.json", {})
    raw = {r["id"]: r for r in load(DATA / "raw.json", [])}

    if args.source != "none":
        last = max((r["date"] for r in raw.values()), default=START)
        # 하루 겹쳐서 받아 시간대 경계 누락을 막는다
        since = START if args.full else max(START, (date.fromisoformat(last) - timedelta(days=1)).isoformat())
        new = fetch_graph(since) if args.source == "graph" else fetch_windsor(since)
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
                "thumb": save_thumb(item), "tags": classify(item, kw)}
        reel = apply_override(reel, overrides.get(item["id"]))
        if not reel.pop("hide", False):
            reels.append(reel)

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
    if gh := os.environ.get("GITHUB_OUTPUT"):
        with open(gh, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:  # 엑셀에서 한글 깨짐 방지
            w = csv.writer(f)
            w.writerow(["날짜", "캡션 첫 줄", "구분", "지역", "유형", "용품", "광고표시", "링크", "id"])
            for r in reels:
                t = r["tags"]
                w.writerow([r["date"], r["title"], t["category"], ", ".join(t.get("region", [])),
                            ", ".join(t.get("type", [])), ", ".join(t.get("goods", [])),
                            t.get("ad", ""), r["permalink"], r["id"]])
        print(f"분류표: {args.csv}")


if __name__ == "__main__":
    main()
