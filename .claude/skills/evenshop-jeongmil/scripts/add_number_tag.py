# -*- coding: utf-8 -*-
"""완성본 mp4 «마지막 몇 초»에 번호 배지를 얹는다. (선택 기능)

왜 있는가
---------
제품 상세로 보내는 통로가 «번호»인 경우가 있다 — 프로필 링크 목록의 몇 번,
판매글 번호 같은 것. 캡션에만 적으면 시청자가 끝까지 안 읽으므로
**화면으로** 보여 준다.

**영상을 다시 굽지 않는다.** 이미 만든 완성본에 자막만 덧씌우므로 편당 10~20초면
끝나고, 번호를 렌더 전에 몰라도 된다 — 제품 등록 뒤 번호가 나오면 그때 얹는다.

쓰는 법
-------
    py scripts\\add_number_tag.py --mp4 "<완성본.mp4>" --num 709
    py scripts\\add_number_tag.py --pkg "<완성본 폴더>" --num 709      # 폴더에서 mp4 를 찾는다
    py scripts\\add_number_tag.py --pkg "..." --num 709 --preview      # 굽지 않고 그림만 본다

기본은 **원본을 덮어쓰지 않고** `<이름>_num709.mp4` 를 옆에 만든다.
`--inplace` 를 주면 원본 자리에 넣고 원본은 `.bak` 으로 남긴다.
"""
import argparse
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")
ASSET_FONTS = os.path.join(REPO, "assets", "fonts")


def _font(name):
    p = os.path.join(ASSET_FONTS, name)
    return p if os.path.exists(p) else os.path.join(FONT_DIR, name)


F_BLACK = _font("Paperlogy-9Black.ttf")

# ---- 배지 규격 ------------------------------------------------------------
# ★한 줄 · 글씨 수준 크기 · 배경은 옅게 — 크면 화면을 가린다.
#   그전 판은 3줄 · 번호 잉크 132 · 판 폭 900 · 알파 235 였다.
INK        = 52                     # 자막 글씨 수준 (쇼핑형 자막 잉크가 58)
BOX_R      = 22                     # 둥근 모서리
BOX_FILL   = (12, 12, 16, 140)      # ★반투명 — 뒤 화면이 비친다
BOX_EDGE   = None                   # 테두리 없앰 (있으면 그것만 도드라진다)
BOX_EDGE_W = 0
PAD_X, PAD_Y = 26, 16

C_WHITE  = (255, 255, 255, 255)
C_YELLOW = (255, 214, 0, 255)

BOX_BOTTOM = 1600                   # 판 아랫선 y
DEFAULT_DUR = 3.5                   # 3~4초


def _fit(text, path, ink_h):
    """글자 «잉크 높이»가 ink_h 가 되도록 폰트 크기를 맞춘다."""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    size = int(ink_h * 1.35)
    for _ in range(24):
        f = ImageFont.truetype(path, size)
        b = probe.textbbox((0, 0), text, font=f)
        h = b[3] - b[1]
        if h == 0:
            break
        if abs(h - ink_h) <= 1:
            break
        size = max(8, int(size * ink_h / h))
    return ImageFont.truetype(path, size), probe.textbbox((0, 0), text, font=ImageFont.truetype(path, size))


def _line(d, text, path, ink_h, top, fill, max_w=None):
    f, b = _fit(text, path, ink_h)
    w = b[2] - b[0]
    if max_w and w > max_w:
        f = ImageFont.truetype(path, int(f.size * max_w / w))
        b = d.textbbox((0, 0), text, font=f)
        w = b[2] - b[0]
    d.text((W / 2 - w / 2 - b[0], top - b[1]), text, font=f, fill=fill)
    return b[3] - b[1]


