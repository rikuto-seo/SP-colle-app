# sakamichi_photo_app/models.py

import uuid
from datetime import datetime

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Index, event, func

from extensions import db
from config import OWNER_USER_ID


GROUP_KEYS = [
    "nogizaka",
    "sakurazaka",
    "hinatazaka",
]


# ============================================================
# User / Image Storage Settings
# ============================================================

# 保存容量・登録数・利用グループ数にプランによる上限は設けない。

# アップロード時に受け付ける元画像の最大サイズ
#
# 実際の保存サイズは、
# services/r2_storage.py でWebPへ変換・圧縮される。
MAX_USER_IMAGE_UPLOAD_BYTES = (
    10 * 1024 * 1024
)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    firebase_uid = db.Column(
        db.String(255),
        unique=True,
        nullable=False
    )

    email = db.Column(
        db.String(120),
        unique=True,
        nullable=True
    )

    username = db.Column(
        db.String(20),
        nullable=True,
        index=True
    )

    dark_mode = db.Column(
        db.Boolean,
        default=False
    )

    icon_url = db.Column(
        db.String(500),
        nullable=True
    )

    twitter_id = db.Column(
        db.String(100)
    )

    instagram_id = db.Column(
        db.String(100)
    )

    show_twitter = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    show_instagram = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    public_uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4())
    )

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

    stripe_customer_id = db.Column(
        db.String(255)
    )

    stripe_subscription_id = db.Column(
        db.String(255),
        unique=True
    )

    subscription_status = db.Column(
        db.String(50)
    )

    current_period_end = db.Column(
        db.DateTime
    )

    cancel_at_period_end = db.Column(
        db.Boolean,
        default=False
    )

    primary_group = db.Column(
        db.String(50),
        nullable=True
    )

    selected_groups = db.Column(
        db.String,
        default=""
    )

    # --------------------------------------------------------
    # UserPhoto relationships
    # --------------------------------------------------------

    # このユーザーが登録している生写真
    owned_photos = db.relationship(
        "UserPhoto",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # このユーザーがアップロードした実物画像
    user_photo_images = db.relationship(
        "UserPhotoImage",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # --------------------------------------------------------
    # WantPhoto relationship
    # --------------------------------------------------------

    want_list = db.relationship(
        "WantPhoto",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # --------------------------------------------------------
    # Account / Plan
    # --------------------------------------------------------

    def is_owner_account(self):
        return self.id == OWNER_USER_ID

    @property
    def effective_plan_type(self):
        # Legacy billing columns remain for existing records; they grant no privileges.
        return "free"

    def is_free(self):
        return True

    def is_lite(self):
        return False

    def is_standard(self):
        return False

    def is_premium(self):
        return False

    def is_active_paid(self):
        return False

    def can_upload_image(self):
        return True

    def get_image_storage_limit_bytes(self):
        """None denotes unlimited storage, rather than a zero-byte quota."""
        return None

    def get_image_storage_limit_mb(self):
        return None

    def get_image_storage_limit_gb(self):
        return None

    def get_image_storage_bytes(self):
        """
        現在このユーザーが使用している
        R2画像ストレージ容量をbytesで返す。

        対象:
            UserPhotoImage.file_size
            +
            UserPhotoImage.thumbnail_file_size

        元画像はR2に保存しないため、
        保存済みのWebP 2種類だけを合計する。
        """

        total = (
            db.session.query(
                func.coalesce(
                    func.sum(
                        UserPhotoImage.file_size
                        + UserPhotoImage.thumbnail_file_size
                    ),
                    0
                )
            )
            .filter(
                UserPhotoImage.user_id == self.id
            )
            .scalar()
        )

        return int(total or 0)

    def get_image_storage_used_mb(self):
        """
        現在使用している画像容量をMBで返す。
        """
        return (
            self.get_image_storage_bytes()
            / (1024 * 1024)
        )

    def get_image_storage_used_gb(self):
        """
        現在使用している画像容量をGBで返す。
        """
        return (
            self.get_image_storage_bytes()
            / (1024 * 1024 * 1024)
        )

    def get_image_storage_remaining_bytes(self):
        return None

    def can_upload_image_bytes(self, additional_bytes=0):
        return additional_bytes >= 0

    def get_image_storage_usage_ratio(self):
        return None

    def is_image_storage_full(self):
        return False

    def can_use_unlimited_photos(self):
        return True

    def can_use_stats_detail(self):
        return True

    def can_use_multiple_groups(self):
        return True

    def can_use_all_groups(self):
        return True

    def get_accessible_group_keys(self):
        return list(GROUP_KEYS)

    def get_selected_groups(self):
        # Also unlock existing accounts without requiring a data migration or setup.
        return list(GROUP_KEYS)

    def set_selected_groups(self, groups):
        self.selected_groups = ",".join(GROUP_KEYS)

    def get_allowed_group_count(self):
        return len(GROUP_KEYS)

    def can_access_group(self, group_key):
        return group_key in GROUP_KEYS

    def get_default_group_key(self):
        if self.primary_group in GROUP_KEYS:
            return self.primary_group
        # Retain a legacy user's previously selected first group as their preference.
        for key in (self.selected_groups or "").split(","):
            if key in GROUP_KEYS:
                return key
        return GROUP_KEYS[0]

    def normalize_groups(self):
        self.primary_group = self.get_default_group_key()
        self.selected_groups = ",".join(GROUP_KEYS)

    def can_add_group(self):
        return False  # All supported groups are already enabled.

    def add_group(self, group_key):
        if group_key not in GROUP_KEYS:
            raise ValueError("グループが見つかりません")
        self.normalize_groups()

    # --------------------------------------------------------
    # Want Share
    # --------------------------------------------------------

    def is_want_share_enabled(
        self,
        group_key: str
    ) -> bool:

        share = WantShare.get_or_create(
            self.id,
            group_key
        )

        return share.want_public

    def toggle_want_share(
        self,
        group_key: str
    ):
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

        share.want_public = not share.want_public

        db.session.add(share)
        db.session.commit()


@event.listens_for(
    User,
    "before_insert"
)
@event.listens_for(
    User,
    "before_update"
)
def receive_before_save(
    mapper,
    connection,
    target
):
    target.normalize_groups()


# ============================================================
# WantPhoto
# ============================================================

class WantPhoto(db.Model):
    __tablename__ = "want_photos"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    photo_id = db.Column(
        db.Integer,
        db.ForeignKey("photos.id"),
        nullable=False
    )

    is_infinite = db.Column(
        db.Boolean,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    photo = db.relationship(
        "Photo"
    )

    user = db.relationship(
        "User",
        back_populates="want_list"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "photo_id"
        ),
    )


# ============================================================
# WantShare
# ============================================================

class WantShare(db.Model):
    __tablename__ = "want_shares"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "users.id"
        ),
        nullable=False,
        index=True
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
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    want_public = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship(
        "User",
        backref="want_shares"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "group_key"
        ),
    )

    @staticmethod
    def get_or_create(
        user_id,
        group_key
    ):
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


# ============================================================
# UserPhoto
# ============================================================

class UserPhoto(db.Model):
    __tablename__ = "user_photos"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    photo_id = db.Column(
        db.Integer,
        db.ForeignKey("photos.id"),
        nullable=False
    )

    quantity = db.Column(
        db.Integer,
        default=1,
        nullable=False
    )

    available_quantity = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    has_owner = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    is_favorite = db.Column(
        db.Boolean,
        default=False
    )

    memo = db.Column(
        db.String
    )

    date = db.Column(
        db.Date
    )

    photo = db.relationship(
        "Photo"
    )

    user = db.relationship(
        "User",
        back_populates="owned_photos"
    )

    # --------------------------------------------------------
    # User uploaded images
    # --------------------------------------------------------

    images = db.relationship(
        "UserPhotoImage",
        back_populates="user_photo",
        cascade="all, delete-orphan",
        order_by="UserPhotoImage.created_at"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "photo_id"
        ),

        CheckConstraint(
            "quantity >= 0"
        ),

        CheckConstraint(
            "available_quantity >= 0"
        ),

        CheckConstraint(
            "available_quantity <= quantity"
        ),
    )

    @property
    def image_count(self):
        """
        このUserPhotoに登録されている
        実物画像の枚数。
        """

        return len(self.images)

    @property
    def has_images(self):
        """
        実物画像が1枚以上登録されているか。
        """

        return self.image_count > 0

    @property
    def image_storage_bytes(self):
        """
        このUserPhotoに紐付く画像が
        R2上で使用している容量。

        表示用画像 + サムネイル。
        """

        return sum(
            image.storage_bytes
            for image in self.images
        )


