from datetime import datetime, date
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config
from models import db, Branch, Request as Req

# Google OAuth
from flask_dance.contrib.google import make_google_blueprint, google
from sqlalchemy import text, extract, func
import os

# Google oauth2 for android mobile 
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from flask import make_response



def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    # =========================================================
    # 유틸 데코레이터
    # =========================================================
    from functools import wraps

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "branch_id" in session:
                return view(*args, **kwargs)
            if "google_user_id" in session:
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
        session["google_user_id"] = new_id
        session["google_email"] = email
        session["google_name"] = name
        session["branch_id"] = branch.id
        session["branch_name"] = branch.branch_name
        session["is_admin"] = False
    
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
            session["google_user_id"] = new_id
            session["google_email"] = email
            session["google_name"] = name
            session["branch_id"] = branch.id
            session["branch_name"] = branch.branch_name
            session["is_admin"] = False

            # 5) JSON 응답 (중요: 쿠키는 Set-Cookie 헤더로 자동 내려감)
            resp = make_response(jsonify({"success": True}))
            return resp

        except Exception as e:
            print("[GOOGLE TOKEN VERIFY ERROR]", e)
            return jsonify({"success": False, "error": "token verify failed"}), 401

    # ============================================================
    # SaaS 데모 대시보드 (모바일 전용 요약)
    # ============================================================
    @app.route("/dashboard_demo")
    @login_required
    @admin_required
    def dashboard_demo():
    
        # -----------------------------------------------
        # 1) 전체 개수
        # -----------------------------------------------
        total = Req.query.count()
    
        # 상태별 개수
        status_wait = Req.query.filter_by(status="모집중").count()
        status_pre = Req.query.filter_by(status="선탑진행중").count()
        status_interview = Req.query.filter_by(status="면접예정").count()
        status_done = Req.query.filter_by(status="배차완료").count()
    
        # 진행률
        progress_rate = round((status_done / total) * 100, 1) if total > 0 else 0
    
        # 비중
        total2 = status_wait + status_pre + status_interview + status_done or 1
        pct_wait = round((status_wait / total2) * 100, 1)
        pct_pre = round((status_pre / total2) * 100, 1)
        pct_interview = round((status_interview / total2) * 100, 1)
        pct_done = round((status_done / total2) * 100, 1)
    
        # -----------------------------------------------
        # 2) 최근 요청 5건
        # -----------------------------------------------
        recent = Req.query.order_by(Req.created_at.desc()).limit(5).all()
    
        # -----------------------------------------------
        # 3) ⭐ 지역별 개수 집계 (TOP 5 + 기타 + 라벨(숫자))
        # -----------------------------------------------
        raw_rows = (
            db.session.query(Req.region, db.func.count(Req.id))
            .group_by(Req.region)
            .all()
        )
        
        # dict 형태로 변환
        temp = { (r or "미기입"): int(cnt) for r, cnt in raw_rows }
    
        # 개수 순으로 정렬
        sorted_regions = sorted(temp.items(), key=lambda x: x[1], reverse=True)
    
        # Top 5
        top5 = sorted_regions[:5]
    
        # 나머지 합산 → 기타
        others_total = sum(cnt for _, cnt in sorted_regions[5:])
        if others_total > 0:
            top5.append(("기타", others_total))
    
        # 최종 dict: “지역명 (숫자)” → value는 숫자 그대로
        region_count = {}
        for region, cnt in top5:
            label = f"{region} ({cnt})"       # 라벨 + 숫자 표시
            region_count[label] = cnt         # value는 숫자 그대로 전달
    
        # -----------------------------------------------
        # 4) ⭐ 택배사별 요청 비율 집계 (TOP 5 + 기타)
        # -----------------------------------------------
        carrier_rows = (
            db.session.query(Req.company, func.count(Req.id))
            .group_by(Req.company)
            .all()
        )
        
        carrier_temp = {
            (c or "미기입"): int(cnt)
            for c, cnt in carrier_rows
        }
        
        # 요청 수 기준 내림차순
        sorted_carriers = sorted(
            carrier_temp.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        top5_carriers = sorted_carriers[:5]
        others_carrier_total = sum(cnt for _, cnt in sorted_carriers[5:])
        
        carrier_count = {}
        
        for name, cnt in top5_carriers:
            label = f"{name} ({cnt})"
            carrier_count[label] = cnt
        
        if others_carrier_total > 0:
            carrier_count[f"기타 ({others_carrier_total})"] = others_carrier_total

    
        # -----------------------------------------------
        # 5) 템플릿 전달
        # -----------------------------------------------
        return render_template(
            "dashboard_demo.html",
            total_cases=total,
            status_wait=status_wait,
            status_pre=status_pre,
            status_interview=status_interview,
            status_done=status_done,
            progress_rate=progress_rate,
            pct_wait=pct_wait,
            pct_pre=pct_pre,
            pct_interview=pct_interview,
            pct_done=pct_done,
            recent=recent,
            region_count=region_count,      # ← 라벨(숫자) 포함 + Top5 구조
            carrier_count=carrier_count      # ⭐ 택배사별 Pie
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
        if "google_user_id" in session:
            return redirect(url_for("request_page"))
        if "branch_id" in session:
            return redirect(url_for("dashboard" if session.get("is_admin") else "request_page"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if "google_user_id" in session:
            return redirect(url_for("request_page"))

        if request.method == "POST":
            login_id = request.form.get("login_id", "").strip()
            password = request.form.get("password", "")

            branch = Branch.query.filter_by(login_id=login_id).first()
            if branch and check_password_hash(branch.password_hash, password):
                branch.last_login_at = datetime.utcnow()   # ✅ 최근로그인 데이트 타임 생성 
                db.session.commit()                        # ✅ 추가, 최근로그인 로그 생성 
                
                session["branch_id"] = branch.id
                session["is_admin"] = branch.is_admin
                session["branch_name"] = branch.branch_name
                return redirect(url_for("dashboard" if branch.is_admin else "request_page"))
            else:
                flash("ID 또는 비밀번호를 확인하세요.", "error")

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
                new_req = Req(
                    branch_id=branch.id,
                    company=form.get("company"),
                    branch_name=form.get("branch"),
                    region=form.get("region"),
                    unit_price=int(form.get("unit_price") or 0),
                    volume=int(form.get("volume") or 0),
                    vehicle_type=form.get("vehicle_type"),
                    headcount=int(form.get("headcount") or 0),
                    etc=form.get("etc"),
                    status="모집중",
                    created_at=datetime.utcnow(),
                )
                db.session.add(new_req)
                db.session.commit()
                flash("요청이 저장되었습니다.", "success")
            except Exception as e:
                db.session.rollback()
                print(e)
                flash("요청 저장 중 오류 발생", "error")
    
            return redirect(url_for("request_page"))
    
        # ⭐ 여기 추가! → 브랜치별 요청 내역 조회
        branch_requests = []
        if branch:
            branch_requests = Req.query.filter_by(branch_id=branch.id).order_by(Req.created_at.desc()).all()
    
        return render_template("request.html",
                               branch=branch,
                               branch_requests=branch_requests)


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
        row = Req.query.filter_by(id=req_id, branch_id=branch_id).first()

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
        total = Req.query.count()
        completed = Req.query.filter_by(status="배차완료").count()
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
        reqs = Req.query.order_by(Req.created_at.desc()).all()
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
        reqs = Req.query.order_by(Req.created_at.desc()).all()
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
            branch.is_admin = bool(is_admin)
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

        query = Req.query

        if company != "all" and company:
            query = query.filter(Req.company == company)

        if status != "all" and status:
            query = query.filter(Req.status == status)

        rows = query.order_by(Req.created_at.desc()).all()

        results = [
            {
                "id": r.id,
                "company": r.company,
                "region": r.region,
                "branch_name": r.branch_name,
                "unit_price": r.unit_price,
                "volume": r.volume,
                "vehicle_type": r.vehicle_type,
                "headcount": r.headcount,
                "etc": r.etc,
                "status": r.status,
                "interview_date": r.interview_date.isoformat() if r.interview_date else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

        return jsonify({"count": len(results), "data": results})

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

        row = Req.query.get(req_id)
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
            r = Req(
                company=data.get("company"),
                region=data.get("region"),
                branch_name=data.get("branch_name"),
                unit_price=int(data.get("unit_price") or 0),
                volume=int(data.get("volume") or 0),
                vehicle_type=data.get("vehicle_type"),
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
                r = Req(
                    branch_id=admin_branch_id,
                    company=random.choice(["CJ", "HPL", "롯데", "로젠", "우체국", "쿠팡"])[:7],
                    region=random.choice(["서울", "경기", "부산", "대구", "광주", "인천"])[:7],
                    branch_name=f"{rand_txt()}지점"[:7],
                    unit_price=random.randint(300, 900),
                    volume=random.randint(10, 900),
                    vehicle_type=random.choice(["다마스", "라보", "1톤", "오토바이"])[:7],
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
            rows = db.session.query(Req.company).distinct().all()
            return [c[0] for c in rows if c[0]]
        except Exception as e:
            print("COMPANY LIST ERROR:", e)
            return []

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
