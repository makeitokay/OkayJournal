from itertools import cycle
import email.utils

from flask import render_template, request, redirect, session, jsonify
from werkzeug.security import check_password_hash
from sqlalchemy.exc import IntegrityError
from validate_email import validate_email

from okayjournal.app import app
from okayjournal.forms import *
from okayjournal.db import *
from okayjournal.login import login
from okayjournal.utils import *


@app.route("/")
@app.route("/index")
def index():
    if logged_in():
        return redirect('/journal')
    else:
        return render_template(
            "index.html", title="OkayJournal",
            after_reg=request.referrer == "http://127.0.0.1:8080/register")


@app.route('/login', methods=['GET', 'POST'])
def login_route():
    form = LoginForm()
    if form.validate_on_submit():
        login_successful = login(form.login.data, form.password.data)
        if not login_successful:
            return render_template('login.html', got=repr(request.form),
                                   form=form,
                                   title="Авторизация",
                                   login_error="Неверный логин или пароль")

        # Запоминание пользователя
        session.permanent = form.remember.data

        if session["role"] == "Student":
            return redirect("/diary")
        elif session["role"] == "Teacher":
            return redirect("/journal")
        elif session['role'] == 'SystemAdmin':
            return redirect('/admin')
        elif session["role"] == "SchoolAdmin":
            return redirect("/school_managing")
    return render_template("login.html", form=form, title="Авторизация")


@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterRequestForm()
    if form.validate_on_submit():
        password_first = request.form["password_first"]
        password_second = request.form["password_second"]
        if not validate_email(request.form["email"]):
            return render_template("register_request.html",
                                   form=form,
                                   title="Запрос на регистрацию",
                                   error="Некорректный адрес электронной "
                                         "почты")
        if password_first == password_second:
            if len(password_first) < 8:
                return render_template("register_request.html",
                                       form=form,
                                       title="Запрос на регистрацию",
                                       error="В пароле должно быть не менее 8 "
                                             "символов")
            db.session.add(Request(region=request.form["region"],
                                   city=request.form["city"],
                                   school=request.form["school"],
                                   name=request.form["name"],
                                   surname=request.form["surname"],
                                   patronymic=request.form["patronymic"],
                                   email=request.form["email"],
                                   password_hash=generate_password_hash(
                                       password_first)))
            try:
                db.session.commit()
            except IntegrityError:
                error = "Учётная запись с такой электронной почтой " \
                        "или названием школы уже существует"
                return render_template("register_request.html",
                                       form=form,
                                       title="Запрос на регистрацию",
                                       error=error)
            return redirect("/")
        return render_template("register_request.html", form=form,
                               title="Запрос на регистрацию",
                               error="Пароли не совпадают")
    return render_template("register_request.html", form=form,
                           title="Запрос на регистрацию")


@app.route("/logout")
def logout():
    del session['user']
    del session['role']

    return redirect("/")


@app.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
    if session["role"] != "SystemAdmin":
        return redirect("/index")

    if request.method == "POST":
        request_id, answer = list(request.form.items())[0]
        register_request = Request.query.filter_by(id=int(request_id)).first()
        if answer == "ok":
            school = School(region=register_request.region,
                            city=register_request.city,
                            school=register_request.school)
            db.session.add(school)
            login = generate_unique_login("SchoolAdmin")
            # noinspection PyArgumentList
            school_admin = SchoolAdmin(
                name=register_request.name,
                surname=register_request.surname,
                patronymic=register_request.patronymic,
                email=register_request.email,
                login=login,
                school_id=school.id,
                password_hash=register_request.password_hash,
                throwaway_password=False)
            db.session.add(school_admin)
            db.session.commit()
            send_approval_letter(school_admin.email,
                                 school_admin.login,
                                 school_admin.name)
        else:
            send_rejection_letter(register_request.email,
                                  register_request.name)
        db.session.delete(register_request)
        db.session.commit()

    requests = Request.query.all()
    return render_template("admin.html", session=session, requests=requests)


# journal routes

@app.route('/diary')
@login_required
@need_to_change_password
def diary():
    week_days = cycle(['Понедельник',
                       'Вторник',
                       'Среда',
                       'Четверг',
                       'Пятница',
                       'Суббота'])

    return render_template('journal/diary.html', session=session,
                           week_days=week_days, next=next,
                           unread=get_count_unread_dialogs(
                               user_id=session["user"]["id"],
                               user_role=session["role"]))


@app.route("/messages", methods=["POST", "GET"])
@login_required
@need_to_change_password
def messages():
    if request.method == "POST":
        db.session.add(Message(
            sender_id=session["user"]["id"],
            sender_role=session["role"],
            recipient_id=int(request.form["user-select"]),
            recipient_role=request.form["role-select"],
            text=request.form["message"]
        ))
        db.session.commit()

    # Список пользователей, которые будут отображаться в добавлении нового
    # диалога
    users = {}
    for user_class in USER_CLASSES:
        users[user_class.__name__] = []
        query = user_class.query.filter_by(
            school_id=session["user"]["school_id"])
        for user in query.order_by(user_class.surname, user_class.name,
                                   user_class.patronymic):
            if not user_equal(user, session):
                users[user_class.__name__].append(user)
    return render_template("journal/messages.html", session=session,
                           users=users,
                           unread=get_count_unread_dialogs(
                               user_id=session["user"]["id"],
                               user_role=session["role"]),
                           type=type)