# ============================================================
# UserPhotoImage
# ============================================================

class UserPhotoImage(db.Model):
    """
    ユーザー自身が撮影・アップロードした
    生写真の実物画像を管理するモデル。

    1つのUserPhotoに対して
    複数枚の画像を登録可能。

    例:

        UserPhoto
            ├── UserPhotoImage
            ├── UserPhotoImage
            └── UserPhotoImage

    実際の画像データはR2に保存し、
    PostgreSQLにはメタデータと
    R2 object keyのみを保存する。
    """

    __tablename__ = "user_photo_images"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # --------------------------------------------------------
    # Ownership
    # --------------------------------------------------------

    user_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "users.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    user_photo_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "user_photos.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    # --------------------------------------------------------
    # R2 Object Keys
    # --------------------------------------------------------

    # 詳細表示用画像
    image_key = db.Column(
        db.String(500),
        nullable=False,
        unique=True
    )

    # 一覧表示用サムネイル
    thumbnail_key = db.Column(
        db.String(500),
        nullable=False,
        unique=True
    )

    # --------------------------------------------------------
    # File Information
    # --------------------------------------------------------

    # 詳細表示用WebPの保存サイズ
    file_size = db.Column(
        db.BigInteger,
        nullable=False,
        default=0
    )

    # サムネイルWebPの保存サイズ
    thumbnail_file_size = db.Column(
        db.BigInteger,
        nullable=False,
        default=0
    )

    mime_type = db.Column(
        db.String(100),
        nullable=False,
        default="image/webp"
    )

    # 詳細表示用画像の幅
    width = db.Column(
        db.Integer,
        nullable=True
    )

    # 詳細表示用画像の高さ
    height = db.Column(
        db.Integer,
        nullable=True
    )

    # --------------------------------------------------------
    # Timestamp
    # --------------------------------------------------------

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

    user = db.relationship(
        "User",
        back_populates="user_photo_images"
    )

    user_photo = db.relationship(
        "UserPhoto",
        back_populates="images"
    )

    # --------------------------------------------------------
    # Properties
    # --------------------------------------------------------

    @property
    def storage_bytes(self):
        """
        この画像が実際にR2上で使用する容量。

        表示用画像
        +
        サムネイル
        """

        return (
            int(self.file_size or 0)
            + int(
                self.thumbnail_file_size or 0
            )
        )

    @property
    def image_url_key(self):
        """
        R2のimage object key。

        実際の公開URL生成は
        services/r2_storage.pyで行う。
        """

        return self.image_key

    @property
    def thumbnail_url_key(self):
        """
        R2のthumbnail object key。

        実際の公開URL生成は
        services/r2_storage.pyで行う。
        """

        return self.thumbnail_key

    __table_args__ = (
        CheckConstraint(
            "file_size >= 0",
            name="check_user_photo_image_file_size"
        ),

        CheckConstraint(
            "thumbnail_file_size >= 0",
            name=(
                "check_user_photo_image_"
                "thumbnail_file_size"
            )
        ),

        Index(
            "ix_user_photo_images_user_created",
            "user_id",
            "created_at"
        ),

        Index(
            "ix_user_photo_images_user_photo_created",
            "user_photo_id",
            "created_at"
        ),
    )


