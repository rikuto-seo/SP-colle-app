# sakamichi_photo_app/models.py
import uuid
from datetime import datetime
from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Index, event
from extensions import db


# =========================
# Photo master
# =========================
class Photo(db.Model):
    __tablename__ = "photo"

    id = db.Column(db.Integer, primary_key=True)
    member = db.Column(db.String(64), nullable=False)
    costume = db.Column(db.String(128), nullable=False)
    photo_type = db.Column(db.String(64), nullable=False)
    group_key = db.Column(db.String(64), nullable=False)
    group = db.Column(db.String(64), nullable=False)
    is_favorite = db.Column(db.Boolean, default=False)

    __table_args__ = (
        db.UniqueConstraint(
            'member', 'costume', 'photo_type', 'group_key',
            name='_photo_uc'
        ),
        Index('idx_photo_group', 'group_key')
    )

# =========================
# User
# =========================
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)

    firebase_uid = db.Column(db.String(255), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    username = db.Column(db.String(20), nullable=True, index=True)

    dark_mode = db.Column(db.Boolean, default=False)
    icon_url = db.Column(db.String(500), nullable=True)

    twitter_id = db.Column(db.String(100))
    instagram_id = db.Column(db.String(100))

    # =========================
    # UUID（共有用）
    # =========================
    public_uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4())
    )

    # =========================
    # 課金
    # =========================
    plan_type = db.Column(
        db.String(20),
        nullable=False,
        default="free"
    )

    __table_args__ = (
        CheckConstraint(
            "plan_type IN ('free','lite','standard','premium')",
            name="check_plan_type"
        ),
    )

    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(
        db.String(255),
        unique=True
    )
    subscription_status = db.Column(db.String(50))  
    # active / canceled / past_due / incomplete など

    current_period_end = db.Column(db.DateTime)
    cancel_at_period_end = db.Column(db.Boolean, default=False)

    # =========================
    # グループ管理
    # =========================
    primary_group = db.Column(db.String(50), nullable=True)
    selected_groups = db.Column(db.String, default="")

    # =========================
    # 🔥 プラン判定
    # =========================
    def is_free(self):
        return self.plan_type == "free"

    def is_lite(self):
        return self.plan_type == "lite"

    def is_standard(self):
        return self.plan_type == "standard"

    def is_premium(self):
        return self.plan_type == "premium"

    # =========================
    # 🔥 機能判定（超重要）
    # =========================
    def is_active_paid(self):
        return (
            self.plan_type != "free"
            and self.subscription_status == "active"
        )

    def can_use_unlimited_photos(self):
        return self.plan_type != "free"

    def can_use_stats_detail(self):
        return self.plan_type != "free"

    def can_upload_image(self):
        return self.plan_type == "premium"

    def can_use_multiple_groups(self):
        return self.plan_type in ["standard", "premium"]

    def can_use_all_groups(self):
        return self.plan_type == "premium"

    # =========================
    # ユーティリティ
    # =========================
    def get_selected_groups(self):
        if not self.selected_groups:
            return []
        return [g for g in self.selected_groups.split(',') if g]

    def set_selected_groups(self, groups: list):
        unique = list(dict.fromkeys(groups))
        self.selected_groups = ",".join(unique)

    def get_allowed_group_count(self):
        if self.plan_type == "free":
            return 1
        elif self.plan_type == "lite":
            return 1
        elif self.plan_type == "standard":
            return 2
        return 999  # premium

    # =========================
    # アクセス制御
    # =========================
    def can_access_group(self, group_key: str) -> bool:
        if not group_key:
            return False

        if self.is_premium():
            return True

        return group_key in self.get_selected_groups()

    # =========================
    # 🔥 DB整合性（重要）
    # =========================
    def normalize_groups(self):
        selected = self.get_selected_groups()
        allowed = self.get_allowed_group_count()

        # 上限制御
        if len(selected) > allowed:
            return

        # free制限
        if self.is_free():
            selected = selected[:1]

        self.set_selected_groups(selected)

        if selected:
            if self.primary_group not in selected:
                self.primary_group = selected[0]
        else:
            self.primary_group = None

    # =========================
    # 操作
    # =========================
    def can_add_group(self):
        return len(self.get_selected_groups()) < self.get_allowed_group_count()

    def add_group(self, group_key: str):
        groups = self.get_selected_groups()

        if group_key in groups:
            return

        if not self.can_add_group():
            raise Exception("グループ上限です")

        groups.append(group_key)
        self.set_selected_groups(groups)

    # =========================
    # WantShare連携
    # =========================
    def is_want_share_enabled(self, group_key: str) -> bool:
        share = WantShare.get_or_create(self.id, group_key)
        return share.is_public

    def toggle_want_share(self, group_key: str):
        share = WantShare.query.filter_by(
            user_id=self.id,
            group_key=group_key
        ).first()

        if not share:
            share = WantShare(
                user_id=self.id,
                group_key=group_key,
                is_public=False
            )

        share.is_public = not share.is_public
        db.session.add(share)
        db.session.commit()

