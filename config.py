import os

basedir = os.path.abspath(os.path.dirname(__file__))

PREFERRED_URL_SCHEME = "https"


class Config:
    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        "koito-annbata"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ========================================================
    # Cloudflare R2
    # ========================================================
    #
    # R2の認証情報はRenderのEnvironment Variablesから取得する。
    #
    # ローカル開発時も環境変数を設定すれば使用可能。
    #

    R2_ACCOUNT_ID = os.environ.get(
        "R2_ACCOUNT_ID"
    )

    R2_ACCESS_KEY_ID = os.environ.get(
        "R2_ACCESS_KEY_ID"
    )

    R2_SECRET_ACCESS_KEY = os.environ.get(
        "R2_SECRET_ACCESS_KEY"
    )

    R2_BUCKET_NAME = os.environ.get(
        "R2_BUCKET_NAME"
    )

    R2_PUBLIC_BASE_URL = os.environ.get(
        "R2_PUBLIC_BASE_URL"
    )


# ============================================================
# 課金なしで全機能を使えるオーナーアカウント
# ============================================================

OWNER_USER_ID = 1