# config.py
import os

basedir = os.path.abspath(os.path.dirname(__file__))

PREFERRED_URL_SCHEME = "https"

class Config:
    SECRET_KEY = 'koito-annbata'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

# 課金なしで全機能を使えるオーナーアカウント
OWNER_USER_ID = 1