# sakamichi_photo_app/forms.py
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import SubmitField, TextAreaField, StringField, PasswordField, SelectField, IntegerField, DateField
from wtforms.validators import DataRequired, NumberRange, Optional, Email, Length

class IconUploadForm(FlaskForm):
    icon = FileField('アイコン画像', validators=[
        FileRequired(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], '画像ファイルのみアップロード可能です。')
    ])
    submit = SubmitField('アップロード')

class LoginForm(FlaskForm):
    # Firebase運用に合わせて username -> email に変更
    email = StringField('メールアドレス', validators=[
        DataRequired(message="メールアドレスは必須です"),
        Email(message="有効なメールアドレスを入力してください")
    ])
    password = PasswordField('パスワード', validators=[
        DataRequired(message="パスワードを入力してください")
    ])
    submit = SubmitField('ログイン')

class AddPhotoForm(FlaskForm):
    # セレクトボックスの内容は views 側で動的にセットすることを想定
    member = SelectField('メンバー', validators=[DataRequired()])
    costume = SelectField('衣装', validators=[DataRequired()])
    photo_type = SelectField('種類', choices=[
        ('ヨリ','ヨリ'), ('チュウ','チュウ'), ('ヒキ','ヒキ'), ('座り','座り')
    ], validators=[DataRequired()])
    quantity = IntegerField('枚数', default=1, validators=[
        DataRequired(), 
        NumberRange(min=1, message="1枚以上指定してください")
    ])
    date_acquired = DateField('入手日', format='%Y-%m-%d', validators=[Optional()])
    memo = TextAreaField('メモ', validators=[Optional(), Length(max=200)])
    submit = SubmitField('追加')