# ============================================================
# Photo
# ============================================================

class Photo(db.Model):
    __tablename__ = "photos"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    member_id = db.Column(
        db.Integer,
        db.ForeignKey("members.id"),
        nullable=False
    )

    costume_id = db.Column(
        db.Integer,
        db.ForeignKey("costumes.id"),
        nullable=False
    )

    type_id = db.Column(
        db.Integer,
        db.ForeignKey("photo_types.id"),
        nullable=False
    )

    member = db.relationship(
        "Member"
    )

    costume = db.relationship(
        "Costume"
    )

    photo_type = db.relationship(
        "PhotoType"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "member_id",
            "costume_id",
            "type_id",
            name="uq_photo"
        ),
    )


# ============================================================
# PhotoType
# ============================================================

class PhotoType(db.Model):
    __tablename__ = "photo_types"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String,
        unique=True,
        nullable=False
    )

    # --------------------------------------------------------
    # Costume Type Normalization
    # --------------------------------------------------------

    # 衣装ごとの統計用Type設定
    #
    # 例:
    #   衣装A / 03 → ヨリ
    #   衣装B / 03 → チュウ
    #
    # PhotoType自体のnameは変更しない。
    costume_normalizations = db.relationship(
        "CostumeTypeNormalization",
        back_populates="photo_type",
        cascade="all, delete-orphan"
    )