# =========================
# 🔥 自動正規化（超重要）
# =========================
@event.listens_for(User, "before_insert")
@event.listens_for(User, "before_update")
def receive_before_save(mapper, connection, target):
    target.normalize_groups()

# =========================
# UserPhoto
# =========================
class UserPhoto(db.Model):
    __tablename__ = "user_photos"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=False,
        index=True
    )

    photo_id = db.Column(
        db.Integer,
        db.ForeignKey('photo.id'),
        nullable=False
    )

    member = db.Column(db.String(64), nullable=False)
    costume = db.Column(db.String(128), nullable=False)
    photo_type = db.Column(db.String(64), nullable=False)
    group_key = db.Column(db.String(64), nullable=False, index=True)
    group = db.Column(db.String(64), nullable=False)

    has_owner = db.Column(db.Boolean, default=True, nullable=False)

    memo = db.Column(db.String)
    date = db.Column(db.Date)

    quantity = db.Column(db.Integer, default=1, nullable=False)
    available_quantity = db.Column(db.Integer, default=0, nullable=False)

    is_favorite = db.Column(db.Boolean, default=False)
    
    photo = db.relationship('Photo', backref='user_photos')
    user = db.relationship('User', backref='owned_photos')

    __table_args__ = (
        db.UniqueConstraint(
            'user_id', 'member', 'costume', 'photo_type', 'group',
            name='_user_photo_uc'
        ),
        CheckConstraint('quantity >= 0'),
        CheckConstraint('available_quantity >= 0'),
        CheckConstraint('available_quantity <= quantity'),
        Index('idx_userphoto_user', 'user_id')
    )

# =========================
# WantPhoto
# =========================
class WantPhoto(db.Model):
    __tablename__ = 'want_photos'

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=False,
        index=True
    )

    group_key = db.Column(db.String(64), nullable=False, index=True)
    member = db.Column(db.String(64), nullable=False)
    costume = db.Column(db.String(128), nullable=False)
    photo_type = db.Column(db.String(64), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='want_list')

    __table_args__ = (
        db.UniqueConstraint(
            'user_id', 'group_key', 'member', 'costume', 'photo_type'
        ),
    )

# =========================
# WantShare
# =========================
class WantShare(db.Model):
    __tablename__ = 'want_shares'

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=False,
        index=True
    )

    group_key = db.Column(db.String(50), nullable=False)

    public_uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4())
    )

    is_public = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    user = db.relationship('User', backref='want_shares')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'group_key'),
    )

    @staticmethod
    def get_or_create(user_id, group_key):
        share = WantShare.query.filter_by(
            user_id=user_id,
            group_key=group_key
        ).first()

        if not share:
            share = WantShare(
                user_id=user_id,
                group_key=group_key,
                is_public=False
            )
            db.session.add(share)

        return share