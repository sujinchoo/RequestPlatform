
```markdown
# 📦 전국 택배 대리점 인력 요청 관리 시스템  
Flask + Render PostgreSQL 기반 인력 요청/배차 관리 플랫폼

---

## 📌 프로젝트 소개

본 시스템은 **전국 택배 대리점(CJ·롯데·한진·로젠·쿠팡 등)**에서  
필요한 인력을 간단히 등록하고, **본사에서 일괄 조회 및 상태 관리**할 수 있도록 만든  
웹 기반 인력 요청 관리 플랫폼입니다.

주요 기능:

- 대리점 로그인 (ID/PW)
- 대리점 인력 요청 등록
- 요청 데이터 PostgreSQL 저장
- 본사 관리자(admin) 로그인
- 대시보드(엑셀 시트 스타일)
- 상태 변경(모집중 → 홍보중 → 선탑진행중 → 면접예정 → 배차완료)
- 면접일 입력 기능
- 모바일/태블릿 대응 UI

전국 대리점의 요청을 하나의 화면에서 빠르게 파악하여  
인력 모집·선탑·면접·배차까지 전체 과정을 효율적으로 관리할 수 있습니다.

---

## 🏗️ 기술 스택

| 구성 | 기술 |
|------|------|
| Backend | Python Flask |
| Frontend | HTML5, CSS, Jinja2 Templates |
| Database | Render PostgreSQL |
| ORM | SQLAlchemy |
| Deployment | Render Web Service |
| Server Gateway | Gunicorn |
| Session/보안 | Flask SECRET_KEY 사용 |

---

## 📁 디렉토리 구조

```

project/
├─ app.py
├─ models.py
├─ config.py
├─ requirements.txt
├─ runtime.txt
├─ templates/
│   ├─ base.html
│   ├─ login.html
│   ├─ request.html
│   └─ dashboard.html
└─ static/
└─ styles.css

````

---

## ⚙️ 설치 및 실행 (로컬)

### 1. 가상환경 생성

```bash
python3 -m venv venv
source venv/bin/activate
````

### 2. 패키지 설치

```bash
pip install -r requirements.txt
```

### 3. 환경변수 설정 (.env)

```
DATABASE_URL=postgresql://user:pass@host:5432/dbname
SECRET_KEY=your-secret-key
# Google OAuth (웹 & 안드로이드 공용)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Kakao OAuth (웹 & 안드로이드 공용)
KAKAO_REST_API_KEY=your-kakao-rest-key
KAKAO_CLIENT_SECRET=your-kakao-client-secret   # 선택
KAKAO_REDIRECT_URI=https://your-domain.com/login/callback/kakao
```

### 4. DB 테이블 생성

```bash
flask --app app shell
>>> from models import db
>>> db.create_all()
```

### 5. 관리자 계정 생성

```bash
flask --app app create-admin
```

### 6. 실행

```bash
flask run
```
### 7. Android WebView & 네이티브 로그인 연동

* **Google**: 네이티브 Google Sign-In 후 `id_token`을 `/auth/google-token`에 `POST` 하면 세션 쿠키가 내려가므로 WebView가 로그인된 상태가 됩니다.
* **Kakao**: Kakao SDK 로그인 후 `access_token`을 `/auth/kakao-token`에 `POST` 합니다. 성공 시 동일하게 세션 쿠키가 WebView에 설정됩니다.

Kotlin 예시 (WebView에서 쿠키 공유):

```kotlin
// 네이티브 로그인 후 받은 토큰을 서버에 전달
suspend fun sendTokenToServer(url: String, payload: JSONObject) {
    withContext(Dispatchers.IO) {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.setRequestProperty("Content-Type", "application/json")
        conn.doOutput = true
        conn.outputStream.use { it.write(payload.toString().toByteArray()) }

        val cookieHeader = conn.headerFields["Set-Cookie"]
        cookieHeader?.forEach { cookie ->
            CookieManager.getInstance().setCookie("https://your-domain.com", cookie)
        }
    }
}

// Google 예시: sendTokenToServer("https://your-domain.com/auth/google-token", jsonObjectOf("id_token" to idToken))
// Kakao 예시:  sendTokenToServer("https://your-domain.com/auth/kakao-token", jsonObjectOf("access_token" to accessToken))
```

WebView 초기화 시 `CookieManager.getInstance().setAcceptCookie(true)`를 설정하면, 이후 `loadUrl("https://your-domain.com")` 호출 시 동일 세션으로 접속됩니다.

---

## 🚀 Render 배포 방법

### 1. Render New Web Service 생성

* **Repository**: 본 프로젝트 GitHub
* **Environment**: Python 3.11
* **Build Command**:

  ```
  pip install -r requirements.txt
  ```
* **Start Command**:

  ```
  gunicorn app:app
  ```

### 2. 환경변수 추가

Render → Environment → Add Environment Variable:

```
DATABASE_URL=postgres://...
SECRET_KEY=your-secret-key
```

### 3. 최초 배포 후

Render Shell 또는 로컬에서:

```
flask --app app shell
>>> from models import db
>>> db.create_all()
```

관리자 계정 생성:

```
flask --app app create-admin
```

---

## 🔐 사용자 역할

### 🟦 대리점 사용자

* 로그인 후 인력 요청 등록 가능
* 등록된 요청은 본사에서만 조회 가능

### 🟥 본사 관리자 (Admin)

* `/dashboard` 접근 가능
* 전체 요청 리스트 조회
* 상태 변경 가능 (모집중 / 선탑진행중 / 면접예정 / 배차완료)
* 면접일 입력 가능

---

## 📊 대시보드 기능

* 엑셀 시트처럼 한 페이지에 모든 데이터 표시
* 지역/대리점명/단가/물량/차종/요청인원/조건/상태/면접일/상태 변경
* 각 행마다 상태 Update 가능
* 최신 등록 순으로 상단 출력

---

## 🧩 향후 확장 가능 기능

* 대리점별 요청 히스토리
* 요청 승인 프로세스 추가
* Excel / CSV Export
* 알림톡 / 문자 연동
* 드라이버 관리 기능 (현재 제외)
* 앱(WebView → Android/iOS) 패키징

---

## 📞 문의 및 유지보수

본 프로젝트는 실제 물류 대리점 운영을 위한
업무 효율화 시스템 구축을 목표로 제작되었습니다.

추가 개선 및 API 연동, 모바일 앱 빌드(WebView),
운영 자동화 등이 필요하면 확장 가능합니다.

Email:
soojinchoo@gmail.com
Abiout me
https://sjc-knowledgebase.onrender.com/

---

## 👍 License

private / internal use only.

```

---

# 🚀 준비 완료!

이 README는:

✔ Render 배포 가능  
✔ 협력업체에게 보여줘도 충분  
✔ 새 개발자가 들어와도 구조 이해 쉬움  
✔ 추후 확장 기능 설명도 포함
