from flask import Flask, render_template, request, redirect, session, Response
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import csv
from datetime import datetime
from io import StringIO, BytesIO
import base64
import requests
import os
app = Flask(__name__)
app.secret_key = "geheimer_schluessel"

ADMIN_EMAIL = "christian.warschburger@gmx.de"
#SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SENDGRID_API_KEY = "SK150a30dd95b17f10961d51638ab76977"


# -----------------------------
# Datenbank Verbindung
# -----------------------------
def get_db():
    return sqlite3.connect("users.db")


# -----------------------------
# Datenbank erstellen
# -----------------------------
def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            bier INTEGER DEFAULT 0
        )
    """)
    db.commit()
    db.close()

#------------------------------
#Admin
#------------------------------
@app.route("/admin")
def admin():
    if "user" not in session or session["user"] != "Admin":
        return "kein Zugriff"
    db = get_db()
    users = db.execute("SELECT id, username, bier FROM users").fetchall()
    db.close()
    return render_template("admin.html", users=users)

# Bier + und -

@app.route("/update_bier/<int:user_id>/<action>")
def update_bier(user_id, action):
    if "user" not in session or session["user"] != "Admin":
        return "kein Zugriff"
    db = get_db()
    if action == "add":
        db.execute("UPDATE users SET bier = bier +1 WHERE id = ?", (user_id,))
    elif action == "sub":
        db.execute("UPDATE users SET bier = bier - 1 WHERE id = ?", (user_id,))
    db.commit()
    db.close()
    return redirect("/admin")

# PW Reseten

@app.route("/reset_password/<int:user_id>", methods=["GET", "POST"])
def reset_password(user_id):
    if "user" not in session or session["user"] != "Admin":
        return "Kein Zugriff"

    if request.method == "POST":
        neues_passwort = request.form["password"]

        db = get_db()
        db.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (generate_password_hash(neues_passwort), user_id)
        )
        db.commit()
        db.close()

        return redirect("/admin")

    return render_template("reset_password.html", user_id=user_id)

# User löschen

@app.route("/delete_user/<int:user_id>", methods=["POST"])
def delete_user(user_id):
    if "user" not in session or session["user"] != "Admin":
        return "Kein Zugriff"

    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    db.close()

    return redirect("/admin")

#Download Tabelle

@app.route("/download")
def download():
    if "user" not in session or session["user"] != "Admin":
        return "Kein Zugriff"

    db = get_db()
    users = db.execute("SELECT username, bier FROM users").fetchall()
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

#Monatsabschluss

@app.route("/abschluss")
def abschluss():
    if "user" not in session or session["user"] != "Admin":
        return "Kein Zugriff"

    db = get_db()
    users = db.execute("SELECT username, bier FROM users").fetchall()

    # Datum für Dateiname
    datum = datetime.now().strftime("%Y-%m")
    filename = f"abschluss_{datum}.csv"

    # CSV im Speicher erstellen
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Bier"])
    for user in users:
        writer.writerow([user[0], user[1]])

    csv_bytes = output.getvalue().encode('utf-8')
    output.close()

    # SendGrid Mail vorbereiten 
    SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
    if not SENDGRID_API_KEY:
        print("kein SendGrid API-Key gefunden!")
    
    encoded_file = base64.b64encode(csv_bytes).decode()

    data = {
        "personalizations": [{
            "to": [{"email": ADMIN_EMAIL}]
        }],
        "from": {"email": ADMIN_EMAIL}, 
        "subject": f"Monatsabschluss {datum}",
        "content": [{
            "type": "text/plain",
            "value": "Hier ist der Monatsabschluss im Anhang."
        }],
        "attachments": [{
            "content": encoded_file,
            "type": "text/csv",
            "filename": filename
        }]
    }

    try:
        response = requests.post(
"https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {SENDGRID_API_KEY}",
                "Content-Type": "application/json"
            },
            json=data
        )
        if response.status_code == 202:
            print("Monatsabschluss per SendGrid gesendet ✅")
        else:
            print("SendGrid Fehler:", response.status_code, response.text)
    except Exception as e:
        print("Fehler beim SendGrid Versand:", e)

    # Bierwerte zurücksetzen
    db.execute("UPDATE users SET bier = 0")
    db.commit()
    db.close()

    # CSV als Download zurückgeben
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
        user = db.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        db.close()

        if user and check_password_hash(user[2], password):
            session["user"] = username
            return redirect("/dashboard")
        else:
            return "Falsche Login-Daten"

    return render_template("login.html")


# -----------------------------
# REGISTRIEREN
# -----------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])

        try:
            db = get_db()
            db.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password)
            )
            db.commit()
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
    user = db.execute(
        "SELECT * FROM users WHERE username = ?",
        (session["user"],)
    ).fetchone()
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
        db.execute(
            "UPDATE users SET bier = bier + 1 WHERE username = ?",
            (session["user"],)
        )
        db.commit()
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
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
