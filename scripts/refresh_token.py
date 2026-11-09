#!/usr/bin/env python3
"""인스타 장기 토큰(60일) 갱신 — 새 토큰을 표준출력에 찍는다.

- 인스타 로그인 토큰(IG…): IG_ACCESS_TOKEN만 있으면 됨 (앱 비밀번호 불필요)
- 페이스북 로그인 토큰(EAA…): FB_APP_ID, FB_APP_SECRET도 필요
워크플로가 이 값을 `gh secret set IG_ACCESS_TOKEN`으로 다시 저장한다.
"""
import json, os, sys, urllib.parse, urllib.request

token = os.environ.get("IG_ACCESS_TOKEN")
if not token:
    sys.exit("환경변수 없음: IG_ACCESS_TOKEN")

if token.startswith("IG"):
    url = "https://graph.instagram.com/refresh_access_token?" + urllib.parse.urlencode({
        "grant_type": "ig_refresh_token", "access_token": token})
else:
    missing = [k for k in ("FB_APP_ID", "FB_APP_SECRET") if not os.environ.get(k)]
    if missing:
        sys.exit(f"환경변수 없음: {', '.join(missing)}")
    url = "https://graph.facebook.com/v21.0/oauth/access_token?" + urllib.parse.urlencode({
        "grant_type": "fb_exchange_token", "client_id": os.environ["FB_APP_ID"],
        "client_secret": os.environ["FB_APP_SECRET"], "fb_exchange_token": token})
try:
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.load(r)
except urllib.error.HTTPError as e:
    sys.exit(f"토큰 갱신 실패 (만료됐을 수 있음): {e.read().decode()[:300]}")

new = data.get("access_token")
if not new:
    sys.exit("토큰 갱신 실패: 응답에 access_token이 없습니다.")
print(new)
