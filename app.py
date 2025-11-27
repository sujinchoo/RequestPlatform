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
from sqlalchemy import text
import os


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
            db.session.commit()
    
        # 🔥 세션 저장 (branch와 google user 모두 반영)
        session["google_user_id"] = new_id
        session["google_email"] = email
        session["google_name"] = name
        session["branch_id"] = branch.id
        session["branch_name"] = branch.branch_name
        session["is_admin"] = False
    
        return redirect(url_for("request_page"))


    # =========================================================
    # SaaS 데모 대시보드 (모바일 전용 요약)
    # =========================================================
    @app.route("/dashboard_demo")
    @login_required
    @admin_required
    def dashboard_demo():
    
        # 전체 개수
        total = Req.query.count()
    
        # 상태별 개수
        status_wait = Req.query.filter_by(status="모집중").count()
        status_pre = Req.query.filter_by(status="선탑진행중").count()
        status_interview = Req.query.filter_by(status="면접예정").count()
        status_done = Req.query.filter_by(status="배차완료").count()
    
        # 상태 진행률 (배차완료 / 전체)
        progress_rate = 0
        if total > 0:
            progress_rate = round((status_done / total) * 100, 1)
    
        # 상태별 비중
        total2 = status_wait + status_pre + status_interview + status_done
        if total2 == 0:
            total2 = 1
    
        pct_wait = round((status_wait / total2) * 100, 1)
        pct_pre = round((status_pre / total2) * 100, 1)
        pct_interview = round((status_interview / total2) * 100, 1)
        pct_done = round((status_done / total2) * 100, 1)
    
        # 최근 요청 5건
        recent = Req.query.order_by(Req.created_at.desc()).limit(5).all()
    
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
