from functools import partial

from flask import render_template, request
from werkzeug.security import check_password_hash
from sqlalchemy.exc import IntegrityError
from validate_email import validate_email

from okayjournal.app import app
from okayjournal.forms import *
from okayjournal.db import *
from okayjournal.login import login
from okayjournal.utils import *


# Как render_template, только сразу добавляет session и unread в параметры вызова.
def journal_render(*args, **kwargs):
    return partial(
        render_template,
        session=session,
        unread=get_count_unread_dialogs(
            user_id=session["user"]["id"], user_role=session["role"]
        ),
    )(*args, **kwargs)


@app.route("/")
@app.route("/index")
def index():
    if logged_in():
        return redirect("/journal")

    return render_template(
        "index.html",
        title="OkayJournal",
        after_reg=request.referrer == "http://127.0.0.1:8080/register",
    )


@app.route("/login", methods=["GET", "POST"])
def login_route():
    form = LoginForm()
    if form.validate_on_submit():
        login_successful = login(form.login.data, form.password.data)
        if not login_successful:
            return render_template(
                "login.html",
                form=form,
                title="Авторизация",
                login_error="Неверный логин или пароль",
            )

        # Запоминание пользователя
        # TODO: Починить
        session.permanent = form.remember.data

        return redirect("/main_page")

    return render_template("login.html", form=form, title="Авторизация")


@app.route("/main_page")
@login_required
def main_page():
    if session["role"] in ("Student", "Parent"):
        return redirect("/diary")
    if session["role"] == "Teacher":
        return redirect("/journal")
    if session["role"] == "SystemAdmin":
        return redirect("/admin")
    if session["role"] == "SchoolAdmin":
        return redirect("/school_managing")


@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterRequestForm()
    if form.validate_on_submit():
        password_first = request.form["password_first"]
        password_second = request.form["password_second"]
        if not validate_email(request.form["email"]):
            return render_template(
                "register_request.html",
                form=form,
                title="Запрос на регистрацию",
                error="Некорректный адрес электронной " "почты",
            )
        if password_first == password_second:
            password_hash = generate_password_hash(password_first)
            db.session.add(
                Request(
                    region=request.form["region"],
                    city=request.form["city"],
                    school=request.form["school"],
                    name=request.form["name"],
                    surname=request.form["surname"],
                    patronymic=request.form["patronymic"],
                    email=request.form["email"],
                    password_hash=password_hash,
                )
            )
            try:
                db.session.commit()
            except IntegrityError:
                error = (
                    "Учётная запись с такой электронной почтой "
                    "или названием школы уже существует"
                )
                return render_template(
                    "register_request.html",
                    form=form,
                    title="Запрос на регистрацию",
                    error=error,
                )
            return redirect("/")
    return render_template(
        "register_request.html", form=form, title="Запрос на регистрацию"
    )


@app.route("/logout")
def logout():
    if logged_in():
        del session["user"]
        del session["role"]

    return redirect("/")


@app.route("/admin", methods=["GET", "POST"])
@restricted_access(["SystemAdmin"])
def admin():
    if request.method == "POST":
        request_id, answer = list(request.form.items())[0]
        register_request = Request.query.filter_by(id=int(request_id)).first()
        if answer == "ok":
            school = School(
                region=register_request.region,
                city=register_request.city,
                school=register_request.school,
            )
            db.session.add(school)
            admin_login = generate_unique_login("SchoolAdmin")
            # noinspection PyArgumentList
            school_admin = SchoolAdmin(
                name=register_request.name,
                surname=register_request.surname,
                patronymic=register_request.patronymic,
                email=register_request.email,
                login=admin_login,
                school_id=school.id,
                password_hash=register_request.password_hash,
                throwaway_password=False,
            )
            db.session.add(school_admin)
            db.session.commit()
            send_approval_letter(
                school_admin.email, school_admin.login, school_admin.name
            )
        else:
            send_rejection_letter(register_request.email, register_request.name)
        db.session.delete(register_request)
        db.session.commit()

    requests = Request.query.all()
    return render_template("admin.html", session=session, requests=requests)


# journal routes


@app.route("/diary")
@restricted_access(["Student", "Parent"])
@need_to_change_password
def diary():
    return journal_render("journal/diary.html", week_days=week_days, next=next)


