from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
import os
from werkzeug.utils import secure_filename

# ---------------- APP CONFIG ----------------
app = Flask(__name__)
app.secret_key = "sportslink_secret"

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ---------------- DATABASE ----------------
def get_db():
    return sqlite3.connect("instance/sports.db")

# ---------------- HOME ----------------
@app.route("/")
def index():
    return render_template("index.html")

# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            db = get_db()
            db.execute(
                "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
                (
                    request.form["name"],
                    request.form["email"],
                    request.form["password"],
                    request.form["role"],
                ),
            )
            db.commit()
            flash("Account created successfully", "success")
            return redirect("/login")
        except sqlite3.IntegrityError:
            flash("Email already exists", "error")

    return render_template("register.html")

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email=? AND password=?",
            (request.form["email"], request.form["password"]),
        ).fetchone()

        if user:
            session["user_id"] = user[0]
            session["role"] = user[4]

            if user[4] == "player":
                return redirect("/profile")
            else:
                return redirect("/team")

        flash("Invalid email or password", "error")

    return render_template("login.html")

# ---------------- PLAYER PROFILE ----------------
@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()

    if request.method == "POST":
        photo_name = None

        # Photo upload
        if "photo" in request.files:
            photo = request.files["photo"]
            if photo.filename != "":
                photo_name = secure_filename(photo.filename)
                photo.save(os.path.join(app.config["UPLOAD_FOLDER"], photo_name))

        # Replace profile
        db.execute("DELETE FROM player_profiles WHERE user_id=?", (session["user_id"],))
        db.execute(
            """
            INSERT INTO player_profiles
            (user_id, sport, role, description, location, skills, photo)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session["user_id"],
                request.form["sport"],
                request.form["role"],
                request.form["description"],
                request.form["location"],
                request.form["skills"],
                photo_name,
            ),
        )
        db.commit()

    profile = db.execute(
        "SELECT * FROM player_profiles WHERE user_id=?",
        (session["user_id"],),
    ).fetchone()

    return render_template("player_profile.html", profile=profile)

# ---------------- SEARCH PLAYERS ----------------
@app.route("/search")
def search_players():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    players = db.execute(
        """
        SELECT users.id, users.name,
               player_profiles.role,
               player_profiles.description,
               player_profiles.location
        FROM users
        JOIN player_profiles ON users.id = player_profiles.user_id
        """
    ).fetchall()

    return render_template("search_players.html", players=players)

# ---------------- CONNECT ----------------
@app.route("/connect/<int:pid>")
def connect(pid):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    db.execute(
        "INSERT INTO connections (sender_id, receiver_id, status) VALUES (?, ?, ?)",
        (session["user_id"], pid, "pending"),
    )
    db.commit()

    return redirect("/connections")

# ---------------- CONNECTIONS ----------------
@app.route("/connections")
def connections():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    conns = db.execute(
        """
        SELECT users.name, connections.status
        FROM connections
        JOIN users ON users.id = connections.sender_id
        WHERE connections.receiver_id=?
        """,
        (session["user_id"],),
    ).fetchall()

    return render_template("connections.html", conns=conns)

# ---------------- TEAM DASHBOARD ----------------
@app.route("/team", methods=["GET", "POST"])
def team_dashboard():
    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":
        db = get_db()
        db.execute(
            "INSERT INTO team_requirements (team_id, role_needed, location) VALUES (?, ?, ?)",
            (
                session["user_id"],
                request.form["role"],
                request.form["location"],
            ),
        )
        db.commit()
        return redirect("/matches")

    return render_template("post_requirement.html")

# ---------------- MATCHED PLAYERS ----------------
@app.route("/matches")
def matches():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    players = db.execute("SELECT * FROM player_profiles").fetchall()

    return render_template("matched_players.html", players=players)

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------------- RUN SERVER ----------------
if __name__ == "__main__":
    app.run(debug=True)
