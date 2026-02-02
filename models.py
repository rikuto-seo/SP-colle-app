#sakamichi_photo_app\models.py
import uuid
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from extensions import db

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
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    group_key = db.Column(db.String(50), nullable=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(128), nullable=False)
    default_group = db.Column(db.String(100), nullable=True)
    dark_mode = db.Column(db.Boolean, default=False)
    #所持共有
    is_nogizaka_shared = db.Column(db.Boolean, default=False)
    is_sakurazaka_shared = db.Column(db.Boolean, default=False)
    is_hinatazaka_shared = db.Column(db.Boolean, default=False)
    #欲しいもの共有
    is_nogizaka_want_shared = db.Column(db.Boolean, default=False)
    is_sakurazaka_want_shared = db.Column(db.Boolean, default=False)
    is_hinatazaka_want_shared = db.Column(db.Boolean, default=False)
    
    icon_filename = db.Column(db.String(255), nullable=True)

    public_uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4())
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def toggle_share_setting(self, group_key):
        if group_key == 'nogizaka':
            self.is_nogizaka_shared = not self.is_nogizaka_shared
        elif group_key == 'sakurazaka':
            self.is_sakurazaka_shared = not self.is_sakurazaka_shared
        elif group_key == 'hinatazaka':
            self.is_hinatazaka_shared = not self.is_hinatazaka_shared
        else:
            raise ValueError(f"無効なグループキー: {group_key}")

    def is_want_share_enabled(self, group_key):
        if group_key == 'nogizaka':
            return self.is_nogizaka_want_shared
        elif group_key == 'sakurazaka':
            return self.is_sakurazaka_want_shared
        elif group_key == 'hinatazaka':
            return self.is_hinatazaka_want_shared
        return False
    
    def is_want_shared(self, group_key):
        return {
            'nogizaka': self.is_nogizaka_want_shared,
            'sakurazaka': self.is_sakurazaka_want_shared,
            'hinatazaka': self.is_hinatazaka_want_shared
        }.get(group_key, False)

    def toggle_want_share(self, group_key):
        if group_key == 'nogizaka':
            self.is_nogizaka_want_shared = not self.is_nogizaka_want_shared
        elif group_key == 'sakurazaka':
            self.is_sakurazaka_want_shared = not self.is_sakurazaka_want_shared
        elif group_key == 'hinatazaka':
            self.is_hinatazaka_want_shared = not self.is_hinatazaka_want_shared

    @property
    def icon_url(self):
        from flask import url_for
        if self.icon_filename:
            return url_for('static', filename='uploads/icons/' + self.icon_filename)
        else:
            return url_for('static', filename='images/default_icon.png')

    received_requests = db.relationship(
        'Friendship',
        foreign_keys='Friendship.friend_id',
        lazy='dynamic',
        cascade='all, delete-orphan',
        backref='receiver_user_explicit',
        overlaps="receiver_user_explicit,friend_requests_received"
    )

    sent_requests = db.relationship(
        'Friendship',
        foreign_keys='Friendship.user_id',
        lazy='dynamic',
        cascade='all, delete-orphan',
        backref='sender_user_explicit',
        overlaps="sender_user_explicit,friend_requests_sent"
    )

class UserPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    photo_id = db.Column(db.Integer, db.ForeignKey('photo.id'), nullable=False)
    member = db.Column(db.String(64), nullable=False)
    costume = db.Column(db.String(128), nullable=False)
    photo_type = db.Column(db.String(64), nullable=False)
    group_key = db.Column(db.String(64), nullable=False)
    group = db.Column(db.String(64), nullable=False)
    has_owner = db.Column(db.Boolean, default=True, nullable=False)
    memo = db.Column(db.String, nullable=True)
    date = db.Column(db.Date, nullable=True)
    quantity = db.Column(db.Integer, nullable=True, default=1)

    photo = db.relationship('Photo', backref='user_photos')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'member', 'costume', 'photo_type', 'group', name='_user_photo_uc'),
    )

class WantPhoto(db.Model):
    __tablename__ = 'want_photos'

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    group_key = db.Column(db.String(64), nullable=False)

    member = db.Column(db.String(64), nullable=False)
    costume = db.Column(db.String(128), nullable=False)
    photo_type = db.Column(db.String(64), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref='want_photos')

    __table_args__ = (
        db.UniqueConstraint(
            'user_id',
            'group_key',
            'member',
            'costume',
            'photo_type',
            name='uq_user_want_photo'
        ),
    )

class WantShare(db.Model):
    __tablename__ = 'want_shares'

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=False
    )

    group_key = db.Column(
        db.String(50),
        nullable=False
    )

    public_uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4())
    )

    is_public = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        onupdate=db.func.now()
    )

    __table_args__ = (
        db.UniqueConstraint(
            'user_id',
            'group_key',
            name='uq_want_share_user_group'
        ),
    )


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_messages')


class Friendship(db.Model):
    __tablename__ = 'friendships'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    chat_enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')  # 'pending', 'accepted', 'rejected'

    user = db.relationship(
        'User',
        foreign_keys=[user_id],
        backref='friend_requests_sent',
        overlaps="sent_requests,sender_user_explicit"
    )

    friend = db.relationship(
        'User',
        foreign_keys=[friend_id],
        backref='friend_requests_received',
        overlaps="received_requests,receiver_user_explicit"
    )

    __table_args__ = (
        db.UniqueConstraint('user_id', 'friend_id', name='uq_user_friend'),
    )
