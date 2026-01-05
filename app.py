from datetime import datetime, date, time
from zoneinfo import ZoneInfo  # Python 3.9+

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config
from models import db, Branch, RequestItem

# Google OAuth
from flask_dance.contrib.google import make_google_blueprint, google
from sqlalchemy import text, extract, func, inspect
import os

# Google oauth2 for android mobile 
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from flask import make_response
import requests

KST = ZoneInfo("Asia/Seoul")

now_kst = datetime.now(KST)
today_start_kst = datetime.combine(
    now_kst.date(),
    time.min,
    tzinfo=KST
)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    def safe_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def ensure_request_region_columns():
        """
        기존 DB에 region_sido / region_sigungu 컬럼이 없으면 자동으로 추가한다.
        (Postgres / SQLite 호환 ALTER 사용, 실패 시 로깅 후 계속 진행)
        """
        insp = inspect(db.engine)
        if "requests" not in insp.get_table_names():
            return

        existing = {col["name"] for col in insp.get_columns("requests")}
        statements = []

        if "region_sido" not in existing:
            statements.append("ALTER TABLE requests ADD COLUMN region_sido VARCHAR(100)")
        if "region_sigungu" not in existing:
            statements.append("ALTER TABLE requests ADD COLUMN region_sigungu VARCHAR(100)")

        for stmt in statements:
            try:
                db.session.execute(text(stmt))
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"[WARN] region column migration skipped: {e}")

    def ensure_requester_column():
        insp = inspect(db.engine)
        if "requests" not in insp.get_table_names():
            return
    
        existing = {col["name"] for col in insp.get_columns("requests")}
    
        if "requester_name" not in existing:
            try:
                db.session.execute(
                    text("ALTER TABLE requests ADD COLUMN requester_name VARCHAR(120)")
                )
                db.session.commit()
                print("[MIGRATION] requester_name column added")
            except Exception as e:
                db.session.rollback()
                print("[WARN] requester_name migration skipped:", e)
    # 신규가입
    def ensure_branch_extra_columns():
        insp = inspect(db.engine)
        if "branches" not in insp.get_table_names():
            return
    
        existing = {col["name"] for col in insp.get_columns("branches")}
        statements = []
    
        if "email" not in existing:
            statements.append("ALTER TABLE branches ADD COLUMN email VARCHAR(120)")
        if "agency_name" not in existing:
            statements.append("ALTER TABLE branches ADD COLUMN agency_name VARCHAR(150)")
    
        for stmt in statements:
            try:
                db.session.execute(text(stmt))
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print("[WARN] branch migration skipped:", e)

    with app.app_context():
        ensure_request_region_columns()
        ensure_requester_column()
        ensure_branch_extra_columns()

    # =========================================================
    # 유틸 데코레이터
    # =========================================================
    from functools import wraps

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("branch_id"):
                return view(*args, **kwargs)
            return redirect(url_for("login"))
        return wrapped


    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("is_admin"):
                flash("접근 권한이 없습니다.", "error")
                return redirect(url_for("request_page"))
            return view(*args, **kwargs)
        return wrapped


    
    
    # =========================================================
    # GOOGLE LOGIN (Blueprint 등록) — 충돌 제거 버전
    # =========================================================
    google_bp = make_google_blueprint(
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scope=["openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_url="/login/callback/google"   # Google Console과 동일하게 맞춤
    )

    app.register_blueprint(google_bp, url_prefix="/login")

    # 🔵 Google Login Start (login_google_start 엔드포인트 복구)
    @app.route("/login/google/start")
    def login_google_start():
        # Flask-Dance의 blueprint 시작 URL로 리다이렉트
        return redirect(url_for("google.login"))

    @app.route("/api/login", methods=["POST"])
    def api_login():
        data = request.get_json(silent=True)
    
        print("LOGIN API DATA:", data)
    
        if not data:
            return jsonify({
                "success": False,
                "error": "invalid or missing JSON"
            }), 400
    
        login_id = data.get("login_id", "").strip()
        password = data.get("password", "")
    
        if not login_id or not password:
            return jsonify({
                "success": False,
                "error": "missing fields"
            }), 400
    
        branch = Branch.query.filter_by(login_id=login_id).first()
        if not branch or not check_password_hash(branch.password_hash, password):
            return jsonify({
                "success": False,
                "error": "invalid credentials"
            }), 401
    
        branch.last_login_at = datetime.utcnow()
        db.session.commit()
    
        session.clear()
        session["branch_id"] = branch.id
        session["branch_name"] = branch.branch_name
        session["is_admin"] = branch.is_admin
        session["login_provider"] = "native"
    
        return jsonify({"success": True}), 200
   
    
    # =========================================================
    # Google OAuth Callback (Flask-Dance의 google.authorized 대신 직접 처리)
    # =========================================================
    @app.route("/login/callback/google")
    def google_callback():
        if not google.authorized:
            flash("Google 인증 실패했습니다.", "error")
            return redirect(url_for("login"))
    
        # 사용자 정보 요청
        resp = google.get("/oauth2/v2/userinfo")
        info = resp.json()
    
        google_id = info["id"]
        email = info.get("email", "")
        name = info.get("name", "")
        profile_img = info.get("picture", "")
    
        # DB 저장 (users 테이블)
        try:
            result = db.session.execute(
                text("""
                    INSERT INTO users (google_id, email, name, profile_img)
                    VALUES (:gid, :email, :name, :pic)
                    ON CONFLICT (google_id) DO NOTHING
                    RETURNING id
                """),
                {"gid": google_id, "email": email, "name": name, "pic": profile_img}
            )
            db.session.commit()
    
            new_id = result.fetchone()[0] if result.rowcount > 0 else None
    
            if not new_id:
                q = db.session.execute(
                    text("SELECT id FROM users WHERE google_id=:gid"),
                    {"gid": google_id}
                ).fetchone()
                new_id = q[0]
    
        except Exception as e:
            print("[GOOGLE LOGIN ERROR]", e)
            flash("Google 로그인 저장 중 오류 발생", "error")
            return redirect(url_for("login"))
    
        # 🔥 Branch 자동 생성 또는 기존 Branch 매핑
        branch = Branch.query.filter_by(login_id=google_id).first()
    
        if not branch:
            branch = Branch(
                login_id=google_id,          # Google ID를 로그인 ID로 사용
                password_hash="",            # 패스워드는 없음
                company="GoogleUser",        # 기본 값
                branch_name=name,            # 구글 이름
                region="온라인",
                is_admin=False
            )
            db.session.add(branch)
        branch.last_login_at = datetime.utcnow()   # ✅ 추가
        db.session.commit()

        # 🔥 세션 저장 (branch와 google user 모두 반영)
        session.clear()                      # ⭐ 여기 추가
        session["google_user_id"] = new_id
        session["google_email"] = email
        session["google_name"] = name
        session["branch_id"] = branch.id
        session["branch_name"] = branch.branch_name
        session["login_provider"] = "google" # ⭐ 추가
        session["is_admin"] = bool(branch.is_admin)

        if session["is_admin"]:
            return redirect(url_for("dashboard_demo"))
        return redirect(url_for("request_page"))


    
        

        
    # /auth/google-token 엔드포인트 추가
    @app.route("/auth/google-token", methods=["POST"])
    def auth_google_token():
        """
        Android 네이티브 Google Sign-In에서 받은 id_token을 검증하고
        Flask session을 생성한 뒤, Set-Cookie(session=...)를 내려준다.
        """
        data = request.get_json(silent=True) or {}
        token = data.get("id_token")

        if not token:
            return jsonify({"success": False, "error": "id_token missing"}), 400

        try:
            # 1) Google ID Token 검증
            CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
            idinfo = google_id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                CLIENT_ID
            )

            google_id = idinfo.get("sub")  # Google 고유 사용자 ID
            email = idinfo.get("email", "")
            name = idinfo.get("name", "")
            profile_img = idinfo.get("picture", "")

            if not google_id:
                return jsonify({"success": False, "error": "invalid token payload"}), 400

            # 2) users 테이블 upsert/조회 (기존 로직 재사용)
            try:
                result = db.session.execute(
                    text("""
                        INSERT INTO users (google_id, email, name, profile_img)
                        VALUES (:gid, :email, :name, :pic)
                        ON CONFLICT (google_id) DO NOTHING
                        RETURNING id
                    """),
                    {"gid": google_id, "email": email, "name": name, "pic": profile_img}
                )
                db.session.commit()

                new_id = result.fetchone()[0] if result.rowcount > 0 else None

                if not new_id:
                    q = db.session.execute(
                        text("SELECT id FROM users WHERE google_id=:gid"),
                        {"gid": google_id}
                    ).fetchone()
                    new_id = q[0] if q else None

            except Exception as e:
                db.session.rollback()
                print("[GOOGLE TOKEN LOGIN DB ERROR]", e)
                return jsonify({"success": False, "error": "db error"}), 500

            # 3) Branch 자동 생성/매핑 (기존 로직 재사용)
            branch = Branch.query.filter_by(login_id=google_id).first()
            if not branch:
                branch = Branch(
                    login_id=google_id,
                    password_hash="",
                    company="GoogleUser",
                    branch_name=name or "GoogleUser",
                    region="온라인",
                    is_admin=False
                )
                db.session.add(branch)
                # ✅ 신규 / 기존 공통 처리
            branch.last_login_at = datetime.utcnow()
            db.session.commit()

            # 4) Flask 세션 생성 (WebView에서 로그인 상태로 사용)
            session.clear()                      # ⭐ 여기 추가
            session["google_user_id"] = new_id
            session["google_email"] = email
            session["google_name"] = name
            session["branch_id"] = branch.id
            session["branch_name"] = branch.branch_name
            session["is_admin"] = bool(branch.is_admin)
            session["login_provider"] = "google" # ⭐ 추가

            # 5) JSON 응답 (중요: 쿠키는 Set-Cookie 헤더로 자동 내려감)
            resp = make_response(jsonify({"success": True}))
            return resp

        except Exception as e:
            print("[GOOGLE TOKEN VERIFY ERROR]", e)
            return jsonify({"success": False, "error": "token verify failed"}), 401

    # =========================================================
    # Kakao Login Start
    # =========================================================
    
    @app.route("/login/kakao/start")
    def login_kakao_start():
        client_id = os.getenv("KAKAO_REST_API_KEY")
        redirect_uri = os.getenv("KAKAO_REDIRECT_URI") or url_for(
            "kakao_callback", _external=True
        )
    
        if not client_id:
            flash("카카오 로그인 설정이 필요합니다.", "error")
            return redirect(url_for("login"))
    
        kakao_auth_url = (
            "https://kauth.kakao.com/oauth/authorize"
            f"?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code"
        )
        return redirect(kakao_auth_url)

    def _upsert_branch_from_kakao(kakao_id, nickname=None):
        branch = Branch.query.filter_by(login_id=f"kakao_{kakao_id}").first()
        
        if not branch:
            branch = Branch(
                login_id=f"kakao_{kakao_id}",
                password_hash="",
                branch_name=nickname,   # ✅ 닉네임 저장
                company="KakaoUser",
                region="온라인",
                is_admin=False
            )
            db.session.add(branch)
        else:
            # 기존 값이 기본값이면 갱신
            if not branch.branch_name or branch.branch_name == "KakaoUser":
                branch.branch_name = nickname
        
        db.session.commit()
        return branch



    # helper 함수 정의 위치 #

    def _set_session_for_branch(branch, name=None, email=None, provider_key=None):
        session.clear()
        session["branch_id"] = branch.id
        session["branch_name"] = name or branch.branch_name   # ✅ 핵심 수정
        session["is_admin"] = branch.is_admin
        session["login_provider"] = provider_key
    
        if provider_key:
            session[f"{provider_key}_name"] = name
            session[f"{provider_key}_email"] = email


    @app.route("/login/callback/kakao")
    def kakao_callback():
        code = request.args.get("code")
        client_id = os.getenv("KAKAO_REST_API_KEY")
        client_secret = os.getenv("KAKAO_CLIENT_SECRET")
        redirect_uri = os.getenv("KAKAO_REDIRECT_URI") or url_for(
            "kakao_callback", _external=True
        )
    
        if not code or not client_id:
            flash("카카오 인증 실패", "error")
            return redirect(url_for("login"))
    
        token_data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code": code,
        }
        if client_secret:
            token_data["client_secret"] = client_secret
    
        token_resp = requests.post(
            "https://kauth.kakao.com/oauth/token",
            data=token_data,
            timeout=10,
        )
    
        if token_resp.status_code != 200:
            flash("카카오 토큰 발급 실패", "error")
            return redirect(url_for("login"))
    
        access_token = token_resp.json().get("access_token")
        if not access_token:
            flash("카카오 토큰 없음", "error")
            return redirect(url_for("login"))
    
        user_resp = requests.get(
            "https://kapi.kakao.com/v2/user/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
    
        if user_resp.status_code != 200:
            flash("카카오 사용자 정보 조회 실패", "error")
            return redirect(url_for("login"))
    
        user_info = user_resp.json()
    
        kakao_id = user_info.get("id")
        kakao_account = user_info.get("kakao_account", {})
        profile = kakao_account.get("profile", {})
    
        nickname = profile.get("nickname") or "KakaoUser"
    
        if not kakao_id:
            flash("카카오 사용자 정보 오류", "error")
            return redirect(url_for("login"))
    
        # 🔴 DB에는 kakao_id 기준으로만 upsert (닉네임 저장 X)
        branch = _upsert_branch_from_kakao(
            kakao_id=kakao_id
        )
    
        # 🔴 닉네임은 세션에만 저장
        _set_session_for_branch(
            branch,
            name=nickname,
            email=None,
            provider_key="kakao"
        )
        
        # 🔥 관리자 여부 분기
        if branch.is_admin:
            return redirect(url_for("dashboard_demo"))
        
        return redirect(url_for("request_page"))


    # =========================================================
    # Kakao Native Login (Android 전용)
    # =========================================================
    @app.route("/auth/kakao-token", methods=["POST"])
    def auth_kakao_token():
        data = request.get_json(silent=True) or {}
        access_token = data.get("access_token")
    
        if not access_token:
            return jsonify({"success": False, "error": "access_token missing"}), 400
    
        try:
            # 1️⃣ 카카오 사용자 정보 조회
            user_resp = requests.get(
                "https://kapi.kakao.com/v2/user/me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
    
            if user_resp.status_code != 200:
                return jsonify({"success": False, "error": "kakao user info failed"}), 401
    
            user_info = user_resp.json()
    
            kakao_id = user_info.get("id")
            kakao_account = user_info.get("kakao_account", {})
            profile = kakao_account.get("profile", {})
            nickname = profile.get("nickname") or "KakaoUser"
    
            if not kakao_id:
                return jsonify({"success": False, "error": "invalid kakao user"}), 400
    
            # 2️⃣ Branch upsert (기존 helper 재사용)
            branch = _upsert_branch_from_kakao(kakao_id=kakao_id)
    
            # 3️⃣ 세션 생성 (기존 helper 재사용)
            _set_session_for_branch(
                branch,
                name=nickname,
                email=None,
                provider_key="kakao"
            )
    
            # 4️⃣ JSON 응답 (쿠키는 자동 Set-Cookie)
            return jsonify({"success": True})
    
        except Exception as e:
            print("[KAKAO TOKEN LOGIN ERROR]", e)
            return jsonify({"success": False, "error": "server error"}), 500
    
    #==========================================
    # new id /pw creation. 신규가입.
    #==========================================
    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            login_id = request.form.get("login_id", "").strip()
            password = request.form.get("password", "")
            email = request.form.get("email", "").strip()
            name = request.form.get("branch_name", "").strip()
            agency = request.form.get("agency_name", "").strip()

            if not login_id or not password or not name:
                flash("필수 항목을 입력해주세요.", "error")
                return redirect(url_for("signup"))

            if Branch.query.filter_by(login_id=login_id).first():
                flash("이미 사용 중인 ID입니다.", "error")
                return redirect(url_for("signup"))

            password_hash = generate_password_hash(password)

            branch = Branch(
                login_id=login_id,
                password_hash=password_hash,
                email=email or None,
                branch_name=name,
                agency_name=agency or None,
                company="NativeUser",
                region="온라인",
                is_admin=False
            )

            db.session.add(branch)
            db.session.commit()

            flash("회원가입이 완료되었습니다. 로그인해주세요.", "success")
            return redirect(url_for("login"))

        return render_template("signup.html")

    
    #==========================================
    # session check 
    #==================================
    @app.route("/api/me")
    def api_me():
        if not session.get("branch_id"):
            return jsonify({"logged_in": False}), 401
    
        return jsonify({
            "logged_in": True,
            "is_admin": bool(session.get("is_admin")),
            "branch_name": session.get("branch_name"),
            "login_provider": session.get("login_provider")
        })

        
    # ============================================================
    # SaaS 데모 대시보드 (모바일 전용 요약)
    # ============================================================
    @app.route("/dashboard_demo")
    @login_required
    @admin_required
    def dashboard_demo():
        # -----------------------------------------------
        # ⭐ 오늘 신규 요청 (KST 기준)
        # -----------------------------------------------
        now_kst = datetime.now(KST)

        today_start_kst = datetime.combine(
            now_kst.date(),
            time.min,
            tzinfo=KST
        )

        # DB created_at 은 UTC 기준이므로 변환
        UTC = ZoneInfo("UTC")
        today_start_utc = today_start_kst.astimezone(UTC)


        today_new_count = (
            RequestItem.query
            .filter(RequestItem.created_at >= today_start_utc)
            .count()
        )

        

        
        # -----------------------------------------------
        # 0) 지역 라벨 헬퍼 (현재 DB 구조 완전 대응)
        # -----------------------------------------------
        def get_region_label(r):
            """
            파이 차트용 지역 라벨
            - region_sido 있으면 그것만 사용
            - 없으면 region에서 첫 단어만 사용
            """
            if hasattr(r, "region_sido") and r.region_sido:
                return r.region_sido
        
            if r.region:
                return r.region.split()[0]
        
            return "미기입"

    
        # -----------------------------------------------
        # 1) 전체 개수 & 상태별 개수
        # -----------------------------------------------
        total = RequestItem.query.count()
    
        status_wait = RequestItem.query.filter_by(status="모집중").count()
        status_promo = RequestItem.query.filter_by(status="홍보중").count()
        status_pre = RequestItem.query.filter_by(status="선탑진행중").count()
        status_interview = RequestItem.query.filter_by(status="면접예정").count()
        status_done = RequestItem.query.filter_by(status="배차완료").count()
    
        # 진행률 (배차완료 기준)
        progress_rate = round((status_done / total) * 100, 1) if total > 0 else 0
    
        # 상태별 비중
        total2 = (
            status_wait
            + status_promo
            + status_pre
            + status_interview
            + status_done
            or 1
        )
    
        pct_wait = round((status_wait / total2) * 100, 1)
        pct_promo = round((status_promo / total2) * 100, 1)
        pct_pre = round((status_pre / total2) * 100, 1)
        pct_interview = round((status_interview / total2) * 100, 1)
        pct_done = round((status_done / total2) * 100, 1)
    
        # -----------------------------------------------
        # 2) 최근 요청 5건
        # -----------------------------------------------
        recent = (
            RequestItem.query
            .order_by(RequestItem.created_at.desc())
            .limit(5)
            .all()
        )
    
        recent_items = [
            {
                "id": r.id,
                "region": get_region_label(r),
                "company": r.company,
                "branch_name": r.branch_name,
                "vehicle_type": getattr(r, "vehicle_type", None),
                "headcount": r.headcount,
                "unit_price": getattr(r, "unit_price", None),
                "volume": r.volume,
                "etc": r.etc,
                "status": r.status,
                "interview_date": (
                    r.interview_date.isoformat()
                    if r.interview_date else ""
                ),
                "created_at": r.created_at.strftime("%Y-%m-%d"),
            }
            for r in recent
        ]
    
        # -----------------------------------------------
        # 3) ⭐ 지역별 요청 집계 (TOP 5 + 기타)
        #    → region_sido 없이도 100% 정상 동작
        # -----------------------------------------------
        region_temp = {}
    
        for r in RequestItem.query.all():
            key = get_region_label(r)
            region_temp[key] = region_temp.get(key, 0) + 1
    
        sorted_regions = sorted(
            region_temp.items(),
            key=lambda x: x[1],
            reverse=True
        )
    
        top5 = sorted_regions[:5]
        others_total = sum(cnt for _, cnt in sorted_regions[5:])
    
        region_count = {}
        for region, cnt in top5:
            region_count[f"{region} ({cnt})"] = cnt
    
        if others_total > 0:
            region_count[f"기타 ({others_total})"] = others_total
    
        # -----------------------------------------------
        # 4) ⭐ 택배사별 요청 집계 (TOP 5 + 기타)
        # -----------------------------------------------
        carrier_rows = (
            db.session.query(RequestItem.company, func.count(RequestItem.id))
            .group_by(RequestItem.company)
            .all()
        )
    
        carrier_temp = {
            (c or "미기입"): int(cnt)
            for c, cnt in carrier_rows
        }
    
        sorted_carriers = sorted(
            carrier_temp.items(),
            key=lambda x: x[1],
            reverse=True
        )
    
        top5_carriers = sorted_carriers[:5]
        others_carrier_total = sum(cnt for _, cnt in sorted_carriers[5:])
    
        carrier_count = {}
        for name, cnt in top5_carriers:
            carrier_count[f"{name} ({cnt})"] = cnt
    
        if others_carrier_total > 0:
            carrier_count[f"기타 ({others_carrier_total})"] = others_carrier_total
    
        # -----------------------------------------------
        # 5) 템플릿 전달
        # -----------------------------------------------
        return render_template(
            "dashboard_demo.html",
    
            total_cases=total,
    
            status_wait=status_wait,
            status_promo=status_promo,
            status_pre=status_pre,
            status_interview=status_interview,
            status_done=status_done,
    
            progress_rate=progress_rate,
    
            pct_wait=pct_wait,
            pct_promo=pct_promo,
            pct_pre=pct_pre,
            pct_interview=pct_interview,
            pct_done=pct_done,
    
            recent=recent_items,
            region_count=region_count,
            carrier_count=carrier_count,
            today_new_count=today_new_count,
        )


    # =========================================================
    # 초기 Admin 생성
    # =========================================================
    @app.route("/init-admin")
    def init_admin():
        try:
            db.create_all()
            if Branch.query.filter_by(login_id="admin").first():
                return "Admin already exists."

            admin = Branch(
                login_id="admin",
                password_hash=generate_password_hash("admin1234"),
                company="본사",
                branch_name="관리자",
                region="서울",
                is_admin=True,
            )
            db.session.add(admin)
            db.session.commit()
            return "Admin created!"
        except Exception as e:
            return f"Error: {e}"

    # =========================================================
    # HOME / LOGIN
    # =========================================================
    @app.route("/")
    def home():
        if "google_user_id" in session or "branch_id" in session:
            if session.get("is_admin"):
                return redirect(url_for("dashboard_demo"))  # 🔥 핵심
            return redirect(url_for("request_page"))
        return redirect(url_for("login"))


    @app.route("/login", methods=["GET", "POST"])
    def login():
        if "google_user_id" in session or "branch_id" in session:
            if session.get("is_admin"):
                return redirect(url_for("dashboard_demo"))
            return redirect(url_for("request_page"))

    
        if request.method == "POST":
            login_id = request.form.get("login_id", "").strip()
            password = request.form.get("password", "")
    
            branch = Branch.query.filter_by(login_id=login_id).first()
            if branch and check_password_hash(branch.password_hash, password):
                branch.last_login_at = datetime.utcnow()
                db.session.commit()
    
                session["branch_id"] = branch.id
                session["is_admin"] = branch.is_admin
                session["branch_name"] = branch.branch_name
    
                if branch.is_admin:
                    return redirect(url_for("dashboard_demo"))
                return redirect(url_for("request_page"))
            else:
                flash("ID 또는 비밀번호를 확인하세요.", "error")
    
        # 🔥 이 줄은 반드시 함수의 최하단 / if 바깥
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # =========================================================
    # 요청 입력 페이지
    # =========================================================
    @app.route("/request", methods=["GET", "POST"])
    @login_required
    def request_page():
        branch = Branch.query.get(session.get("branch_id"))
    
        if request.method == "POST":
            form = request.form
            try:
                # 지역 처리 (시/도 + 시/군/구)
                region_sido = form.get("region_sido", "").strip()
                region_sigungu = form.get("region_sigungu", "").strip()
                region_combined = " ".join(
                    [p for p in [region_sido, region_sigungu] if p]
                ).strip()
    
                new_req = RequestItem(
                    branch_id=branch.id,
                
                    # ✅ 영업점 / 대리점명 (사용자 입력값)
                    branch_name=form.get("branch_name", "").strip(),
                
                    # ✅ 요청자 (세션 닉네임 / 구글 이름)
                    requester_name=session.get("branch_name"),
                
                    company=form.get("company", "").strip(),
                    region=region_combined,
                    region_sido=region_sido or None,
                    region_sigungu=region_sigungu or None,
                    volume=safe_int(form.get("volume")),
                    headcount=safe_int(form.get("headcount")),
                    work_type=form.get("work_type", "").strip(),
                    center_location=form.get("center_location", "").strip(),
                    etc=form.get("etc", "").strip(),
                    status="모집중",
                    created_at=datetime.utcnow(),
                )

    
                db.session.add(new_req)
                db.session.commit()
                flash("요청이 저장되었습니다.", "success")
    
            except Exception as e:
                db.session.rollback()
                print("❌ 요청 저장 오류:", e)
                flash("요청 저장 중 오류가 발생했습니다.", "error")
    
            return redirect(url_for("request_page"))
    
        # 브랜치별 요청 목록
        branch_requests = []
        if branch:
            branch_requests = (
                RequestItem.query
                .filter_by(branch_id=branch.id)
                .order_by(RequestItem.created_at.desc())
                .all()
            )
    
        return render_template(
            "request.html",
            branch=branch,
            branch_requests=branch_requests
        )


    # =========================================================
    # 요청 삭제 (본인 지점 데이터만 삭제)
    # =========================================================
    @app.route("/request/delete/<int:req_id>", methods=["POST"])
    @login_required
    def delete_request(req_id):
        branch_id = session.get("branch_id")

        # 로그인 안 되어 있으면 방어
        if not branch_id:
            flash("로그인 후 이용해주세요.", "error")
            return redirect(url_for("login"))

        # 🔒 보안: 내 지점(branch_id)의 데이터만 삭제 가능
        row = RequestItem.query.filter_by(id=req_id, branch_id=branch_id).first()

        if not row:
            flash("삭제할 요청을 찾을 수 없습니다.", "error")
            return redirect(url_for("request_page"))

        try:
            db.session.delete(row)
            db.session.commit()
            flash("요청이 삭제되었습니다.", "success")
        except Exception as e:
            db.session.rollback()
            print("[DELETE ERROR]", e)
            flash("삭제 중 오류가 발생했습니다.", "error")

        return redirect(url_for("request_page"))

    # =========================================================
    # 통계 함수
    # =========================================================
    def get_stats():
        total = RequestItem.query.count()
        completed = RequestItem.query.filter_by(status="배차완료").count()
        active = total - completed
        return total, active, completed

    # =========================================================
    # 대시보드 (v1 / v2 / v3)
    # =========================================================
    @app.route("/dashboard")
    @login_required
    @admin_required
    def dashboard():
        total, active, completed = get_stats()

        return render_template("dashboard.html",
                               total_cases=total,
                               active_cases=active,
                               completed_cases=completed,
                               company_list=get_company_list())

    @app.route("/dashboard_v2")
    @login_required
    @admin_required
    def dashboard_v2():
        reqs = RequestItem.query.order_by(RequestItem.created_at.desc()).all()
        total, active, completed = get_stats()

        return render_template("dashboard_v2.html",
                               reqs=reqs,
                               total_cases=total,
                               active_cases=active,
                               completed_cases=completed,
                               company_list=get_company_list())

    @app.route("/dashboard_v3")
    @login_required
    @admin_required
    def dashboard_v3():
        reqs = RequestItem.query.order_by(RequestItem.created_at.desc()).all()
        total, active, completed = get_stats()

        return render_template("dashboard_v3.html",
                               reqs=reqs,
                               total_cases=total,
                               active_cases=active,
                               completed_cases=completed,
                               company_list=get_company_list())

    # =========================================================
    # 관리자 계정 관리 - 계정 리스트
    # =========================================================
    @app.route("/admin/accounts")
    @login_required
    @admin_required
    def admin_account_list():
    
        accounts = (
            Branch.query
            .order_by(Branch.created_at.desc())
            .all()
        )
    
        return render_template(
            "admin/accountList.html",
            accounts=accounts
        )
    
    # =========================================================
    # 관리자 계정 관리 - 관리자 권한 변경 API
    # =========================================================
    @app.route("/admin/accounts/update-role", methods=["POST"])
    @login_required
    @admin_required
    def admin_update_account_role():
    
        data = request.get_json(force=True)
    
        branch_id = data.get("branch_id")
        is_admin = data.get("is_admin")
    
        if branch_id is None or is_admin is None:
            return jsonify({"success": False, "message": "잘못된 요청"}), 400
    
        branch = Branch.query.get(branch_id)
    
        if not branch:
            return jsonify({"success": False, "message": "계정을 찾을 수 없습니다"}), 404
    
        # 🔒 자기 자신 관리자 권한 변경 방지
        if branch.id == session.get("branch_id"):
            return jsonify({
                "success": False,
                "message": "본인 권한은 변경할 수 없습니다."
            }), 403
    
        try:
             # 문자열/불리언/숫자 모두 안전하게 처리
            true_values = {"true", "1", "yes", "y", True, 1}
            branch.is_admin = is_admin in true_values
            db.session.commit()
    
            return jsonify({
                "success": True,
                "message": "권한이 변경되었습니다."
            })
    
        except Exception as e:
            db.session.rollback()
            print("[ROLE UPDATE ERROR]", e)
            return jsonify({
                "success": False,
                "message": "권한 변경 중 오류 발생"
            }), 500

    
   # =========================================================
    # 요청 리스트 API (필터)
    # =========================================================
    @app.route("/api/requests", methods=["GET"])
    @login_required
    @admin_required
    def api_requests():
        company = request.args.get("company", "all")
        status = request.args.get("status", "all")
        region_sido = request.args.get("region_sido", "").strip()
        region_sigungu = request.args.get("region_sigungu", "").strip()
    
        query = RequestItem.query
    
        # 택배사 필터
        if company != "all" and company:
            query = query.filter(RequestItem.company == company)
    
        # 상태 필터
        if status != "all" and status:
            query = query.filter(RequestItem.status == status)
    
        # 지역 필터 (문자열 contains 방식)
        if region_sido:
            query = query.filter(RequestItem.region.contains(region_sido))
    
        if region_sigungu:
            query = query.filter(RequestItem.region.contains(region_sigungu))
    
        rows = query.order_by(RequestItem.created_at.desc()).all()
    
        results = [
            {
                "id": r.id,
                "region": r.region,
                "company": r.company,
        
                # ✅ 추가
                "requester_name": getattr(r, "requester_name", None),
        
                # ✅ 기존 (영업소 / 대리점명 = 입력값)
                "branch_name": r.branch_name,
        
                "work_days": r.work_type,
                "volume": r.volume,
                "headcount": r.headcount,
                "etc": r.etc,
                "status": r.status,
                "interview_date": (
                    r.interview_date.strftime("%Y-%m-%d")
                    if r.interview_date else ""
                ),
                "created_at": r.created_at.strftime("%Y-%m-%d"),
            }
            for r in rows
        ]

        return jsonify({
            "count": len(results),
            "data": results
        })


    # =========================================================
    # 상태 업데이트 API
    # =========================================================
    @app.route("/api/update-status", methods=["POST"])
    @login_required
    @admin_required
    def api_update_status():

        data = request.get_json(force=True)

        req_id = data.get("req_id")
        new_status = data.get("status")
        interview_date = data.get("interview_date")

        row = RequestItem.query.get(req_id)
        if not row:
            return jsonify({"success": False, "error": "Invalid request ID"}), 404

        row.status = new_status

        try:
            if interview_date:
                row.interview_date = datetime.strptime(interview_date, "%Y-%m-%d").date()
            else:
                row.interview_date = None
        except:
            row.interview_date = None

        db.session.commit()

        return jsonify({"success": True})

    # =========================================================
    # DB TEST PAGE
    # =========================================================
    @app.route("/dbtest")
    @login_required
    @admin_required
    def dbtest_page():
        return render_template("dbtest.html")

    # =========================================================
    # 수동 데이터 저장
    # =========================================================
    @app.route("/api/dbtest-insert", methods=["POST"])
    @login_required
    @admin_required
    def api_dbtest_insert():

        data = request.get_json()

        try:
            r = RequestItem(
                company=data.get("company"),
                region=data.get("region"),
                branch_name=data.get("branch_name"),
               
                volume=int(data.get("volume") or 0),
                headcount=int(data.get("headcount") or 0),
                etc=data.get("etc"),
                status="모집중",
                created_at=datetime.utcnow()
            )
            db.session.add(r)
            db.session.commit()
            return jsonify({"success": True})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "error": str(e)}), 500

    # =========================================================
    # 랜덤 데이터 100개 자동 생성
    # =========================================================
    @app.route("/api/dbtest-generate", methods=["POST"])
    @login_required
    @admin_required
    def api_dbtest_generate():

        import random
        import string

        def rand_txt():
            return ''.join(random.choices(string.ascii_uppercase, k=5))

        admin_branch_id = session.get("branch_id", 1)

        try:
            for _ in range(100):
                r = RequestItem(
                    branch_id=admin_branch_id,
                    company=random.choice(["CJ", "HPL", "롯데", "로젠", "우체국", "쿠팡"])[:7],
                    region=random.choice(["서울", "경기", "부산", "대구", "광주", "인천"])[:7],
                    branch_name=f"{rand_txt()}지점"[:7],
                    
                    volume=random.randint(10, 900),
                   
                    headcount=random.randint(1, 5),
                    etc="테스트",
                    status="모집중",
                    created_at=datetime.utcnow()
                )
                db.session.add(r)

            db.session.commit()
            return jsonify({"success": True})

        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "error": str(e)}), 500

    # =========================================================
    # 회사 목록 수집
    # =========================================================
    def get_company_list():
        try:
            rows = db.session.query(RequestItem.company).distinct().all()
            return [c[0] for c in rows if c[0]]
        except Exception as e:
            print("COMPANY LIST ERROR:", e)
            return []

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
