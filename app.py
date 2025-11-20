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
    # GOOGLE LOGIN (Blueprint 등록)
    # =========================================================
    google_bp = make_google_blueprint(
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scope=["email", "profile"],
        redirect_url="/login/google/authorized"
    )
    app.register_blueprint(google_bp, url_prefix="/login")


    # =========================================================
    # SaaS 데모 대시보드 페이지
    # =========================================================
    @app.route("/dashboard_demo")
    @login_required
    @admin_required
    def dashboard_demo():
    
        # 실제 DB 데이터 가져오기
        total = Req.query.count()
        completed = Req.query.filter_by(status="배차완료").count()
        active = total - completed
    
        # 최근 요청 10개
        recent = Req.query.order_by(Req.created_at.desc()).limit(10).all()
    
        # 상태 분포 (샘플 스타일)
        status_wait = Req.query.filter_by(status="모집중").count()
        status_pre = Req.query.filter_by(status="선탑진행중").count()
        status_interview = Req.query.filter_by(status="면접예정").count()
        status_done = Req.query.filter_by(status="배차완료").count()
    
        return render_template(
            "dashboard_demo.html",
            total_cases=total,
            active_cases=active,
            completed_cases=completed,
            recent=recent,
            status_wait=status_wait,
            status_pre=status_pre,
            status_interview=status_interview,
            status_done=status_done
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
    # GOOGLE LOGIN ROUTE
    # =========================================================
    @app.route("/login/google")
    def login_google():
        if not google.authorized:
            return redirect(url_for("google.login"))

        resp = google.get("/oauth2/v2/userinfo")
        info = resp.json()

        google_id = info["id"]
        email = info.get("email", "")
        name = info.get("name", "")
        profile_img = info.get("picture", "")

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
            flash("구글 로그인 오류", "error")
            return redirect(url_for("login"))

        session["google_user_id"] = new_id
        session["google_email"] = email
        session["google_name"] = name
        session["is_admin"] = False

        return redirect(url_for("request_page"))

    # =========================================================
    # 요청 입력 페이지
    # =========================================================
    @app.route("/request", methods=["GET", "POST"])
    @login_required
    def request_page():
        branch = Branch.query.get(session["branch_id"]) if "branch_id" in session else None

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
                               completed_cases=completed)

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
                               completed_cases=completed)

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
                               completed_cases=completed)

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
    # 🔥 최종 완성 — 상태 업데이트 API (JSON 방식)
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

        # 날짜 저장 처리
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
    # DB TEST PAGE (GUI)
    # =========================================================
    @app.route("/dbtest")
    @login_required
    @admin_required
    def dbtest_page():
        return render_template("dbtest.html")
    
    
    # =========================================================
    # 수동 데이터 1건 저장 API
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
    # 랜덤 데이터 100개 자동 생성 API
    # =========================================================
    @app.route("/api/dbtest-generate", methods=["POST"])
    @login_required
    @admin_required
    def api_dbtest_generate():
        import random
        import string
    
        def rand_txt():
            return ''.join(random.choices(string.ascii_uppercase, k=5))
    
        try:
            for _ in range(100):
                r = Req(
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

    
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
