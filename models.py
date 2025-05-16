from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class Photo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    member = db.Column(db.String(64), nullable=False)
    costume = db.Column(db.String(128), nullable=False)
    photo_type = db.Column(db.String(64), nullable=False)
    group_key = db.Column(db.String(64), nullable=False)
    group = db.Column(db.String(64), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('member', 'costume', 'photo_type', 'group_key', name='_photo_uc'),
    )

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)  # Werkzeugでハッシュ化

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)  # Werkzeugで検証

class UserPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    photo_id = db.Column(db.Integer, db.ForeignKey('photo.id'), nullable=False)
    member = db.Column(db.String(64), nullable=False)
    costume = db.Column(db.String(128), nullable=False)
    photo_type = db.Column(db.String(64), nullable=False)
    group = db.Column(db.String(64), nullable=False)
    has_owner = db.Column(db.Boolean, default=True, nullable=False)  # ← 追加
    memo = db.Column(db.String, nullable=True)
    date = db.Column(db.Date, nullable=True)
    quantity = db.Column(db.Integer, nullable=True, default=1)
    photo = db.relationship('Photo', backref='user_photos')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'member', 'costume', 'photo_type', 'group', name='_user_photo_uc'),
    )