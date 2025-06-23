from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import SubmitField, TextAreaField,StringField, PasswordField,SelectField, IntegerField,DateField
from wtforms.validators import DataRequired, NumberRange, Optional

class IconUploadForm(FlaskForm):
    icon = FileField('アイコン画像', validators=[
        FileRequired(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], '画像ファイルのみアップロード可能です。')
    ])
    submit = SubmitField('アップロード')

class ChatForm(FlaskForm):
    content = TextAreaField('メッセージ', validators=[DataRequired()])
    submit = SubmitField('送信')

class LoginForm(FlaskForm):
    username = StringField('ユーザー名', validators=[DataRequired()])
    password = PasswordField('パスワード', validators=[DataRequired()])
    submit = SubmitField('ログイン')

class AddPhotoForm(FlaskForm):
    member = SelectField('メンバー', validators=[DataRequired()])
    costume = SelectField('衣装', validators=[DataRequired()])
    photo_type = SelectField('種類', choices=[('ヨリ','ヨリ'), ('チュウ','チュウ'), ('ヒキ','ヒキ'), ('座り','座り')], validators=[DataRequired()])
    quantity = IntegerField('枚数', default=1, validators=[DataRequired(), NumberRange(min=1)])
    date_acquired = DateField('入手日', format='%Y-%m-%d', validators=[Optional()])
    memo = TextAreaField('メモ', validators=[Optional()])
    submit = SubmitField('追加')