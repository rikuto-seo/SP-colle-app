# config.py
import os

basedir = os.path.abspath(os.path.dirname(__file__))

PREFERRED_URL_SCHEME = "https"

class Config:
    SECRET_KEY = 'koito-annbata'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or \
        'sqlite:///' + os.path.join(basedir, 'instance', 'main.db')
