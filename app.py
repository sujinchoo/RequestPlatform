# app.py

from datetime import datetime, date
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config
from models import db, Branch, Request as Req


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
            if "branch_id" not in session:
                return redirect(url_for("login"))
            return view(*args, **kwargs)
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
        if "branch_id" in session:
            return redirect(url_for("dashboard" if session.get("is_admin") else "request_page"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
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
    # 요청 등록 페이지
    # =========================================================
    @app.route("/request", methods=["GET", "POST"])
    @login_required
    def request_page():
        branch = Branch.query.get(session["branch_id"])

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
                flash("요청 저장 중 오류 발생", "error")
                print(e)

            return redirect(url_for("request_page"))

        return render_template("request.html", branch=branch)


    # =========================================================
    # 대시보드 (v1 / v2 / v3)
    # =========================================================
    @app.route("/dashboard")
    @login_required
    @admin_required
    def dashboard():
        return render_template("dashboard.html")

    @app.route("/dashboard_v2")
    @login_required
    @admin_required
    def dashboard_v2():
        return render_template("dashboard_v2.html")

    @app.route("/dashboard_v3")
    @login_required
    @admin_required
    def dashboard_v3():
        return render_template("dashboard_v3.html")


    # =========================================================
    # 상태 업데이트 공통 함수
    # =========================================================
    def update_req_status(req_id, status, interview_date):
        req = Req.query.get(req_id)
        if not req:
            return False

        req.status = status

        req.interview_date = (
            datetime.strptime(interview_date, "%Y-%m-%d").date()
            if interview_date else None
        )

        db.session.commit()
        return True


    # =========================================================
    # 🔥 JSON API — 모달에서 사용하는 저장 엔드포인트
    # =========================================================
    @app.route("/api/update-status", methods=["POST"])
    @login_required
    @admin_required
    def api_update_status():
        data = request.get_json()

        req_id = data.get("req_id")
        status = data.get("status")
        interview_date = data.get("interview_date")

        ok = update_req_status(req_id, status, interview_date)

        if not ok:
            return jsonify({"success": False, "error": "Invalid request ID"}), 400

        return jsonify({"success": True})


    # =========================================================
    # 기존 form 방식 (호환 유지)
    # =========================================================
    @app.route("/update-status", methods=["POST"])
    @login_required
    @admin_required
    def update_status():
        update_req_status(
            request.form.get("req_id"),
            request.form.get("status"),
            request.form.get("interview_date")
        )
        flash("업데이트 완료", "success")
        return redirect(url_for("dashboard"))


    # =========================================================
    # 🔥 필터 API
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
                "created_at": r.created_at.isoformat() if r.created_at else None
            }
            for r in rows
        ]

        return jsonify({"count": len(results), "data": results})


    return app



app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
