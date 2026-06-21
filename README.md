# 🗞️ 뉴스콕 — 오늘의 뉴스를 콕 집어서

여러 분야의 뉴스(주요·정치·경제·사회·IT·세계·연예·스포츠·건강)를 한눈에 모아 보고,
영상으로 만들고 싶은 뉴스는 **⭐ 제작 후보 보관함**에 콕 담아두는 사이트예요.
뉴닉처럼 쉽고 친근하게, 남녀노소 누구나 보기 편하게 만들었어요.

- 뉴스 데이터: **구글 뉴스 RSS** (무료, 키 불필요, 각 언론사 기사로 연결)
- 만드는 방식: Node.js + GitHub + Render (지난번 '황금비율 연구소'와 동일)

---

## 0단계. 프로그램 (이미 깔려 있으면 생략)
- **Node.js**: https://nodejs.org → LTS 설치
- **Git**: https://git-scm.com/download/win → 설치

## 1단계. 내 컴퓨터에서 실행
1. 이 `newscok` 폴더에서 (폴더 주소창에 `cmd` 입력 → Enter)
2. 부품 설치: `npm install`
3. 실행: `npm start`
4. 브라우저에서 **http://localhost:3000**
   - 뉴스는 **키 없이 바로** 나와요. (보관함은 아래 Turso를 연결하면 영구 저장)

## 2단계. GitHub에 올리기
1. github.com → New repository → 이름 `newscok` → **Public** → 체크박스 건드리지 말고 Create
2. `newscok` 폴더에서 cmd 열고 (마지막 줄 주소는 본인 것으로):
```
git init
git add .
git commit -m "뉴스콕 첫 업로드"
git branch -M main
git remote add origin https://github.com/내아이디/newscok.git
git push -u origin main
```

## 3단계. Render로 공개(배포)
1. render.com → New + → Web Service
2. **Public Git Repository** 칸에 저장소 주소 붙여넣기 (또는 GitHub 연결) → Continue
3. 설정: Language **Node** / Build `npm install` / Start `npm start` / Instance **Free**
4. Create Web Service → 몇 분 후 `https://newscok-xxxx.onrender.com` 공개 주소 완성!

> 무료 플랜은 15분 미사용 시 잠들고, 다음 접속 때 ~50초 깨어나요(정상).

## 4단계. (선택) 보관함 영구 저장 — Turso
보관함(⭐)을 서버가 꺼져도 유지하려면:
1. turso.tech 가입 → Create Database → **Database URL** 과 **Auth Token(Read & Write)** 복사
2. Render → **Environment** → Add variable 로 추가:
   - `TURSO_DATABASE_URL` = libsql 주소
   - `TURSO_AUTH_TOKEN` = 토큰
3. Save Changes → 자동 재배포 → 보관함이 영구 저장돼요

---

## 기능
- **카테고리 탭**으로 분야별 뉴스 한눈에 보기
- **검색**으로 키워드 뉴스 찾기
- 제목/원문 보기로 **각 언론사 기사**로 이동
- **⭐ 제작 후보 보관함** — 영상으로 만들 뉴스 모아두기 (상단 ⭐ 버튼에서 확인)
- 상대 시간(예: "3시간 전")으로 최신 여부 한눈에

## 더 추가하면 좋은 것
- 영상 대본 초안 자동 생성, 카테고리 추가, 키워드 알림, 즐겨보는 언론사 필터 등 — 원하면 언제든!

폴더 구조: `server.js`(서버) · `newsSource.js`(뉴스 RSS) · `db.js`(보관함) · `public/`(화면)