# ============================================================
# Costume
# ============================================================

class Costume(db.Model):
    __tablename__ = "costumes"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String,
        nullable=False
    )

    group_id = db.Column(
        db.Integer,
        db.ForeignKey("groups.id"),
        nullable=False
    )

    group = db.relationship(
        "Group",
        backref="costumes"
    )

    # --------------------------------------------------------
    # Costume Type Normalization
    # --------------------------------------------------------

    # この衣装における
    # PhotoType → 統計用Type の対応設定
    type_normalizations = db.relationship(
        "CostumeTypeNormalization",
        back_populates="costume",
        cascade="all, delete-orphan"
    )


# ============================================================
# CostumeTypeNormalization
# ============================================================

class CostumeTypeNormalization(db.Model):
    """
    衣装ごとのPhotoType統計分類を管理する。

    PhotoTypeの表示名は変更せず、
    統計処理で使用する分類だけを
    衣装単位で設定する。

    例:

        衣装A
            01 → ヒキ
            02 → チュウ
            03 → ヨリ
            04 → 座り

        衣装B
            01 → ヨリ
            02 → ヒキ
            03 → チュウ
            04 → 座り

    「03」の意味が衣装によって異なるケースにも対応できる。
    """

    __tablename__ = "costume_type_normalizations"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # --------------------------------------------------------
    # Costume
    # --------------------------------------------------------

    costume_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "costumes.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    # --------------------------------------------------------
    # PhotoType
    # --------------------------------------------------------

    photo_type_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "photo_types.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    # --------------------------------------------------------
    # Normalized Type
    # --------------------------------------------------------

    normalized_type = db.Column(
        db.String(20),
        nullable=False
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

    costume = db.relationship(
        "Costume",
        back_populates="type_normalizations"
    )

    photo_type = db.relationship(
        "PhotoType",
        back_populates="costume_normalizations"
    )

    # --------------------------------------------------------
    # Constraints
    # --------------------------------------------------------

    __table_args__ = (
        # 同じ衣装・同じPhotoTypeについて
        # 統計Type設定を1件だけ保持する。
        db.UniqueConstraint(
            "costume_id",
            "photo_type_id",
            name="uq_costume_type_normalization"
        ),

        # 統計上の分類は4種類に限定する。
        CheckConstraint(
            "normalized_type IN ('ヨリ','チュウ','ヒキ','座り')",
            name="check_normalized_type"
        ),
    )


# ============================================================
# Member
# ============================================================

class Member(db.Model):
    __tablename__ = "members"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String,
        nullable=False
    )

    group_id = db.Column(
        db.Integer,
        db.ForeignKey("groups.id"),
        nullable=False
    )

    generation = db.Column(
        db.Integer
    )

    display_order = db.Column(
        db.Integer
    )

    group = db.relationship(
        "Group",
        backref="members"
    )


# ============================================================
# Group
# ============================================================

class Group(db.Model):
    __tablename__ = "groups"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    key = db.Column(
        db.String,
        unique=True,
        nullable=False
    )

    name = db.Column(
        db.String,
        nullable=False
    )


class WantMember(db.Model):
    """A member-wide wish, without a placeholder Photo."""
    __tablename__ = 'want_members'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    member = db.relationship('Member')
    is_infinite = True
    __table_args__ = (db.UniqueConstraint('user_id', 'member_id'),)
