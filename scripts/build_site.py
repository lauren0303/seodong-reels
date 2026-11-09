#!/usr/bin/env python3
"""사이트에 필요한 파일만 모아 배포 폴더를 만든다.

  python scripts/build_site.py _site

- index.html, data/reels.json, data/keywords.json
- 사이트에 보이는 릴스의 썸네일만, 가로 540px로 줄여서 (원본은 저장소에 그대로)
"""
import json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIDTH = 540


def main(out):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    (out / "images").mkdir()
    shutil.copy(ROOT / "index.html", out / "index.html")
    for name in ("reels.json", "keywords.json", "groupbuy.json"):
        if (ROOT / "data" / name).exists():
            shutil.copy(ROOT / "data" / name, out / "data" / name)
    (out / ".nojekyll").write_text("")

    try:
        from PIL import Image
    except ImportError:
        Image = None
        print("Pillow가 없어 썸네일을 줄이지 않고 복사합니다.")

    reels = json.loads((ROOT / "data" / "reels.json").read_text("utf-8"))
    before = after = 0
    for r in reels:
        thumb = r.get("thumb")
        src = ROOT / thumb if thumb else None
        if not src or not src.exists():
            continue
        dst = out / thumb
        before += src.stat().st_size
        if Image:
            with Image.open(src) as im:
                im = im.convert("RGB")
                if im.width > WIDTH:
                    im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
                im.save(dst, "JPEG", quality=80, optimize=True, progressive=True)
        else:
            shutil.copy(src, dst)
        after += dst.stat().st_size
    print(f"썸네일 {len(reels)}개: {before/1e6:.1f}MB → {after/1e6:.1f}MB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "_site")
