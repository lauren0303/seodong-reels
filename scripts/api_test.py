#!/usr/bin/env python3
"""인스타 토큰 점검 (읽기만 함, 아무것도 저장·커밋하지 않음).

  IG_ACCESS_TOKEN=… python scripts/api_test.py

1) 토큰으로 계정 정보가 읽히는지
2) 게시물 목록·좋아요·댓글 수가 읽히는지
3) 릴스 성과(조회수·도달·저장·공유 등)가 지표별로 읽히는지
4) 사이트 수집과 똑같이 최근 90일을 받아, 지금 데이터(Windsor로 받은 것)와 맞는지

저장소가 공개라 실행 기록도 공개된다. 그래서 도달·저장 같은 비공개 숫자는
'읽힘/안 읽힘'만 남기고 값은 찍지 않는다. 토큰도 찍지 않는다.
"""
import json, os, sys, urllib.error, urllib.parse, urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update  # noqa: E402  (fetch_graph, IG_GRAPH, GRAPH, IG_USER_ID)

TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
OK, BAD = "✅", "❌"
lines = []


def say(level, msg):
    print(f"::{level}::{msg}", flush=True)
    lines.append(msg)


def call(path, **params):
    params["access_token"] = TOKEN
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "seodong-reels-test"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8", "replace")).get("error", {})
            return None, f"HTTP {e.code} {err.get('type', '')}: {err.get('message', '')}"[:300]
        except Exception:
            return None, f"HTTP {e.code}"
    except Exception as e:
        return None, type(e).__name__


if not TOKEN:
    say("error", f"{BAD} IG_ACCESS_TOKEN이 비어 있어요. Secrets 이름이 정확히 IG_ACCESS_TOKEN인지 확인해 주세요.")
    sys.exit(1)

kind = "인스타 로그인 토큰(IG…)" if TOKEN.startswith("IG") else "페이스북 로그인 토큰(EAA…)" if TOKEN.startswith("EAA") else "알 수 없는 형식"
BASE = update.IG_GRAPH if TOKEN.startswith("IG") else update.GRAPH
ME = "me" if TOKEN.startswith("IG") else update.IG_USER_ID
say("notice", f"토큰 종류: {kind} (길이 {len(TOKEN)}자, 앞뒤 공백 {'있음 ⚠️' if TOKEN != TOKEN.strip() else '없음'})")

# 1) 계정
acc, err = call(ME, fields="username,media_count" + (",account_type" if ME == "me" else ",followers_count"))
if err:
    say("error", f"{BAD} 계정 정보 못 읽음 → {err}")
    sys.exit(1)
say("notice", f"{OK} 계정: @{acc.get('username')} · 게시물 {acc.get('media_count')}개" + (f" · 계정 종류 {acc['account_type']}" if acc.get("account_type") else ""))

# 2) 게시물 목록 + 좋아요·댓글 (공개 숫자라 값도 남김)
media, err = call(f"{ME}/media", limit=10,
                  fields="id,media_type,media_product_type,permalink,timestamp,like_count,comments_count")
if err:
    say("error", f"{BAD} 게시물 목록 못 읽음 → {err}")
    sys.exit(1)
items = media.get("data", [])
reels = [m for m in items if m.get("media_product_type") == "REELS"]
has_like = any("like_count" in m for m in items)
say("notice", f"{OK} 최근 게시물 {len(items)}개 읽힘 (릴스 {len(reels)}개)")
say("notice", f"{OK if has_like else BAD} 좋아요·댓글 수 " + ("읽힘" if has_like else "안 읽힘 (숨김 설정이거나 권한 부족)"))
for m in reels[:3]:
    say("notice", f"   {m['timestamp'][:10]} {m['permalink']} · 좋아요 {m.get('like_count', '?')} · 댓글 {m.get('comments_count', '?')}")

# 3) 릴스 성과 지표 (지표마다 따로 물어봐서 어떤 게 되는지 확인, 값은 비공개라 찍지 않음)
METRICS = ["views", "reach", "likes", "comments", "saved", "shares", "total_interactions",
           "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"]
if reels:
    rid = reels[0]["id"]
    got, failed = [], []
    for mt in METRICS:
        data, err = call(f"{rid}/insights", metric=mt)
        if data and data.get("data"):
            got.append(mt)
        else:
            failed.append(f"{mt}({err or '빈 응답'})")
    say("notice", f"{OK if got else BAD} 릴스 성과 지표 읽힘 {len(got)}/{len(METRICS)}: {', '.join(got) or '없음'}")
    for f in failed:
        say("warning", f"   안 읽힘: {f}")
else:
    say("warning", "최근 10개 중 릴스가 없어 성과 지표는 확인하지 못했어요.")

# 4) 사이트 수집과 같은 방식으로 최근 90일 받아서 지금 데이터와 비교
since = (date.today() - timedelta(days=90)).isoformat()
try:
    new = update.fetch_graph(since)
except SystemExit as e:
    say("error", f"{BAD} 사이트용 수집 실패 → {e}")
    sys.exit(1)
raw = json.loads((update.DATA / "raw.json").read_text("utf-8"))
have = {r["permalink"].rstrip("/") for r in raw if r["date"] >= since}
got_links = {n["permalink"].rstrip("/") for n in new}
same_id = sum(1 for n in new if n["id"] in {r["id"] for r in raw})
only_new, only_old = got_links - have, have - got_links
say("notice", f"{OK} 사이트용 수집 {since} 이후 {len(new)}개 (릴스 {sum(n['kind']=='reel' for n in new)}, 캐러셀 {sum(n['kind']=='carousel' for n in new)}) · 지금 데이터 {len(have)}개 · id까지 같은 것 {same_id}개")
say("notice", f"   토큰에만 있는 것 {len(only_new)}개, 지금 데이터에만 있는 것 {len(only_old)}개")
for link in sorted(only_new)[:5]:
    say("notice", f"   토큰에만: {link}")
for link in sorted(only_old)[:5]:
    say("notice", f"   지금 데이터에만: {link}")

if s := os.environ.get("GITHUB_STEP_SUMMARY"):
    Path(s).write_text("## 인스타 토큰 점검\n\n" + "\n".join(f"- {l}" for l in lines) + "\n", "utf-8")
