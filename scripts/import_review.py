#!/usr/bin/env python3
"""검수한 키워드 확인표(엑셀)를 data/overrides.json에 반영한다.

  python3 scripts/import_review.py 확인표.xlsx

- '사이트 릴스' 시트에 남아 있는 행: 적힌 구분·지역·장소 유형·제품 종류·검색 키워드로 고정
- 시트에서 지운 릴스: 파일럿으로 보고 숨김(hide)
- 해변 → 바다, 광고 관련 단어는 검색 키워드에서 제외
- 공구는 용품 키워드도 함께, 레시피가 있으면 구분을 '정보'로
"""
import json, re, sys
from pathlib import Path
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

TYPES = ["맛집", "애견카페", "숙소", "바다", "관광지(산책)", "체험", "운동장", "동물병원", "애견용품점", "코스"]
CATS = ["장소", "용품", "공구", "정보", "일상"]
RENAME = {"해변": "바다", "평초": "평촌", "강화": "강화도"}
DROP = {"E247"}


def split(v, seps=r"[,·]"):
    out = []
    for t in re.split(seps, str(v or "")):
        t = t.strip()
        if t and t not in DROP:
            out.append(RENAME.get(t, t))
    return out


def parse_regions(v):
    """'서울(잠실), 인천(영종도)' → (['서울','인천'], ['잠실','영종도'])"""
    regions, areas = [], []
    for main, inner in re.findall(r"([^,()]+)(?:\(([^)]*)\)?)?", str(v or "").replace("홍대)", "홍대")):
        main = main.strip()
        if main and main not in DROP:
            regions.append(RENAME.get(main, main))
        areas += [a.strip() for a in (inner or "").split(",") if a.strip()]
    # "서울(합정, 홍대)"처럼 괄호 안 쉼표로 잘린 경우
    return regions, areas


def uniq(xs):
    seen, out = set(), []
    for x in xs:
        if x and x not in seen:
            seen.add(x); out.append(x)
    return out


def main(xlsx):
    kw = json.loads((DATA / "keywords.json").read_text("utf-8"))
    ad_words = set(kw["ad_labels"]) | {"AD", "A광고"}
    ov = json.loads((DATA / "overrides.json").read_text("utf-8"))
    reels = {r["id"]: r for r in json.loads((DATA / "reels.json").read_text("utf-8"))}

    ws = load_workbook(xlsx)["사이트 릴스"]
    head = [c.value for c in ws[1]]
    col = {name: head.index(name) for name in head if name}
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[col["id"]]]

    # 지역으로 볼 이름: 사전의 지역 + 엑셀 지역 칸에 적힌 이름
    region_names = set(RENAME.get(k, k) for k in kw["regions"])
    for r in rows:
        region_names.update(parse_regions(r[col["지역"]])[0])

    # 동네·별칭(잠실, 묵호, 영종도 …)은 대표 지역으로 묶고 키워드로 남긴다
    alias = {w: RENAME.get(k, k) for k, ws_ in kw["regions"].items() for w in ws_ if w != k}
    alias["영종도"] = "인천"
    # 제품 키워드로 볼 단어: 엑셀 제품 종류 칸에 한 번이라도 적힌 단어
    goods_vocab = set()
    for r in rows:
        for g in split(r[col["제품 종류"]]):
            goods_vocab.update(x for x in g.split() if x not in ("레시피", "정보"))

    kept = set()
    for r in rows:
        rid = str(r[col["id"]]); kept.add(rid)
        cat = str(r[col["구분"]] or "").strip() or "일상"
        regions, areas = parse_regions(r[col["지역"]])
        types_raw = split(r[col["장소 유형"]])
        goods_raw = split(r[col["제품 종류"]])
        words = split(r[col["검색 키워드 (태그)"]], r"[,·\s]+")

        extra = []
        types = [t for t in types_raw if t in TYPES]
        extra += [t for t in types_raw if t not in TYPES and t != "모음"]
        types += [w for w in words if w in TYPES]
        regions += [w for w in words if w in region_names and w != "전국"]
        for i, g in enumerate(regions):
            if g in alias:
                areas.append(g); regions[i] = alias[g]

        goods = []
        for g in goods_raw:
            if g == "레시피":
                extra.append(g)
            elif g == "정보":
                extra.append(g)
            else:
                goods += [x.strip() for x in g.split() if x.strip()]
        goods += [w for w in words if w in goods_vocab]
        if "레시피" in goods_raw or "레시피" in words:
            cat = "정보"  # 레시피는 정보로
        if cat == "공구":
            words.append("용품")  # 공구도 용품으로 찾히게

        words = [w for w in words if w not in ad_words and w not in ("광고",)]
        keywords = uniq(regions + areas + types + goods + [cat] + extra + words)
        keywords = [k for k in keywords if k not in ad_words]

        e = ov.setdefault(rid, {})
        e.pop("hide", None)
        e["keep"] = True  # 직접 남긴 릴스는 자동 파일럿 규칙에서 제외
        e["tags"] = {"category": cat if cat in CATS else "일상",
                     "region": uniq(regions), "type": uniq(types),
                     "goods": uniq(goods), "keywords": keywords}

    hidden = 0
    for rid in reels:
        if rid not in kept:
            e = ov.setdefault(rid, {})
            e.pop("keep", None); e.pop("tags", None)
            e["hide"] = True
            hidden += 1

    ov["_분류_수정"] = "검수 엑셀(서동언니_릴스_키워드_확인표) 반영: tags는 직접 고른 값이라 자동 분류보다 우선합니다. hide는 파일럿(엑셀에서 지운 릴스)."
    (DATA / "overrides.json").write_text(json.dumps(ov, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"반영 {len(kept)}개, 새로 숨김 {hidden}개")


if __name__ == "__main__":
    main(sys.argv[1])
