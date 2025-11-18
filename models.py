# models.py
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Branch(db.Model):
    __tablename__ = "branches"

    id = db.Column(db.Integer, primary_key=True)
    login_id = db.Column(db.String(50), unique=True, nullable=False)  # 로그인 ID
    password_hash = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(50))          # 택배사
    branch_name = db.Column(db.String(100))     # 영업소명
    region = db.Column(db.String(100))          # 기본 지역
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    requests = db.relationship("Request", backref="branch", lazy=True)


class Request(db.Model):
    __tablename__ = "requests"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)

    # 폼에서 입력받는 항목들
    company = db.Column(db.String(50), nullable=False)       # 택배사
    region = db.Column(db.String(100), nullable=False)       # 지역
    branch_name = db.Column(db.String(150), nullable=False)  # 영업소 / 대리점명
    unit_price = db.Column(db.Integer, nullable=False)       # 단가
    volume = db.Column(db.Integer, nullable=False)           # 월 물량
    vehicle_type = db.Column(db.String(100))                 # 차종
    headcount = db.Column(db.Integer, nullable=False)        # 필요 인원
    etc = db.Column(db.Text)                                 # 기타/제한사항

    status = db.Column(db.String(20), default="모집중")      # 모집중 / 선탑진행중 / 면접예정 / 배차완료
    interview_date = db.Column(db.Date)                      # 면접 예정일

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