@app.route("/messages", methods=["POST", "GET"])
@login_required
@need_to_change_password
def messages():
    if request.method == "POST":
        db.session.add(
            Message(
                sender_id=session["user"]["id"],
                sender_role=session["role"],
                recipient_id=int(request.form["user-select"]),
                recipient_role=request.form["role-select"],
                text=request.form["message"],
            )
        )
        db.session.commit()

    # Список пользователей, которые будут отображаться в добавлении нового
    # диалога
    users = {}
    for user_class in USER_CLASSES:
        users[user_class.__name__] = []
        query = user_class.query.filter_by(school_id=session["user"]["school_id"])
        for user in query.order_by(
            user_class.surname, user_class.name, user_class.patronymic
        ):
            if not user_equal(user, session):
                users[user_class.__name__].append(user)
    return journal_render("journal/messages.html", users=users, type=type)


@app.route("/school_managing")
@restricted_access(["SchoolAdmin"])
@need_to_change_password
def school_managing():
    return journal_render("journal/school_managing.html")


@app.route("/users", methods=["GET", "POST"])
@restricted_access(["SchoolAdmin"])
@need_to_change_password
def users():
    add_teacher_form = AddTeacherForm(prefix="add-teacher")
    add_student_form = AddStudentForm(prefix="add-student")
    add_parent_form = AddParentForm(prefix="add-parent")

    kwargs = {
        "add_teacher_form": add_teacher_form,
        "add_student_form": add_student_form,
        "add_parent_form": add_parent_form,
        "teachers": Teacher.query.filter_by(
            school_id=session["user"]["school_id"]
        ).all(),
        "parents": Parent.query.filter_by(school_id=session["user"]["school_id"]).all(),
        "students": Student.query.filter_by(
            school_id=session["user"]["school_id"]
        ).all(),
    }

    if add_teacher_form.validate_on_submit():
        if not validate_email(request.form["add-teacher-email"]):
            return journal_render(
                "journal/users.html",
                **kwargs,
                error="Некорректный адрес электронной " "почты"
            )
        password = generate_throwaway_password()
        login = generate_unique_login("Teacher")
        print(login, password)
        # noinspection PyArgumentList
        teacher = Teacher(
            school_id=session["user"]["school_id"],
            name=request.form["add-teacher-name"],
            surname=request.form["add-teacher-surname"],
            patronymic=request.form["add-teacher-patronymic"],
            email=request.form["add-teacher-email"],
            login=login,
            password_hash=generate_password_hash(password),
        )
        for k in request.form:
            if k.startswith("subjectSelect"):
                if request.form[k] != "none":
                    subj = Subject.query.filter_by(id=int(request.form[k]))
                    teacher.subjects.append(subj.first())
        send_registration_letter(teacher.email, teacher.login, password, teacher.name)
        db.session.add(teacher)
        db.session.commit()
        kwargs["teachers"] = Teacher.query.filter_by(
            school_id=session["user"]["school_id"]
        ).all()

    if add_student_form.validate_on_submit():
        if not validate_email(request.form["add-student-email"]):
            return journal_render(
                "journal/users.html",
                **kwargs,
                error="Некорректный адрес электронной почты"
            )
        password = generate_throwaway_password()
        login = generate_unique_login("Student")
        print(login, password)

        grade = Grade.query.filter_by(
            school_id=session["user"]["school_id"],
            number=int(request.form["grade_number"]),
            letter=request.form["grade_letter"],
        )
        # noinspection PyArgumentList
        student = Student(
            school_id=session["user"]["school_id"],
            name=request.form["add-student-name"],
            surname=request.form["add-student-surname"],
            patronymic=request.form["add-student-patronymic"],
            email=request.form["add-student-email"],
            login=login,
            password_hash=generate_password_hash(password),
            grade_id=grade.first().id,
            parent_id=int(request.form["parent"]),
        )
        db.session.add(student)
        db.session.commit()

        send_registration_letter(student.email, student.login, password, student.name)

        kwargs["students"] = Student.query.filter_by(
            school_id=session["user"]["school_id"]
        ).all()

    if add_parent_form.validate_on_submit():
        if not validate_email(request.form["add-parent-email"]):
            return journal_render(
                "journal/users.html",
                **kwargs,
                error="Некорректный адрес электронной почты"
            )
        password = generate_throwaway_password()
        login = generate_unique_login("Parent")
        print(login, password)

        # noinspection PyArgumentList
        parent = Parent(
            school_id=session["user"]["school_id"],
            name=request.form["add-parent-name"],
            surname=request.form["add-parent-surname"],
            patronymic=request.form["add-parent-patronymic"],
            email=request.form["add-parent-email"],
            login=login,
            password_hash=generate_password_hash(password),
        )
        db.session.add(parent)
        db.session.commit()

        send_registration_letter(parent.email, parent.login, password, parent.name)

        kwargs["parents"] = Parent.query.filter_by(
            school_id=session["user"]["school_id"]
        ).all()

    return journal_render("journal/users.html", **kwargs)


