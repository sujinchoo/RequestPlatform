from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Branch(db.Model):
    __tablename__ = "branches"

    id = db.Column(db.Integer, primary_key=True)
    login_id = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    company = db.Column(db.String(50)
    )
    branch_name = db.Column(db.String(100))
    region = db.Column(db.String(100))

    is_admin = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    # ✅ 반드시 RequestItem
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
    region = db.Column(db.String(100), nullable=False)
    branch_name = db.Column(db.String(150), nullable=False)

    center_location = db.Column(db.String(200))
    work_type = db.Column(db.String(200))

    headcount = db.Column(db.Integer, nullable=False)
    volume = db.Column(db.Integer, nullable=False)

    etc = db.Column(db.Text)

    status = db.Column(db.String(20), default="모집중")
    interview_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
