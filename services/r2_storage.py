# services/r2_storage.py

import io
import logging
import os
import uuid

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image, ImageOps


logger = logging.getLogger(__name__)


# ============================================================
# Configuration
# ============================================================

# ユーザーがアップロードする元画像の最大サイズ
# R2へ保存する前にWebPへ変換するため、
# このサイズは「ユーザーが送信する元ファイル」に対する制限。
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


# 表示用画像
#
# 長辺をこのサイズ以内に縮小する。
# 生写真の詳細表示を想定。
MAX_IMAGE_SIZE = 2400


# 一覧表示用サムネイル
MAX_THUMBNAIL_SIZE = 500


# WebP品質
IMAGE_QUALITY = 85
THUMBNAIL_QUALITY = 78


# R2上でブラウザキャッシュさせる期間
#
# 画像URLはUUIDベースで毎回異なるため、
# 長期間キャッシュしても古い画像との衝突が起きない。
CACHE_CONTROL = "public, max-age=31536000, immutable"


# ============================================================
# Environment
# ============================================================

def _get_env(name):
    """
    環境変数を取得する。

    .env / Renderの環境変数を
    関数実行時に取得することで、
    モジュール読み込み時の値固定を避ける。
    """

    value = os.environ.get(name)

    if value is None:
        return None

    value = value.strip()

    return value or None


def _get_r2_account_id():
    return _get_env("R2_ACCOUNT_ID")


def _get_r2_access_key_id():
    return _get_env("R2_ACCESS_KEY_ID")


def _get_r2_secret_access_key():
    return _get_env("R2_SECRET_ACCESS_KEY")


def _get_r2_bucket_name():
    return _get_env("R2_BUCKET_NAME")


def _get_r2_public_base_url():
    return _get_env("R2_PUBLIC_BASE_URL")


# ============================================================
# R2 Client
# ============================================================

def _get_r2_client():
    """
    Cloudflare R2用のS3互換クライアントを作成する。

    R2はS3互換APIを提供しているため、
    boto3を使用してアクセスする。
    """

    account_id = _get_r2_account_id()
    access_key_id = _get_r2_access_key_id()
    secret_access_key = _get_r2_secret_access_key()
    bucket_name = _get_r2_bucket_name()

    if not account_id:
        raise RuntimeError(
            "R2_ACCOUNT_ID が設定されていません。"
        )

    if not access_key_id:
        raise RuntimeError(
            "R2_ACCESS_KEY_ID が設定されていません。"
        )

    if not secret_access_key:
        raise RuntimeError(
            "R2_SECRET_ACCESS_KEY が設定されていません。"
        )

    if not bucket_name:
        raise RuntimeError(
            "R2_BUCKET_NAME が設定されていません。"
        )

    endpoint_url = (
        f"https://{account_id}.r2.cloudflarestorage.com"
    )

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
        config=BotoConfig(
            signature_version="s3v4"
        ),
    )


def _get_bucket_name():
    """
    R2バケット名を取得する。
    """

    bucket_name = _get_r2_bucket_name()

    if not bucket_name:
        raise RuntimeError(
            "R2_BUCKET_NAME が設定されていません。"
        )

    return bucket_name


# ============================================================
# Validation
# ============================================================

def validate_upload_size(file_bytes):
    """
    アップロードされた元画像のファイルサイズをチェックする。

    Args:
        file_bytes: bytes

    Returns:
        True

    Raises:
        ValueError
    """

    if not file_bytes:
        raise ValueError(
            "画像ファイルが空です。"
        )

    size = len(file_bytes)

    if size > MAX_UPLOAD_BYTES:
        raise ValueError(
            "画像サイズが大きすぎます。"
            "10MB以下の画像をアップロードしてください。"
        )

    return True


def validate_image(file_bytes):
    """
    Pillowで実際に画像として読み込めるか確認する。

    ファイルサイズだけではなく、
    Pillowでデコードできることまで確認する。

    Returns:
        PIL.Image.Image

    Raises:
        ValueError
    """

    validate_upload_size(file_bytes)

    try:
        image = Image.open(
            io.BytesIO(file_bytes)
        )

        # 画像を完全に読み込む。
        # 壊れた画像などを検出する。
        image.load()

        # Pillowが認識した形式を確認。
        if not image.format:
            raise ValueError(
                "画像形式を判定できません。"
            )

        return image

    except ValueError:
        raise

    except Exception as exc:
        logger.warning(
            "Invalid image upload: %s",
            exc
        )

        raise ValueError(
            "有効な画像ファイルではありません。"
        ) from exc


# ============================================================
# Image Processing
# ============================================================

