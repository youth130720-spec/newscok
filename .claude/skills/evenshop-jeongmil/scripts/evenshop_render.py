# -*- coding: utf-8 -*-
"""쇼핑형(이븐쇼핑 리뉴얼) 렌더러.

.claude/skills/algoshopping/reference/채널규격.md 의 실측값을 그대로 구현한다.
볼케이노 MCP 서버를 거치지 않고, Typecast 음성 API 만 직접 호출한다.

원칙 세 가지
------------
1. 소재는 **움직이는 영상 클립**이다. 정지 프레임 슬라이드쇼를 만들지 않는다.
2. 나레이션은 **Typecast 유료 음성**이다. 무료 TTS 로 대체하지 않는다.
3. 인트로 카드에도 **멘트가 깔린다.** 카드가 무음이면 첫 2초를 버리는 것이다.

쓰는 법
-------
    python tools\\algoshopping_render.py --work work\\<작업폴더>

작업 폴더에 plan.json 이 있어야 한다.

    {
      "slug": "paper-plate",
      "title": "종이접시 도마",
      "channel": "쇼핑형",
      "logo": "꿀템쇼핑",              // 헤더 워드마크. ★채널명을 넣지 않는다. 넉 자
      "hl1": "천재가 왜 게으른지",
      "hl2": "알수있는 제품",
      "post_title": "천재가 왜 게으른지 알수있는 제품?",   // = hl1 + hl2 + "?"
      "intro_line": "천재가 왜 게으른지 알수있는 제품",     // 생략하면 post_title 에서 ? 를 뗀다
      "metrics": "조회수 235만 | 댓글 697개",             // ★고정값. 편마다 바꾸지 않는다
      "intro_cuts": [                 // 카드 1.8초 안에서 컷을 2~4번 바꾼다
        {"src": "s00.mp4", "ss": 11.2},
        {"src": "s01.mp4", "ss": 4.0},
        {"src": "s02.mp4", "ss": 7.5}
      ],
      "blocks": [
        {"text": "지금 이 용도를 알 수 없는", "src": "s00.mp4", "ss": 2.4},
        {"text": "여러 겹의 네모난 양파 같은게", "src": "s01.mp4", "ss": 6.0},
        {"text": "바로 새 접시가 나온다는 거", "src": "s02.mp4", "ss": 1.5,
         "src2": "s03.mp4", "ss2": 9.0, "voice": "PUNCH", "sfx": "hit"},
        ...
      ]
    }

blocks[i].src / ss 가 있으면 거기서 새 컷이 시작된다. 없으면 앞 컷이 계속 흐른다.
blocks[i].src2 / ss2 를 주면 그 블록 **한가운데서 컷이 한 번 더 바뀐다** (cut_at 로
자리 조절). 원본은 컷 수가 자막 블록 수의 1.08~1.42배다.
blocks[i].voice 는 NARR(기본) 또는 PUNCH. blocks[i].sfx 는 SFX 표의 이름.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- 화면 규격
W, H = 1080, 1920
FPS = "30000/1001"

BODY_HEADER_H = 405          # 0 ~ 404   가짜 앱 헤더
CAP_Y, CAP_H = 405, 185      # 405 ~ 589 흰 자막 띠 (규격값)
# 자막 띠 영상 트랙은 libx264 가 짝수 높이를 요구해 404 에서 186px 로 굽고,
# 그 위에 헤더 판(0~404)을 다시 덮어 405 경계를 되살린다.
CAP_TRACK_Y, CAP_TRACK_H = 404, 186
BODY_VID_Y, BODY_VID_H = 590, 1220
INTRO_TOP_H = 730            # 0 ~ 729
INTRO_VID_Y, INTRO_VID_H = 730, 1080

C_HEADER = (0x42, 0x42, 0x42)
C_INTRO_BG = (0x20, 0x20, 0x20)
C_GRAY = (0x7E, 0x7E, 0x7E)
C_WHITE = (0xFF, 0xFF, 0xFF)
C_BLACK = (0x00, 0x00, 0x00)
C_CYAN = (0x00, 0xE5, 0xF5)
C_METRIC = (0xCC, 0xCC, 0xCC)   # 실측 #BDBBBC ~ #D7D5D4 (인코딩 편차)
C_LENS = (0xD4, 0x2A, 0x2A)

# --- 2026-08-22 레퍼런스 5편 실측 좌표 (전 편이 픽셀 단위로 같다)
#     ABjQ0YCZoes · gf25fMSZHO4 · 3RxLl0NeR2Q · kC8fkx1Ve3Q · Y2YXuAE4J00
LOGO_INK_H, LOGO_TOP, LOGO_W = 90, 31, 457     # 로고 y31~120, x311~767
TITLE_INK_H, TITLE_TOP = 63, 229               # 게시글 제목 y229~291 (5편 동일)
METRIC_INK_H, METRIC_TOP, METRIC_X = 35, 337, 68   # 지표줄 y337~371, x68~487
CAP_INK_H, CAP_TOP = 58, 456                   # 자막 y454~514
# 카드 HL 두 줄. 폭을 채우도록 키우고(HL_W), HL2 의 잉크 윗선을 y=394 에 고정한 뒤
# HL1 을 그 위에 HL_GAP 만큼 띄워 쌓는다. 실측 HL2 윗선 387·388·401·402 (평균 394),
# 줄 간격(HL1 아랫선→HL2 윗선) 12·14·15·23 (평균 16), 잉크 폭 918~988 (평균 950).
# 최근 두 편(2026-08-20·08-22)이 둘 다 401~402 라 평균보다 그쪽으로 붙였다.
HL_W, HL2_TOP, HL_GAP = 960, 399, 16
BOX_INK_H, BOX_TOP = 60, 598                   # 인트로 흰 박스 글자 y598~657
CARD_ICON_TOP = 50                             # 카드 햄버거 y50~125 (본편은 23~97)
C_CARD_ICON = (0x80, 0x80, 0x80)               # 카드 아이콘은 회색, 본편은 흰색
# 인트로 흰 띠(글로우) — 실측 밝기 곡선을 smoothstep 세 구간으로 옮긴 값
GLOW_Y0, GLOW_RISE_END, GLOW_FALL_START, GLOW_Y1 = 536, 596, 658, 727
GLOW_EDGE = 42

FONT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_FONTS = os.path.join(REPO, "assets", "fonts")


def _font(name):
    p = os.path.join(ASSET_FONTS, name)
    return p if os.path.exists(p) else os.path.join(FONT_DIR, name)


F_BLACK = _font("Paperlogy-9Black.ttf")       # 자막 · HL1 · HL2
F_EB = _font("Paperlogy-8ExtraBold.ttf")      # 게시글 제목 · 인트로 박스
F_LOGO = _font("Pretendard-ExtraBold.otf")    # 로고 · 지표 줄

# 글자가 화면 밖으로 나가지 않게 하는 최대 폭
# 실측: 카드 HL 929~988 / 게시글 제목 872~997 / 자막 476~774
MAX_HL_W, MAX_TITLE_W, MAX_CAP_W = 990, 1000, 800

# --- plain 껍데기 상단 헤드라인 (뇌전구 완성본 3편 실측을 405px 블록에 맞춘 값)
#     뇌전구 실측: 상단 여백 220 / 글자 높이 88 / 줄 간격 24 / 하단 여백 40  (블록 469px)
#     쇼핑형 블록은 405px 이라 상단 여백만 168 로 줄이고 나머지는 실측 그대로 쓴다.
PLAIN_TOP = 168        # HL1 글자 윗선
PLAIN_INK = 88         # 글자 높이 (두 줄 같음)
PLAIN_GAP = 24         # HL1 아랫선 ~ HL2 윗선
PLAIN_HL_W = 1028      # 뇌전구 실측 최대 폭 (x 26~1053)

# --- plain2 껍데기 (이븐형 2줄자막 · 2026-08-27)
#     검정 바탕 + 제목 2줄은 `plain` 그대로 두고 **자막만 shop2 처럼 2줄로 굴린다.**
#     사용자 지시: "이븐형는 자막이 한줄인데 활용정점형처럼 자막 2줄로 수정해주고
#     그걸 이븐형 2줄자막으로". 그러므로 바꾸는 것은 자막 띠 안쪽뿐이고, 헤더·영상 칸·여백
#     좌표는 `plain` 과 한 픽셀도 다르지 않다 (같은 plan 을 껍데기만 갈아 끼워 여러
#     판을 굽는 mk_variants 가 그대로 돌아가야 한다).
#     띠는 405~589(185px)이고 두 줄 잉크가 차지하는 높이는 58 + 76 = 134px 이라,
#     위 26 · 아래 24 로 나눠 넣는다.
#     ★잉크는 shop2 의 55 가 아니라 **한 줄짜리 `plain` 과 같은 58** 이다. shop2 는
#     같은 흰 헤더 안에 잉크 58 짜리 게시글 제목이 함께 있어서 자막을 그보다 작게
#     둔 것인데, `plain2` 의 띠에는 자막밖에 없다. 55 로 굽고 봤더니 띠에 견줘 글자가
#     작아 보여서 되돌렸다.
#     ★가로 한도도 `plain` 의 800 이 아니라 940 이다. 800 이면 열다섯 자 넘는 줄이
#     통째로 줄어들어 잉크 58 이 무너진다 (첫 시험판에서 실제로 그랬다).
P2_CAP_INK = 58        # 자막 글자 높이 — plain 한 줄짜리와 같다
P2_CAP_TOP1 = 431      # 윗줄 잉크 윗선 (아랫줄은 +P2_CAP_PITCH)
P2_CAP_PITCH = 76      # 줄 간격
P2_MAX_CAP_W = 940     # 이 폭을 넘으면 글자를 줄인다

# --- shop2 껍데기 (@ho_shop 활용정점 칼 카피 · reference/화면규격.md **2026-08-24 재실측**)
#     0~271 상단 바 + 흰 알약 / 272~643 흰 헤더 / 644~ 영상(높이 가변) / 그 아래 흰 여백
#     원본 5편의 프레임 14장씩을 픽셀로 훑어 뽑았다 (work/_hoshop_ref/shell3.py·shell4.py).
S2_BAR_H = 272
S2_HEAD_Y, S2_HEAD_H = 272, 372
S2_TOP_H = S2_HEAD_Y + S2_HEAD_H        # 644 — 오버레이 판 한 장의 높이
S2_VID_Y = 644
S2_PAD_H = H - S2_VID_Y                 # 1276 — 영상 칸 + 흰 여백을 합친 판
# ★영상 높이는 컷마다 다르다. 남의 영상에 구워진 자막을 «띠를 좁혀» 밀어내는 기법이라
#   실측 범위(888~1014)를 그대로 쓴다. 짝수여야 libx264 가 받는다.
S2_VID_HS = [1014, 988, 962, 936, 910, 888]
# 실측 원본의 «영상 아래 흰 여백»은 262~389px 이었다. 칸이 그보다 낮아 여백이 더
# 남으면 칸을 내려 위아래로 나눈다 — 안 그러면 화면이 위로 쏠려 아래가 텅 빈다.
S2_PAD_MAX = 389
C_S2_BAR = (0xE0, 0x39, 0x2E)           # 커머스 레드. 원본 #D44D40 보다 선명하게
C_S2_HEAD = (0xFF, 0xFF, 0xFF)
C_S2_PAD = (0xFD, 0xFD, 0xFD)           # 영상 아래 여백 — ★검정이 아니라 흰색이다
C_S2_DIV = (0x00, 0x00, 0x00)           # 구분선은 검정 2px
C_S2_METRIC = (0x6A, 0x65, 0x67)
C_S2_PILL_EDGE = (0xD1, 0xCC, 0xCB)
C_S2_PILL_BG = (0xFD, 0xFD, 0xFD)
# 알약 검색창 — 바 **아래쪽에 붙어** 있다 (위 여백 152 · 아래 여백 18)
S2_PILL = (202, 152, 877, 254)          # x0, y0, x1, y1
S2_LOGO_INK, S2_LOGO_TOP = 55, 176      # 워드마크 잉크 y176~230, 화면 가운데 정렬
# ★두 줄 워드마크 — 「가성 VS 진성」 시리즈 (2026-09-04 제작자 지시)
#   "제목을 가성VS진성 (위에 작게 쇼핑형) 기존 스타일은 변경 없이 상단바만 이렇게 고쳐서".
#   알약(y152~254) 안에 두 줄을 앉힌다 — 위 여백 11 · 줄 사이 11 · 아래 여백 12.
#   `plan.sublogo` 를 주면 이 두 줄 판으로 갈리고, 안 주면 기존 한 줄 그대로다.
S2_SUB_INK, S2_SUB_TOP = 22, 163        # 위 작은 줄 — 채널 이름
S2_LOGO2_INK, S2_LOGO2_TOP = 46, 196    # 아래 큰 줄 — 시리즈 이름. `*VS*` 만 빨강
S2_LENS_R, S2_LENS_CX, S2_LENS_CY = 30, 810, 203
S2_TITLE_INK, S2_TITLE_TOP, S2_TITLE_X = 58, 305, 62   # 게시글 제목 — ★좌측 정렬
S2_METRIC_INK, S2_METRIC_TOP, S2_METRIC_X = 27, 388, 73
S2_DIV_Y = 451
S2_CAP_INK, S2_CAP_TOP1, S2_CAP_PITCH = 55, 490, 72    # 2줄 롤링 자막 — 제목보다 작다
S2_MAX_CAP_W, S2_MAX_TITLE_W = 900, 996
# 인트로 카드 큰 제목 두 줄 — 원본 실측: 잉크 y402~490 · y520~608 (높이 88, 간격 30)
S2_CARD_HL_W = 1010                     # 폭은 여기까지 채운다
S2_CARD_MAX_INK = 92                    # ★높이 상한. 짧은 문구가 폭에 맞춰 커지는 것을 막는다
S2_CARD_TOP, S2_CARD_GAP = 400, 30      # 잉크 윗선 · 줄 사이
# ★강조 낱말 색. 흰 바탕 위에서는 시안(#00E5F5)이 밝기가 비슷해 묻힌다
#   (2026-08-24 사용자 지적 — "제목 색상이 눈에 안 들어옴"). 제작 지침서 3절의
#   «강조 단어만 색상 변경 (노랑/빨강)» 을 따라 노랑으로 가고, 검정 테두리를 두른다.
C_S2_HI = (0xFF, 0xD4, 0x00)
S2_CARD_ZOOM0 = 0.70                    # 제목이 이 크기에서 시작해 1.0 으로 커진다
S2_CARD_ZOOM_SEC = 0.55                 # 커지는 데 걸리는 시간

# --- shop3 껍데기 («활용정점 정밀형» · @ho_shop **30편 전수** 실측 2026-09-10)
#     shop2 와 좌표가 같다 — 상단 바 272 · 흰 헤더 372 · 영상 윗선 644 · 알약 x203~876 ·
#     구분선 451 · 제목 잉크 58/305 · 지표 27/388 · 자막 55/490/간격 72 는 30편에서
#     그대로 확인됐다(work/_hoshop_ref/fine30.py). **그러니 그 상수는 공유한다.**
#     갈라지는 것은 아래 넷뿐이다.
#
#     ① 상단 바 색 — 제작자가 주황으로 고르셨다 (2026-09-10). 활용정점형 의 빨강
#        `#E0392E` 과 한눈에 갈리게 하려는 것이고, 원본 `#D44D40` 과도 다르다.
#     ② 인트로 카드 글씨 — **흰 글씨 + 굵은 검정 테두리 + 그림자, 강조는 시안.**
#        shop2 는 검정 글씨 + 흰 테두리 + 노랑 강조인데, 그건 5편 표본으로 세운 뒤
#        「흰 바탕에서 시안이 묻힌다」는 이유로 노랑으로 바꾼 것이었다. 30편을 다시
#        보니 원본은 **글씨 자체가 흰색**이라 시안이 묻히지 않는다 (30/30편).
#     ③ 영상 칸 높이 사다리 — shop2 는 888~1014 여섯 칸뿐인데 실측은 **587~1276**
#        이다. 낮은 칸이 있어야 박힌 자막을 더 밀어낼 수 있고, 1276 은 «바닥까지
#        꽉 찬» 컷이다(30편 중 10편에 나온다).
#     ④ 아래 흰 여백 상한 — 실측 최대가 600 이다 (shop2 는 389 로 잡혀 있었다).
C_S3_BAR = (0xF2, 0x65, 0x22)           # 주황 — 2026-09-10 제작자 선택
C_S3_HI = (0x00, 0xFD, 0xFC)            # 인트로 강조 시안 (28편 표본 중앙값)
# 기본은 1014(원본의 압도적 다수가 1015). 아래로 26px 씩 내려가며 박힌 자막을 밀어낸다.
S3_VID_HS = [1014, 988, 962, 936, 910, 884, 858, 832, 806, 780,
             754, 728, 702, 676, 650, 624, 598]
S3_VID_FULL = 1276                      # «바닥까지 꽉 참» — plan 에서 vid_h 로 직접 준다
S3_PAD_MAX = 600                        # 아래 흰 여백 실측 상한 (shop2 는 389)
# ★인트로 카드 제목 — **원본은 언제나 화면 폭을 꽉 채운다.**
#   시범편 1호를 원본과 나란히 놓아 보고 찾은 차이다. 원본 4편(WwUhL·azDE·8hOi·DXsA)의
#   제목 잉크가 전부 x0~1079 로 **폭 1080** 인데 우리 판은 793 밖에 안 됐다.
#   원인은 폭이 아니라 **높이 상한**이었다 — shop2 는 92 라, 폭 1010 에 맞추면 높이가
#   92 를 넘어서 다시 높이 기준으로 줄어들고 그만큼 폭이 남는다. 그래서 정밀판은
#   **폭을 먼저 채우게** 상한을 올린다. 두 줄(165×2 + 14 = 344)이 흰 헤더 372 안에 든다.
S3_CARD_HL_W = 1080                     # 화면 폭 그대로
S3_CARD_MAX_INK = 165                   # 높이 상한 (shop2 는 92)
S3_CARD_GAP = 14                        # 줄 사이 — 원본은 두 줄이 거의 붙어 있다

# ★첫 화면이 제목 카드인 형식은 **제목이 점점 커진다** — 채널을 가리지 않는 공통 규칙
#   (2026-09-04 사용자 지시: "제목이 쥼인 점점 커지도록 설계 앞으로 제작본에 있어서
#   모두 적용 할것 왜냐 화면의 집중도 몰입감을 더 불어 넣기 위함"). 멈춰 있는 글자는
#   읽고 넘어가는 대상이지만 커지는 글자는 눈이 따라가게 만든다.
#   커지는 것은 **글자뿐**이고 배경·띠·영상 칸은 고정이다. 그래서 판을 통째로
#   키우지 않고 «글자만 그린 투명 레이어»를 스케일해 다시 얹는다.
CARD_ZOOM0 = S2_CARD_ZOOM0              # 시작 크기
CARD_ZOOM_SEC = S2_CARD_ZOOM_SEC        # 자라는 데 걸리는 시간
# 스케일의 «고정점» — 이 y 가 커져도 제자리에 남는다. 헤드라인 덩어리의 세로 한가운데를
# 잡아야 글자가 위나 아래로 흘러가지 않는다. 껍데기마다 헤드라인 자리가 달라 따로 둔다.
CARD_ZOOM_CY = 391                      # plain·shop 인트로 (HL1 윗선 295 ~ HL2 아랫선 487)
HT_ZOOM_CY = 410                        # 핫템 (HL1 296 ~ HL2 524)
RE_ZOOM_CY = 1040                       # 릴스 (아랫선 1120 기준 두 줄 덩어리)

# --- reels 껍데기 (인스타 릴스판 · 2026-08-24 멀티배포 규격)
#     릴스에는 «자막을 상단 헤더에 두는» 문법이 없다. 영상으로 화면을 꽉 채우고 자막을
#     가운데 아래에 큰 덩어리로 얹는 것이 기본형이라, 다른 판을 그대로 올리면
#     «유튜브에서 퍼온 영상»으로 읽힌다. 채널명·로고·워드마크는 어디에도 넣지 않는다.
RE_SAFE_TOP = 250              # 릴스 상단 UI 가 덮는 높이 — 글자를 두지 않는다
RE_SAFE_BOT = 420              # 캡션·계정·음원 줄 + 오른쪽 버튼 기둥
RE_CAP_BAND = (1060, 1500)     # 자막 판이 차지하는 띠. 아랫선이 하단 안전영역의 윗선이다
RE_CAP_INK = 74                # 자막 글자 높이 (풀블리드라 shop2 의 55 보다 크다)
RE_CAP_PITCH = 96              # 두 줄로 접혔을 때 줄 간격
RE_CAP_MAX_W = 900             # 이 폭을 넘으면 낱말 경계에서 두 줄로 접는다
RE_CAP_PAD_X, RE_CAP_PAD_Y = 34, 20
RE_CAP_RADIUS = 30
C_RE_BOX = (0x11, 0x11, 0x11, 0xC4)     # 자막 뒤 어두운 판 (반투명)

# --- hottem 껍데기 (핫템형 @핫템형 칼 카피 · 2026-09-02 실측)
#     `IRFN5B_2LMo`(64.4만)를 1080x1920 으로 재서 뽑았다. 규격 문서는
#     .claude/skills/hottem/reference/채널규격.md
#     ★`plain2` 와 뼈대가 같고 다른 것은 셋뿐이다 —
#       ① 제목이 «강조 낱말만»이 아니라 **줄 통째로** 색이다 (1줄 노랑 / 2줄 빨강)
#       ② 자막이 흰 띠 안이 아니라 **영상 위에** 흰 글씨 + 검정 테두리로 얹힌다
#       ③ 맨 위에 채널명 한 줄이 있다
#     ②가 눈에 띄는 차이다 — 흰 띠가 사라지면서 영상이 그만큼 커 보인다.
HT_NAME_TOP, HT_NAME_INK = 170, 46      # 채널명 (흰색, 얇게)
HT_HL1_TOP, HT_HL1_INK = 296, 104       # 제목 1줄
HT_HL2_TOP, HT_HL2_INK = 410, 114       # 제목 2줄
HT_HL_W = 1000                          # 이 폭을 넘으면 글자를 줄인다
HT_STROKE = 14                          # 제목 검정 테두리 두께
HT_VID_Y, HT_VID_H = 554, 1156          # 영상 칸 (554 ~ 1710)
HT_CAP_BAND = (1240, 1500)              # 자막 판이 차지하는 띠 — 영상 «위»다
HT_CAP_INK = 76
HT_CAP_PITCH = 96
HT_CAP_MAX_W = 940
HT_CAP_STROKE = 9
# ★2줄 롤링일 때 윗줄 잉크 윗선. 두 줄 덩어리(76 + 96 = 172)를 260px 띠 안에
#   위아래 44 로 나눠 넣은 값이다 — 1240 + 44. **줄 자리를 고정해야** 윗줄이
#   그대로 남고 아랫줄만 붙는 것으로 보인다 (가운데 정렬로 두면 윗줄이 위로
#   밀려 올라가서 «굴러가는» 느낌이 죽는다).
HT_CAP_TOP1 = 1284
C_HT_Y = (0xFF, 0xD4, 0x00)             # 제목 1줄 노랑
C_HT_R = (0xF0, 0x1E, 0x1E)             # 제목 2줄 빨강
RE_HL_INK_MAX = 120            # 인트로 카드 헤드라인 — 폭으로 맞추되 이보다 크게는 안 간다
RE_HL_GAP = 26
RE_HL_MAX_W = 960
RE_HL_BOTTOM = 1120            # 헤드라인 두 줄 덩어리의 잉크 아랫선

# ---------------------------------------------------------------- 소리 규격
GAP = 0.06            # 블록 사이 숨. 이븐쇼핑 나레이션은 거의 안 쉬므로 아주 짧게
TARGET_BLOCK = 0.93   # 자막 블록 목표 길이 (5편 실측 0.91·0.93·0.93·0.95·0.99)
INTRO_MIN, INTRO_MAX = 1.50, 2.10   # 실측 1.50 / 1.67 / 1.80 / 1.83 / 2.00
# ★첫 음절이 먹히는 것을 막는 «머리 여유». 나레이션을 0초에 붙여 놓으면 AAC 재생
#   시작 지연(프라이밍 ~40ms)과 겹쳐 첫 낱말의 첫 소리가 잘려 나간다. 실제로
#   「세척솔을 없애버린」이 「척솔을 없애버린」으로 들린다는 지적을 받았다(2026-08-23).
#   카드 길이 계산은 그대로 두고 통째로 이만큼 뒤로 민다.
# ★2026-08-26 에 사용자가 "그 텀을 지금의 절반 정도로 줄여봐. 너무 긴듯. 모든 영상에
#   적용, 이후 제작분부터" 라고 해서 0.35 → 0.175 로 내렸다. Typecast 원음 머리에도
#   0.08초쯤 무음이 붙으므로 완성본의 실제 첫 소리는 0.25초 근처다.
LEAD_IN = 0.175
AMB_GAIN = 0.12       # 소스 현장음 (-18dB 쯤)
BGM_GAIN = 0.20       # 배경음악. 활용정점 계열에서만 쓴다 (plan.bgm 을 줄 때만 깔린다)
SFX_CUT_GAIN = 0.10   # 컷 전환 클릭
SFX_MARK_GAIN = 0.44  # 블록에 지정한 강조 효과음. 자막 등장음보다 확실히 커야 한다
# shop2 자막 등장음 — 자막 줄이 바뀔 때마다 한 발.
# ★0.13 으로 깔았더니 그 순간 나레이션보다 11~17dB 낮아 통째로 안 들렸다(2026-08-24 실측).
#   그래서 강조음과 같은 크기로 올리고, 대신 **말보다 조금 앞세워** 첫 음절을 덮지 않게 한다.
# ★★한 소리만 되풀이하면 지루하다 (2026-08-24 사용자 지적 — "다 똑같은 효과음으로만
#   넣었어? 재미 없잖아... 활용정점이 그렇게 했는데"). 그래서 **쪽이 열릴 때**와
#   **줄이 붙을 때**를 다른 소리로 가르고, 쪽마다 돌려 쓴다.
#   길이가 잣대다 — 말 위에 얹히는 소리라 길면 다음 낱말까지 번진다. 자산 78개 중
#   0.1초 아래는 pop4 여섯뿐이라(work/heatgun/_sfxlen.py), 짧은 팝은 «줄이 붙을 때»에
#   두고, 한 호흡 쉬어 가는 «쪽이 열릴 때»에만 0.31~0.49초짜리를 쓴다.
SFX_CAP_LEAD = 0.06   # 자막이 바뀌는 시각보다 이만큼 먼저 친다
# 셋째 값은 **목표 봉우리 크기**다 (build_sfx 가 파일 원음 크기로 나눠 맞춘다).
#
# ★★사람 목소리가 든 소리를 쓰지 않는다 (2026-08-24 사용자 지적 — "효과음에 팅 뽕 탁
#   이런건 되는데 사람 음성 같은거는 안되지"). 처음에 `ding` 계열을 이름만 보고 골랐다가
#   음성이 섞였다. 자산 78개를 신호로 재 보니(work/heatgun/_voicelike.py) 하모닉이 세고
#   오래 끄는 무리에 `ding` 계열이 몰려 있는데, **내 잣대로는 종소리와 목소리가 갈리지
#   않는다** — 둘 다 하모닉이 세다. 그래서 지금은 **하모닉이 약하고 짧게 죽는 타격음만**
#   쓴다(위 파일들은 전부 목소리다움 점수 0.6 아래다). 사람이 들어 가려낸 뒤에야
#   종소리 계열을 다시 넣는다.
SFX_CAP_TOP = [("click_0.mp3", 0.30), ("r3_click_7.mp3", 0.30), ("boing_0.mp3", 0.30),
               ("click_5.mp3", 0.30), ("x_swoosh_4.mp3", 0.30), ("x_click_3.mp3", 0.30)]
SFX_CAP_BOT = [("pop4_0.mp3", 0.30), ("pop4_2.mp3", 0.30), ("pop4_4.mp3", 0.30),
               ("pop4_1.mp3", 0.30), ("pop4_5.mp3", 0.30), ("pop4_3.mp3", 0.30)]
# shop2 강조 4자리 — 공용 SFX 표에는 `ding` 이 종소리 계열이라 여기서만 갈아 끼운다.
S2_ACCENT = {"pop": "pop4_2.mp3", "ding": "hit_0.mp3",
             "drum": "drum_0.mp3", "boing": "boing_0.mp3"}

TC_URL = "https://api.typecast.ai/v1/text-to-speech"
TC_KEYFILE = os.path.expanduser("~/.volcano/keys/typecast")
VOICES = {"NARR": "tc_65a0e1d1d7012c484fe4bfc7",
          "PUNCH": "tc_618b1849ef7827cfea34ea1e"}


def voices_of(plan):
    """이 편이 쓸 목소리. `plan.voice_narr` · `plan.voice_punch` 로 갈아 끼운다.

    ★2026-09-05 제작자 — 「칼카피가 목소리까지니까」. 프리셋마다 원본 성우가 달라서
    전역 상수 하나로는 못 맞춘다. 실제로 이븐쇼핑 원본은 **152Hz 남성**인데 위
    기본값(Jerome)은 **205Hz 여성**이라, 584개 후보 중 226위짜리로 굽고 있었다
    (2026-09-10 이븐쇼핑 정밀 실측). 프리셋 규격이 목소리를 정하면 여기로 들어온다.
    """
    v = dict(VOICES)
    if plan.get("voice_narr"):
        v["NARR"] = plan["voice_narr"]
    if plan.get("voice_punch"):
        v["PUNCH"] = plan["voice_punch"]
    return v

def _sfx_dir():
    """효과음 폴더를 찾는다 — 패키지 안 → 볼케이노 → 환경변수 순.

    효과음은 볼케이노가 배포하는 자산이라 이 패키지에 번들하지 않는다.
    볼케이노를 쓰고 있으면 그대로 잡히고, 아니면 `EVENSHOP_SFX_DIR` 로 지정한다."""
    for p in (os.path.join(REPO, "assets", "sfx"),
              os.path.expanduser("~/volcano/sfx_norm"),
              os.environ.get("EVENSHOP_SFX_DIR") or ""):
        if p and os.path.isdir(p):
            return p
    return os.path.join(REPO, "assets", "sfx")   # 없으면 조용히 무음으로 간다

SFX_DIR = _sfx_dir()
SFX = {"click": "click_0.mp3", "pop": "pop4_0.mp3", "ding": "ding_0.mp3",
       "hit": "hit_2.mp3", "boing": "boing_1.mp3", "fail": "fail_0.mp3",
       "swoosh": "swoosh_1.mp3", "swoosh2": "x_swoosh_4.mp3", "drum": "drum_0.mp3",
       "end": "r3_hit_11.mp3"}

FF = shutil.which("ffmpeg") or "ffmpeg"
FPROBE = shutil.which("ffprobe") or FF.replace("ffmpeg", "ffprobe")


def run(argv, **kw):
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", **kw)
    if p.returncode != 0:
        sys.stderr.write("\n[FAIL] " + " ".join(str(a) for a in argv[:14]) + " ...\n")
        sys.stderr.write((p.stderr or "")[-3000:] + "\n")
        raise SystemExit(1)
    return p.stdout


def probe_dur(path):
    return float(run([FPROBE, "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", path]).strip())


# ---------------------------------------------------------------- 글자 그리기
def fit(text, path, target_ink_h, lo=10, hi=400):
    """글자(잉크)의 실제 높이가 target_ink_h 가 되는 폰트를 찾는다."""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        f = ImageFont.truetype(path, mid)
        b = probe.textbbox((0, 0), text, font=f)
        h = b[3] - b[1]
        best = (f, b)
        if h < target_ink_h:
            lo = mid + 1
        elif h > target_ink_h:
            hi = mid - 1
        else:
            break
    return best


def fit_w(text, path, target_w, lo=10, hi=400):
    """글자(잉크)의 실제 **폭**이 target_w 가 되는 폰트를 찾는다.

    ★카드 헤드라인은 높이가 아니라 폭으로 맞춘다. 레퍼런스 5편의 HL 글자 높이는
    106~149 로 제각각인데 폭은 918~988 로 거의 같았다 — 화면 폭을 채우도록 키운 것이지
    글자 크기를 정해 놓은 것이 아니다. 높이로 맞추면 받침 있는 문구만 헐렁해진다."""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        f = ImageFont.truetype(path, mid)
        b = probe.textbbox((0, 0), text, font=f)
        best = (f, b)
        if b[2] - b[0] < target_w:
            lo = mid + 1
        elif b[2] - b[0] > target_w:
            hi = mid - 1
        else:
            break
    return best


def _ink_h(text, target_w, path=None):
    """폭을 target_w 로 맞췄을 때의 잉크 높이."""
    f, b = fit_w(text, path or F_BLACK, target_w)
    return b[3] - b[1]


def draw_headline(d, text, path, ink_bottom, cx, fill, target_w=HL_W,
                  stroke=9, shadow=6):
    """카드 헤드라인 한 줄. 폭을 target_w 에 맞추고 **잉크 아랫선**을 ink_bottom 에 둔다.
    돌려주는 값은 그 줄의 잉크 높이 (윗줄을 그 위에 쌓을 때 쓴다)."""
    f, b = fit_w(text, path, target_w)
    h = b[3] - b[1]
    x = cx - (b[2] - b[0]) / 2 - b[0]
    y = ink_bottom - h - b[1]
    if shadow:
        d.text((x, y + shadow), text, font=f, fill=C_BLACK,
               stroke_width=stroke, stroke_fill=C_BLACK)
    d.text((x, y), text, font=f, fill=fill, stroke_width=stroke, stroke_fill=C_BLACK)
    return h


def draw_ink(d, text, path, ink_h, ink_top, cx=None, left=None,
             fill=C_WHITE, stroke=0, stroke_fill=C_BLACK, shadow=0, max_w=None):
    """잉크 상단을 ink_top 에 맞추고, 가로는 cx 중심 정렬 또는 left 좌측 정렬.
    max_w 를 주면 그 폭을 넘지 않게 글자를 줄인다 (화면 밖으로 나가는 것을 막는다)."""
    f, b = fit(text, path, ink_h)
    w = b[2] - b[0]
    if max_w and w > max_w:
        f = ImageFont.truetype(path, max(8, int(f.size * max_w / w)))
        b = d.textbbox((0, 0), text, font=f)
        w = b[2] - b[0]
        ink_top += (ink_h - (b[3] - b[1])) / 2      # 줄어든 만큼 세로 가운데로
    x = (cx - w / 2 - b[0]) if cx is not None else (left - b[0])
    y = ink_top - b[1]
    if shadow:
        d.text((x, y + shadow), text, font=f, fill=C_BLACK,
               stroke_width=stroke, stroke_fill=C_BLACK)
    d.text((x, y), text, font=f, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
    return w


def _ink_x(f, ch, _cache={}):
    """이 글자의 **앵커 기준 잉크 좌우 경계**.

    ⚠ `textbbox` 는 Pretendard 한글에서 가로로 «전진폭»(넉 자 모두 86)을 돌려주지
    실제 잉크 경계가 아니다. 세로는 잉크를 제대로 주는데 가로만 그렇다.
    그래서 한 글자를 실제로 그려 보고 잰다 (글자당 한 번만 — 캐시).
    """
    k = (id(f), f.size, ch)
    if k in _cache:
        return _cache[k]
    pad = max(8, int(f.size * 0.8))
    im = Image.new("L", (int(f.size * 2.5) + pad * 2, int(f.size * 2.5) + pad * 2), 0)
    ImageDraw.Draw(im).text((pad, pad), ch, font=f, fill=255)
    bb = im.getbbox()
    r = (0, 0) if not bb else (bb[0] - pad, bb[2] - pad)
    _cache[k] = r
    return r


def draw_tracked(d, text, path, ink_h, ink_top, total_w, cx, fill=C_WHITE):
    """자간을 벌려 **잉크 폭**이 total_w 가 되게 한다 (로고용).

    ★2026-09-10 에 고쳤다. 옛 판은 `textbbox` 의 전진폭으로 자간을 나눠서,
    좌우 사이드베어링(「이븐쇼핑」 기준 합 13px)만큼 잉크가 안쪽으로 들어왔다 —
    원본 실측 457px 인데 444px 로 나왔다(이븐쇼핑 정밀 대조 `eB_verify.py`).
    이제 글자마다 실제 잉크 경계를 재므로 total_w 가 그대로 잉크 폭이 된다.
    """
    f, _ = fit(text, path, ink_h)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    boxes = [probe.textbbox((0, 0), c, font=f) for c in text]   # 세로(b[1])는 이쪽이 맞다
    xs = [_ink_x(f, c) for c in text]
    widths = [b - a for a, b in xs]
    gap = (total_w - sum(widths)) / max(1, len(text) - 1)
    x = cx - total_w / 2
    for c, b, (ax, _), wd in zip(text, boxes, xs, widths):
        d.text((x - ax, ink_top - b[1]), c, font=f, fill=fill)
        x += wd + gap


def draw_icons(d, color=C_WHITE, top=23):
    """햄버거(좌) · 돋보기(우).

    ★두 화면 상태에서 자리도 색도 다르다 (5편 실측 일치).
      본편  : 흰색 #FFFFFF, 햄버거 y23~97   — 로고와 같은 줄에 맞춰 위쪽
      카드  : 회색 #808080, 햄버거 y50~125  — 로고가 없어 띠(0~174) 한가운데
    카드 아이콘까지 흰색으로 그리면 헤드라인과 밝기가 맞붙어 카드가 시끄러워진다.
    햄버거는 굵기 12 짜리 막대 3개를 31 간격으로, x51~163."""
    for i in range(3):
        y = top + i * 31
        d.rounded_rectangle([51, y, 163, y + 12], radius=6, fill=color)
    dy = top - 23
    d.ellipse([940, 18 + dy, 1030, 108 + dy], outline=color, width=11)
    d.line([1019, 97 + dy, 1046, 126 + dy], fill=C_LENS, width=13)


# ---------------------------------------------------------------- 오버레이 판
def _smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def _glow_band(_cache={}):
    """인트로 카드의 흰 띠 한 장 (y536~729). 회색 위에 얹힌 부드러운 글로우다."""
    if "im" in _cache:
        return _cache["im"]
    g = C_GRAY[0]
    rows = []
    for y in range(GLOW_Y0, GLOW_Y1 + 1):
        if y < GLOW_RISE_END:
            k = _smooth((y - GLOW_Y0) / float(GLOW_RISE_END - GLOW_Y0))
        elif y <= GLOW_FALL_START:
            k = 1.0
        else:
            k = 1.0 - _smooth((y - GLOW_FALL_START) / float(GLOW_Y1 - GLOW_FALL_START))
        rows.append(k)
    im = Image.new("RGB", (W, len(rows)), C_GRAY)
    d = ImageDraw.Draw(im)
    for j, k in enumerate(rows):
        v = int(round(g + (255 - g) * k))
        d.line([0, j, W - 1, j], fill=(v, v, v))
    # 좌우 바깥 42px 만 살짝 죽는다 (실측 x0:182 · x20:240 · x40~:255)
    px = im.load()
    for x in range(GLOW_EDGE):
        e = 0.45 + 0.55 * (x / float(GLOW_EDGE - 1)) ** 0.4
        for xx in (x, W - 1 - x):
            for j in range(len(rows)):
                v = px[xx, j][0]
                nv = int(round(g + (v - g) * e))
                px[xx, j] = (nv, nv, nv)
    _cache["im"] = im
    return im


def shell_of(plan):
    """`plain`(기본) = 검정 바탕 + 제목 2줄. `shop` = 이븐쇼핑식 가짜 쇼핑몰 앱 헤더.

    ★기본값은 `plain` 이다. 쇼핑형 완성본들이 이 껍데기로 나와 있고
    (`<완성본 폴더>\\<제품>\\<제목>_v001.mp4`),
    2026-08-22 에 사용자가 "그냥 껍데기는 기존 스타일로" 라고 못 박았다.
    상단바에 채널명·로고가 없어서 그 편을 다른 채널로 그대로 옮길 수 있다는 것이
    이 껍데기를 쓰는 이유다.

    `shop` 은 이븐쇼핑 원본을 그대로 재현한 껍데기다. 로고 자리가 생기므로
    **일부러 고를 때만** 쓴다. 로고 글자는 `plan.logo` 로 준다 (없으면 채널명).

    `reels` 는 인스타 릴스판이다 — 영상이 화면을 통째로 채우고 자막만 가운데 아래에
    얹힌다. 껍데기랄 것이 없으므로 채널명이 들어갈 자리도 없다. 자세한 것은
    [docs/멀티배포규격.md](../docs/멀티배포규격.md).

    `plain2` 는 «이븐형 2줄자막» 이다 — `plain` 과 좌표가 같고 **자막만 두 줄로 굴러간다.**
    2026-08-27 사용자 지시로 갈라져 나온 껍데기이고, 대본은 활용정점형(활용정점) 틀을 쓴다."""
    return plan.get("shell", "plain")


def is_plain(plan):
    """검정 바탕 + 제목 2줄 계열인가 (`plain` · `plain2`).

    두 껍데기는 화면 좌표가 같고 **자막 띠 안쪽만** 다르므로, 헤더·바탕·인트로 카드를
    가르는 자리에서는 언제나 이 함수로 묶어서 본다."""
    return shell_of(plan) in ("plain", "plain2")


def rolls(plan):
    """자막이 **두 줄로 굴러가는** 껍데기인가 (`shop2` · `plain2` · `hottem`).

    굴러가는 자막은 «줄이 바뀔 때마다 뽁» 소리와 한 몸이다 (화면규격.md 3절).
    그래서 자막 등장음도 이 함수로 가른다.

    ★`hottem` 은 2026-09-03 에 제작자 지시로 이 무리에 들어왔다 —
    "자막 형식을 이븐형 2줄자막처럼 두줄로 한줄 나올때 마다 소리 나는 형식으로 바꿔 주고".
    원본 핫템형는 한 블록을 통째로 얹지만, 우리 판은 이븐형 2줄자막 과 같은 리듬으로
    간다. 옛 방식으로 되돌리려면 `plan.ht_roll: false` 를 준다."""
    sh = shell_of(plan)
    if sh == "hottem":
        return plan.get("ht_roll", True)
    return sh in ("shop2", "shop3", "plain2")


def is_s2(plan):
    """활용정점 계열 껍데기인가 — `shop2`(활용정점형) · `shop3`(활용정점 정밀형).

    둘은 좌표가 같고 **색과 인트로 글씨, 칸 높이 사다리만** 다르다. 그래서
    「이 껍데기냐」를 묻는 자리에서는 언제나 이 함수로 묶어서 본다."""
    return shell_of(plan) in ("shop2", "shop3")


def s3_style(plan):
    """이 plan 이 정밀판(`shop3`)인가. 색·글씨·사다리를 가르는 하나의 잣대다."""
    return shell_of(plan) == "shop3"


def _ladder(plan):
    """영상 칸 높이 사다리 — 정밀판은 실측대로 훨씬 넓다 (598~1014 vs 888~1014)."""
    return S3_VID_HS if s3_style(plan) else S2_VID_HS


def _pad_max(plan):
    """영상 아래 흰 여백의 상한. 이보다 더 남으면 칸을 내려 위아래로 나눈다.

    30편 실측에서 원본의 아래 여백은 **261~600px** 이었다(대다수가 261). shop2 는
    5편만 보고 389 로 잡았는데, 그 문턱이 낮으면 낮은 칸을 쓸 때마다 칸이 억지로
    내려가 원본에 없는 «위쪽 흰 띠»가 생긴다."""
    return S3_PAD_MAX if s3_style(plan) else S2_PAD_MAX


def logo_of(plan):
    """`shop` 껍데기의 헤더 워드마크. 넉 자여야 실측 자간이 그대로 산다."""
    return plan.get("logo") or plan.get("channel", "")


def sublogo_of(plan):
    """알약 위쪽 작은 줄. 주면 상단 바가 두 줄 판으로 갈린다 (「가성 VS 진성」)."""
    return plan.get("sublogo") or ""


def base_color(plan):
    sh = shell_of(plan)
    if sh in ("shop2", "shop3", "reels", "hottem"):
        return C_BLACK          # shop2·shop3 은 영상 아래 여백, reels·hottem 은 검정 바탕
    return C_INTRO_BG if is_plain(plan) else C_HEADER


# ------------------------------------------------------------- shop2 껍데기
def draw_ink_parts(d, parts, path, ink_h, ink_top, cx, max_w=None):
    """`[(글자, 색), ...]` 를 한 줄로 이어 그린다 — 낱말마다 색이 다른 줄용.

    `draw_ink` 와 달리 조각을 따로 그리므로, 자간이 벌어지지 않도록 **한 폰트로
    전체 폭을 먼저 재고** 조각을 이어 붙인다."""
    plain = "".join(t for t, _ in parts)
    f, b = fit(plain, path, ink_h)
    w = b[2] - b[0]
    if max_w and w > max_w:
        f = ImageFont.truetype(path, max(8, int(f.size * max_w / w)))
        b = d.textbbox((0, 0), plain, font=f)
        w = b[2] - b[0]
        ink_top += (ink_h - (b[3] - b[1])) / 2
    x, y = cx - w / 2 - b[0], ink_top - b[1]
    for t, col in parts:
        d.text((x, y), t, font=f, fill=col)
        x += d.textlength(t, font=f)
    return w


def _s2_bar(d, logo, sublogo="", bar_rgb=None):
    """상단 바 + 흰 알약형 검색창(워드마크 · 돋보기).

    ★알약은 바 한가운데가 아니라 **바닥에 붙어** 있다 (위 152 · 아래 18). 가운데에
    두면 원본과 확연히 달라 보인다 (2026-08-24 사용자 지적).

    `sublogo` 를 주면 알약 안이 **두 줄**이 된다 — 위에 작게 채널 이름, 아래에 크게
    시리즈 이름. 시리즈 이름의 `*낱말*` 은 상단 바와 같은 빨강으로 칠해 띠와 묶는다
    (2026-09-04 「가성 VS 진성」). 알약·바·돋보기 좌표는 하나도 건드리지 않는다.

    `bar_rgb` 는 바 색이다 — 안 주면 활용정점형 의 빨강(`C_S2_BAR`). 정밀판(`shop3`)이
    주황을 넘긴다. **색 말고는 한 픽셀도 다르지 않다.**"""
    bar = bar_rgb or C_S2_BAR
    d.rectangle([0, 0, W - 1, S2_BAR_H - 1], fill=bar)
    x0, y0, x1, y1 = S2_PILL
    d.rounded_rectangle([x0, y0, x1, y1], radius=(y1 - y0) // 2,
                        fill=C_S2_PILL_BG, outline=C_S2_PILL_EDGE, width=4)
    if sublogo:
        draw_ink(d, _nomark(sublogo), F_BLACK, S2_SUB_INK, S2_SUB_TOP, cx=W // 2,
                 fill=C_S2_METRIC, max_w=420)
        draw_ink_parts(d, [(t, bar if hi else C_BLACK) for t, hi in split_hi(logo)],
                       F_BLACK, S2_LOGO2_INK, S2_LOGO2_TOP, W // 2, max_w=560)
    else:
        draw_ink(d, _nomark(logo), F_BLACK, S2_LOGO_INK, S2_LOGO_TOP, cx=W // 2,
                 fill=C_BLACK, max_w=480)
    cx, cy, r = S2_LENS_CX, S2_LENS_CY, S2_LENS_R
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(0x33, 0x33, 0x33), width=8)
    d.line([cx + r * 0.72, cy + r * 0.72, cx + r * 1.45, cy + r * 1.45],
           fill=(0x33, 0x33, 0x33), width=10)


def split_hi(text):
    """`*낱말*` 로 감싼 조각을 강조(시안)로 갈라 [(글자, 강조인가), ...] 로 돌려준다."""
    out, buf, hi = [], "", False
    for ch in text:
        if ch == "*":
            if buf:
                out.append((buf, hi))
            buf, hi = "", not hi
        else:
            buf += ch
    if buf:
        out.append((buf, hi))
    return out or [(text, False)]


def _nomark(text):
    """`*낱말*` 강조 표시를 뗀 맨 글자.

    강조를 낱말 단위로 칠하는 것은 `shop2` 카드뿐이다. 다른 껍데기는 줄 단위로
    색을 주므로 별표가 그대로 그려지면 안 된다 — 같은 plan 을 껍데기만 갈아 끼워
    여러 판을 굽기 때문에(`tools/mk_variants.py`) 어느 판에서든 안전해야 한다."""
    return text.replace("*", "")


def draw_card_line(d, text, ink_top, target_w, hi_fill, white=False, max_ink=None):
    """카드 큰 제목 한 줄. `*낱말*` 만 강조색으로 칠한다.

    두 벌이 있다 — 껍데기마다 원본이 다르기 때문이다.

    | | 획 | 테두리 | 강조 낱말 |
    |---|---|---|---|
    | `white=False` (**shop2** · 활용정점형) | 검정 | 흰색 | 노랑 + 검정 테두리 |
    | `white=True` (**shop3** · 활용정점 정밀형) | **흰색** | **검정** | 시안 + 검정 테두리 |

    ★정밀판이 흰 글씨인 근거 — 활용정점 **30편 전수**에서 인트로 제목이 전부
      「흰 획 + 굵은 검정 테두리 + 그림자」였다(work/_hoshop_ref/intro30.py).
      shop2 가 검정 글씨인 것은 5편 표본 시절 판정이고, 그때 강조색을 시안에서
      노랑으로 바꾼 이유(「흰 바탕에서 시안이 묻힌다」)도 **글씨가 검정일 때만**
      성립한다. 흰 글씨에 검정 테두리를 두르면 시안이 안 묻는다.
      **shop2 는 그대로 둔다** — 이미 그 색으로 나간 편들이 있다."""
    parts = split_hi(text)
    plain = "".join(p for p, _ in parts)
    cap = S2_CARD_MAX_INK if max_ink is None else max_ink
    f, b = fit_w(plain, F_BLACK, target_w)
    if b[3] - b[1] > cap:                  # 폭보다 높이가 먼저 찼으면 높이로 맞춘다
        f, b = fit(plain, F_BLACK, cap)
    h = b[3] - b[1]
    x = W / 2 - (b[2] - b[0]) / 2 - b[0]
    y = ink_top - b[1]
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    edge = C_BLACK if white else C_WHITE
    body = C_WHITE if white else C_BLACK
    # 테두리를 먼저 통째로 깔아야 낱말 경계에서 선이 끊기지 않는다
    d.text((x, y + 7), plain, font=f, fill=C_BLACK, stroke_width=11, stroke_fill=C_BLACK)
    d.text((x, y), plain, font=f, fill=edge, stroke_width=11, stroke_fill=edge)
    cx = x
    for seg, is_hi in parts:
        if is_hi:
            # ★강조 낱말에는 **검정 테두리**를 두른다. 밝은 색을 그냥 올리면 바탕과
            #   밝기가 비슷해 글자가 묻힌다 (2026-08-24 사용자 지적 — "제목 색상이
            #   눈에 안 들어옴"). 원본도 강조 글자에 검정 테두리가 있다.
            d.text((cx, y), seg, font=f, fill=hi_fill, stroke_width=5,
                   stroke_fill=C_BLACK)
        else:
            d.text((cx, y), seg, font=f, fill=body)
        cx += probe.textlength(seg, font=f)
    return h


def _card_text_layer(plan):
    """카드 큰 제목 두 줄만 그린 투명 판 (흰 헤더 칸 크기).

    확대 애니메이션을 주려고 글자를 따로 뽑아 둔다. 상단 바와 바탕은 고정이고
    **이 판만 커진다.**"""
    im = Image.new("RGBA", (W, S2_HEAD_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fine = s3_style(plan)
    hw = plan.get("hl_w", S3_CARD_HL_W if fine else S2_CARD_HL_W)
    hi = plan.get("hl2_color", C_S3_HI if fine else C_S2_HI)
    gap = S3_CARD_GAP if fine else S2_CARD_GAP
    cap = S3_CARD_MAX_INK if fine else S2_CARD_MAX_INK
    if fine:
        # ★정밀판은 두 줄 덩어리를 **흰 헤더의 세로 한가운데**에 놓는다.
        #   글자가 폭에 맞춰 커지므로 덩어리 높이가 문구마다 달라진다 —
        #   shop2 처럼 윗선을 고정하면 짧은 문구일 때 아래로 넘친다.
        probe = ImageDraw.Draw(Image.new("RGBA", (W, S2_HEAD_H)))
        ph1 = draw_card_line(probe, plan["hl1"], 0, hw, hi, white=True, max_ink=cap)
        ph2 = draw_card_line(probe, plan["hl2"], 0, hw, hi, white=True, max_ink=cap)
        top = max(0, (S2_HEAD_H - (ph1 + gap + ph2)) // 2)
    else:
        top = S2_CARD_TOP - S2_HEAD_Y
    h1 = draw_card_line(d, plan["hl1"], top, hw, hi, white=fine, max_ink=cap)
    draw_card_line(d, plan["hl2"], top + h1 + gap, hw, hi, white=fine, max_ink=cap)
    return im


def make_shop2_top(plan, out, line1=None, line2=None, card=False, hl_scale=1.0):
    """shop2 오버레이 판 한 장 (0~643). 본편이면 자막 두 줄까지 그려 넣는다.

    ★이 형식의 자막은 **두 줄로 굴러간다** — 앞 줄이 위에 남고 새 줄이 아래에 붙는다.
    그래서 자막이 헤더 안에 있고, 헤더 전체를 블록마다 다시 그린다. 이븐형 처럼
    자막 띠만 따로 굽는 방식으로는 «위에 남는 줄»을 만들 수 없다.

    `hl_scale` 은 인트로 카드 제목의 크기다. 1.0 보다 작게 주면 그만큼 작게 그려져서,
    프레임마다 키워 나가면 **제목이 점점 확대되는** 효과가 된다."""
    im = Image.new("RGB", (W, S2_TOP_H), C_S2_HEAD)
    d = ImageDraw.Draw(im)
    _s2_bar(d, logo_of(plan), sublogo_of(plan),
            bar_rgb=C_S3_BAR if s3_style(plan) else None)
    if card:
        lay = _card_text_layer(plan)
        if abs(hl_scale - 1.0) > 0.002:
            lay = lay.resize((max(2, int(W * hl_scale)),
                              max(2, int(S2_HEAD_H * hl_scale))), Image.LANCZOS)
        im.paste(lay, ((W - lay.width) // 2,
                       S2_HEAD_Y + (S2_HEAD_H - lay.height) // 2), lay)
    else:
        # ★제목은 자막보다 커야 한다 (잉크 58 vs 55). 작아지면 이 채널이 아니다.
        draw_ink(d, plan["post_title"], F_EB, S2_TITLE_INK, S2_TITLE_TOP,
                 left=S2_TITLE_X, fill=C_BLACK, max_w=S2_MAX_TITLE_W)
        draw_ink(d, plan["metrics"], F_LOGO, S2_METRIC_INK, S2_METRIC_TOP,
                 left=S2_METRIC_X, fill=C_S2_METRIC)
        d.rectangle([0, S2_DIV_Y, W - 1, S2_DIV_Y + 1], fill=C_S2_DIV)
        for k, t in enumerate((line1, line2)):
            if t:
                draw_ink(d, t, F_BLACK, S2_CAP_INK, S2_CAP_TOP1 + k * S2_CAP_PITCH,
                         cx=W // 2, fill=C_BLACK, max_w=S2_MAX_CAP_W)
    im.save(out)


def roll_lines(texts, i):
    """i 번째 블록에서 화면에 떠 있는 자막 두 줄. **두 줄이 한 쪽(page)을 이룬다.**

    짝수 블록에서 윗줄만 뜨고, 홀수 블록에서 그 아래에 아랫줄이 붙는다. 두 줄이 차면
    다음 블록에서 통째로 비우고 다시 윗줄부터 쌓는다.

        블록 0    이건 원래 페인트 벗기는
        블록 1    이건 원래 페인트 벗기는        ← 그대로 남고
                  평범한 열풍기였음              ← 아래에 붙는다
        블록 2    근데 최근 이 제품 특유의        ← 비우고 다시 윗줄부터

    ★«미끄러지는 창»(앞 블록을 윗줄로 계속 끌고 가는 방식)으로 만들면 안 된다.
      그렇게 하면 블록이 넘어갈 때마다 윗줄에 **이미 말이 끝난 문장**이 새로 나타나서,
      소리와 자막 시각이 ±20ms 로 맞는데도 자막이 늦는 것처럼 보인다
      (2026-08-24 사용자 지적: "자막이 맨 처음만 첫줄 후 두번째 줄로 표시되고
      나머지부터는 한꺼번에 나와 버림"). 이 방식이면 **새로 뜨는 줄이 언제나 지금
      말하고 있는 줄**이라 «뽁» 소리와도 맞아떨어진다."""
    return (texts[i], None) if i % 2 == 0 else (texts[i - 1], texts[i])


def make_body_header(plan, out):
    """본편 상단 0~404."""
    plain = is_plain(plan)
    im = Image.new("RGB", (W, BODY_HEADER_H), base_color(plan))
    d = ImageDraw.Draw(im)
    if plain:
        # ★채널명·로고·아이콘을 넣지 않는다. 넣으면 그 영상이 한 채널 전용이 된다.
        top = plan.get("plain_top", PLAIN_TOP)
        ink = plan.get("plain_ink", PLAIN_INK)
        gap = plan.get("plain_gap", PLAIN_GAP)
        draw_ink(d, _nomark(plan["hl1"]), F_BLACK, ink, top, cx=W // 2,
                 fill=C_WHITE, max_w=PLAIN_HL_W)
        draw_ink(d, _nomark(plan["hl2"]), F_BLACK, ink, top + ink + gap, cx=W // 2,
                 fill=plan.get("hl2_color", C_CYAN), max_w=PLAIN_HL_W)
    else:
        draw_icons(d)
        draw_tracked(d, logo_of(plan), F_LOGO, LOGO_INK_H, LOGO_TOP, LOGO_W, W // 2)
        d.rectangle([0, 175, W - 1, 176], fill=C_WHITE)
        draw_ink(d, plan["post_title"], F_EB, TITLE_INK_H, TITLE_TOP, cx=W // 2,
                 fill=C_WHITE, max_w=MAX_TITLE_W)
        draw_ink(d, plan["metrics"], F_LOGO, METRIC_INK_H, METRIC_TOP,
                 left=METRIC_X, fill=C_METRIC)
    im.save(out)


def _paste_zoom(im, lay, cy, hl_scale):
    """글자만 그린 투명 레이어를 `hl_scale` 로 키워 `cy` 를 고정점으로 다시 얹는다.

    판을 통째로 키우면 배경·띠·아이콘까지 커진다. 그래서 글자 레이어를 따로 받아
    여기서만 스케일한다. `cy` 는 커져도 제자리에 남을 y — 헤드라인 덩어리의 세로
    한가운데를 주면 글자가 위아래로 흘러가지 않고 그 자리에서 자란다."""
    if abs(hl_scale - 1.0) <= 0.002:
        im.paste(lay, (0, 0), lay)
        return
    nw = max(2, int(round(lay.width * hl_scale)))
    nh = max(2, int(round(lay.height * hl_scale)))
    lay = lay.resize((nw, nh), Image.LANCZOS)
    im.paste(lay, ((im.width - nw) // 2, int(round(cy * (1.0 - hl_scale)))), lay)


def _intro_text_layer(plan):
    """인트로 카드의 큰 헤드라인 두 줄만 그린 투명 판 (카드 상단 크기)."""
    lay = Image.new("RGBA", (W, INTRO_TOP_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    hw = min(MAX_HL_W, plan.get("hl_w", HL_W))
    h2_top = plan.get("hl2_top", HL2_TOP)
    hl1, hl2 = _nomark(plan["hl1"]), _nomark(plan["hl2"])
    draw_headline(d, hl2, F_BLACK, h2_top + _ink_h(hl2, hw), W // 2,
                  plan.get("hl2_color", C_CYAN), hw)
    draw_headline(d, hl1, F_BLACK, h2_top - HL_GAP, W // 2, C_WHITE, hw)
    return lay


def make_intro_top(plan, out, hl_scale=1.0):
    """인트로 카드 상단 0~729.

    `hl_scale` 은 큰 제목 두 줄의 크기다. 1.0 보다 작게 주면 그만큼 작게 그려져서,
    프레임마다 키워 나가면 **제목이 점점 확대된다**(2026-09-04 사용자 지시)."""
    plain = is_plain(plan)
    im = Image.new("RGB", (W, INTRO_TOP_H), C_INTRO_BG)
    d = ImageDraw.Draw(im)
    # ★회색 띠 위에 얹힌 흰 띠는 단순한 사각형이 아니라 **부드러운 글로우**다.
    #   실측 세로 밝기(x=540): 535:126 → 550:142 → 560:165 → 570:202 → 580:230 →
    #   590:250 → (596~664 순백) → 680:223 → 700:161 → 720:127.
    #   선형으로 그리면 중간이 밝고 끝이 급해 원본과 다른 인상이 된다. smoothstep 이 맞다.
    #   가로로는 바깥 40px 만 살짝 죽는다 (x0:182 → x20:240 → x40~1039:255).
    d.rectangle([0, 405, W - 1, INTRO_TOP_H - 1], fill=C_GRAY)
    im.paste(_glow_band(), (0, GLOW_Y0))
    if not plain:                      # 아이콘·구분선도 쇼핑몰 껍데기 요소다
        draw_icons(d, color=C_CARD_ICON, top=CARD_ICON_TOP)
        d.rectangle([0, 175, W - 1, 176], fill=C_WHITE)
    _paste_zoom(im, _intro_text_layer(plan), CARD_ZOOM_CY, hl_scale)
    # 흰 박스 안의 작은 게시글 제목은 고정이다 — 띠와 함께 배경 노릇을 하므로
    # 같이 키우면 흰 띠 밖으로 글자가 삐져 나간다.
    draw_ink(d, plan["post_title"], F_EB, BOX_INK_H, BOX_TOP, cx=W // 2,
             fill=C_BLACK, max_w=MAX_TITLE_W)
    im.save(out)


def make_caption(text, out):
    """자막 띠 한 장 (흰 바탕 · 검정 1줄 · 애니메이션 없음)."""
    im = Image.new("RGB", (W, CAP_TRACK_H), C_WHITE)
    d = ImageDraw.Draw(im)
    f, b = fit(text, F_BLACK, CAP_INK_H)
    if b[2] - b[0] > MAX_CAP_W:               # 폭이 넘치면 크기를 줄인다
        f = ImageFont.truetype(F_BLACK, int(f.size * MAX_CAP_W / (b[2] - b[0])))
        b = d.textbbox((0, 0), text, font=f)
    d.text((W / 2 - (b[2] - b[0]) / 2 - b[0], (CAP_TOP - CAP_TRACK_Y) - b[1]), text,
           font=f, fill=C_BLACK)
    im.save(out)


def make_caption2(line1, line2, out):
    """`plain2`(이븐형 2줄자막) 자막 띠 한 장 — 흰 바탕 · 검정 **2줄 롤링**.

    ★활용정점형(`shop2`)의 굴러가는 자막을 그대로 옮긴 것이다. 앞 줄이 위에 남고
    새 줄이 아래에 붙으며, 두 줄이 차면 다음 블록에서 통째로 비우고 다시 쌓는다
    (어느 줄이 언제 뜨는지는 `roll_lines` 가 정한다).

    글자 크기는 한 줄짜리 `make_caption` 과 같은 잉크 58 이고, 줄 간격 76 을 얹어도
    185px 띠 안에 위 26 · 아래 24 로 들어앉는다."""
    im = Image.new("RGB", (W, CAP_TRACK_H), C_WHITE)
    d = ImageDraw.Draw(im)
    for k, t in enumerate((line1, line2)):
        if t:
            draw_ink(d, _nomark(t), F_BLACK, P2_CAP_INK,
                     P2_CAP_TOP1 - CAP_TRACK_Y + k * P2_CAP_PITCH,
                     cx=W // 2, fill=C_BLACK, max_w=P2_MAX_CAP_W)
    im.save(out)


# ------------------------------------------------------------- reels 껍데기
def _wrap2(text, path, ink_h, max_w):
    """폭을 넘으면 낱말 경계에서 **두 줄로** 접는다. 양쪽 길이가 비슷한 자리로 가른다."""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f, b = fit(text, path, ink_h)
    if b[2] - b[0] <= max_w:
        return [text], f
    words = text.split()
    if len(words) < 2:
        return [text], f
    best, cost = None, None
    for i in range(1, len(words)):
        a, z = " ".join(words[:i]), " ".join(words[i:])
        c = abs(probe.textlength(a, font=f) - probe.textlength(z, font=f))
        if cost is None or c < cost:
            best, cost = (a, z), c
    return list(best), f


def make_reels_caption(text, out):
    """릴스판 자막 한 장 — 어두운 반투명 판 위 흰 글씨. **알파가 살아 있다.**

    영상이 화면을 통째로 채우므로 자막은 배경 없이 얹힌다. 흰 글씨만으로는 밝은
    장면에서 읽히지 않아 뒤에 어두운 판을 깔고, 판 크기는 글자 폭에 맞춰 줄인다."""
    bh = RE_CAP_BAND[1] - RE_CAP_BAND[0]
    im = Image.new("RGBA", (W, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    lines, _ = _wrap2(_nomark(text), F_BLACK, RE_CAP_INK, RE_CAP_MAX_W)
    block_h = RE_CAP_INK + (len(lines) - 1) * RE_CAP_PITCH
    top = bh - 20 - RE_CAP_PAD_Y - block_h        # 판 아랫선을 띠 바닥에 붙인다
    wmax = 0
    for t in lines:
        f, b = fit(t, F_BLACK, RE_CAP_INK)
        w = b[2] - b[0]
        if w > RE_CAP_MAX_W:
            w = RE_CAP_MAX_W
        wmax = max(wmax, w)
    d.rounded_rectangle([W // 2 - wmax // 2 - RE_CAP_PAD_X, top - RE_CAP_PAD_Y,
                         W // 2 + wmax // 2 + RE_CAP_PAD_X,
                         top + block_h + RE_CAP_PAD_Y],
                        radius=RE_CAP_RADIUS, fill=C_RE_BOX)
    for k, t in enumerate(lines):
        draw_ink(d, t, F_BLACK, RE_CAP_INK, top + k * RE_CAP_PITCH, cx=W // 2,
                 fill=C_WHITE, max_w=RE_CAP_MAX_W)
    im.save(out)


# ------------------------------------------------------------- hottem 껍데기
def make_hottem_top(plan, out, hl_scale=1.0):
    """검정 바탕 위의 «채널명 + 제목 2줄» 판. 인트로와 본편에 **똑같이** 쓴다 —
    핫템형는 제목이 영상 내내 화면에 박혀 있다.

    `hl_scale` 은 제목 두 줄의 크기다. 인트로 카드에서만 1.0 미만으로 시작해
    자라고, 본편 판은 언제나 1.0 이라 카드 끝과 본편 첫 프레임이 그대로 이어진다.

    알파를 살린 RGBA 로 굽는다. 영상(554~) 위에 겹치지 않는 자리라 불투명해도
    되지만, 같은 판을 인트로 카드에도 얹으므로 알파로 두는 편이 다루기 쉽다."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W - 1, HT_VID_Y - 1], fill=(0, 0, 0, 255))
    d.rectangle([0, HT_VID_Y + HT_VID_H, W - 1, H - 1], fill=(0, 0, 0, 255))
    # ★채널명은 **일부러 안 넣는 것이 기본값**이다 (2026-09-03 제작자 지시 —
    #   "상단에 다른 채널 채널이름은 빼줘 다른데 올릴수도 있으니"). `plain` 껍데기가
    #   채널명을 안 박는 것과 같은 이유다 — 이름이 박히는 순간 그 편은 한 채널
    #   전용이 되어, 같은 파일을 다른 채널에 돌려쓸 수 없다.
    #   정말 넣을 편에서만 `plan.hottem_name` 에 이름을 적는다.
    name = plan.get("hottem_name", "")
    if name:
        draw_ink(d, name, F_LOGO, HT_NAME_INK, HT_NAME_TOP, cx=W // 2, fill=C_WHITE)
    # ★제목 두 줄만 따로 그려 얹는다 — 인트로에서 이 두 줄이 «점점 커지기» 때문이다
    #   (2026-09-04 사용자 지시). 검정 바탕까지 함께 키우면 영상 칸을 덮어 버린다.
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dl = ImageDraw.Draw(lay)
    draw_ink(dl, _nomark(plan["hl1"]), F_BLACK, HT_HL1_INK, HT_HL1_TOP, cx=W // 2,
             fill=plan.get("ht1_color", C_HT_Y), stroke=HT_STROKE, max_w=HT_HL_W)
    draw_ink(dl, _nomark(plan["hl2"]), F_BLACK, HT_HL2_INK, HT_HL2_TOP, cx=W // 2,
             fill=plan.get("ht2_color", C_HT_R), stroke=HT_STROKE, max_w=HT_HL_W)
    _paste_zoom(im, lay, HT_ZOOM_CY, hl_scale)
    im.save(out)


def make_hottem_caption(text, out):
    """영상 위에 얹히는 자막 — 흰 글씨 + 검정 테두리, 뒤 판은 없다.
    `reels` 는 반투명 검정 판을 깔지만 핫템은 안 깐다 (실측)."""
    bh = HT_CAP_BAND[1] - HT_CAP_BAND[0]
    im = Image.new("RGBA", (W, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    lines, _ = _wrap2(_nomark(text), F_BLACK, HT_CAP_INK, HT_CAP_MAX_W)
    block_h = HT_CAP_INK + (len(lines) - 1) * HT_CAP_PITCH
    top = (bh - block_h) // 2
    for k, t in enumerate(lines):
        draw_ink(d, t, F_BLACK, HT_CAP_INK, top + k * HT_CAP_PITCH, cx=W // 2,
                 fill=C_WHITE, stroke=HT_CAP_STROKE, max_w=HT_CAP_MAX_W)
    im.save(out)


def make_hottem_caption2(line1, line2, out):
    """영상 위에 얹히는 자막 — **2줄 롤링** (2026-09-03 제작자 지시).

    `make_caption2`(이븐형 2줄자막)와 같은 리듬이고, 다른 것은 흰 띠가 아니라 **영상
    위**라서 흰 글씨 + 검정 테두리로 그린다는 점뿐이다. 어느 줄이 언제 뜨는지는
    `roll_lines` 가 정한다 — 윗줄이 뜨고, 다음 블록에서 그 아래 아랫줄이 붙고,
    두 줄이 차면 통째로 비우고 다시 쌓는다.

    ★`make_hottem_caption`(옛 방식)과 달리 **낱말 경계에서 접지 않는다.** 접으면
    한 블록이 두 줄을 차지해 롤링이 무너지므로, 폭을 넘으면 `max_w` 로 글자를
    줄여 한 줄에 앉힌다 (이븐형 2줄자막 과 같은 처리)."""
    bh = HT_CAP_BAND[1] - HT_CAP_BAND[0]
    im = Image.new("RGBA", (W, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for k, t in enumerate((line1, line2)):
        if t:
            draw_ink(d, _nomark(t), F_BLACK, HT_CAP_INK,
                     HT_CAP_TOP1 - HT_CAP_BAND[0] + k * HT_CAP_PITCH,
                     cx=W // 2, fill=C_WHITE, stroke=HT_CAP_STROKE,
                     max_w=HT_CAP_MAX_W)
    im.save(out)


def make_reels_intro(plan, out, hl_scale=1.0):
    """릴스판 인트로 카드 — 풀블리드 영상 위에 헤드라인 두 줄만 얹은 투명 판.

    ★검정 바탕도 흰 헤더도 없다. 릴스에서 «틀»이 보이는 순간 다른 데서 퍼온 영상이
    된다. 글자는 굵은 검정 테두리와 그림자로 띄운다 (배경이 무엇이든 읽혀야 한다).

    이 판은 처음부터 글자뿐이라 판 통째로 `hl_scale` 을 먹여도 된다."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    hl1, hl2 = _nomark(plan["hl1"]), _nomark(plan["hl2"])
    hw = plan.get("reels_hl_w", RE_HL_MAX_W)
    # 폭으로 맞추되 받침 없는 짧은 문구가 지나치게 커지지 않게 높이 상한을 둔다
    if _ink_h(hl2, hw) > RE_HL_INK_MAX:
        hw = int(hw * RE_HL_INK_MAX / _ink_h(hl2, hw))
    h2 = draw_headline(d, hl2, F_BLACK, RE_HL_BOTTOM, W // 2,
                       plan.get("hl2_color", C_CYAN), hw, stroke=11, shadow=8)
    draw_headline(d, hl1, F_BLACK, RE_HL_BOTTOM - h2 - RE_HL_GAP, W // 2,
                  C_WHITE, hw, stroke=11, shadow=8)
    if abs(hl_scale - 1.0) > 0.002:
        base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        _paste_zoom(base, im, RE_ZOOM_CY, hl_scale)
        im = base
    im.save(out)


def alpha_track(frames, durs, out, work, tag):
    """PNG 들을 길이대로 이어 «알파가 살아 있는» 무손실 영상 하나로 굽는다.

    자막 띠를 불투명 mp4 로 굽는 다른 껍데기와 달리, 릴스판 자막은 영상 위에 떠야
    하므로 qtrle(무손실 RGBA)로 간다. yuv420p 로 굽는 순간 알파가 통째로 날아간다."""
    lst = os.path.join(work, f"_{tag}.txt")
    with open(lst, "w", encoding="utf-8") as fp:
        for p, d in zip(frames, durs):
            fp.write("file '" + p.replace("\\", "/") + f"'\nduration {d:.3f}\n")
        fp.write("file '" + frames[-1].replace("\\", "/") + "'\n")
    run([FF, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
         "-vf", f"fps={FPS},format=rgba", "-c:v", "qtrle", out])
    return out


def build_card_track(plan, maker, ov_intro, intro_sec, work, tag="cardzoom", alpha=False):
    """카드 제목이 «점점 커지는» 오버레이 트랙 하나. 다 자란 뒤에는 완성 판으로 버틴다.

    2026-09-04 사용자 지시 — **첫 화면이 제목이면 그 제목은 정지해 있으면 안 된다.**
    "제목이 쥼인 점점 커지도록 설계 앞으로 제작본에 있어서 모두 적용 할것 왜냐
    화면의 집중도 몰입감을 더 불어 넣기 위함". 커지는 구간만 프레임을 따로 굽고
    나머지는 이미 만들어 둔 완성 판(`ov_intro`) 한 장으로 버티므로, 카드가 길어져도
    굽는 장수는 늘지 않는다.

    `alpha=True` 면 알파를 살린 qtrle 로 굽는다 (영상 위에 글자만 떠야 하는 껍데기)."""
    cdir = os.path.join(work, tag)
    shutil.rmtree(cdir, ignore_errors=True)
    os.makedirs(cdir, exist_ok=True)
    grow = min(CARD_ZOOM_SEC, max(0.25, intro_sec * 0.35))
    nf = max(2, int(round(grow * 30000.0 / 1001.0)))
    frames, durs = [], []
    for k in range(nf):
        u = (k + 1) / nf
        sc = CARD_ZOOM0 + (1.0 - CARD_ZOOM0) * (1 - (1 - u) ** 3)      # ease-out
        p = os.path.join(cdir, f"{k:03d}.png")
        maker(plan, p, hl_scale=sc)
        frames.append(p)
        durs.append(1001.0 / 30000.0)
    frames.append(ov_intro)                       # 다 자란 판
    durs.append(max(0.05, intro_sec - grow))
    out = os.path.join(work, tag + (".mov" if alpha else ".mp4"))
    if alpha:
        alpha_track(frames, durs, out, work, tag)
    else:
        lst = os.path.join(work, f"_{tag}.txt")
        with open(lst, "w", encoding="utf-8") as fp:
            for p, dd in zip(frames, durs):
                fp.write("file '" + p.replace("\\", "/") + f"'\nduration {dd:.4f}\n")
            fp.write("file '" + frames[-1].replace("\\", "/") + "'\n")
        run([FF, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
             "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-crf", "14", out])
    print(f"      카드 제목 확대 {CARD_ZOOM0:.2f}→1.00 · {grow:.2f}초 ({nf}프레임)")
    return out


# ---------------------------------------------------------------- 나레이션 (Typecast)
def tc_post(body, apikey, out, tries=4):
    """★429·403 에는 다시 던지지 않는다. 예전에 되풀이 요청이 어뷰징으로 읽혀
    계정이 정지된 적이 있다. 다시 던지는 것은 5xx 와 진짜 연결 끊김뿐이다."""
    data = json.dumps(body).encode("utf-8")
    backoff = [2, 4, 8, 16]
    last = None
    for a in range(tries):
        req = urllib.request.Request(TC_URL, data=data, method="POST", headers={
            "X-API-KEY": apikey, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                blob = r.read()
            if len(blob) < 2000:
                raise RuntimeError(f"응답이 비었다 ({len(blob)}바이트)")
            with open(out, "wb") as fp:
                fp.write(blob)
            return
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.read()[:200]!r}"
            if e.code not in (500, 502, 503, 504):
                raise SystemExit(f"Typecast 가 거절했다 — 다시 던지지 않는다.\n  {last}")
        except Exception as e:                       # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        if a < tries - 1:
            time.sleep(backoff[min(a, len(backoff) - 1)])
    raise SystemExit(f"Typecast 합성 실패 ({tries}회).\n  마지막 오류: {last}\n"
                     f"  ★키 파일을 확인하라: {TC_KEYFILE}")


def synth(texts, labels, work, tempo_extra=1.0, audio_tempo=1.2, voices=None):
    """블록마다 따로 합성하되 앞뒤 문장을 알려 줘 억양이 이어지게 한다.

    `audio_tempo` 는 **Typecast 가 그 속도로 읽게** 하는 값이다. 다 구워 놓고 atempo 로
    늘이거나 줄이는 것과 달라서 소리가 상하지 않는다. 기본 1.2 는 쇼핑형 규격이므로
    건드리지 않는다 — 느리게 읽어야 하는 형식만 이 값을 낮춰 부른다."""
    if not os.path.exists(TC_KEYFILE):
        raise SystemExit(f"Typecast 키가 없다: {TC_KEYFILE}")
    apikey = open(TC_KEYFILE, encoding="utf-8").read().strip()
    cache = os.path.join(work, "cache", "tts")
    tdir = os.path.join(work, "tts")
    os.makedirs(cache, exist_ok=True)
    os.makedirs(tdir, exist_ok=True)

    # 꼬리는 바짝 자른다 — 초당 1블록 리듬이 여기서 나온다.
    TAIL = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.03:"
            "detection=rms")
    # ★첫 멘트(i=0)의 **머리만** 약하게 자른다. -45dB/rms 로 깎으면 «세척솔»의 ㅅ,
    #   «척»의 ㅊ 같은 여린 마찰음 어택이 통째로 날아가 첫 낱말이 뭉개진다
    #   (2026-08-23 지적). 본문 블록까지 약하게 걸면 블록마다 숨이 남아 편이 4초 길어지고
    #   리듬이 무너지므로, 첫 멘트에만 적용한다.
    HEAD_SOFT = ("silenceremove=start_periods=1:start_threshold=-60dB:start_silence=0.05:"
                 "detection=peak")
    HEAD_TIGHT = TAIL

    def chain(soft_head):
        head = HEAD_SOFT if soft_head else HEAD_TIGHT
        s = f"{head},areverse,{TAIL},areverse,aresample=48000"
        if abs(tempo_extra - 1.0) > 0.005:
            s += f",atempo={tempo_extra:.4f}"
        return s

    wavs, made = [], 0
    for i, (txt, lab) in enumerate(zip(texts, labels)):
        vmap = voices or VOICES
        vid = vmap.get(lab, vmap["NARR"])
        prompt = {"emotion_type": "smart"}
        if i:
            prompt["previous_text"] = texts[i - 1]
        if i < len(texts) - 1:
            prompt["next_text"] = texts[i + 1]
        body = {"voice_id": vid, "text": txt, "model": "ssfm-v30", "language": "KOR",
                "prompt": prompt,
                "output": {"volume": 100, "audio_pitch": 0, "audio_tempo": audio_tempo,
                           "audio_format": "wav"}}
        key = hashlib.sha1(json.dumps(body, ensure_ascii=False,
                                      sort_keys=True).encode("utf-8")).hexdigest()[:16]
        raw = os.path.join(cache, key + ".raw.wav")
        if not (os.path.exists(raw) and os.path.getsize(raw) > 2000):
            tc_post(body, apikey, raw)
            made += 1
            time.sleep(0.25)                 # 요청을 몰아치지 않는다
        out = os.path.join(tdir, f"{i:03d}.wav")
        run([FF, "-y", "-v", "error", "-i", raw, "-af", chain(i == 0),
             "-ac", "2", "-ar", "48000", out])
        if probe_dur(out) < 0.05:            # 묵음 제거가 너무 먹으면 원본으로
            run([FF, "-y", "-v", "error", "-i", raw, "-ac", "2", "-ar", "48000", out])
        wavs.append(out)
    return wavs, made


def narrate(plan, blocks, work):
    """인트로 멘트 1개 + 블록 나레이션. 길이는 합성된 음성의 실측으로 정한다."""
    intro_line = plan.get("intro_line") or plan["post_title"].rstrip("? ").strip()
    texts = [intro_line] + [b["text"] for b in blocks]
    labels = ["NARR"] + [b.get("voice", "NARR") for b in blocks]

    vmap = voices_of(plan)
    if vmap != VOICES:
        print(f"      목소리 갈아 끼움 — NARR {vmap['NARR']}"
              + (f" · PUNCH {vmap['PUNCH']}" if vmap["PUNCH"] != VOICES["PUNCH"] else ""))
    wavs, made = synth(texts, labels, work, voices=vmap)
    print(f"      Typecast {len(texts)}컷 (새로 만든 것 {made}개)")

    # 블록 평균이 규격에서 크게 벗어나면 한 번만 속도를 손본다.
    # ★목표 길이는 형식마다 다르다. 쇼핑형(이븐쇼핑)은 0.93초, 활용정점은 1.5~1.7초라
    #   `plan.target_block` 으로 갈아 끼운다. 안 주면 쇼핑형 값 그대로다.
    target = float(plan.get("target_block", TARGET_BLOCK))
    avg = sum(probe_dur(w) for w in wavs[1:]) / len(blocks)
    tempo = min(1.25, max(1.0, avg / max(0.05, target - GAP)))
    if tempo > 1.02:
        print(f"      블록 평균 {avg:.2f}초 → atempo {tempo:.2f}")
        wavs, _ = synth(texts, labels, work, tempo_extra=tempo, voices=vmap)

    intro_wav, block_wavs = wavs[0], wavs[1:]
    speech = probe_dur(intro_wav)
    # 카드 «말» 구간은 실측 그대로 두고, 그 앞에 lead_in 만큼 무음을 덧댄다.
    # ★기본값 0.35 는 첫 음절이 먹히는 것을 막는 값인데, 2026-08-24 에 사용자가
    #   "앞부분 여백이 너무 길다 — 지금 공백의 1/3로" 라고 해서 편마다 `plan.lead_in`
    #   으로 줄일 수 있게 했다. Typecast 원음에도 0.08초쯤 머리 무음이 붙어 있으므로
    #   완성본의 실제 첫 소리는 이 값보다 그만큼 늦다.
    lead = float(plan.get("lead_in", LEAD_IN))
    card = round(min(INTRO_MAX, max(INTRO_MIN, speech + 0.22)), 3)
    intro_sec = round(lead + card, 3)

    pieces = [_silence(work, lead, "leadin"),
              intro_wav,
              _silence(work, max(0.0, card - speech), f"intropad{lead:.2f}")]
    starts, durs, t = [], [], 0.0
    for i, wav in enumerate(block_wavs):
        d = probe_dur(wav)
        pieces += [wav, _silence(work, GAP, f"g{i:03d}")]
        starts.append(t)
        durs.append(round(d + GAP, 3))
        t += d + GAP
    # ★Typecast 원음은 RMS -34dB 쯤으로 꽤 작다. 효과음과 섞기 전에 기준 크기로
    #   맞춰 두지 않으면 효과음에 나레이션이 묻힌다.
    rawnarr = concat(pieces, os.path.join(work, "narr_raw.wav"), work, "narr")
    narr = os.path.join(work, "narr.wav")
    run([FF, "-y", "-v", "error", "-i", rawnarr,
         # ★loudnorm 은 float 로 뱉기 때문에 0dBFS 를 넘길 수 있다. 리미터를 뒤에 두고
         #   s16 으로 못 박아야 실제로 안 터진다.
         "-af", "loudnorm=I=-16:TP=-2.0:LRA=11,alimiter=limit=0.89:level=disabled",
         "-c:a", "pcm_s16le", "-ac", "2", "-ar", "48000", narr])
    return narr, intro_sec, starts, durs, t


def _silence(work, sec, tag):
    p = os.path.join(work, "tts", f"_sil_{tag}.wav")
    run([FF, "-y", "-v", "error", "-f", "lavfi", "-t", f"{max(0.01, sec):.4f}",
         "-i", "anullsrc=r=48000:cl=stereo", p])
    return p


# ---------------------------------------------------------------- 효과음
def _sfx_peak(path, _cache={}):
    """효과음 파일의 최대 진폭 (0~1)."""
    if path in _cache:
        return _cache[path]
    raw = subprocess.run([FF, "-v", "error", "-i", path, "-ac", "1", "-ar", "8000",
                          "-f", "s16le", "-"], capture_output=True).stdout
    import array
    a = array.array("h")
    a.frombytes(raw[:len(raw) // 2 * 2])
    _cache[path] = (max((abs(v) for v in a), default=1) / 32768.0) or 1.0
    return _cache[path]


def build_sfx(events, total, work):
    """events = [(초, 파일명, **목표 봉우리 크기**)] → 전체 길이짜리 효과음 트랙 한 개.

    ★셋째 값은 곱하는 게인이 아니라 **그 소리가 트랙에서 가질 봉우리 크기**다.
      자산 78개는 원음 크기가 제각각이라(같은 0.34 를 줘도 어떤 건 −3dB, 어떤 건
      −15dB 로 들어간다) 게인을 손으로 맞추면 편마다 들쭉날쭉해진다. 파일의 실제
      봉우리를 재서 목표에 맞춰 나눈다 — 그러면 «넣었는데 안 들린다» 가 구조적으로
      사라진다 (2026-08-24)."""
    out = os.path.join(work, "sfx_bed.wav")
    have = []
    for t, f, g in events:
        p = os.path.join(SFX_DIR, f)
        if os.path.exists(p):
            have.append((t, p, min(4.0, g / _sfx_peak(p))))
    if not have:
        print("      ⚠ 효과음 파일을 못 찾았다 — 효과음 없이 간다")
        return _silence(work, total, "nosfx")
    argv = [FF, "-y", "-v", "error", "-f", "lavfi", "-t", f"{total:.3f}",
            "-i", "anullsrc=r=48000:cl=stereo"]
    for _, p, _ in have:
        argv += ["-i", p]
    parts, tags = [], ["[0:a]"]
    for i, (t, _, g) in enumerate(have, 1):
        ms = int(round(t * 1000))
        parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,"
                     f"adelay={ms}|{ms},volume={g:.3f}[s{i}]")
        tags.append(f"[s{i}]")
    # ★normalize=0 이면 amix 가 이미 그냥 더한다. 여기에 입력 개수를 곱하면
    #   효과음이 통째로 터진다(실측: peak +3dB 로 클리핑, 나레이션이 묻혔다).
    parts.append("".join(tags) + f"amix=inputs={len(tags)}:duration=first:normalize=0[o]")
    argv += ["-filter_complex", ";".join(parts), "-map", "[o]",
             "-t", f"{total:.3f}", "-ac", "2", "-ar", "48000", out]
    run(argv)
    return out


# ---------------------------------------------------------------- 컷 만들기
def _abs(work, p):
    return p if os.path.isabs(p) else os.path.join(work, p)


def probe_size(path):
    w, h = run([FPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=width,height", "-of", "csv=p=0:s=x", path]).strip().split("x")[:2]
    return int(w), int(h)


SUB_MAX_BAND = 0.12     # 자막 띠 두께 상한 (프레임 높이 대비)
# ★파일 전체가 아니라 **컷이 쓰는 구간**을 본다. 소스는 몇 분짜리인데 컷은 1초라,
#   파일 단위로 표본을 뜨면 잠깐 뜨는 자막이 평균에 묻혀 통째로 안 잡힌다
#   (개방형 빨대 편의 `(탄력적!!!)` 을 그렇게 놓쳤다). 구간 안에서는 자막이 대부분의
#   프레임에 떠 있으므로 비율을 높게 잡아도 잘 잡힌다.
#   0.5 로 잡았더니 컷 끝에서 잠깐 뜨는 `톡!` 같은 짧은 자막을 놓쳤다. 0.25 가 맞다.
SUB_MIN_SHARE = 0.25    # 구간 프레임 중 그 행이 잡혀야 하는 비율


def burned_sub_bands(path, ss=0.0, dur=None, _cache={}):
    """소스에 **박힌 자막** 띠가 있으면 [(윗선, 아랫선), ...] 을 원본 y 로 돌려준다.

    ★남의 영상에는 자막이 구워져 있는 경우가 흔하다 — 중국 소스의 중국어·영어 자막,
    한국 소스의 `(탄력적!!!)` 같은 손자막. 그대로 쓰면 우리 자막 띠 아래에 남의 자막이
    같이 보인다 (2026-08-22 개방형 빨대·전동 서핑보드 편에서 사용자가 지적).

    ★자막은 화면 **어디에나** 있을 수 있다. 처음엔 아래쪽 45% 만 뒤졌다가 화면 위쪽에
    박힌 한글 자막을 통째로 놓쳤다. 그래서 세로 전체를 본다.

    ★글자를 로고·제품 무늬와 가르는 잣대는 세 가지다 (실측으로 정했다).
      양쪽 테두리 — 자막은 글자 양옆에 반대 밝기가 붙는다. 흰 글자면 좌우가 어둡고,
                    검은 글자면 좌우가 밝다. 한쪽만 보면 금속 모서리·물결에 걸린다.
      두께 — 자막은 얇다. 실측 44·50·98px. 헛짚은 것(보드에 박힌 JETFLY 로고 + 물결)은
             252px 였다. 프레임 높이의 12% 를 넘으면 자막이 아니다.
      빈도 — 자막은 자주 떠 있다. 실측 40프레임 중 9·18·18. 헛짚은 것은 3뿐이었다."""
    dur = dur or probe_dur(path)
    key = (path, round(ss, 2), round(dur, 2))
    if key in _cache:
        return _cache[key]
    try:
        import numpy as np
    except ImportError:
        _cache[key] = []
        return []
    w, h = probe_size(path)
    n = max(6, min(20, int(dur * 10)))
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{ss:.3f}", "-i", path,
                          "-t", f"{dur:.3f}", "-vf", f"fps={n / max(dur, 0.3):.4f}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True).stdout
    got = len(raw) // (w * h)
    if got < 3:
        _cache[key] = []
        return []
    fr = np.frombuffer(raw, dtype=np.uint8)[:got * w * h].reshape(got, h, w).astype(np.int16)
    hits = np.zeros(h)
    for i in range(got):
        a = fr[i]
        # 밝기가 확 꺾이는 자리 — 흰 글자든 검은 글자든 글자에는 이런 모서리가 많다.
        # ★어두운 쪽 문턱을 110 까지 열어 둔다. 60 으로 잡았더니 흰 바탕 위의
        #   **초록 글자**(`톡!` 같은 손자막, 휘도 95쯤)를 통째로 놓쳤다.
        light = (a[:, 2:] >= 215) & (a[:, :-2] <= 120)
        dark = (a[:, 2:] <= 110) & (a[:, :-2] >= 195)
        hits += ((light | dark).sum(axis=1) > 6)

    hot = hits >= max(3, got * SUB_MIN_SHARE)
    bands, y = [], 0
    while y < h:                                   # 붙어 있는 행끼리 묶는다
        if hot[y]:
            a = y
            while y < h and (hot[y] or (y - a < 14 and hot[y:y + 14].any())):
                y += 1
            if (y - a) <= h * SUB_MAX_BAND:
                bands.append((a, y - 1))
        else:
            y += 1
    _cache[key] = bands
    return bands


# ★가로 소스(1280×720 등)를 9:16 칸에 넣으면 세로를 통째로 쓰므로 크롭을 밀 여유가
#   0 이다. 자막을 빼려면 더 당기는 수밖에 없어서 한도를 넉넉히 잡았다. 그만큼 좌우가
#   더 잘리므로, 이 값을 올렸으면 결과를 눈으로 보고 피사체가 살아 있는지 확인한다.
SUB_MAX_ZOOM = 1.85     # 자막을 피하려고 더 당길 수 있는 한도 (기본 배율 대비)


def plan_crop(bands, w, h, out_w, out_h, max_zoom=SUB_MAX_ZOOM):
    """자막 띠를 피해 (배율, 크롭 y) 를 고른다. 돌려주는 셋째 값은 피했는지 여부.

    ★두 가지 수를 쓴다.
      1) **크롭 창을 민다** — 위로도 아래로도. 자막이 위에 박힌 소스는 내려야 빠진다.
      2) **살짝 더 당긴다** — 위아래 여유가 아예 없는 소스(예: 1280×520 처럼 납작한
         원본은 세로를 통째로 쓴다)에서는 미는 것만으로 안 된다. 그럴 때 배율을
         조금 올려 자리를 만든다. 화질이 상하므로 기본 배율의 1.4배까지만 허용한다.
    잘라내고 다시 확대하는 것보다 이쪽이 항상 낫다."""
    sc0 = max(out_w / w, out_h / h)
    if not bands:
        return sc0, (h * sc0 - out_h) / 2, True

    # 자막을 뺀 '깨끗한' 세로 구간들 (원본 좌표)
    runs, y = [], 0
    for a, b in sorted(bands):
        a2, b2 = max(0, a - 4), min(h - 1, b + 4)
        if a2 - y >= 8:
            runs.append((y, a2 - 1))
        y = max(y, b2 + 1)
    if h - y >= 8:
        runs.append((y, h - 1))

    best = None
    for a, b in runs:
        span = b - a + 1
        sc = max(sc0, out_h / span)          # 이 구간에 창을 넣으려면 필요한 배율
        if sc > sc0 * max_zoom:
            continue
        nh = h * sc
        # 구간 [a, b] 는 b-a+1 행이므로 아래 경계는 (b+1)*sc 다. b*sc 로 쓰면
        # 딱 맞는 배율에서도 1픽셀 모자라 늘 실패한다.
        lo, hi = a * sc, (b + 1) * sc - out_h
        if hi < lo - 0.5:
            continue
        hi = max(hi, lo)
        mid = (nh - out_h) / 2
        y0 = min(max(mid, lo), hi)           # 되도록 원본 중앙에 가깝게
        cost = (sc / sc0 - 1) * 3 + abs(y0 - mid) / max(nh, 1)
        if best is None or cost < best[0]:
            best = (cost, sc, y0)
    if best is None:
        return sc0, (h * sc0 - out_h) / 2, False
    return best[1], best[2], True


def pick_vid_h(path, ss, dur, work, ladder=None):
    """shop2·shop3 전용 — 이 컷의 영상 칸 높이를 고른다.

    ★남의 영상에 구워진 자막을 **띠를 좁혀서** 화면 밖으로 밀어내는 것이 이 채널의
    기법이다. 크롭 창을 위아래로 미는 방식은 피사체가 한쪽으로 쏠리지만, 좁히는
    방식은 **제품이 정중앙에 남는다.** 그래서 «자막을 피하면서 가장 가운데인» 높이를
    고르되, 같은 조건이면 큰 띠를 쓴다.

    `ladder` 는 고를 수 있는 높이들이다. 활용정점형(`shop2`)은 888~1014 여섯 칸이고,
    정밀판(`shop3`)은 30편 실측대로 **598~1014 열일곱 칸**이라 자막을 더 밀어낼 수 있다."""
    ladder = ladder or S2_VID_HS
    p = _abs(work, path)
    bands = burned_sub_bands(p, ss, dur)
    if not bands:
        return ladder[0], None
    sw, sh = probe_size(p)
    best = None
    for hh in ladder:
        sc, cy, clean = plan_crop(bands, sw, sh, W, hh)
        if not clean:
            continue
        off = abs(cy - (sh * sc - hh) / 2)          # 가운데에서 벗어난 정도
        cost = off / 40.0 + (ladder[0] - hh) / 26.0
        if best is None or cost < best[0]:
            best = (cost, hh, cy, off)
    if best is None:
        return ladder[0], None
    _, hh, cy, off = best
    if hh != ladder[0]:
        print(f"      {os.path.basename(p)}: 띠를 {hh}px 로 좁혀 박힌 자막을 밀어냄"
              f" (가운데에서 {off:.0f}px)")
    return hh, cy


def s2_panel_x(width, align=None, vid_x=None):
    """영상 칸의 왼쪽 자리 — 가운데(기본) · 왼쪽 끝 · 오른쪽 끝.

    ★원본은 칸을 늘 가운데 두지 않는다. 실측(XGPOSNsM2-8)에서 885폭 칸이 오른쪽 끝에
    붙고(왼쪽 흰 여백 195), 897폭 칸이 왼쪽 끝에 붙었다(오른쪽 여백 183). 자세한 것은
    reference/화면규격.md 3절."""
    if vid_x is not None:
        return max(0, min(W - width, int(vid_x)))
    if align == "left":
        return 0
    if align == "right":
        return W - width
    return (W - width) // 2


def fit_panel(path, max_w=W, max_h=None):
    """소스를 **하나도 안 자르고** 담을 수 있는 영상 칸 크기를 돌려준다 (짝수).

    ★원본 채널이 칸을 좁히는 까닭이 이것이다. 칸은 «잘라내는 창»이 아니라 «그림이
    들어앉는 자리»라서, 세로로 긴 소스가 오면 칸이 좁아지고 양옆이 흰 여백이 된다.
    실측한 칸들(766×997 · 828×962 · 972×979)의 가로세로비가 제각각인 것도 그래서다.

    2026-08-25 에 이걸 거꾸로 구현했다가 반려됐다 — 칸을 좁혔더니 그림이 작아지는 게
    아니라 양옆이 더 잘려서 "너무 확대되니 보기 거북스럽다"는 말을 들었다. 소스를
    통째로 보여 주는 것이 먼저고, 칸 크기는 그 결과다."""
    sw, sh = probe_size(path)
    max_h = max_h or S2_VID_HS[0]
    sc = min(max_w / sw, max_h / sh)
    w = max(2, int(round(sw * sc)) & ~1)
    h = max(2, int(round(sh * sc)) & ~1)
    return w, h


def bake_clip(src, ss, dur, out, height, work, crop_y=None, pad_h=None,
              pad_rgb=C_S2_PAD, vid_w=None, align=None, vid_x=None,
              pad_max=None):
    """소스 구간을 잘라 vid_w×height 짜리 '움직이는 클립'을 굽고 1080 폭에 앉힌다.

    기본은 세로 중앙 크롭이지만, 소스 아래에 박힌 자막이 있으면 **크롭 창을 위로
    밀어** 그 띠를 화면 밖으로 내보낸다. 잘라내고 다시 확대하는 것보다 화질 손해가
    없다. `crop_y`(출력 화소 기준 위에서부터의 오프셋)를 주면 그 값을 그대로 쓴다.

    ★`vid_w` 를 주면 영상 칸이 화면 폭보다 좁아지고 남는 양옆이 흰 여백이 된다.
    `align`(`left`·`right`) 또는 `vid_x` 로 그 칸을 한쪽 끝에 붙일 수 있다. 원본이
    컷마다 칸을 좁히고 좌우로 옮기는 기법을 그대로 쓴 것이다."""
    path = _abs(work, src)
    sw, sh = probe_size(path)
    vw = int(vid_w or W)
    vw = max(2, min(W, vw - (vw % 2)))       # 짝수여야 libx264 가 받는다
    sc = max(vw / sw, height / sh)
    if crop_y is None:
        bands = burned_sub_bands(path, ss, dur)
        sc, crop_y, clean = plan_crop(bands, sw, sh, vw, height)
        if bands:
            tag = os.path.basename(path)
            ys = "·".join(f"{a}~{b}" for a, b in bands)
            if clean:
                zoom = sc / max(vw / sw, height / sh)
                extra = f", {zoom:.2f}배로 더 당겨서" if zoom > 1.005 else ""
                print(f"      {tag}: 박힌 자막(원본 y{ys}) 피함{extra}")
            else:
                print(f"      ⚠ {tag}: 박힌 자막(원본 y{ys})을 피할 수 없다. "
                      f"다른 구간을 쓰거나 소재를 갈아라")
    nw, nh = int(round(sw * sc)), int(round(sh * sc))
    crop_y = max(0, min(nh - height, int(round(crop_y))))
    vf = (f"scale={nw}:{nh},crop={vw}:{height}:{(nw - vw) // 2}:{crop_y},"
          f"fps={FPS},setsar=1")
    # ★shop2 는 컷마다 영상 칸의 높이와 폭이 다르다. 그대로 이으면 concat 이 안 되므로
    #   고른 칸만큼만 그리고 **남는 자리를 흰색으로 채워** 판 크기를 하나로 맞춘다.
    ph = pad_h or height
    if ph > height or vw < W:
        px = s2_panel_x(vw, align, vid_x)
        # ★칸이 낮으면 아래 흰 여백만 커져 화면이 위로 쏠린다. 실측 원본의 아래 여백은
        #   262~389px 이라, 그보다 많이 남으면 칸을 내려 위아래로 나눠 준다.
        py = 0
        pmax = S2_PAD_MAX if pad_max is None else pad_max
        if pad_h and ph - height > pmax:
            py = int(round((ph - height - pmax) * 0.5))
        vf += f",pad={W}:{ph}:{px}:{py}:color=0x%02X%02X%02X" % pad_rgb
    run([FF, "-y", "-v", "error", "-ss", f"{ss:.3f}", "-i", path,
         "-t", f"{dur:.3f}", "-an", "-vf", vf,
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out])
    return out


def build_cuts(plan, blocks, durs, work, vid_h=None, s2=False):
    """src/ss 가 붙은 블록에서 새 컷이 시작된다. 컷은 언제나 '움직이는 클립'이다.

    ★블록 하나 안에서 컷을 한 번 더 바꾸려면 `src2`(+`ss2`)를 준다. 레퍼런스 5편의
    컷 수는 자막 블록 수의 1.08~1.42배였다 — 조회수가 큰 편일수록 컷이 촘촘했다
    (kC8 35컷/25블록, Y2Y 37컷/26블록). 자막 한 줄에 컷 하나로만 가면 원본보다
    느슨해진다. 쪼갤 자리는 `cut_at`(0~1, 기본 0.5)로 옮길 수 있다."""
    cuts, cur, block_cut = [], None, []

    def open_cut(src, ss, crop_y=None, vh=None, vw=None, align=None, vx=None,
                 fit=False):
        nonlocal cur
        if src is None:
            raise SystemExit("첫 블록에 src 가 없다. plan.json 을 확인하라.")
        cur = {"src": src, "ss": float(ss), "d": 0.0, "texts": [], "crop_y": crop_y}
        # ★블록에 vid_h 를 주면 그 컷의 영상 칸 높이를 손으로 정한다. 자막이 화면
        #   정중앙에 박힌 소스는 pick_vid_h 가 «자막을 피하는» 높이만 보고 고르느라
        #   컷마다 창이 제멋대로 오르내려 제품이 가운데에서 밀려난다 (2026-08-25
        #   만능 보수제 편에서 사용자가 지적). crop_y 와 짝으로 준다.
        if vh:
            cur["vid_h"] = int(vh)
        # ★vid_w / align 은 «영상 칸을 좁히고 좌우로 옮기는» 원본 기법이다.
        if vw:
            cur["vid_w"] = int(vw)
        if align:
            cur["align"] = align
        if vx is not None:
            cur["vid_x"] = int(vx)
        # ★fit — 소스를 하나도 안 자르고 담는다. vid_w·vid_h 는 «칸의 한도»로 읽는다.
        if fit:
            fw, fh = fit_panel(_abs(work, src), vw or W, vh or _ladder(plan)[0])
            cur["vid_w"], cur["vid_h"], cur["crop_y"] = fw, fh, 0
        cuts.append(cur)

    for b, d in zip(blocks, durs):
        if b.get("src") or cur is None:
            open_cut(b.get("src") or (cuts[-1]["src"] if cuts else None),
                     b.get("ss", 0.0), b.get("crop_y"), b.get("vid_h"),
                     b.get("vid_w"), b.get("align"), b.get("vid_x"), b.get("fit"))
        block_cut.append(len(cuts) - 1)          # 이 자막이 처음 얹히는 컷
        cur["texts"].append(b["text"])
        if b.get("src2"):
            head = d * min(0.9, max(0.1, float(b.get("cut_at", 0.5))))
            cur["d"] += head
            open_cut(b["src2"], b.get("ss2", 0.0), b.get("crop_y2"), b.get("vid_h2"),
                     b.get("vid_w2"), b.get("align2"), b.get("vid_x2"), b.get("fit2"))
            cur["d"] += d - head
        else:
            cur["d"] += d

    cdir = os.path.join(work, "cuts")
    os.makedirs(cdir, exist_ok=True)
    for i, c in enumerate(cuts):
        hh, cy, pad = vid_h or BODY_VID_H, c.get("crop_y"), None
        if s2:
            pad = S2_PAD_H
            if c.get("vid_h"):                      # plan 에서 손으로 정해 줄 수도 있다
                hh, cy2 = int(c["vid_h"]), None
            else:
                hh, _ = pick_vid_h(c["src"], c["ss"], c["d"], work, _ladder(plan))
            # ★pick_vid_h 가 고른 crop_y 를 그대로 넘기지 않는다. 그 값은 «자막을
            #   피하려고 더 당긴» 배율(plan_crop 이 돌려준 sc)에서 잰 것인데,
            #   bake_clip 은 crop_y 를 받으면 배율을 다시 재지 않고 **기본 배율**로
            #   자른다. 그래서 넘기는 순간 창이 엉뚱한 자리로 내려가, 피하려던 워터마크가
            #   화면에 그대로 남는다 (2026-08-24 접이식 책상 편에서 잡았다 — 상단 자막은
            #   빠졌는데 하단 워터마크가 통째로 살아 있었다).
            #   비워 두면 bake_clip 이 배율과 crop_y 를 **함께** 다시 계산한다.
            #   burned_sub_bands 는 캐시가 있어 다시 훑지 않으므로 비용도 없다.
        c["vid_h"] = hh
        c["mp4"] = bake_clip(c["src"], c["ss"], c["d"],
                             os.path.join(cdir, f"{i:02d}.mp4"), hh,
                             work, crop_y=cy, pad_h=pad,
                             vid_w=c.get("vid_w"), align=c.get("align"),
                             vid_x=c.get("vid_x"), pad_max=_pad_max(plan))
        c["wav"] = os.path.join(cdir, f"{i:02d}.wav")
        r = subprocess.run([FF, "-y", "-v", "error", "-ss", f"{c['ss']:.3f}",
                            "-i", _abs(work, c["src"]), "-t", f"{c['d']:.3f}",
                            "-vn", "-ac", "2", "-ar", "48000", c["wav"]],
                           capture_output=True)
        if r.returncode != 0 or not os.path.exists(c["wav"]):
            run([FF, "-y", "-v", "error", "-f", "lavfi", "-t", f"{c['d']:.3f}",
                 "-i", "anullsrc=r=48000:cl=stereo", c["wav"]])

    # ★컷마다 프레임 경계로 잘리면서 조금씩 짧아진다. 컷이 열 개를 넘으면 그 부스러기가
    #   0.4초까지 쌓이고, 그만큼 **마지막 프레임이 멈춘 채로** 끝난다 (2026-09-02 핫템
    #   유리컵 편에서 잡았다 — 컷 11개에 body_raw 31.498 / 필요 31.932).
    #   마지막 컷에게 모자란 만큼을 더 주어 메운다. 소스가 모자라면 더 못 늘리므로
    #   그때는 경고만 하고 넘어간다 (정지 검사에서 다시 걸린다).
    want = sum(c["d"] for c in cuts)
    have = sum(probe_dur(c["mp4"]) or 0.0 for c in cuts)
    short = want - have
    if short > 0.05 and cuts:
        last = cuts[-1]
        src_left = (probe_dur(_abs(work, last["src"])) or 0.0) - last["ss"]
        extra = min(short + 0.10, max(0.0, src_left - last["d"]))
        if extra > 0.02:
            last["d"] += extra
            last["mp4"] = bake_clip(
                last["src"], last["ss"], last["d"],
                os.path.join(cdir, f"{len(cuts) - 1:02d}.mp4"), last["vid_h"],
                work, crop_y=last.get("crop_y"), pad_max=_pad_max(plan),
                pad_h=(S2_PAD_H if s2 else None),
                vid_w=last.get("vid_w"), align=last.get("align"),
                vid_x=last.get("vid_x"))
            print(f"      컷 부스러기 {short:.2f}초를 마지막 컷에 더했다 (+{extra:.2f}초)")
        else:
            print(f"      ⚠ 컷이 {short:.2f}초 모자란데 마지막 소스에 여유가 없다 — "
                  f"«{last['src']}» 를 그만큼 길게 잘라 두라")
    return cuts, block_cut


def build_intro_clip(plan, cuts, intro_sec, work, vid_h=None, s2=False):
    """인트로 카드 1.5~2.0초 안에 들어가는 정사각 영상.

    ★원본은 이 짧은 카드 안에서도 컷을 2~4번 바꾼다 (실측: ABjQ 0.53/1.40 에서 전환,
    Y2Y 0.47/1.03 에서 전환). 제품의 제일 센 장면들을 0.4초씩 몰아쳐 보여 주는 것이
    첫 2초를 버티게 하는 장치다. 한 클립을 통으로 깔면 그 장치가 없어진다.
    `plan.intro_cuts = [{"src": "s01.mp4", "ss": 3.2}, ...]` 로 준다."""
    specs = plan.get("intro_cuts") or [{"src": cuts[0]["src"], "ss": cuts[0]["ss"]}]
    idir = os.path.join(work, "cuts")
    os.makedirs(idir, exist_ok=True)
    each = intro_sec / len(specs)
    parts = []
    for i, s in enumerate(specs):
        hh, cy, pad = vid_h or INTRO_VID_H, s.get("crop_y"), None
        vw_i = s.get("vid_w")
        if s2:
            pad = S2_PAD_H
            if s.get("fit"):                        # 소스를 안 자르고 담는다
                vw_i, hh = fit_panel(_abs(work, s["src"]),
                                     s.get("vid_w") or W,
                                     s.get("vid_h") or _ladder(plan)[0])
                cy = 0
            elif s.get("vid_h"):                    # 손으로 정해 준 창
                hh = int(s["vid_h"])
            else:
                hh, _ = pick_vid_h(s["src"], float(s.get("ss", 0.0)), each, work,
                                   _ladder(plan))
            # ★pick_vid_h 가 돌려준 crop_y 를 여기서도 쓰면 안 된다 — 본편(build_cuts)
            #   과 같은 이유다. 그 값은 «더 당긴» 배율에서 잰 것인데 bake_clip 은
            #   crop_y 를 받으면 기본 배율로 자르므로 창이 엉뚱한 자리로 내려간다.
            #   비워 두면 bake_clip 이 배율과 crop_y 를 함께 다시 계산한다.
        parts.append(bake_clip(s["src"], float(s.get("ss", 0.0)), each,
                               os.path.join(idir, f"intro{i:02d}.mp4"), hh,
                               work, crop_y=cy, pad_h=pad,
                               vid_w=vw_i, align=s.get("align"),
                               vid_x=s.get("vid_x"), pad_max=_pad_max(plan)))
    if len(parts) == 1:
        return parts[0], 1
    return concat(parts, os.path.join(work, "intro_raw.mp4"), work, "intro",
                  reenc=True), len(parts)


def _is_silent(wav, floor_db=-60.0):
    out = subprocess.run([FF, "-v", "error", "-i", wav, "-ac", "1", "-ar", "8000",
                          "-f", "s16le", "-"], capture_output=True).stdout
    if not out:
        return True
    import array
    a = array.array("h")
    a.frombytes(out[:len(out) // 2 * 2])
    peak = max(abs(v) for v in a) / 32768.0 if a else 0.0
    return peak <= 10 ** (floor_db / 20.0)


def concat(paths, out, work, tag, reenc=False):
    """★`reenc=True` 는 이어 붙이면서 다시 굽는다.

    컷 수십 개를 `-c copy` 로 이어 붙이면 조각마다 표시 시각이 프레임 길이의
    반올림만큼 어긋난 채 쌓인다. 그 스트림을 뒤에서 filter_complex 의 `fps=` 로
    다시 열면 겹친 시각의 프레임이 **버려져서** 그 자리에 바탕색이 그대로 드러난다
    — 검은 화면이 2~3프레임 번쩍인다(2026-08-25 투명 방수젤 편에서 869프레임 중
    9프레임이 버려졌고, 이음매 9군데가 번쩍였다).

    `-fps_mode cfr -r FPS` 로 이어 붙이면서 다시 구우면 시각이 정확히 균일해져
    한 프레임도 안 버려진다. `setpts=N/FRAME_RATE/TB` 로는 안 된다 — concat
    입력에서는 영상이 6초에서 잘린다."""
    lst = os.path.join(work, f"_{tag}.txt")
    with open(lst, "w", encoding="utf-8") as fp:
        for p in paths:
            fp.write("file '" + p.replace("\\", "/") + "'\n")
    tail = (["-fps_mode", "cfr", "-r", FPS, "-c:v", "libx264",
             "-crf", "16", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an"]
            if reenc else ["-c", "copy"])
    run([FF, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst] + tail + [out])
    return out


# ---------------------------------------------------------------- 렌더
def render(work):
    work = os.path.abspath(work)
    plan = json.load(open(os.path.join(work, "plan.json"), encoding="utf-8"))
    plan.setdefault("channel", "쇼핑형")
    plan.setdefault("metrics", "조회수 235만 | 댓글 697개")
    blocks = plan["blocks"]
    out_dir = os.path.join(work, "out")
    os.makedirs(out_dir, exist_ok=True)

    print(f"[1/7] 나레이션 — 인트로 멘트 1 + 블록 {len(blocks)}")
    narr, intro_sec, starts, durs, body_sec = narrate(plan, blocks, work)
    avg = body_sec / len(blocks)
    print(f"      인트로 카드 {intro_sec:.2f}초 · 본편 {body_sec:.2f}초 · "
          f"블록 평균 {avg:.2f}초" + ("  ⚠ 규격(0.9~1.1초) 밖" if not 0.75 <= avg <= 1.30 else "  ✓"))

    s2 = is_s2(plan)                     # shop2(활용정점형) · shop3(활용정점 정밀형)
    reels = shell_of(plan) == "reels"
    p2 = shell_of(plan) == "plain2"      # 이븐형 2줄자막 — plain 좌표 + 2줄 롤링 자막
    ht = shell_of(plan) == "hottem"      # 핫템형 — 영상 위에 자막이 얹힌다
    roll = rolls(plan)
    # shop2 는 컷마다 다르다 (pick_vid_h). reels 는 화면을 통째로 채운다.
    vid_h = H if reels else (HT_VID_H if ht else (None if s2 else BODY_VID_H))

    print("[2/7] 오버레이 판")
    ov_head = os.path.join(work, "ov_header.png")
    ov_intro = os.path.join(work, "ov_intro.png")
    if s2:
        # shop2 는 헤더 안에 자막이 들어가므로 본편 헤더를 블록마다 다시 그린다.
        make_shop2_top(plan, ov_intro, card=True)
    elif reels:
        make_reels_intro(plan, ov_intro)     # 본편에는 오버레이 판이 없다
    elif ht:
        # ★인트로와 본편이 **같은 판**이다 — 제목이 영상 내내 화면에 박혀 있다.
        make_hottem_top(plan, ov_head)
        make_hottem_top(plan, ov_intro)
    else:
        make_body_header(plan, ov_head)
        make_intro_top(plan, ov_intro)

    print("[3/7] 헤더 판 (2줄 롤링 자막)" if s2 else
          ("[3/7] 자막 (영상 위 · 2줄 롤링)" if roll else
           "[3/7] 자막 (영상 위에 얹음)") if ht else
          "[3/7] 자막 띠 (2줄 롤링)" if p2 else "[3/7] 자막 띠")
    capdir = os.path.join(work, "caps")
    os.makedirs(capdir, exist_ok=True)
    texts = [b["text"] for b in blocks]
    caps = []
    for i, b in enumerate(blocks):
        p = os.path.join(capdir, f"{i:03d}.png")
        if s2:
            l1, l2 = roll_lines(texts, i)
            make_shop2_top(plan, p, l1, l2)
        elif reels:
            make_reels_caption(b["text"], p)
        elif ht:
            if roll:
                l1, l2 = roll_lines(texts, i)
                make_hottem_caption2(l1, l2, p)
            else:
                make_hottem_caption(b["text"], p)
        elif p2:
            l1, l2 = roll_lines(texts, i)
            make_caption2(l1, l2, p)
        else:
            make_caption(b["text"], p)
        caps.append(p)
    if reels or ht:
        # 영상 위에 떠야 하므로 알파를 살린 무손실 트랙으로 굽는다
        capvid = alpha_track(caps, durs, os.path.join(work, "capstrip.mov"), work, "caps")
    else:
        lst = os.path.join(work, "_caps.txt")
        with open(lst, "w", encoding="utf-8") as fp:
            for p, d in zip(caps, durs):
                fp.write("file '" + p.replace("\\", "/") + f"'\nduration {d:.3f}\n")
            fp.write("file '" + caps[-1].replace("\\", "/") + "'\n")
        capvid = os.path.join(work, "capstrip.mp4")
        run([FF, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
             "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-crf", "14", capvid])

    print("[4/7] 컷 자르기 (움직이는 클립)")
    cuts, block_cut = build_cuts(plan, blocks, durs, work, vid_h=vid_h, s2=s2)
    ratio = len(cuts) / len(blocks)
    # 컷 밀도의 잣대는 껍데기가 아니라 **대본 리듬**이다. 같은 plan 을 껍데기만 갈아
    # 끼워 여러 판을 굽으므로(mk_variants), 활용정점 계열인지는 target_block 으로 본다.
    slow = float(plan.get("target_block", TARGET_BLOCK)) >= 1.2
    if s2 or slow:            # 활용정점 계열은 컷이 느리다 — 블록의 0.5배가 목표다
        print(f"      컷 {len(cuts)}개 / 자막 {len(blocks)}블록 = {ratio:.2f}배"
              + ("  ✓" if 0.35 <= ratio <= 0.75 else "  ⚠ 이 형식의 목표는 0.5배다"))
    else:
        print(f"      컷 {len(cuts)}개 / 자막 {len(blocks)}블록 = {ratio:.2f}배"
              + ("  ✓" if ratio >= 1.05 else "  ⚠ 원본은 1.08~1.42배다. src2 로 컷을 더 쪼개라"))
    body_raw = concat([c["mp4"] for c in cuts], os.path.join(work, "body_raw.mp4"), work, "body",
                      reenc=True)
    amb_raw = concat([c["wav"] for c in cuts], os.path.join(work, "amb_raw.wav"), work, "amb")
    if plan.get("mute_source"):
        print("      현장음 끔 (plan.mute_source) — 원본에 사람 나레이션이 깔린 소재")
    elif _is_silent(amb_raw):
        print("      ⚠ 소스에 오디오가 없다. 현장음 층이 비었다 —"
              " 소재를 받을 때 오디오를 버리지 않았는지 보라")

    print("[5/7] 효과음")
    total = intro_sec + body_sec
    # ★«활용정점» 계열은 효과음을 한 발도 안 쓴다 (원본 5편 실측 0발, 대신 BGM).
    #   plan.no_sfx 를 주면 컷 클릭·스우시·마무리까지 통째로 끈다. 쇼핑형 편은
    #   이 값을 안 주므로 동작이 그대로다.
    if plan.get("no_sfx"):
        sfx = _silence(work, total, "nosfx")
        print("      효과음 끔 (plan.no_sfx) — 활용정점 계열")
    else:
        # ★카드 등장 스우시는 **말이 시작되기 전** 머리 여유(LEAD_IN) 안에서 끝나야 한다.
        #   전에는 0.04초에 0.42 게인으로 깔려 첫 낱말을 통째로 덮었다(2026-08-23 지적).
        #   그런데 swoosh_1 은 0.756초짜리라 LEAD_IN(0.35초)을 훌쩍 넘어 첫 멘트 위에
        #   그대로 얹힌다 — 2026-08-24 실측(나레이션 0.427초 시작). 그래서 shop2 에서는
        #   카드 등장음을 **아예 넣지 않는다**. 이 형식의 소리 규격에도 없는 소리다.
        ev = [(intro_sec - 0.10, SFX["swoosh2"], 0.38)]    # 본편 진입
        if not s2:
            ev.insert(0, (0.0, SFX["swoosh"], 0.26))       # 카드 등장 — 말보다 먼저, 작게
        for i, b in enumerate(blocks):
            t = intro_sec + starts[i]
            if i and b.get("src"):
                ev.append((t, SFX["click"], SFX_CUT_GAIN))  # 컷 전환 클릭
            # ★shop2 는 «자막이 바뀔 때마다 소리 한 발»이다. 윗줄이 새로 뜰 때 한 발,
            #   아랫줄이 붙을 때 한 발 (화면규격.md 3절). 컷 전환음과는 별개다.
            #   그 블록에 강조음이 따로 있으면 겹쳐 치지 않는다 — 강조음이 곧 그 자리의
            #   자막 등장음 노릇을 한다.
            if roll and not b.get("sfx"):
                page = i // 2
                tbl = SFX_CAP_TOP if i % 2 == 0 else SFX_CAP_BOT
                name, g = tbl[page % len(tbl)]
                ev.append((max(0.0, t - SFX_CAP_LEAD), name, g))
            if b.get("sfx"):
                nm = (S2_ACCENT.get(b["sfx"]) if roll else None) or \
                    SFX.get(b["sfx"], SFX["hit"])
                ev.append((t, nm, SFX_MARK_GAIN))
        ev.append((intro_sec + starts[-1], SFX["end"], 0.30))
        sfx = build_sfx(ev, total, work)
        print(f"      효과음 {len(ev)}발")

    print("[6/7] 합성")
    intro_vid, intro_n = build_intro_clip(plan, cuts, intro_sec, work, vid_h=vid_h, s2=s2)
    print(f"      인트로 카드 컷 {intro_n}개"
          + ("  ✓" if intro_n >= 2 else "  ⚠ 원본은 2~4개다. plan.intro_cuts 를 채워라"))
    seg_intro = os.path.join(work, "seg_intro.mp4")
    if s2:
        # 카드와 본편의 영상 자리가 같다 — 판만 갈아 끼운다.
        # 영상 클립은 이미 «영상 칸 + 흰 여백» 을 합친 1080x1276 판이라 그대로 얹는다.
        pad_hex = "0x%02X%02X%02X" % C_S2_PAD
        # ★카드 제목은 **점점 커진다** (2026-08-24 사용자 요청). 상단 바와 바탕은
        #   고정이고 글자만 자라므로, 커지는 구간만 프레임을 따로 굽고 나머지는 완성
        #   크기 한 장으로 버틴다.
        cdir = os.path.join(work, "card")
        os.makedirs(cdir, exist_ok=True)
        grow = min(S2_CARD_ZOOM_SEC, max(0.25, intro_sec * 0.35))
        nf = max(2, int(round(grow * 30000.0 / 1001.0)))
        paths, holds = [], []
        for k in range(nf):
            u = (k + 1) / nf
            sc = S2_CARD_ZOOM0 + (1.0 - S2_CARD_ZOOM0) * (1 - (1 - u) ** 3)   # ease-out
            p = os.path.join(cdir, f"{k:03d}.png")
            make_shop2_top(plan, p, card=True, hl_scale=sc)
            paths.append(p)
            holds.append(1001.0 / 30000.0)
        paths.append(ov_intro)                       # 다 자란 판
        holds.append(max(0.05, intro_sec - grow))
        clst = os.path.join(work, "_card.txt")
        with open(clst, "w", encoding="utf-8") as fp:
            for p, dd in zip(paths, holds):
                fp.write("file '" + p.replace("\\", "/") + f"'\nduration {dd:.4f}\n")
            fp.write("file '" + paths[-1].replace("\\", "/") + "'\n")
        cardvid = os.path.join(work, "cardstrip.mp4")
        run([FF, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", clst,
             "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-crf", "14", cardvid])
        print(f"      카드 제목 확대 {S2_CARD_ZOOM0:.2f}→1.00 · {grow:.2f}초 ({nf}프레임)")
        run([FF, "-y", "-v", "error", "-i", intro_vid, "-i", cardvid,
             "-filter_complex",
             f"color=c={pad_hex}:s={W}x{H}:r={FPS}[bg];"
             f"[0:v]fps={FPS},setsar=1[v];"
             f"[bg][v]overlay=0:{S2_VID_Y}:shortest=0[a];"
             f"[a][1:v]overlay=0:0[o]",
             "-map", "[o]", "-t", f"{intro_sec:.3f}", "-an",
             "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", seg_intro])
        seg_body = os.path.join(work, "seg_body.mp4")
        run([FF, "-y", "-v", "error", "-i", body_raw, "-i", capvid,
             "-filter_complex",
             f"color=c={pad_hex}:s={W}x{H}:r={FPS}[bg];"
             f"[0:v]fps={FPS},setsar=1[v];"
             f"[bg][v]overlay=0:{S2_VID_Y}[a];"
             f"[a][1:v]overlay=0:0:shortest=1[o]",
             "-map", "[o]", "-an", "-t", f"{body_sec:.3f}",
             "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", seg_body])
    elif reels:
        # 영상이 화면을 통째로 채운다 — 바탕색도 헤더도 여백도 없다.
        # 인트로 판과 자막 판은 둘 다 알파를 살린 채로 얹는다.
        # 카드 제목이 커지는 트랙은 알파를 살려야 한다 — 영상 위에 글자만 떠야 한다.
        cardvid = build_card_track(plan, make_reels_intro, ov_intro, intro_sec, work,
                                   alpha=True)
        run([FF, "-y", "-v", "error", "-i", intro_vid, "-i", cardvid,
             "-filter_complex",
             f"[0:v]fps={FPS},scale={W}:{H},setsar=1[v];"
             f"[v][1:v]overlay=0:0:format=auto:shortest=0[o]",
             "-map", "[o]", "-t", f"{intro_sec:.3f}", "-an",
             "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", seg_intro])
        seg_body = os.path.join(work, "seg_body.mp4")
        run([FF, "-y", "-v", "error", "-i", body_raw, "-i", capvid,
             "-filter_complex",
             f"[0:v]fps={FPS},scale={W}:{H},setsar=1[v];"
             f"[v][1:v]overlay=0:{RE_CAP_BAND[0]}:format=auto:eof_action=pass[o]",
             "-map", "[o]", "-an", "-t", f"{body_sec:.3f}",
             "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", seg_body])
    elif ht:
        # 핫템 — 검정 바탕 + 영상(554~1710) + **영상 위에 얹는 자막** + 제목 판.
        # 제목 판은 인트로와 본편이 같은 것을 쓴다(제목이 내내 박혀 있다).
        # 카드에서만 제목이 자란다. 다 자란 판 = 본편 판이라 이음매가 안 보인다.
        cardvid = build_card_track(plan, make_hottem_top, ov_intro, intro_sec, work,
                                   alpha=True)
        run([FF, "-y", "-v", "error", "-i", intro_vid, "-i", cardvid,
             "-filter_complex",
             f"color=c=0x000000:s={W}x{H}:r={FPS}[bg];"
             f"[0:v]fps={FPS},setsar=1[v];"
             f"[bg][v]overlay=0:{HT_VID_Y}:shortest=0[a];"
             f"[a][1:v]overlay=0:0[o]",
             "-map", "[o]", "-t", f"{intro_sec:.3f}", "-an",
             "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", seg_intro])
        seg_body = os.path.join(work, "seg_body.mp4")
        run([FF, "-y", "-v", "error", "-i", body_raw,
             "-loop", "1", "-framerate", FPS, "-t", f"{body_sec:.3f}", "-i", ov_head,
             "-i", capvid,
             "-filter_complex",
             f"color=c=0x000000:s={W}x{H}:r={FPS}[bg];"
             f"[0:v]fps={FPS},setsar=1[v];"
             f"[bg][v]overlay=0:{HT_VID_Y}[a];"
             f"[a][2:v]overlay=0:{HT_CAP_BAND[0]}:format=auto:eof_action=pass[b];"
             f"[b][1:v]overlay=0:0:shortest=1[o]",
             "-map", "[o]", "-an", "-t", f"{body_sec:.3f}",
             "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", seg_body])
    else:
        # ★카드 제목은 **점점 커진다** (2026-09-04 사용자 지시 · build_card_track).
        #   그래서 인트로 판은 PNG 한 장이 아니라 «자라는 트랙»으로 들어간다.
        #   본편 판(ov_head)은 그대로 PNG 이고, 그쪽은 반드시 -loop 1 로 넣는다 —
        #   그냥 -i 로 넣으면 1프레임짜리 스트림이라 몇 초 뒤 판이 통째로 사라진다
        #   (ffmpeg 9.0 실측: 본편 3초쯤부터 헤드라인이 안 보였다).
        cardvid = build_card_track(plan, make_intro_top, ov_intro, intro_sec, work)
        run([FF, "-y", "-v", "error", "-i", intro_vid, "-i", cardvid,
             "-filter_complex",
             f"color=c=0x202020:s={W}x{H}:r={FPS}[bg];"
             f"[0:v]fps={FPS},setsar=1[v];"
             f"[bg][v]overlay=0:{INTRO_VID_Y}:shortest=0[a];"
             f"[a][1:v]overlay=0:0[o]",
             "-map", "[o]", "-t", f"{intro_sec:.3f}", "-an",
             "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", seg_intro])

        seg_body = os.path.join(work, "seg_body.mp4")
        bg_hex = "0x%02X%02X%02X" % base_color(plan)
        run([FF, "-y", "-v", "error", "-i", body_raw,
             "-loop", "1", "-framerate", FPS, "-t", f"{body_sec:.3f}", "-i", ov_head,
             "-i", capvid,
             "-filter_complex",
             f"color=c={bg_hex}:s={W}x{H}:r={FPS}[bg];"
             f"[0:v]fps={FPS},setsar=1[v];"
             f"[bg][v]overlay=0:{BODY_VID_Y}[a];"
             f"[a][2:v]overlay=0:{CAP_TRACK_Y}[b];"
             f"[b][1:v]overlay=0:0:shortest=1[o]",
             "-map", "[o]", "-an", "-t", f"{body_sec:.3f}",
             "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", seg_body])

    silent = os.path.join(work, "video_mute.mp4")
    concat([seg_intro, seg_body], silent, work, "final")

    # ★BGM 은 «활용정점» 계열에서만 쓴다. `plan.bgm` 에 파일을 주면 전 구간에 깔고
    #   앞뒤로 0.4초 페이드를 준다. 쇼핑형 편은 이 값을 안 주므로 동작이 그대로다.
    bgm = plan.get("bgm")
    bgm_path = _abs(work, bgm) if bgm else None
    if bgm and not os.path.exists(bgm_path):
        print(f"      ⚠ BGM 파일을 못 찾았다: {bgm_path} — BGM 없이 간다")
        bgm_path = None
    layers = "나레이션 · 현장음 · 효과음" + (" · BGM" if bgm_path else "")
    print(f"[7/7] 소리 {3 + (1 if bgm_path else 0)}층 섞기 ({layers})")
    slug = plan.get("slug", "algoshopping")
    final = os.path.join(out_dir, f"{slug}_v001.mp4")
    ms = int(round(intro_sec * 1000))
    amb_gain = 0.0 if plan.get("mute_source") else AMB_GAIN
    argv = [FF, "-y", "-v", "error", "-i", silent, "-i", narr, "-i", amb_raw, "-i", sfx]
    fc = (f"[1:a]volume=1.0[n];"
          f"[2:a]adelay={ms}|{ms},volume={amb_gain}[m];"      # 현장음은 본편부터
          f"[3:a]volume=1.0[s];")
    tags, n_in = "[n][m][s]", 3
    if bgm_path:
        argv += ["-stream_loop", "-1", "-i", bgm_path]
        g = float(plan.get("bgm_gain", BGM_GAIN))
        fc += (f"[4:a]atrim=0:{total:.3f},asetpts=N/SR/TB,volume={g:.3f},"
               f"afade=t=in:st=0:d=0.4,afade=t=out:st={max(total - 0.6, 0):.3f}:d=0.6[g];")
        tags += "[g]"
        n_in = 4
    fc += (f"{tags}amix=inputs={n_in}:duration=longest:normalize=0,"
           f"loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.94:level=disabled[a]")
    argv += ["-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-shortest",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", final]
    run(argv)

    # 편집자용 srt
    srt = os.path.join(out_dir, f"{slug}_v001.srt")
    with open(srt, "w", encoding="utf-8") as fp:
        for i, (b, s, d) in enumerate(zip(blocks, starts, durs), 1):
            a, z = s + intro_sec, s + d + intro_sec
            fmt = lambda t: f"{int(t//3600):02d}:{int(t//60%60):02d}:{int(t%60):02d},{int(t%1*1000):03d}"
            fp.write(f"{i}\n{fmt(a)} --> {fmt(z)}\n{b['text']}\n\n")

    # 패키저가 컷을 짚을 수 있게 남긴다. img 는 그 자막이 얹힌 **영상 클립**을 가리킨다.
    block_clip = [cuts[k]["mp4"] for k in block_cut]
    if s2:
        hs = sorted({c.get("vid_h", _ladder(plan)[0]) for c in cuts})
        ws = sorted({(c.get("vid_w") or W, c.get("align") or "가운데") for c in cuts})
        wtxt = " · ".join(f"{w}px {a}" for w, a in ws)
        _bar = C_S3_BAR if s3_style(plan) else C_S2_BAR
        layout = [["상단 바", [0, S2_BAR_H - 1],
                   "#%02X%02X%02X + 흰 알약 검색창(y152~254) · 워드마크 %s"
                   % (_bar + (logo_of(plan),))],
                  ["흰 헤더", [S2_HEAD_Y, S2_TOP_H - 1],
                   "#FFFFFF · 제목(잉크58·좌측x62) · 지표줄 · 검정 구분선 y451 · "
                   "2줄 롤링 자막(잉크55 · y490/y562)"],
                  ["영상", [S2_VID_Y, H - 1],
                   "y644 고정 · 높이는 컷마다 다름 " + "·".join(str(x) for x in hs)
                   + " · 폭/자리 " + wtxt
                   + " (박힌 자막을 밀어내는 기법) · 남는 자리는 흰 여백 #FDFDFD"]]
    elif reels:
        layout = [["영상", [0, H - 1], "1080x1920 풀블리드 — 헤더도 여백도 없다"],
                  ["자막", list(RE_CAP_BAND),
                   "반투명 검정 판(#111111 α196) + 흰 글씨 잉크%d · 알파 합성"
                   % RE_CAP_INK],
                  ["상단 안전영역", [0, RE_SAFE_TOP - 1], "릴스 UI — 글자를 두지 않는다"],
                  ["하단 안전영역", [H - RE_SAFE_BOT, H - 1],
                   "릴스 캡션·계정·음원 줄 + 오른쪽 버튼 기둥 — 글자를 두지 않는다"]]
    else:
        layout = [["헤더", [0, 404],
                   ("검정 바탕 + 제목 2줄 (채널 중립)" if is_plain(plan)
                    else f"가짜 앱 헤더 #424242 · 로고 {logo_of(plan)}")],
                  ["자막", [405, 589],
                   ("흰 띠 · 검정 **2줄 롤링** (잉크%d · y%d/y%d)"
                    % (P2_CAP_INK, P2_CAP_TOP1, P2_CAP_TOP1 + P2_CAP_PITCH)) if p2
                   else "흰 띠 · 검정 1줄"],
                  ["영상", [590, 1809], "1080x1220 움직이는 클립"],
                  ["여백", [1810, 1919], "#%02X%02X%02X" % base_color(plan)]]
    pc = {"head": [plan["hl1"], plan["hl2"]], "head_span": [0.0, intro_sec],
          "layout": layout,
          "cuts": [{"t": round(s + intro_sec, 3), "d": d, "lines": [b["text"]],
                    "text": b["text"], "role": b.get("voice", "NARR"), "color": "#000000",
                    "img": os.path.relpath(block_clip[i], work).replace("\\", "/")}
                   for i, (b, s, d) in enumerate(zip(blocks, starts, durs))]}
    json.dump(pc, open(os.path.join(work, "package_cuts.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ★마지막 3.5초에 «번호 배지»를 얹는다 (선택).
    #   제품 상세로 보내는 통로가 «번호»인 경우 화면으로 보여 주는 용도다.
    #   plan.json 에 "num": 714 가 있을 때만 붙는다 — 번호를 아직 모르면 나중에
    #   `py scripts\\add_number_tag.py --pkg <완성본폴더> --num 714` 로 얹으면 된다.
    num = plan.get("num")
    if num:
        try:
            import add_number_tag as _nt
            badge = os.path.join(work, f"_배지{num}.png")
            _nt.make_badge(num, badge)
            tagged = os.path.join(out_dir, f"{slug}_v001_num{num}.mp4")
            dur_all = probe_dur(final)
            run([FF, "-y", "-v", "error", "-i", final, "-i", badge,
                 "-filter_complex",
                 "[0:v][1:v]overlay=0:0:enable='between(t,%.3f,%.3f)'[v]"
                 % (max(0.0, dur_all - _nt.DEFAULT_DUR), dur_all),
                 "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", "18",
                 "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy", tagged])
            os.replace(tagged, final)       # 완성본 자리에 넣는다
            os.remove(badge)
            print(f"  번호 자막 {num}번 · 마지막 {_nt.DEFAULT_DUR}초")
        except Exception as e:              # noqa: BLE001
            print(f"  ⚠ 번호 자막을 못 얹었다({e}) — add_number_tag.py 로 따로 얹어라")

    print(f"\n완성: {final}  ({probe_dur(final):.2f}초)")
    print(f"자막: {srt}")
    return final


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    render(ap.parse_args().work)
