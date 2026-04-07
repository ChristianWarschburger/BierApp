from flask import Flask, render_template, request, redirect, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
import csv
from datetime import datetime
from io import StringIO
import base64
import requests
import os
import psycopg2

app = Flask(__name__)
app.secret_key = "geheimer_schluessel"

ADMIN_EMAIL = "christian.warschburger@gmx.de"

# -----------------------------
# Datenbank Verbindung
# -----------------------------
def get_db():
    url = os.environ.get("DATABASE_URL")

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    return psycopg2.connect(url, sslmode="require")


# -----------------------------
# Datenbank erstellen
# -----------------------------
def init_db():
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            bier INTEGER DEFAULT 0
        )
    """)

    db.commit()
    cur.close()
    db.close()


# -----------------------------
# ADMIN
# -----------------------------
@app.route("/admin")
def admin():
    if "user" not in session or session["user"] != "Admin":
        return "kein Zugriff"

    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT id, username, bier FROM users")
    users = cur.fetchall()

    cur.close()
    db.close()

    return render_template("admin.html", users=users)


# Bier + / -
@app.route("/update_bier/<int:user_id>/<action>")
def update_bier(user_id, action):
    if "user" not in session or session["user"] != "Admin":
        return "kein Zugriff"

    db = get_db()
    cur = db.cursor()

    if action == "add":
        cur.execute("UPDATE users SET bier = bier + 1 WHERE id = %s", (user_id,))
    elif action == "sub":
        cur.execute("UPDATE users SET bier = bier - 1 WHERE id = %s", (user_id,))

    db.commit()
    cur.close()
    db.close()

    return redirect("/admin")


# Passwort reset
@app.route("/reset_password/<int:user_id>", methods=["GET", "POST"])
def reset_password(user_id):
    if "user" not in session or session["user"] != "Admin":
        return "Kein Zugriff"

    if request.method == "POST":
        neues_passwort = request.form["password"]

        db = get_db()
        cur = db.cursor()

        cur.execute(
            "UPDATE users SET password = %s WHERE id = %s",
            (generate_password_hash(neues_passwort), user_id)
        )

        db.commit()
        cur.close()
        db.close()

        return redirect("/admin")

    return render_template("reset_password.html", user_id=user_id)


# User löschen
@app.route("/delete_user/<int:user_id>", methods=["POST"])
def delete_user(user_id):
    if "user" not in session or session["user"] != "Admin":
        return "Kein Zugriff"

    db = get_db()
    cur = db.cursor()

    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))

    db.commit()
    cur.close()
    db.close()

    return redirect("/admin")


# -----------------------------
# DOWNLOAD
# -----------------------------
@app.route("/download")
def download():
    if "user" not in session or session["user"] != "Admin":
        return "Kein Zugriff"

    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT username, bier FROM users")
    users = cur.fetchall()

    cur.close()
    db.close()

    dateiname = datetime.now().strftime("%Y%m%d")

    def generate():
        yield "Name,Bier\n"
        for user in users:
            yield f"{user[0]},{user[1]}\n"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=bierliste_{dateiname}.csv"}
    )


# -----------------------------
# MONATSABSCHLUSS
# -----------------------------
@app.route("/abschluss")
def abschluss():
    if "user" not in session or session["user"] != "Admin":
        return "Kein Zugriff"

    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT username, bier FROM users")
    users = cur.fetchall()

    datum = datetime.now().strftime("%Y-%m")
    filename = f"abschluss_{datum}.csv"

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Bier"])

    for user in users:
        writer.writerow([user[0], user[1]])

    csv_bytes = output.getvalue().encode('utf-8')
    output.close()

    # SendGrid
    SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")

    if SENDGRID_API_KEY:
        encoded_file = base64.b64encode(csv_bytes).decode()

        data = {
            "personalizations": [{"to": [{"email": ADMIN_EMAIL}]}],
            "from": {"email": ADMIN_EMAIL},
            "subject": f"Monatsabschluss {datum}",
            "content": [{"type": "text/plain", "value": "CSV im Anhang"}],
            "attachments": [{
                "content": encoded_file,
                "type": "text/csv",
                "filename": filename
            }]
        }

        requests.post(
"https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {SENDGRID_API_KEY}",
                "Content-Type": "application/json"
            },
            json=data
        )

    # Reset
    cur.execute("UPDATE users SET bier = 0")
    db.commit()

    cur.close()
    db.close()

    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# -----------------------------
# LOGIN
# -----------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        db = get_db()
        cur = db.cursor()

        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()

        cur.close()
        db.close()

        if user and check_password_hash(user[2], password):
            session["user"] = username
            return redirect("/dashboard")
        else:
            return "Falsche Login-Daten"

    return render_template("login.html")


# -----------------------------
# REGISTER
# -----------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])

        try:
            db = get_db()
            cur = db.cursor()

            cur.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s)",
                (username, password)
            )

            db.commit()
            cur.close()
            db.close()

            return redirect("/")
        except:
            return "Benutzer existiert schon"

    return render_template("register.html")


# -----------------------------
# DASHBOARD
# -----------------------------
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")

    db = get_db()
    cur = db.cursor()

    cur.execute(
        "SELECT * FROM users WHERE username = %s",
        (session["user"],)
    )
    user = cur.fetchone()

    cur.close()
    db.close()

    if not user:
        return "User nicht gefunden"

    bier = user[3]

    return render_template("dashboard.html", user=session["user"], bier=bier)


# -----------------------------
# +1 BIER
# -----------------------------
@app.route("/add_bier")
def add_bier():
    if "user" in session:
        db = get_db()
        cur = db.cursor()

        cur.execute(
            "UPDATE users SET bier = bier + 1 WHERE username = %s",
            (session["user"],)
        )

        db.commit()
        cur.close()
        db.close()

    return redirect("/dashboard")


# -----------------------------
# LOGOUT
# -----------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# -----------------------------
# START
# -----------------------------
init_db()

if __name__ == "__main__":
    app.run(debug=True)
