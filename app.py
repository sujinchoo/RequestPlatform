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

    # ---------------------------------------------------------
    # 데코레이터: 로그인 & 관리자 체크
    # ---------------------------------------------------------
    def login_required(view):
        from functools import wraps
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "branch_id" not in session:
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    def admin_required(view):
        from functools import wraps
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("is_admin"):
                flash("접근 권한이 없습니다.", "error")
                return redirect(url_for("request_page"))
            return view(*args, **kwargs)
        return wrapped

    # ---------------------------------------------------------
    # 임시 Admin 계정 생성
    # ---------------------------------------------------------
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
            return "Admin created! login_id=admin / password=admin1234"

        except Exception as e:
            return f"Error: {e}"

    # ---------------------------------------------------------
    # 기본 라우트
    # ---------------------------------------------------------
    @app.route("/")
    def home():
        if "branch_id" in session:
            return redirect(url_for("dashboard" if session.get("is_admin") else "request_page"))
        return redirect(url_for("login"))

    # 로그인
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

    # 로그아웃
    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---------------------------------------------------------
    # 요청 페이지
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    # 대시보드 V1 (기본)
    # ---------------------------------------------------------
    @app.route("/dashboard")
    @login_required
    @admin_required
    def dashboard():
        reqs = Req.query.order_by(Req.created_at.desc()).all()
        return render_template("dashboard.html", reqs=reqs, current_date=date.today())

    # ---------------------------------------------------------
    # 대시보드 V2 (스크롤 없는 버전)
    # ---------------------------------------------------------
    @app.route("/dashboard_v2")
    @login_required
    @admin_required
    def dashboard_v2():
        reqs = Req.query.order_by(Req.created_at.desc()).all()
        return render_template("dashboard_v2.html", reqs=reqs, current_date=date.today())

    # ---------------------------------------------------------
    # 대시보드 V3 (카드형)
    # ---------------------------------------------------------
    @app.route("/dashboard_v3")
    @login_required
    @admin_required
    def dashboard_v3():
        reqs = Req.query.order_by(Req.created_at.desc()).all()
        return render_template("dashboard_v3.html", reqs=reqs, current_date=date.today())

    # ---------------------------------------------------------
    # 상태 변경 (버전 1)
    # ---------------------------------------------------------
    @app.route("/update-status", methods=["POST"])
    @login_required
    @admin_required
    def update_status():
        req_id = request.form.get("req_id")
        status = request.form.get("status")
        interview_date = request.form.get("interview_date") or None

        req_obj = Req.query.get(req_id)
        if req_obj:
            req_obj.status = status
            req_obj.interview_date = (
                datetime.strptime(interview_date, "%Y-%m-%d").date()
                if interview_date else None
            )
            db.session.commit()

        flash("업데이트 완료", "success")
        return redirect(url_for("dashboard"))

    # ---------------------------------------------------------
    # 상태 변경 (버전 2)
    # ---------------------------------------------------------
    @app.route("/update-status_v2", methods=["POST"])
    @login_required
    @admin_required
    def update_status_v2():
        req_id = request.form.get("req_id")
        status = request.form.get("status")
        interview_date = request.form.get("interview_date") or None

        req_obj = Req.query.get(req_id)
        if req_obj:
            req_obj.status = status
            req_obj.interview_date = (
                datetime.strptime(interview_date, "%Y-%m-%d").date()
                if interview_date else None
            )
            db.session.commit()

        flash("업데이트 완료", "success")
        return redirect(url_for("dashboard_v2"))

    # ---------------------------------------------------------
    # 상태 변경 (버전 3)
    # ---------------------------------------------------------
    @app.route("/update-status_v3", methods=["POST"])
    @login_required
    @admin_required
    def update_status_v3():
        req_id = request.form.get("req_id")
        status = request.form.get("status")
        interview_date = request.form.get("interview_date") or None

        req_obj = Req.query.get(req_id)
        if req_obj:
            req_obj.status = status
            req_obj.interview_date = (
                datetime.strptime(interview_date, "%Y-%m-%d").date()
                if interview_date else None
            )
            db.session.commit()

        flash("업데이트 완료", "success")
        return redirect(url_for("dashboard_v3"))
    
      # ---------------------------------------------------------
    # 필터 
    # ---------------------------------------------------------
    
    @app.route('/api/requests', methods=['GET'])
    def api_requests():
        # URL 파라미터 받기
        company = request.args.get('company', default="all", type=str)
        status = request.args.get('status', default="all", type=str)
    
        # 기본 Query
        query = Request.query  # 🔥 모델명: Request 또는 RequestModel 등 사용 중인 모델명으로 변경 필요
    
        # 회사 필터
        if company != "all" and company != "" and company is not None:
            query = query.filter(Request.company == company)
    
        # 상태 필터
        if status != "all" and status != "" and status is not None:
            query = query.filter(Request.status == status)
    
        # DB에서 결과 가져오기
        rows = query.order_by(Request.created_at.desc()).all()
    
        # Dict 변환 (프론트에서 JS로 사용하기 위해)
        results = [
            {
                "id": row.id,
                "company": row.company,
                "status": row.status,
                "title": row.title if hasattr(row, 'title') else None,
                "region": row.region if hasattr(row, 'region') else None,
                "created_at": row.created_at.strftime('%Y-%m-%d %H:%M')
            }
            for row in rows
        ]
    
        return jsonify({
            "count": len(results),
            "data": results
        })

    
    return app
    
  

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
