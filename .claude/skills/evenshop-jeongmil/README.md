# 이븐쇼핑 정밀 프리셋 (evenshop-jeongmil)

제품 영상 링크를 주면 **정체를 숨긴 제품 소개 쇼츠**(9:16)를 만들어주는
Claude Code 스킬입니다.

- 화면을 **쇼핑몰 앱의 게시글 상세 화면**처럼 꾸민 가짜 헤더
- `조회수 235만 | 댓글 697개` 가짜 지표 — 남들이 이미 난리 난 글을 넘겨다보는 기분
- 초당 1블록으로 몰아치는 **7~11자 한 줄 자막**
- 여덟 칸 대본 틀 + 고정 문구 7개 (`최근…` `이건 바로…` `근데 진짜 충격적인 포인트는…`)

> **원본 채널 36편을 픽셀·밀리초 단위로 재서 세운 규격입니다.**
> 좌표는 흔들림 0~2px, 나레이션은 F0·호흡·소리 압축까지 실측해서 맞췄습니다.
> 짐작으로 만든 값이 하나도 없습니다.

> **볼케이노(volcano) MCP 사용자를 위해 만들었습니다.**
> 음성 API 키와 효과음을 볼케이노가 이미 갖고 있는 위치에서 자동으로 찾아 씁니다.

## 설치

압축을 풀어 나온 `evenshop-jeongmil` 폴더를 통째로 아래 위치에 넣습니다.

| 범위 | 경로 |
|---|---|
| 내 계정 전체 | `~/.claude/skills/evenshop-jeongmil/` |
| 특정 프로젝트만 | `<프로젝트>/.claude/skills/evenshop-jeongmil/` |

`skills` 폴더가 없으면 새로 만들면 됩니다. Windows 에서 `~` 는 `C:\Users\<이름>` 입니다.

넣은 뒤 Claude Code 를 다시 시작하고 **"이 링크로 이븐쇼핑 정밀 쇼츠 만들어줘"**
라고 하면 됩니다.

> ⚠️ **"쇼핑 쇼츠 만들어줘" 라고만 하면 볼케이노 MCP 가 잡힙니다.**
> 볼케이노에도 쇼핑 프리셋이 있어서 둘이 겹칩니다. **"이븐쇼핑 정밀"** 이라고 콕 집어 말하세요.

## 사전 준비

### 볼케이노를 쓰고 있다면 — 자동으로 잡히는 것들

| 항목 | 위치 | 비고 |
|---|---|---|
| 음성 API 키 | `~/.volcano/keys/typecast` | Typecast |
| 효과음 | `~/volcano/sfx_norm/` | `click` `pop` `ding` `hit` `boing` `fail` `swoosh` `drum` |

설정할 것이 없습니다. 그대로 쓰면 됩니다.

### 직접 설치해야 하는 것

**1. Python 패키지**
```bash
pip install -r requirements.txt
```

**2. ffmpeg / ffprobe** (PATH 에 있어야 함)
```
Windows  winget install Gyan.FFmpeg
macOS    brew install ffmpeg
Linux    sudo apt install ffmpeg
```

**3. 폰트 3종** — 재배포할 수 없어 번들되어 있지 않습니다. 셋 다 무료입니다.

