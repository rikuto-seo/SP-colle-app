# config.py
import os

basedir = os.path.abspath(os.path.dirname(__file__))

PREFERRED_URL_SCHEME = "https"

class Config:
    SECRET_KEY = 'koito-annbata'
    SQLALCHEMY_TRACK_MODIFICATIONS = False