#!/usr/bin/env python3
"""Instagram Graph API 장기 토큰(60일) 갱신.

IG_ACCESS_TOKEN, FB_APP_ID, FB_APP_SECRET 환경변수로 새 장기 토큰을 받아 표준출력에 찍는다.
워크플로가 이 값을 `gh secret set IG_ACCESS_TOKEN`으로 다시 저장한다.
"""
import json, os, sys, urllib.parse, urllib.request

need = ["IG_ACCESS_TOKEN", "FB_APP_ID", "FB_APP_SECRET"]
missing = [k for k in need if not os.environ.get(k)]
if missing:
    sys.exit(f"환경변수 없음: {', '.join(missing)}")

url = "https://graph.facebook.com/v21.0/oauth/access_token?" + urllib.parse.urlencode({
    "grant_type": "fb_exchange_token",
    "client_id": os.environ["FB_APP_ID"],
    "client_secret": os.environ["FB_APP_SECRET"],
    "fb_exchange_token": os.environ["IG_ACCESS_TOKEN"],
})
try:
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.load(r)
except urllib.error.HTTPError as e:
    sys.exit(f"토큰 갱신 실패 (만료됐을 수 있음): {e.read().decode()[:300]}")

token = data.get("access_token")
if not token:
    sys.exit(f"토큰 갱신 실패: {data}")
print(token)
