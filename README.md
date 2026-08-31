# 📱 인스타그램 삭제 DM 실시간 감지 & 아이폰 텔레그램 알림 시스템

상대방이 인스타그램 DM을 보냈다가 **전송 취소(삭제)**했을 때, **누가 뭐라고 보냈었는지**를 감지하여 내 아이폰 텔레그램 앱으로 실시간 푸시 알림을 쏴주는 파이썬 프로그램입니다.

---

## 💡 주요 특징 및 작동 원리

1. **필터링 알림**: 모든 평범한 DM 알림으로 텔레그램이 도배되지 않습니다. 오직 **'상대방이 전송 취소한 메시지'**만 감지하여 알림을 보냅니다.
2. **로컬 DB 기록**: 들어온 메시지는 로컬 SQLite 데이터베이스에 무소음 기록되며, 삭제되는 순간 텔레그램으로 발송됩니다.
3. **아이폰 연동**: 애플 보안상 아이폰 내부에 알림 앱을 설치할 수 없으므로, 텔레그램 봇 API를 통해 아이폰으로 실시간 알림을 보냅니다.

---

## 🚀 1. 텔레그램 봇 만들기 (1분 소요 - 무료)

아이폰으로 삭제 알림을 받기 위해 텔레그램 봇 토큰과 Chat ID가 필요합니다.

1. 아이폰 앱스토어에서 **Telegram(텔레그램)** 앱을 다운로드하고 가입합니다.
2. 텔레그램 검색창에 `@BotFather`를 검색하여 대화를 시작합니다.
3. `/newbot` 입력 ➡️ 봇 이름 입력 ➡️ 봇 아이디 입력 (끝이 `bot`으로 끝나야 함, 예: `my_insta_alert_bot`).
4. 대화창에 나오는 **HTTP API Token** (예: `123456789:ABCdefGHI...`)을 복사해 둡니다. (`TELEGRAM_BOT_TOKEN`)
5. 텔레그램 검색창에 `@userinfobot`을 검색하여 대화를 시작하면 나오는 **Id** 숫자 (예: `987654321`)를 복사해 둡니다. (`TELEGRAM_CHAT_ID`)

---

## ⚙️ 2. 환경 설정 (`.env` 파일 생성)

터미널에서 `/Users/naeun/insta` 폴더로 이동한 후 `.env` 파일을 만듭니다.

```bash
cd /Users/naeun/insta
cp .env.example .env
```

`.env` 파일을 열어 본인의 정보로 수정합니다:

```env
INSTAGRAM_USERNAME=내_인스타_아이디
INSTAGRAM_PASSWORD=내_인스타_비밀번호

TELEGRAM_BOT_TOKEN=아까_복사한_봇_토큰
TELEGRAM_CHAT_ID=아까_복사한_Chat_ID

CHECK_INTERVAL=12
```

---

## 📦 3. 파이썬 라이브러리 설치 및 실행

### 필수 라이브러리 설치
```bash
pip3 install -r requirements.txt
```

### 프로그램 실행
```bash
python3 main.py
```

* 처음 실행하면 인스타그램 로그인이 진행되며 `session.json` 파일이 생성됩니다.
* 이후부터는 세션으로 자동 로그인되므로 인스타 계정 보안에 안전합니다.

---

## ☁️ 4. 컴퓨터를 꺼도 24시간 돌리는 법 (무료 클라우드 배포)

내 맥북/컴퓨터를 꺼두어도 삭제 DM을 감시하려면 **무료 클라우드 서버**에 올려두시면 됩니다.

### [추천] Render.com (무료)
1. GitHub에 `/Users/naeun/insta` 코드(보안을 위해 `.env`는 빼고)를 올립니다.
2. [Render.com](https://render.com) 회원가입 ➡️ **New Background Worker** 생성.
3. GitHub 리포지토리 연동 후 실행 명령어로 `python main.py` 설정.
4. **Environment Variables** 항목에 `.env`에 적었던 4가지 값(`INSTAGRAM_USERNAME`, `INSTAGRAM_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)을 추가해주면 끝입니다!

---

## 📩 알림 수신 예시 (아이폰 텔레그램)

```
🚨 [인스타그램 삭제된 DM 감지!]

👤 보낸 사람: 홍길동 (@hong_gildong)
💬 삭제된 내용: 너 오늘 저녁에 뭐해? 시간 됨?
🕒 발송 시간: 2026-08-31 11:35:12

⚠️ 상대방이 인스타에서 위 메시지를 전송 취소(삭제)했습니다.
```