def make_badge(num, out, line1="댓글에", line3="남겨주세요", bottom=None):
    """번호 배지 PNG 한 장 (알파 살림).

    **한 줄**이다 — `댓글에 710번 남겨주세요`. 번호만 노랑, 나머지는 흰색이고,
    판은 글자 폭에 맞춰 줄어든다(고정 폭이 아니다)."""
    bottom = BOX_BOTTOM if bottom is None else bottom
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    parts = [(line1 + " ", C_WHITE), (f"{num}번", C_YELLOW), (" " + line3, C_WHITE)]
    parts = [(t, c) for t, c in parts if t.strip()]

    f, _ = _fit("댓글에 " + str(num) + "번 남겨주세요", F_BLACK, INK)
    widths = [d.textlength(t, font=f) for t, _ in parts]
    total = sum(widths)
    # 화면 폭을 넘으면 글자를 줄인다
    if total > W - 2 * PAD_X - 40:
        f = ImageFont.truetype(F_BLACK, int(f.size * (W - 2 * PAD_X - 40) / total))
        widths = [d.textlength(t, font=f) for t, _ in parts]
        total = sum(widths)

    probe = d.textbbox((0, 0), "댓글에 남겨주세요", font=f)
    ink_h = probe[3] - probe[1]
    box_h = ink_h + 2 * PAD_Y
    x0, x1 = W / 2 - total / 2 - PAD_X, W / 2 + total / 2 + PAD_X
    y0, y1 = bottom - box_h, bottom
    d.rounded_rectangle([x0, y0, x1, y1], radius=BOX_R,
                        fill=BOX_FILL, outline=BOX_EDGE, width=BOX_EDGE_W)

    x = W / 2 - total / 2
    top = y0 + PAD_Y - probe[1]
    for (t, c), w in zip(parts, widths):
        d.text((x, top), t, font=f, fill=c)
        x += w

    im.save(out)
    return out


def probe_dur(mp4):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", mp4],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def find_mp4(pkg):
    """완성본 폴더에서 «버전이 제일 높은» mp4 를 고른다 (편집본 폴더는 뺀다)."""
    best = None
    for root, dirs, files in os.walk(pkg):
        dirs[:] = [x for x in dirs if not x.endswith("_편집본")]
        for f in files:
            if f.lower().endswith(".mp4") and "_num" not in f:
                p = os.path.join(root, f)
                if best is None or f > os.path.basename(best):
                    best = p
        break                      # 맨 위 한 겹만 본다
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mp4")
    ap.add_argument("--pkg", help="완성본 폴더 (여기서 mp4 를 찾는다)")
    ap.add_argument("--num", required=True, help="제품번호 (숫자만)")
    ap.add_argument("--dur", type=float, default=DEFAULT_DUR, help="띄우는 시간 (기본 3.5초)")
    ap.add_argument("--bottom", type=int, default=BOX_BOTTOM, help="판 아랫선 y")
    ap.add_argument("--line1", default="댓글에")
    ap.add_argument("--line3", default="남겨주세요")
    ap.add_argument("--out", help="출력 mp4 (기본: 원본 옆에 _num<번호>.mp4)")
    ap.add_argument("--inplace", action="store_true", help="원본 자리에 넣는다 (원본은 .bak)")
    ap.add_argument("--preview", action="store_true", help="굽지 않고 배지 PNG 만 만든다")
    a = ap.parse_args()

    mp4 = a.mp4 or (find_mp4(a.pkg) if a.pkg else None)
    if not mp4 or not os.path.exists(mp4):
        raise SystemExit(f"mp4 를 못 찾았다: {a.mp4 or a.pkg}")

    base, ext = os.path.splitext(mp4)
    badge = base + f"_배지{a.num}.png"
    make_badge(a.num, badge, a.line1, a.line3, bottom=a.bottom)
    print(f"  배지: {badge}")
    if a.preview:
        print("  --preview 라 여기서 멈춘다. PNG 를 눈으로 보고 색·크기를 정하라.")
        return

    dur = probe_dur(mp4)
    start = max(0.0, dur - a.dur)
    out = a.out or (base + f"_num{a.num}" + ext)
    print(f"  영상 {dur:.2f}초 · 배지 {start:.2f}~{dur:.2f}초 ({a.dur}초)")

    cmd = ["ffmpeg", "-y", "-i", mp4, "-i", badge,
           "-filter_complex",
           f"[0:v][1:v]overlay=0:0:enable='between(t,{start:.3f},{dur:.3f})'[v]",
           "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-crf", "18", "-preset", "medium",
           "-pix_fmt", "yuv420p", "-c:a", "copy", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1500:], file=sys.stderr)
        raise SystemExit("ffmpeg 실패")

    if a.inplace:
        bak = base + ".bak" + ext
        if not os.path.exists(bak):
            os.replace(mp4, bak)
        else:
            os.remove(mp4)
        os.replace(out, mp4)
        out = mp4
        print(f"  원본은 {os.path.basename(bak)} 로 남겼다")

    os.remove(badge)
    print(f"완료: {out}")


if __name__ == "__main__":
    main()