def _prepare_image(image):
    """
    EXIFの回転情報を反映し、
    WebP変換に適したRGB/RGBAへ変換する。

    スマートフォンなどで撮影した画像は
    EXIF Orientationに回転情報が入っていることがあるため、
    先にexif_transposeを行う。
    """

    # EXIFの回転情報を画像そのものへ反映
    image = ImageOps.exif_transpose(image)

    # WebPで扱いやすいモードへ変換
    if image.mode == "RGBA":
        return image

    if image.mode == "LA":
        return image.convert("RGBA")

    if image.mode == "P":
        # パレット画像は透過情報を持つ場合があるためRGBAへ。
        return image.convert("RGBA")

    # RGB以外の特殊モード
    # 例: CMYK, I, F, 1, L など
    return image.convert("RGB")


def _resize_image(image, max_size):
    """
    アスペクト比を維持したまま、
    長辺をmax_size以内にする。

    元画像がmax_size以下の場合は、
    不要な拡大を行わない。
    """

    image = image.copy()

    image.thumbnail(
        (max_size, max_size),
        Image.Resampling.LANCZOS,
    )

    return image


def _encode_webp(image, quality):
    """
    PIL ImageをWebP bytesへ変換する。
    """

    buffer = io.BytesIO()

    image.save(
        buffer,
        format="WEBP",
        quality=quality,
        method=6,
    )

    return buffer.getvalue()


def create_image_variants(file_bytes):
    """
    元画像から2種類のWebPを生成する。

    1. 詳細表示用
       最大長辺 2400px / quality 85

    2. 一覧表示用サムネイル
       最大長辺 500px / quality 78

    元画像そのものは保存しない。

    Returns:
        {
            "image_bytes": bytes,
            "thumbnail_bytes": bytes,
            "width": int,
            "height": int,
            "mime_type": "image/webp"
        }

    Raises:
        ValueError
    """

    original = validate_image(file_bytes)

    try:
        image = _prepare_image(original)

        # ----------------------------------------
        # 詳細表示用
        # ----------------------------------------

        display_image = _resize_image(
            image,
            MAX_IMAGE_SIZE,
        )

        image_bytes = _encode_webp(
            display_image,
            IMAGE_QUALITY,
        )

        # ----------------------------------------
        # サムネイル
        # ----------------------------------------

        thumbnail_image = _resize_image(
            image,
            MAX_THUMBNAIL_SIZE,
        )

        thumbnail_bytes = _encode_webp(
            thumbnail_image,
            THUMBNAIL_QUALITY,
        )

        return {
            "image_bytes": image_bytes,
            "thumbnail_bytes": thumbnail_bytes,
            "width": display_image.width,
            "height": display_image.height,
            "mime_type": "image/webp",
        }

    except Exception as exc:
        logger.exception(
            "Failed to create image variants: %s",
            exc,
        )

        raise ValueError(
            "画像の変換に失敗しました。"
        ) from exc

    finally:
        # 元画像を明示的にclose
        try:
            original.close()
        except Exception:
            pass


# ============================================================
# Object Key
# ============================================================

def generate_object_keys(
    user_id,
    user_photo_id,
):
    """
    R2上の保存先を生成する。

    例:

    users/1/user_photos/123/uuid.webp
    users/1/user_photos/123/uuid_thumb.webp

    UUIDを使用するため、
    同じUserPhotoへ複数枚アップロードしても
    ファイル名が衝突しない。
    """

    unique_id = uuid.uuid4().hex

    base_path = (
        f"users/"
        f"{user_id}/"
        f"user_photos/"
        f"{user_photo_id}/"
    )

    image_key = (
        f"{base_path}"
        f"{unique_id}.webp"
    )

    thumbnail_key = (
        f"{base_path}"
        f"{unique_id}_thumb.webp"
    )

    return image_key, thumbnail_key


# ============================================================
# Upload
# ============================================================

def upload_bytes(
    file_bytes,
    object_key,
    content_type="image/webp",
):
    """
    bytesをR2へアップロードする。

    Returns:
        object_key

    Raises:
        ValueError
        RuntimeError
    """

    if not file_bytes:
        raise ValueError(
            "アップロードするデータが空です。"
        )

    if not object_key:
        raise ValueError(
            "R2オブジェクトキーが指定されていません。"
        )

    client = _get_r2_client()
    bucket_name = _get_bucket_name()

    try:
        client.put_object(
            Bucket=bucket_name,
            Key=object_key,
            Body=file_bytes,
            ContentType=content_type,
            CacheControl=CACHE_CONTROL,
        )

    except (BotoCoreError, ClientError) as exc:
        logger.exception(
            "R2 upload failed: key=%s error=%s",
            object_key,
            exc,
        )

        raise RuntimeError(
            "画像の保存に失敗しました。"
        ) from exc

    return object_key