@app.route('/school_managing')
@school_admin_only
@need_to_change_password
def school_managing():
    return render_template('journal/school_managing.html', session=session,
                           unread=get_count_unread_dialogs(
                               user_id=session["user"]["id"],
                               user_role=session["role"]))


@app.route('/users', methods=["GET", "POST"])
@school_admin_only
@need_to_change_password
def users():
    add_teacher_form = AddTeacherForm()
    if request.method == "POST":
        if not validate_email(request.form["email"]):
            return render_template('journal/users.html', session=session,
                                   unread=get_count_unread_dialogs(
                                       user_id=session["user"]["id"],
                                       user_role=session["role"]),
                                   add_teacher_form=add_teacher_form,
                                   error="Некорректный адрес электронной "
                                         "почты")
        password = generate_throwaway_password()
        login = generate_unique_login("Teacher")
        print(login, password)
        # noinspection PyArgumentList
        teacher = Teacher(school_id=session["user"]["school_id"],
                          name=request.form["name"],
                          surname=request.form["surname"],
                          patronymic=request.form["patronymic"],
                          email=request.form["email"],
                          login=login,
                          password_hash=
                          generate_password_hash(password))
        for k in request.form:
            if k.startswith("subjectSelect"):
                if request.form[k] != "none":
                    subj = Subject.query.filter_by(id=int(request.form[k]))
                    teacher.subjects.append(subj.first())
        send_registration_letter(teacher.email, teacher.login, password,
                                 teacher.name)
        db.session.add(teacher)
        db.session.commit()
    return render_template('journal/users.html', session=session,
                           unread=get_count_unread_dialogs(
                               user_id=session["user"]["id"],
                               user_role=session["role"]),
                           add_teacher_form=add_teacher_form)


@app.route('/school_settings', methods=['GET', 'POST'])
@school_admin_only
@need_to_change_password
def school_settings():
    school = School.query.filter_by(id=session['user']['school_id']).first()

    form = SchoolEditForm()
    if form.validate_on_submit():
        school.region = form.region.data
        school.city = form.city.data
        school.school = form.school.data
        db.session.commit()

        return render_template('journal/school_settings.html', session=session,
                               form=form,
                               unread=get_count_unread_dialogs(
                                   user_id=session["user"]["id"],
                                   user_role=session["role"]),
                               school=school,
                               success=True)

    return render_template('journal/school_settings.html', session=session,
                           form=form,
                           unread=get_count_unread_dialogs(
                               user_id=session["user"]["id"],
                               user_role=session["role"]),
                           school=school)


@app.route('/classes')
@school_admin_only
@need_to_change_password
def classes():
    grades = Grade.query.filter_by(school_id=session['user']['school_id'])\
        .all()
    grades_structured = {}
    for n in range(1, 12):
        grades_structured[n] = list(sorted(
                filter(lambda g: g.number == n, grades),
                key=lambda g: g.letter))

    return render_template('journal/classes.html', session=session,
                           unread=get_count_unread_dialogs(
                               user_id=session["user"]["id"],
                               user_role=session["role"]),
                           grades=grades_structured)


@app.route('/subjects', methods=["GET", "POST"])
@school_admin_only
@need_to_change_password
def subjects():
    if request.method == "POST":
        db.session.add(Subject(
            name=request.form["name"],
            school_id=session["user"]["school_id"]
        ))
        db.session.commit()
    subject_list = Subject.query.filter_by(
        school_id=session["user"]["school_id"]).all()
    form = AddSubjectForm()
    return render_template('journal/subjects.html', session=session,
                           unread=get_count_unread_dialogs(
                               user_id=session["user"]["id"],
                               user_role=session["role"]),
                           subjects=subject_list,
                           form=form)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        print(session["user"]["password_hash"])
        old_password_right = check_password_hash(
            session['user']['password_hash'],
            form.old_password.data)
        if not old_password_right:
            return render_template('journal/settings.html', session=session,
                                   form=form, password_change_error=True,
                                   unread=get_count_unread_dialogs(
                                       user_id=session["user"]["id"],
                                       user_role=session["role"]))

        user = find_user_by_role(session['user']['id'], session['role'])
        user.password_hash = generate_password_hash(form.new_password.data)
        user.throwaway_password = False
        db.session.commit()
        id, role = session["user"]["id"], session["role"]
        del session["user"]
        session["user"] = user_to_dict(find_user_by_role(id, role))
        return render_template('journal/settings.html', session=session,
                               form=form, password_change_success=True,
                               unread=get_count_unread_dialogs(
                                   user_id=session["user"]["id"],
                                   user_role=session["role"]))

    return render_template('journal/settings.html', session=session, form=form,
                           unread=get_count_unread_dialogs(
                               user_id=session["user"]["id"],
                               user_role=session["role"]))


@app.route('/journal')
@login_required
@need_to_change_password
def journal():
    return render_template('journal.html')


@app.route('/timetable')
@login_required
@need_to_change_password
def timetable():
    week_days = cycle(['Понедельник',
                       'Вторник',
                       'Среда',
                       'Четверг',
                       'Пятница',
                       'Суббота'])

    return render_template('journal/timetable.html', session=session,
                           week_days=week_days, next=next,
                           unread=get_count_unread_dialogs(
                               user_id=session["user"]["id"],
                               user_role=session["role"]
                           ))