| 폰트 | 쓰이는 곳 | 받는 곳 |
|---|---|---|
| `Paperlogy-9Black.ttf` | 자막 · 인트로 카드 큰 글자 | [Paperlogy](https://noonnu.cc/font_page/1622) |
| `Paperlogy-8ExtraBold.ttf` | 게시글 제목 · 인트로 박스 | 위와 같음 |
| `Pretendard-ExtraBold.otf` | 로고 · 지표 줄 | [Pretendard](https://github.com/orioncactus/pretendard/releases) |

받은 파일을 **둘 중 아무 데나** 두면 잡힙니다.

```
<이 폴더>/assets/fonts/           ← 여기에 넣는 걸 권합니다
C:\Users\<이름>\AppData\Local\Microsoft\Windows\Fonts\   ← 그냥 설치해도 됨
```

**4. 목소리** — Typecast 계정이 필요합니다. `~/.volcano/keys/typecast` 에 키를
한 줄로 넣으세요. 어떤 목소리를 골라야 하는지는 `references/채널규격.md` 8절에
원본 실측값(**F0 152Hz · 남성 · 기복 43**)이 적혀 있습니다.

**5. 효과음** — 볼케이노를 안 쓴다면 직접 준비해서 `assets/sfx/` 에 넣거나
환경변수 `EVENSHOP_SFX_DIR` 로 폴더를 지정하세요. 없으면 무음으로 굽습니다.

## 빠른 시작

```bash
# 1. 소스 영상 4개 이상 내려받기 (work/<slug>/s00.mp4 ...)
# 2. plan.json 작성 (references/plan_example.json 을 복사해서 수정)
# 3. 렌더링
python scripts/evenshop_render.py --work work/<slug>
```

보통은 이 과정을 Claude 가 알아서 진행합니다 — 링크만 주면 소스 수집·대본·
컷 배치·자막 타이밍·효과음까지 잡아줍니다. 위 명령은 직접 손볼 때만 쓰면 됩니다.

### 결과물은 어디에 저장되나요

```
work/<slug>/
├── plan.json          설정 (지우지 마세요)
├── s00.mp4 ...        내려받은 소스 영상
├── cache/tts/         구운 나레이션 (남겨두면 재렌더가 공짜입니다)
└── out/<제목>_v001.mp4  ★ 완성본
```

`cache/tts/` 를 남겨두면 대본이 안 바뀐 컷은 다시 굽지 않습니다.
파일 하나가 음성 API 호출 한 번이라, 대본을 몇 번 갈아엎었는지가 여기 그대로 남습니다.

## 구성

```
evenshop-jeongmil/
├── SKILL.md                    # Claude 가 읽는 작업 지침 (핵심)
├── README.md                   # 이 파일
├── requirements.txt
├── scripts/
│   ├── evenshop_render.py      # 영상 합성·렌더링 (2,192줄)
│   └── add_number_tag.py       # 마지막 몇 초에 번호 자막 얹기 (선택)
└── references/
    ├── 채널규격.md              # 화면 좌표·색·글꼴·리듬·목소리·소리 레벨
    ├── 대본작법.md              # 여덟 칸 대본 틀·고정 문구·제목 공식
    └── plan_example.json       # 설정 예시
```

`채널규격.md` 에는 원본 36편을 실제로 측정한 값(좌표, 색 코드, 자막 잉크 폭 분포,
블록 길이, F0, 음압 곡선 등)과 그 근거가 정리되어 있습니다. 스타일을 바꾸고 싶을 때
어디를 건드려야 하는지 판단하는 데 쓰세요.

## 이것만은 지키세요

프리셋을 그대로 써도 아래 넷을 어기면 원본과 다른 영상이 나옵니다.

1. **`plan.voice_narr` 를 반드시 채운다** — 빼면 기본 목소리(205Hz 여성)로 구워집니다.
2. **말속도 8.8자/초** — 27초 편이면 대본 235자. 길면 TTS 속도를 올리지 말고 문장을 줄입니다.
3. **링크 하나로 만들지 않는다** — 최소 4개 소스를 섞습니다. 원본과 구성까지 같으면
   중복 콘텐츠로 읽혀 수익창출이 거절됩니다.
4. **정지 이미지 슬라이드쇼로 만들지 않는다** — 이 채널은 움직이는 영상이 정체입니다.

## 소재 권리

원본 영상은 각자 준비합니다. 이 프리셋은 편집 규격만 담당하며,
남의 영상을 재편집할 경우 출처와 사용 권리는 업로드·수익화 전에 직접 확인해야 합니다.
실존 제품을 다루므로 **AI 생성 이미지를 쓰지 마세요** — 소개가 아니라 거짓이 됩니다.