def upload_image_variants(
    user_id,
    user_photo_id,
    file_bytes,
):
    """
    元画像から2種類のWebPを生成し、
    R2へアップロードする。

    保存するのは、

    - 詳細表示用画像
    - サムネイル

    の2つだけ。

    元画像はR2へ保存しない。

    Returns:
        {
            "image_key": str,
            "thumbnail_key": str,
            "file_size": int,
            "thumbnail_file_size": int,
            "width": int,
            "height": int,
            "mime_type": "image/webp"
        }

    Raises:
        ValueError
        RuntimeError
    """

    variants = create_image_variants(
        file_bytes
    )

    image_key, thumbnail_key = generate_object_keys(
        user_id=user_id,
        user_photo_id=user_photo_id,
    )

    image_uploaded = False
    thumbnail_uploaded = False

    try:
        # ----------------------------------------
        # 詳細表示用画像
        # ----------------------------------------

        upload_bytes(
            variants["image_bytes"],
            image_key,
            variants["mime_type"],
        )

        image_uploaded = True

        # ----------------------------------------
        # サムネイル
        # ----------------------------------------

        upload_bytes(
            variants["thumbnail_bytes"],
            thumbnail_key,
            variants["mime_type"],
        )

        thumbnail_uploaded = True

    except Exception:
        # ----------------------------------------
        # R2ロールバック
        # ----------------------------------------
        #
        # 片方だけ保存された状態を残さない。
        #

        if image_uploaded:
            try:
                delete_object(image_key)
            except Exception:
                logger.exception(
                    "Failed to rollback image object: %s",
                    image_key,
                )

        if thumbnail_uploaded:
            try:
                delete_object(thumbnail_key)
            except Exception:
                logger.exception(
                    "Failed to rollback thumbnail object: %s",
                    thumbnail_key,
                )

        raise

    return {
        "image_key": image_key,
        "thumbnail_key": thumbnail_key,
        "file_size": len(
            variants["image_bytes"]
        ),
        "thumbnail_file_size": len(
            variants["thumbnail_bytes"]
        ),
        "width": variants["width"],
        "height": variants["height"],
        "mime_type": variants["mime_type"],
    }


# ============================================================
# Delete
# ============================================================

def delete_object(object_key):
    """
    R2から1つのオブジェクトを削除する。

    Args:
        object_key: R2 object key

    Raises:
        RuntimeError
    """

    if not object_key:
        return

    client = _get_r2_client()
    bucket_name = _get_bucket_name()

    try:
        client.delete_object(
            Bucket=bucket_name,
            Key=object_key,
        )

    except (BotoCoreError, ClientError) as exc:
        logger.exception(
            "R2 delete failed: key=%s error=%s",
            object_key,
            exc,
        )

        raise RuntimeError(
            "画像の削除に失敗しました。"
        ) from exc


def delete_image_variants(
    image_key,
    thumbnail_key,
):
    """
    表示用画像とサムネイルを削除する。

    片方の削除に失敗しても、
    もう片方の削除は試行する。

    Raises:
        RuntimeError
    """

    errors = []

    for key in (
        image_key,
        thumbnail_key,
    ):
        if not key:
            continue

        try:
            delete_object(key)

        except Exception as exc:
            errors.append(exc)

    if errors:
        raise RuntimeError(
            "画像の一部または全部を削除できませんでした。"
        )


# ============================================================
# Public URL
# ============================================================

def get_public_url(object_key):
    """
    R2 object keyから公開URLを生成する。

    R2_PUBLIC_BASE_URLには、将来的に例えば

        https://img.spcolle.com

    を設定する。

    現時点でR2_PUBLIC_BASE_URLが未設定でも、
    R2へのアップロード・削除処理には影響しない。

    Raises:
        RuntimeError
    """

    if not object_key:
        return None

    base_url = _get_r2_public_base_url()

    if not base_url:
        raise RuntimeError(
            "R2_PUBLIC_BASE_URL が設定されていません。"
        )

    base_url = base_url.rstrip("/")

    # object_keyの先頭に余計な "/" があっても
    # URLが二重スラッシュにならないようにする。
    object_key = object_key.lstrip("/")

    return f"{base_url}/{object_key}"


def get_image_url(image_key):
    """
    表示用画像URLを返す。
    """

    return get_public_url(
        image_key
    )


def get_thumbnail_url(thumbnail_key):
    """
    サムネイルURLを返す。
    """

    return get_public_url(
        thumbnail_key
    )