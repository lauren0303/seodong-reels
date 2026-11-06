# 서동언니 릴스 검색

@seodong_love 릴스(2024-10-01~)를 키워드로 찾는 정적 사이트. 매일 오전 7시(KST)에 GitHub Actions가 새 릴스를 반영합니다.

## 파일
| 경로 | 역할 |
|---|---|
| `index.html` | 사이트 (안내 메뉴 + 릴스 검색) |
| `data/reels.json` | 사이트가 읽는 최종 목록 (자동 생성 — 직접 고치지 마세요) |
| `data/raw.json` | 인스타에서 받은 원본 캡션 보관 |
| `data/keywords.json` | 지역·유형·용품 분류 단어와 검색 동의어 |
| `data/overrides.json` | 사람이 고치는 분류 (자동 분류보다 우선) |
| `images/` | 썸네일 (인스타 URL은 만료되므로 내려받아 저장) |
| `review.csv` | 검수용 분류표 (엑셀에서 열기) |
| `scripts/update.py` | 수집 → 분류 → overrides → 썸네일 → reels.json |
| `.github/workflows/update-reels.yml` | 매일 자동 실행 |

## 처음 설정
1. GitHub에 새 저장소를 만들고 이 폴더를 올립니다.
2. **Settings → Pages**: Source를 `Deploy from a branch`, 브랜치 `main` / `/(root)`로 지정.
3. **Settings → Secrets and variables → Actions → Secrets**에 추가:
   - `IG_ACCESS_TOKEN`: 장기 토큰(60일)
   - `FB_APP_ID`, `FB_APP_SECRET`: 토큰 자동 갱신용 (Meta 앱 정보)
   - `GH_PAT`: 갱신된 토큰을 Secret에 다시 저장하기 위한 개인 토큰 (fine-grained, 이 저장소의 *Secrets: Read and write* 권한)
   - Windsor.ai로 받으려면 대신 `WINDSOR_API_KEY`를 넣고, **Variables**에 `DATA_SOURCE` = `windsor`
4. **Actions → 릴스 업데이트 → Run workflow**에서 `full`을 체크해 한 번 실행 → 전체 릴스와 썸네일이 채워집니다.
5. 생성된 `review.csv`를 열어 분류를 검수하고, 틀린 것은 `data/overrides.json`에서 고칩니다.

## 분류 고치기
`data/overrides.json`에 릴스 id(review.csv 마지막 열)를 키로 적습니다.
```json
{
  "18067442830826850": { "tags": { "region": ["경주"], "type": ["숙소", "독채", "풀빌라"] } },
  "18465571624037595": { "hide": true }
}
```
고친 뒤 로컬에서 확인하려면:
```
python3 scripts/update.py --source none --csv review.csv
python3 -m http.server 8765    # http://localhost:8765
```
캡션에 새 지역·용품이 자주 나오면 `data/keywords.json`에 단어를 추가하는 편이 overrides보다 낫습니다.

## 분류 규칙 요약
- 캡션 + 해시태그만 봅니다. 매번 붙는 "…궁금하다면 @seodong_love 팔로우" 문구는 제외.
- 구분: `공구`(공구·공동구매, 또는 오픈/마감 + 구매·주문) → `장소`(장소 유형이 하나라도 있으면) → `용품` → 어디에도 안 맞으면 `일상`.
- 독채·풀빌라는 숙소로도 잡힙니다.
- 캡션 맨 앞/뒤에 `#광고 #협찬 #제작지원 #숙소제공 …` 표시가 있으면 그 문구 그대로 카드에 표시.
- 캡션에 없는 정보(주차, 무게 제한 등)는 만들어 넣지 않습니다.

## 실패 알림
업데이트가 실패하면 저장소에 "릴스 업데이트 실패" 이슈가 생기고, GitHub이 기본으로 메일도 보냅니다. 대개 토큰 만료이니 새 토큰을 `IG_ACCESS_TOKEN`에 넣고 다시 실행하세요.