@app.route("/school_settings", methods=["GET", "POST"])
@restricted_access(["SchoolAdmin"])
@need_to_change_password
def school_settings():
    school = School.query.filter_by(id=session["user"]["school_id"]).first()

    form = SchoolEditForm()
    if form.validate_on_submit():
        school.region = form.region.data
        school.city = form.city.data
        school.school = form.school.data
        db.session.commit()

        return journal_render(
            "journal/school_settings.html", form=form, school=school, success=True
        )

    return journal_render("journal/school_settings.html", form=form, school=school)


@app.route("/classes", methods=["GET", "POST"])
@restricted_access(["SchoolAdmin"])
@need_to_change_password
def classes():
    if request.method == "POST":
        grade_number = int(request.form["grade"].split()[0])
        grade_letter = request.form["grade"].split()[1][1]
        teacher = find_user_by_role(int(request.form["homeroom_teacher"]), "Teacher")
        grade = Grade(
            number=grade_number,
            letter=grade_letter,
            school_id=session["user"]["school_id"],
        )
        db.session.add(grade)
        db.session.commit()
        teacher.homeroom_grade_id = grade.id
        db.session.commit()
    free_teachers = Teacher.query.filter_by(homeroom_grade_id=None).all()
    return journal_render("journal/classes.html", free_teachers=free_teachers)


@app.route("/subjects", methods=["GET", "POST"])
@restricted_access(["SchoolAdmin"])
@need_to_change_password
def subjects():
    if request.method == "POST":
        db.session.add(
            Subject(name=request.form["name"], school_id=session["user"]["school_id"])
        )
        db.session.commit()
    subject_list = Subject.query.filter_by(school_id=session["user"]["school_id"]).all()
    form = AddSubjectForm()
    return journal_render("journal/subjects.html", subjects=subject_list, form=form)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        print(session["user"]["password_hash"])
        old_password_right = check_password_hash(
            session["user"]["password_hash"], form.old_password.data
        )
        if not old_password_right:
            return journal_render(
                "journal/settings.html", form=form, password_change_error=True
            )

        user = find_user_by_role(session["user"]["id"], session["role"])
        user.password_hash = generate_password_hash(form.new_password.data)
        user.throwaway_password = False
        db.session.commit()
        id, role = session["user"]["id"], session["role"]
        del session["user"]
        session["user"] = user_to_dict(find_user_by_role(id, role))
        return journal_render(
            "journal/settings.html", form=form, password_change_success=True
        )

    return journal_render("journal/settings.html", form=form)


@app.route("/journal")
@restricted_access(["Teacher"])
@need_to_change_password
def journal():
    if session['role'] == "SystemAdmin":
        return redirect("/admin")
    return journal_render("journal.html", str=str)


@app.route("/timetable", methods=["GET", "POST"])
@restricted_access(["SchoolAdmin"])
@need_to_change_password
def timetable_index():
    if request.method == "POST":
        grade = Grade.query.filter_by(
            number=int(request.form["number"]),
            letter=request.form["letter"],
            school_id=session["user"]["school_id"],
        )
        return redirect("/timetable/" + str(grade.first().id))

    return journal_render("journal/timetable.html", week_days=week_days, next=next)


