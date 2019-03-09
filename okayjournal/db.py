from tkinter import simpledialog, Tk

from werkzeug.security import generate_password_hash

from okayjournal.app import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30), unique=False, nullable=False)
    surname = db.Column(db.String(30), unique=False, nullable=False)
    patronymic = db.Column(db.String(30), unique=False, nullable=False)
    login = db.Column(db.String(31), unique=False, nullable=False)
    password_hash = db.Column(db.String(128), unique=True, nullable=False)
    status = db.Column(db.String(7), unique=False, nullable=False)


class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    region = db.Column(db.String(50), unique=False, nullable=False)
    city = db.Column(db.String(50), unique=False, nullable=False)
    school = db.Column(db.String(80), unique=True, nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    student = db.relationship("User", backref=db.backref("schools"), lazy=True)


class Request(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    region = db.Column(db.String(50), unique=False, nullable=False)
    city = db.Column(db.String(50), unique=False, nullable=False)
    school = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(30), unique=False, nullable=False)
    surname = db.Column(db.String(30), unique=False, nullable=False)
    patronymic = db.Column(db.String(30), unique=False, nullable=False)
    password_hash = db.Column(db.String(128), unique=True, nullable=False)


db.create_all()

# Создание админа при первом запуске
if User.query.filter_by(login='admin').first() is None:
    Tk().withdraw()
    password = simpledialog.askstring("Установить пароль админа",
                                      "Сервер запускается в первый раз. "
                                      "Установите пароль учетной записи администратора (admin).",
                                      show='*')
    db.session.add(User(name='', surname='', patronymic='', login='admin',
                        password_hash=generate_password_hash(password), status=''))
    db.session.commit()
