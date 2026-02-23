from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Branch(db.Model):
    __tablename__ = "branches"

    id = db.Column(db.Integer, primary_key=True)
    login_id = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(120))              # 🔥 신규
    company = db.Column(db.String(50))
    branch_name = db.Column(db.String(100))
    agency_name = db.Column(db.String(150))        # 🔥 대리점명
    region = db.Column(db.String(100))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)
    requests = db.relationship("RequestItem", backref="branch", lazy=True)


class RequestItem(db.Model):
    __tablename__ = "requests"

    id = db.Column(db.Integer, primary_key=True)

    branch_id = db.Column(
        db.Integer,
        db.ForeignKey("branches.id"),
        nullable=False
    )

    company = db.Column(db.String(50), nullable=False)
    requester_full_name = db.Column(db.String(120))
    requester_contact = db.Column(db.String(50))

    region = db.Column(db.String(100), nullable=False)
    region_sido = db.Column(db.String(100))
    region_sigungu = db.Column(db.String(100))

    #  요청자 (로그인 사용자: 구글 이름 / 카카오 닉네임)
    requester_name = db.Column(db.String(120))

    #  영업소 / 대리점명 (입력값)
    branch_name = db.Column(db.String(150), nullable=False)

    center_location = db.Column(db.String(200))
    work_type = db.Column(db.String(200))

    headcount = db.Column(db.Integer, nullable=False)
    volume = db.Column(db.Integer, nullable=False)
    delivery_unit_price = db.Column(db.Integer)

    etc = db.Column(db.Text)

    status = db.Column(db.String(20), default="모집중")
    interview_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
