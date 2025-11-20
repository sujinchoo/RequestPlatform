# app.py

from datetime import datetime, date
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config
from models import db, Branch, Request as Req

# =========================================================
# 🟦 GOOGLE LOGIN IMPORT
# =========================================================
from flask_dance.contrib.google import make_google_blueprint, google
from sqlalchemy import text
import os


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    # =========================================================
    # 데코레이터
    # =========================================================
    from functools import wraps

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            # (1) 브랜치 계정 로그인
            if "branch_id" in session:
                return view(*args, **kwargs)

            # (2) 구글 로그인 사용자
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
    # 🌐 GOOGLE LOGIN BLUEPRINT 등록
    # =========================================================
    google_bp = make_google_blueprint(
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scope=["email", "profile"],
        redirect_url="/login/google/authorized"
    )
    app.register_blueprint(google_bp, url_prefix="/login")


    # =========================================================
    # 임시 관리자 생성
    # =========================================================
    @app.route("/init-admin")
    def init_admin():
        try:
            db.create_all()
            existing = Branch.query.filter_by(login_id="admin").first()
            if existing:
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
    # 홈 / 로그인
    # =========================================================
    @app.route("/")
    def home():
        # 구글 사용자 → request_page
        if "google_user_id" in session:
            return redirect(url_for("request_page"))

        # 기존 브랜치 관리자/지점 계정
        if "branch_id" in session:
            return redirect(url_for("dashboard" if session.get("is_admin") else "request_page"))

        return redirect(url_for("login"))


    @app.route("/login", methods=["GET", "POST"])
    def login():
        # 구글 사용자는 로그인 페이지 접속 시 바로 service 페이지로 보내기
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
    # 🟦 GOOGLE LOGIN ROUTE (DB 저장)
    # =========================================================
    @app.route("/login/google")
    def login_google():
        if not google.authorized:
            return redirect(url_for("google.login"))

        # 사용자 정보 받아오기
        resp = google.get("/oauth2/v2/userinfo")
        info = resp.json()

        google_id = info["id"]
        email = info.get("email", "")
        name = info.get("name", "")
        profile_img = info.get("picture", "")

        # DB 저장 (users table)
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

            # 신규유저
            new_id = result.fetchone()[0] if result.rowcount > 0 else None

            # 기존 유저면 다시 조회
            if not new_id:
                q = db.session.execute(
                    text("SELECT id FROM users WHERE google_id=:gid"),
                    {"gid": google_id}
                ).fetchone()
                new_id = q[0]

        except Exception as e:
            print("[GOOGLE LOGIN ERROR]", e)
            flash("구글 로그인 오류", "error")
            return redirect(url_for("login"))

        # 세션 저장
        session["google_user_id"] = new_id
        session["google_email"] = email
        session["google_name"] = name
        session["is_admin"] = False

        return redirect(url_for("request_page"))


    # =========================================================
    # 요청 등록 페이지
    # =========================================================
    @app.route("/request", methods=["GET", "POST"])
    @login_required
    def request_page():
        branch = None
        if "branch_id" in session:
            branch = Branch.query.get(session["branch_id"])

        if request.method == "POST":
            form = request.form
            try:
                new_req = Req(
                    branch_id=branch.id if branch else None,
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
                flash("요청 저장 중 오류 발생", "error")
                print(e)

            return redirect(url_for("request_page"))

        return render_template("request.html", branch=branch)


    # =========================================================
    # 공통 통계 함수
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
        return render_template(
            "dashboard.html",
            total_cases=total,
            active_cases=active,
            completed_cases=completed
        )

    @app.route("/dashboard_v2")
    @login_required
    @admin_required
    def dashboard_v2():
        reqs = Req.query.order_by(Req.created_at.desc()).all()
        total, active, completed = get_stats()
        return render_template(
            "dashboard_v2.html",
            reqs=reqs,
            total_cases=total,
            active_cases=active,
            completed_cases=completed
        )

    @app.route("/dashboard_v3")
    @login_required
    @admin_required
    def dashboard_v3():
        reqs = Req.query.order_by(Req.created_at.desc()).all()
        total, active, completed = get_stats()
        return render_template(
            "dashboard_v3.html",
            reqs=reqs,
            total_cases=total,
            active_cases=active,
            completed_cases=completed
        )

        # =========================================================
    # 📌 요청 데이터 API (대시보드 테이블용)
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

        # JSON 변환
        results = []
        for r in rows:
            results.append({
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
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })

        return jsonify({
            "count": len(results),
            "data": results
        })


       # =========================================================
    # 📌 상태 변경 API (대시보드 팝업용)
    # =========================================================
    @app.route("/api/update-status", methods=["POST"])
    @login_required
    @admin_required
    def update_status():
        req_id = request.form.get("req_id")
        new_status = request.form.get("new_status")

        row = Req.query.get(req_id)
        if not row:
            return jsonify({"success": False, "message": "요청을 찾을 수 없습니다."}), 404

        row.status = new_status
        db.session.commit()

        return jsonify({"success": True})



app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