@app.route("/timetable/<int:grade_id>", methods=["GET", "POST"])
@restricted_access(["SchoolAdmin"])
@need_to_change_password
def timetable(grade_id):
    if request.method == "POST":
        for i in range(1, 7):
            for j in range(1, 7):
                subject = request.form["subject" + str(i) + str(j)]
                teacher = request.form.get("teacher" + str(i) + str(j), None)
                if subject != "none" and teacher is not None:
                    schedule = Schedule.query.filter_by(
                        school_id=session["user"]["school_id"],
                        day=i,
                        subject_number=j,
                        grade_id=grade_id,
                    ).first()
                    if schedule is None:
                        db.session.add(
                            Schedule(
                                day=i,
                                subject_number=j,
                                subject_id=int(subject),
                                school_id=session["user"]["school_id"],
                                teacher_id=int(teacher),
                                grade_id=grade_id,
                            )
                        )
                    else:
                        schedule.subject_id = int(subject)
                        schedule.teacher_id = int(teacher)
                    db.session.commit()
    schedule = get_grade_schedule(grade_id, session["user"]["school_id"])
    teachers_subjects = get_teachers_subjects(session["user"]["school_id"])
    selectors = {}
    # TODO: рефакторинг
    for i in range(1, 7):
        # Заполним расписание для i-го дня
        selectors.update({i: {}})
        for j in range(1, 7):
            # Для j-го урока
            selectors[i].update({j: {}})
            # Если в полученном расписании есть данный день и данный урок,
            # то сделаем его выбранным
            if schedule.get(i) and schedule.get(i).get(j):
                selected_subject = schedule.get(i).get(j)["subject"]
                selected_teacher = schedule.get(i).get(j)["teacher"]
            else:
                id = list(teachers_subjects.keys())[0]
                selected_subject = {
                    "id": id,
                    "name": list(teachers_subjects.values())[0]["name"],
                }
                teachers = teachers_subjects[id]["teachers"]
                if teachers:
                    selected_teacher = {
                        "id": list(teachers.keys())[0],
                        "name": list(teachers.values())[0]["name"],
                    }
                else:
                    selected_teacher = None
            selectors[i][j].update(
                {"subjects": {selected_subject["id"]: selected_subject["name"]}}
            )
            # Заполним остальные возможные варианты уроков и учителей
            for id, subject in teachers_subjects.items():
                if id != selected_subject["id"]:
                    selectors[i][j]["subjects"].update({id: subject["name"]})
                else:
                    if selected_teacher:
                        selectors[i][j].update(
                            {
                                "teachers": {
                                    selected_teacher["id"]: selected_teacher["name"]
                                }
                            }
                        )
                    else:
                        selectors[i][j].update({"teachers": {}})
                    for teacher_id, teacher in subject["teachers"].items():
                        if teacher_id != selected_teacher["id"]:
                            selectors[i][j]["teachers"].update(
                                {teacher_id: teacher["name"]}
                            )
    return journal_render(
        "journal/timetable.html", week_days=week_days, next=next, selectors=selectors
    )


@app.route("/announcements", methods=["GET", "POST"])
@login_required
@need_to_change_password
def announcements():
    if request.method == "POST":
        db.session.add(
            Announcement(
                school_id=session["user"]["school_id"],
                author_id=session["user"]["id"],
                author_role=session["role"],
                header=request.form.get("announcementHeader"),
                text=request.form.get("announcement"),
            )
        )
        db.session.commit()
    announcements = {}
    for announcement in (
        Announcement.query.filter_by(school_id=session["user"]["school_id"])
        .order_by(Announcement.date)
        .all()
    ):
        author = find_user_by_role(announcement.author_id, announcement.author_role)
        announcements.update(
            {
                announcement.id: {
                    "author": {
                        "name": " ".join(
                            [author.surname, author.name, author.patronymic]
                        )
                    },
                    "header": announcement.header,
                    "text": announcement.text,
                    "date": announcement.date,
                }
            }
        )
    return journal_render(
        "journal/announcements.html",
        announcements=announcements,
        reversed=reversed,
        list=list,
    )


@app.route("/lesson_times", methods=["GET", "POST"])
@restricted_access(["SchoolAdmin"])
@need_to_change_password
def lesson_times():
    if request.method == "POST":
        for i in range(1, len(request.form) // 2 + 1):
            start = request.form["start" + str(i)]
            end = request.form["end" + str(i)]
            if start and end:
                schedule = CallSchedule.query.filter_by(
                    school_id=session["user"]["school_id"], subject_number=i
                ).first()
                if schedule:
                    schedule.start = start
                    schedule.end = end
                else:
                    db.session.add(
                        CallSchedule(
                            school_id=session["user"]["school_id"],
                            subject_number=i,
                            start=start,
                            end=end,
                        )
                    )
                db.session.commit()

    schedule = {}
    for subject in CallSchedule.query.filter_by(
        school_id=session["user"]["school_id"]
    ).all():
        schedule[subject.subject_number] = {"start": subject.start, "end": subject.end}

    return journal_render("journal/lesson_times.html", schedule=schedule)


@app.route("/grading", methods=["GET", "POST"])
@restricted_access(["Teacher"])
@need_to_change_password
def grading():
    return journal_render("journal/grading.html")


@app.errorhandler(404)
def not_found_error(_):
    if logged_in():
        return journal_render("journal/404.html")

    return redirect("/")
