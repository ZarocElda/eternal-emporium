print("APP STARTING")

import os
import re
import requests
import hashlib
import math
import secrets
from pathlib import Path
from flask import Flask, request, redirect, url_for, render_template, flash, Response
import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv
from datetime import timedelta
from datetime import datetime
import pytz

from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from config import load_settings

load_dotenv()

settings = load_settings()
DATABASE_URL = settings.database_url

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set.")

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

app = Flask(__name__)
app.secret_key = settings.secret_key
app.config.update(
    APP_ENV=settings.app_env,
    INITIALIZE_DATABASE=settings.initialize_database,
    RUN_DB_MIGRATIONS=settings.run_db_migrations,
    LEGACY_SCHEMA_BOOTSTRAP=settings.legacy_schema_bootstrap,
)
app.permanent_session_lifetime = timedelta(minutes=15)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def run_database_migrations():
    """Apply versioned SQL files exactly once and reject edited migrations."""
    migrations_dir = Path(__file__).with_name("migrations")
    if not migrations_dir.exists():
        return

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename VARCHAR(255) PRIMARY KEY,
                    checksum VARCHAR(64) NOT NULL,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

            for migration_path in sorted(migrations_dir.glob("*.sql")):
                sql = migration_path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()

                cur.execute(
                    "SELECT checksum FROM schema_migrations WHERE filename = %s",
                    (migration_path.name,),
                )
                applied = cur.fetchone()

                if applied:
                    if applied[0] != checksum:
                        raise RuntimeError(
                            f"Applied migration was modified: {migration_path.name}"
                        )
                    continue

                try:
                    cur.execute(sql)
                    cur.execute(
                        """
                        INSERT INTO schema_migrations (filename, checksum)
                        VALUES (%s, %s)
                        """,
                        (migration_path.name, checksum),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
    finally:
        conn.close()

def send_discord_order_notification(username, rsn, item_name, quantity, total_cost, discord_ids=None):
    if not DISCORD_WEBHOOK_URL:
        print("Discord webhook URL is not configured.")
        return

    mentions = ""

    if discord_ids:
        mentions = " ".join(
            f"<@{discord_id}>"
            for discord_id in discord_ids
            if discord_id
        )

    eastern = pytz.timezone("US/Eastern")
    order_time = datetime.now(eastern).strftime("%m/%d/%y, %I:%M %p")

    embed = {
        "title": "📦 New Store Purchase",
        "description": (
            f"👤 **Player:** {username}\n\n"
            f"🎮 **RSN:** {rsn or 'Not Set'}\n\n"
            f"🎁 **Item:** {item_name}\n\n"
            f"🔢 **Quantity:** {quantity}\n\n"
            f"💰 **Cost:** {total_cost:,} points"
        ),
        "color": 15158332,
        "footer": {
            "text": order_time
        }
    }

    payload = {
        "username": "Eternal Emporium",
        "content": mentions,
        "embeds": [embed],
        "allowed_mentions": {
            "parse": ["users"]
        }
    }

    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=10
        )

        if response.status_code not in (200, 204):
            print(
                "Discord webhook failed:",
                response.status_code,
                response.text
            )

    except requests.RequestException as error:
        print("Discord webhook error:", error)

def ensure_discord_notification_table():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS discord_notifications (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            discord_id VARCHAR(50) NOT NULL UNIQUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    cur.close()
    conn.close()

def ensure_item_catalog_table():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS item_catalog (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE,
            default_cost INTEGER NOT NULL DEFAULT 0,
            image TEXT
        )
    """)

    conn.commit()
    cur.close()
    conn.close()

def ensure_store_image_columns():
    conn = get_db_connection()
    cur = conn.cursor()

    # Catalog item images
    cur.execute("""
        ALTER TABLE item_catalog
        ADD COLUMN IF NOT EXISTS image_data BYTEA
    """)

    cur.execute("""
        ALTER TABLE item_catalog
        ADD COLUMN IF NOT EXISTS image_type VARCHAR(50)
    """)

    # Active store item images
    cur.execute("""
        ALTER TABLE items
        ADD COLUMN IF NOT EXISTS image_data BYTEA
    """)

    cur.execute("""
        ALTER TABLE items
        ADD COLUMN IF NOT EXISTS image_type VARCHAR(50)
    """)

    conn.commit()
    cur.close()
    conn.close()

def ensure_profile_picture_column():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS profile_picture TEXT
    """)

    conn.commit()
    cur.close()
    conn.close()

def ensure_profile_picture_data_column():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS profile_picture_data BYTEA
    """)

    conn.commit()
    cur.close()
    conn.close()

def ensure_theme_tables():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS themes (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE,
            theme_title VARCHAR(150),
            primary_color VARCHAR(20) NOT NULL DEFAULT '#3b82f6',
            accent_color VARCHAR(20) NOT NULL DEFAULT '#22c55e',
            page_background VARCHAR(20) NOT NULL DEFAULT '#0f172a',
            card_background VARCHAR(20) NOT NULL DEFAULT '#1e293b',
            header_background VARCHAR(20) NOT NULL DEFAULT '#020617',
            text_color VARCHAR(20) NOT NULL DEFAULT '#e2e8f0',
            muted_text_color VARCHAR(20) NOT NULL DEFAULT '#94a3b8',
            button_color VARCHAR(20) NOT NULL DEFAULT '#3b82f6',
            border_color VARCHAR(20) NOT NULL DEFAULT '#334155',

            banner_image BYTEA,
            banner_image_type VARCHAR(50),

            background_image BYTEA,
            background_image_type VARCHAR(50),

            logo_image BYTEA,
            logo_image_type VARCHAR(50),

            is_active BOOLEAN NOT NULL DEFAULT FALSE,

            start_date TIMESTAMP,
            end_date TIMESTAMP,

            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create the permanent default theme if it does not already exist.
    cur.execute("""
        INSERT INTO themes (
            name,
            theme_title,
            primary_color,
            accent_color,
            page_background,
            card_background,
            header_background,
            text_color,
            muted_text_color,
            button_color,
            border_color,
            is_active
        )
        VALUES (
            'Eternal Emporium Default',
            'Eternal Emporium',
            '#3b82f6',
            '#22c55e',
            '#0f172a',
            '#1e293b',
            '#020617',
            '#e2e8f0',
            '#94a3b8',
            '#3b82f6',
            '#334155',
            TRUE
        )
        ON CONFLICT (name) DO NOTHING
    """)

    conn.commit()
    cur.close()
    conn.close()

def ensure_theme_text_columns():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        ALTER TABLE themes
        ADD COLUMN IF NOT EXISTS login_title VARCHAR(200)
    """)

    cur.execute("""
        ALTER TABLE themes
        ADD COLUMN IF NOT EXISTS login_message TEXT
    """)

    cur.execute("""
        ALTER TABLE themes
        ADD COLUMN IF NOT EXISTS register_title VARCHAR(200)
    """)

    cur.execute("""
        ALTER TABLE themes
        ADD COLUMN IF NOT EXISTS register_message TEXT
    """)

    cur.execute("""
        ALTER TABLE themes
        ADD COLUMN IF NOT EXISTS browser_title VARCHAR(200)
    """)

    conn.commit()
    cur.close()
    conn.close()


def ensure_password_security_columns():
    """Add password-upgrade state and flag existing elevated accounts once."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE
    """)
    cur.execute("""
        ALTER TABLE users
        ALTER COLUMN password TYPE TEXT
        USING password::text
    """)
    cur.execute("""
        ALTER TABLE users
        ALTER COLUMN pin TYPE TEXT
        USING pin::text
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_migrations (
            name VARCHAR(100) PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        INSERT INTO app_migrations (name)
        VALUES (%s)
        ON CONFLICT (name) DO NOTHING
        RETURNING name
    """, ("require_elevated_password_v1",))

    if cur.fetchone():
        cur.execute("""
            UPDATE users
            SET must_change_password = TRUE
            WHERE role IN ('admin', 'store_manager', 'owner')
        """)

    conn.commit()
    cur.close()
    conn.close()


ELEVATED_ROLES = {"admin", "store_manager", "owner"}
ROLE_LEVELS = {"user": 0, "admin": 1, "store_manager": 2, "owner": 3}
EVENT_MANAGER_ROLES = {"store_manager", "owner"}


def role_can_manage_events(role):
    return role in EVENT_MANAGER_ROLES


def parse_event_datetime(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def event_slug(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:150] or "event"


PUZZLE_TYPES = {
    "code": "Code",
    "password": "Password",
    "trivia": "Trivia",
    "ordering": "Ordering",
    "image_hotspot": "Image hotspot",
    "scavenger": "Scavenger hunt",
    "hidden_clue": "Hidden website clue",
    "interactive": "Interactive puzzle",
}


def nonempty_lines(value):
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def build_puzzle_configuration(form):
    puzzle_type = form.get("puzzle_type", "code")
    if puzzle_type not in PUZZLE_TYPES:
        raise ValueError("Choose a valid puzzle type")

    content = {
        "instructions": form.get("instructions", "").strip(),
        "options": nonempty_lines(form.get("options", "")),
        "hidden_location": form.get("hidden_location", "").strip(),
    }
    solution = {}

    if puzzle_type == "ordering":
        correct_order = nonempty_lines(form.get("correct_order", ""))
        options = nonempty_lines(form.get("options", ""))
        if len(correct_order) < 2:
            raise ValueError("Ordering puzzles need at least two items")
        if len(options) < 2:
            raise ValueError("Add the ordering items in a shuffled display order")
        if sorted(normalize_puzzle_answer(item) for item in options) != sorted(normalize_puzzle_answer(item) for item in correct_order):
            raise ValueError("The display items and correct order must contain the same items")
        content["options"] = options
        solution["correct_order"] = correct_order
    elif puzzle_type == "image_hotspot":
        try:
            x = float(form.get("hotspot_x", ""))
            y = float(form.get("hotspot_y", ""))
            radius = float(form.get("hotspot_radius", "8") or 8)
        except ValueError as exc:
            raise ValueError("Hotspot position and size must be numbers") from exc
        if not 0 <= x <= 100 or not 0 <= y <= 100 or not 1 <= radius <= 50:
            raise ValueError("Hotspot values must fit within the image")
        solution["hotspot"] = {"x": x, "y": y, "radius": radius}
    else:
        answers = nonempty_lines(form.get("accepted_answers", ""))
        if not answers:
            raise ValueError("Add at least one accepted answer")
        solution["accepted_answers"] = answers

    hints = [
        hint for hint in (
            form.get("hint_1", "").strip(),
            form.get("hint_2", "").strip(),
            form.get("hint_3", "").strip(),
        ) if hint
    ]
    return puzzle_type, content, solution, hints


def normalize_puzzle_answer(value):
    return re.sub(r"\s+", " ", (value or "").strip().casefold())


def puzzle_answer_is_correct(puzzle_type, solution, submitted_answer=None, ordered_items=None, hotspot=None):
    if puzzle_type == "ordering":
        expected = [normalize_puzzle_answer(item) for item in solution.get("correct_order", [])]
        actual = [normalize_puzzle_answer(item) for item in (ordered_items or []) if item.strip()]
        return bool(expected) and actual == expected
    if puzzle_type == "image_hotspot":
        target = solution.get("hotspot", {})
        if not hotspot or not target:
            return False
        try:
            distance = math.hypot(float(hotspot[0]) - float(target["x"]), float(hotspot[1]) - float(target["y"]))
            return distance <= float(target.get("radius", 8))
        except (TypeError, ValueError, KeyError):
            return False
    answer = normalize_puzzle_answer(submitted_answer)
    accepted = {normalize_puzzle_answer(item) for item in solution.get("accepted_answers", [])}
    return bool(answer) and answer in accepted


def event_is_open(status, starts_at, ends_at, now=None):
    now = now or datetime.now()
    if status not in {"published", "scheduled"}:
        return False
    if starts_at and now < starts_at:
        return False
    if ends_at and now >= ends_at:
        return False
    return True


def request_page_scope():
    path = request.path
    if path.startswith("/store"):
        return "store"
    if path.startswith("/dashboard"):
        return "dashboard"
    if path.startswith("/profile"):
        return "profile"
    if path.startswith("/purchases"):
        return "purchases"
    return None


def valid_elevated_password(password):
    return (
        len(password) >= 5
        and re.search(r"[A-Za-z]", password)
        and re.search(r"\d", password)
        and re.search(r"[^A-Za-z0-9\s]", password)
    )


def credential_matches(stored_password, supplied_password):
    if not stored_password:
        return False

    if stored_password.startswith(("scrypt:", "pbkdf2:", "argon2:")):
        return check_password_hash(stored_password, supplied_password)

    return stored_password == supplied_password

class User(UserMixin):
    def __init__(self, id, username, password, role, must_change_password=False):
        self.id = id
        self.username = username
        self.password = password
        self.role = role
        self.must_change_password = must_change_password


@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, username, password, role, must_change_password
        FROM users
        WHERE id = %s
    """, (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return User(*user) if user else None


@app.route("/")
def home():
    return redirect(url_for("login"), code=302)


# ================= REGISTER =================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        pin = request.form["pin"]
        verify = request.form["verify"]

        if pin != verify:
            flash("PINs do not match", "error")
            return render_template("register.html")

        if len(pin) != 4 or not pin.isdigit():
            flash("PIN must be 4 digits", "error")
            return render_template("register.html")

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute(
                "INSERT INTO users (username, password, role, pin) VALUES (%s, %s, %s, %s)",
                (username, pin, "user", pin)
            )
            conn.commit()
        except:
            flash("Username already exists", "error")
            return render_template("register.html")
        finally:
            cur.close()
            conn.close()

        flash("Account created successfully", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("store"))

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, username, password, role, must_change_password
            FROM users
            WHERE username = %s
        """, (username,))
        user = cur.fetchone()

        cur.close()
        conn.close()

        if user and credential_matches(user[2], password):
            from flask import session
            session.permanent = True
            login_user(User(*user))
            if user[4]:
                return redirect(url_for("change_password"))
            return redirect(url_for("store"))

        flash("Invalid credentials", "error")
        return render_template("login.html")

    return render_template("login.html")


@app.before_request
def enforce_required_password_change():
    if not current_user.is_authenticated or not current_user.must_change_password:
        return None

    allowed_endpoints = {
        "change_password", "logout", "static", "theme_logo_image",
        "theme_banner_image", "theme_background_image"
    }
    if request.endpoint not in allowed_endpoints:
        return redirect(url_for("change_password"))

    return None


@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT password FROM users WHERE id = %s", (current_user.id,))
        row = cur.fetchone()

        if not row or not credential_matches(row[0], current_password):
            cur.close()
            conn.close()
            flash("Current PIN or password is incorrect", "error")
            return redirect(url_for("change_password"))

        if new_password != confirm_password:
            cur.close()
            conn.close()
            flash("New passwords do not match", "error")
            return redirect(url_for("change_password"))

        if current_user.role in ELEVATED_ROLES:
            if not valid_elevated_password(new_password):
                cur.close()
                conn.close()
                flash("Password must be at least 5 characters and include a letter, number, and special character", "error")
                return redirect(url_for("change_password"))
        elif len(new_password) != 4 or not new_password.isdigit():
            cur.close()
            conn.close()
            flash("PIN must be 4 digits", "error")
            return redirect(url_for("change_password"))

        cur.execute("""
            UPDATE users
            SET password = %s, pin = %s, must_change_password = FALSE
            WHERE id = %s
        """, (generate_password_hash(new_password), new_password, current_user.id))
        conn.commit()
        cur.close()
        conn.close()

        current_user.must_change_password = False
        flash("Password updated successfully", "success")
        return redirect(url_for("store"))

    return render_template("change_password.html")


# ================= DASHBOARD =================
@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT rsn, points FROM users WHERE id = %s", (current_user.id,))
    rsn, points = cur.fetchone()

    cur.execute("SELECT COUNT(*) FROM purchases WHERE user_id = %s", (current_user.id,))
    total_purchases = cur.fetchone()[0]

    cur.execute("""
        SELECT item_name, total_cost, timestamp
        FROM purchases
        WHERE user_id = %s
        ORDER BY timestamp DESC
        LIMIT 1
    """, (current_user.id,))
    last_purchase = cur.fetchone()

    cur.execute("""
        SELECT item_name, total_cost
        FROM purchases
        WHERE user_id = %s
        ORDER BY timestamp DESC
        LIMIT 3
    """, (current_user.id,))
    recent = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "dashboard.html",
        username=current_user.username,
        role=current_user.role,
        rsn=rsn,
        points=points,
        total_purchases=total_purchases,
        last_purchase=last_purchase,
        recent=recent
    )

@app.route("/profile_picture/<int:user_id>")
def profile_picture_image(user_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT profile_picture_data, profile_picture
        FROM users
        WHERE id = %s
    """, (user_id,))

    result = cur.fetchone()

    cur.close()
    conn.close()

    if not result or not result[0]:
        return "", 404

    image_data, content_type = result

    return Response(
        bytes(image_data),
        mimetype=content_type or "image/jpeg"
    )

# ================= STORE ITEM IMAGES =================

@app.route("/catalog_image/<int:catalog_id>")
def catalog_image(catalog_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT image_data, image_type
        FROM item_catalog
        WHERE id = %s
    """, (catalog_id,))

    result = cur.fetchone()

    cur.close()
    conn.close()

    if not result or not result[0]:
        return "", 404

    image_data, content_type = result

    return Response(
        bytes(image_data),
        mimetype=content_type or "image/jpeg"
    )


@app.route("/item_image/<int:item_id>")
def item_image(item_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT image_data, image_type
        FROM items
        WHERE id = %s
    """, (item_id,))

    result = cur.fetchone()

    cur.close()
    conn.close()

    if not result or not result[0]:
        return "", 404

    image_data, content_type = result

    return Response(
        bytes(image_data),
        mimetype=content_type or "image/jpeg"
    )

# ================= THEME IMAGES =================

@app.route("/theme_logo/<int:theme_id>")
def theme_logo_image(theme_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT logo_image, logo_image_type
        FROM themes
        WHERE id = %s
    """, (theme_id,))

    result = cur.fetchone()

    cur.close()
    conn.close()

    if not result or not result[0]:
        return "", 404

    image_data, content_type = result

    return Response(
        bytes(image_data),
        mimetype=content_type or "image/png"
    )


@app.route("/theme_banner/<int:theme_id>")
def theme_banner_image(theme_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT banner_image, banner_image_type
        FROM themes
        WHERE id = %s
    """, (theme_id,))

    result = cur.fetchone()

    cur.close()
    conn.close()

    if not result or not result[0]:
        return "", 404

    image_data, content_type = result

    return Response(
        bytes(image_data),
        mimetype=content_type or "image/jpeg"
    )

@app.route("/theme_background/<int:theme_id>")
def theme_background_image(theme_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT background_image, background_image_type
        FROM themes
        WHERE id = %s
    """, (theme_id,))

    result = cur.fetchone()

    cur.close()
    conn.close()

    if not result or not result[0]:
        return "", 404

    image_data, content_type = result

    return Response(
        bytes(image_data),
        mimetype=content_type or "image/jpeg"
    )

# ================= PROFILE =================
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":

                # ================= OWNER DISCORD NOTIFICATIONS =================
        if "discord_action" in request.form:

            if current_user.role != "owner":
                flash("Unauthorized", "error")
                cur.close()
                conn.close()
                return redirect(url_for("profile"))

            discord_action = request.form.get("discord_action")

            # ================= ADD DISCORD RECIPIENT =================
            if discord_action == "add":

                name = request.form.get("discord_name", "").strip()
                discord_id = request.form.get("discord_id", "").strip()

                if not name or not discord_id:
                    flash("Name and Discord ID are required", "error")
                    cur.close()
                    conn.close()
                    return redirect(url_for("profile"))

                if not discord_id.isdigit():
                    flash("Discord ID must contain numbers only", "error")
                    cur.close()
                    conn.close()
                    return redirect(url_for("profile"))

                try:
                    cur.execute("""
                        INSERT INTO discord_notifications (
                            name,
                            discord_id
                        )
                        VALUES (%s, %s)
                    """, (
                        name,
                        discord_id
                    ))

                    conn.commit()
                    flash(f"{name} added to Discord notifications", "success")

                except psycopg2.IntegrityError:
                    conn.rollback()
                    flash("That Discord ID is already on the notification list", "error")

                cur.close()
                conn.close()
                return redirect(url_for("profile"))

            # ================= REMOVE DISCORD RECIPIENT =================
            if discord_action == "remove":

                notification_id = request.form.get("notification_id")

                if notification_id:
                    cur.execute("""
                        DELETE FROM discord_notifications
                        WHERE id = %s
                    """, (notification_id,))

                    conn.commit()
                    flash("Discord notification recipient removed", "success")

                cur.close()
                conn.close()
                return redirect(url_for("profile"))

        # ================= PROFILE PICTURE =================
        if "profile_picture" in request.files:
            file = request.files["profile_picture"]

            if file and file.filename != "":
                extension = os.path.splitext(file.filename)[1].lower()
                allowed_extensions = [".jpg", ".jpeg", ".png", ".webp"]

                if extension not in allowed_extensions:
                    flash("Profile picture must be JPG, PNG, or WEBP", "error")
                    cur.close()
                    conn.close()
                    return redirect(url_for("profile"))

                image_data = file.read()

                if len(image_data) > 5 * 1024 * 1024:
                    flash("Profile picture must be smaller than 5 MB", "error")
                    cur.close()
                    conn.close()
                    return redirect(url_for("profile"))

                content_type = file.content_type

                cur.execute("""
                    UPDATE users
                    SET profile_picture_data = %s,
                        profile_picture = %s
                    WHERE id = %s
                """, (
                    psycopg2.Binary(image_data),
                    content_type,
                    current_user.id
                ))

                conn.commit()
                flash("Profile picture updated", "success")

                cur.close()
                conn.close()

                return redirect(url_for("profile"))

        # ================= OWNER ITEM CATALOG =================
        if "catalog_action" in request.form:

            if current_user.role not in ["owner", "store_manager"]:
                flash("Unauthorized", "error")
                cur.close()
                conn.close()
                return redirect(url_for("profile"))

            catalog_action = request.form.get("catalog_action")

            # ================= ADD CATALOG ITEM =================
            if catalog_action == "add":
                name = request.form.get("catalog_name", "").strip()
                cost = request.form.get("catalog_cost")
                image_data = None
                image_type = None

                if not name or not cost:
                    flash("Item name and default cost are required", "error")
                    cur.close()
                    conn.close()
                    return redirect(url_for("profile"))

                try:
                    cost = int(cost)
                except ValueError:
                    flash("Default cost must be a number", "error")
                    cur.close()
                    conn.close()
                    return redirect(url_for("profile"))

                if "catalog_image" in request.files:
                    file = request.files["catalog_image"]

                    if file and file.filename != "":
                        extension = os.path.splitext(file.filename)[1].lower()
                        allowed_extensions = [".jpg", ".jpeg", ".png", ".webp"]

                        if extension not in allowed_extensions:
                            flash("Catalog image must be JPG, PNG, or WEBP", "error")
                            cur.close()
                            conn.close()
                            return redirect(url_for("profile"))

                        image_data = file.read()

                        if len(image_data) > 5 * 1024 * 1024:
                            flash("Catalog image must be smaller than 5 MB", "error")
                            cur.close()
                            conn.close()
                            return redirect(url_for("profile"))

                        image_type = file.content_type

                try:
                    cur.execute("""
                        INSERT INTO item_catalog (
                            name,
                            default_cost,
                            image_data,
                            image_type
                        )
                        VALUES (%s, %s, %s, %s)
                    """, (
                        name,
                        cost,
                        psycopg2.Binary(image_data) if image_data else None,
                        image_type
                    ))

                    conn.commit()
                    flash("Item added to Store Catalog", "success")

                except psycopg2.IntegrityError:
                    conn.rollback()
                    flash("That item is already in the catalog", "error")

                cur.close()
                conn.close()
                return redirect(url_for("profile"))

            # ================= REMOVE CATALOG ITEM =================
            if catalog_action == "remove":
                catalog_id = request.form.get("catalog_id")

                if catalog_id:
                    cur.execute(
                        "DELETE FROM item_catalog WHERE id = %s",
                        (catalog_id,)
                    )

                    conn.commit()
                    flash("Item removed from Store Catalog", "success")

                cur.close()
                conn.close()
                return redirect(url_for("profile"))

        # ================= CHANGE PIN =================
        if "current_pin" in request.form:
            current_pin = request.form["current_pin"]
            new_pin = request.form["new_pin"]
            confirm_pin = request.form["confirm_pin"]

            cur.execute(
                "SELECT pin FROM users WHERE id = %s",
                (current_user.id,)
            )

            stored_pin = cur.fetchone()[0]

            if current_pin != stored_pin:
                flash("Current PIN is incorrect", "error")
                cur.close()
                conn.close()
                return redirect(url_for("profile"))

            if new_pin != confirm_pin:
                flash("New PINs do not match", "error")
                cur.close()
                conn.close()
                return redirect(url_for("profile"))

            if current_user.role in ELEVATED_ROLES and not valid_elevated_password(new_pin):
                flash("Password must be at least 5 characters and include a letter, number, and special character", "error")
                cur.close()
                conn.close()
                return redirect(url_for("profile"))

            if current_user.role not in ELEVATED_ROLES and (len(new_pin) != 4 or not new_pin.isdigit()):
                flash("PIN must be 4 digits", "error")
                cur.close()
                conn.close()
                return redirect(url_for("profile"))

            cur.execute(
                "UPDATE users SET pin = %s, password = %s, must_change_password = FALSE WHERE id = %s",
                (new_pin, generate_password_hash(new_pin), current_user.id)
            )

            conn.commit()
            flash("PIN updated successfully", "success")

            cur.close()
            conn.close()

            return redirect(url_for("profile"))

        # ================= UPDATE RSN =================
        if "rsn" in request.form:
            new_rsn = request.form["rsn"].strip()

            cur.execute(
                "SELECT id FROM users WHERE rsn = %s AND id != %s",
                (new_rsn, current_user.id)
            )

            if cur.fetchone():
                flash("RSN already in use", "error")
                cur.close()
                conn.close()
                return redirect(url_for("profile"))

            cur.execute(
                "UPDATE users SET rsn = %s WHERE id = %s",
                (new_rsn, current_user.id)
            )

            conn.commit()
            flash("RSN updated", "success")

            cur.close()
            conn.close()

            return redirect(url_for("profile"))

    # ================= USER INFO =================
    cur.execute("""
        SELECT rsn, points, profile_picture_data
        FROM users
        WHERE id = %s
    """, (current_user.id,))

    rsn, points, profile_picture_data = cur.fetchone()

    profile_picture = None

    if profile_picture_data:
        profile_picture = url_for(
            "profile_picture_image",
            user_id=current_user.id
        )

    # ================= TOTAL PURCHASES =================
    cur.execute(
        "SELECT COUNT(*) FROM purchases WHERE user_id = %s",
        (current_user.id,)
    )

    total_purchases = cur.fetchone()[0]

    # ================= LAST PURCHASE =================
    cur.execute("""
        SELECT item_name, total_cost
        FROM purchases
        WHERE user_id = %s
        ORDER BY timestamp DESC
        LIMIT 1
    """, (current_user.id,))

    last_purchase = cur.fetchone()

    # ================= RECENT PURCHASES =================
    cur.execute("""
        SELECT item_name, total_cost
        FROM purchases
        WHERE user_id = %s
        ORDER BY timestamp DESC
        LIMIT 3
    """, (current_user.id,))

    recent = cur.fetchall()

    # ================= OWNER ITEM CATALOG =================
    catalog_items = []

    if current_user.role in ["owner", "store_manager"]:
        cur.execute("""
            SELECT
                id,
                name,
                default_cost,
                image_data IS NOT NULL
            FROM item_catalog
            ORDER BY name ASC
        """)

        catalog_rows = cur.fetchall()

        catalog_items = [
            {
                "id": item[0],
                "name": item[1],
                "default_cost": item[2],
                "image": (
                    url_for("catalog_image", catalog_id=item[0])
                    if item[3]
                    else None
                )
            }
            for item in catalog_rows
        ]

# ================= OWNER DISCORD NOTIFICATIONS =================
    discord_notifications = []

    if current_user.role == "owner":
        cur.execute("""
            SELECT id, name, discord_id
            FROM discord_notifications
            ORDER BY name ASC
        """)

        discord_rows = cur.fetchall()

        discord_notifications = [
            {
                "id": row[0],
                "name": row[1],
                "discord_id": row[2]
            }
            for row in discord_rows
        ]

    cur.close()
    conn.close()

    return render_template(
        "profile.html",
        username=current_user.username,
        role=current_user.role,
        rsn=rsn,
        points=points,
        profile_picture=profile_picture,
        total_purchases=total_purchases,
        last_purchase=last_purchase,
        recent=recent,
        catalog_items=catalog_items,
        discord_notifications=discord_notifications
    )

# ================= THEME MANAGER =================
@app.route("/theme_manager", methods=["GET", "POST"])
@login_required
def theme_manager():

    # OWNER ONLY
    if current_user.role != "owner":
        flash("Only the owner can manage website themes", "error")
        return redirect(url_for("store"))

    conn = get_db_connection()
    cur = conn.cursor()

    # ================= THEME ACTIONS =================
    if request.method == "POST":

        theme_action = request.form.get("theme_action")
        theme_id = request.form.get("theme_id")

        # ================= ACTIVATE THEME =================
        if theme_action == "activate" and theme_id:

            cur.execute("""
                UPDATE themes
                SET is_active = FALSE
            """)

            cur.execute("""
                UPDATE themes
                SET is_active = TRUE
                WHERE id = %s
            """, (theme_id,))

            conn.commit()

            flash("Theme activated!", "success")
            cur.close()
            conn.close()

            return redirect(url_for("theme_manager"))

        # ================= DELETE THEME =================
        if theme_action == "delete" and theme_id:

            cur.execute("""
                SELECT name
                FROM themes
                WHERE id = %s
            """, (theme_id,))

            theme = cur.fetchone()

            if not theme:
                flash("Theme not found", "error")

            elif theme[0] == "Eternal Emporium Default":
                flash("The default theme cannot be deleted", "error")

            else:
                cur.execute("""
                    DELETE FROM themes
                    WHERE id = %s
                """, (theme_id,))

                conn.commit()
                flash("Theme deleted", "success")

            cur.close()
            conn.close()

            return redirect(url_for("theme_manager"))

        # ================= RESTORE DEFAULT =================
        if theme_action == "restore_default":

            cur.execute("""
                UPDATE themes
                SET is_active = FALSE
            """)

            cur.execute("""
                UPDATE themes
                SET is_active = TRUE
                WHERE name = 'Eternal Emporium Default'
            """)

            conn.commit()

            flash("Default Eternal Emporium theme restored!", "success")

            cur.close()
            conn.close()

            return redirect(url_for("theme_manager"))

        # ================= EDIT THEME =================
        if theme_action == "edit" and theme_id:

            theme_name = request.form.get("theme_name", "").strip()
            theme_title = request.form.get("theme_title", "").strip()
            browser_title = request.form.get("browser_title", "").strip()

            login_title = request.form.get("login_title", "").strip()
            login_message = request.form.get("login_message", "").strip()

            register_title = request.form.get("register_title", "").strip()
            register_message = request.form.get("register_message", "").strip()

            primary_color = request.form.get("primary_color", "#3b82f6")
            accent_color = request.form.get("accent_color", "#22c55e")
            page_background = request.form.get("page_background", "#0f172a")
            card_background = request.form.get("card_background", "#1e293b")
            header_background = request.form.get("header_background", "#020617")
            text_color = request.form.get("text_color", "#e2e8f0")
            muted_text_color = request.form.get("muted_text_color", "#94a3b8")
            button_color = request.form.get("button_color", "#3b82f6")
            border_color = request.form.get("border_color", "#334155")

            start_date_raw = request.form.get("start_date", "").strip()
            end_date_raw = request.form.get("end_date", "").strip()

            activate_now = request.form.get("activate_now") == "yes"

            # Theme name is required
            if not theme_name:
                flash("Theme name is required", "error")
                cur.close()
                conn.close()
                return redirect(url_for("theme_manager"))

            # ================= DATES =================
            start_date = None
            end_date = None

            try:
                if start_date_raw:
                    start_date = datetime.fromisoformat(start_date_raw)

                if end_date_raw:
                    end_date = datetime.fromisoformat(end_date_raw)

            except ValueError:
                flash("Invalid theme start or end date", "error")
                cur.close()
                conn.close()
                return redirect(url_for("theme_manager"))

            if start_date and end_date and end_date <= start_date:
                flash("Theme end date must be after the start date", "error")
                cur.close()
                conn.close()
                return redirect(url_for("theme_manager"))

            # ================= IMAGE HELPER =================
            allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
            max_image_size = 5 * 1024 * 1024

            def read_edit_theme_image(field_name):

                file = request.files.get(field_name)

                if not file or file.filename == "":
                    return None, None

                extension = os.path.splitext(file.filename)[1].lower()

                if extension not in allowed_extensions:
                    raise ValueError(
                        "Theme images must be JPG, PNG, or WEBP"
                    )

                image_data = file.read()

                if len(image_data) > max_image_size:
                    raise ValueError(
                        "Each theme image must be smaller than 5 MB"
                    )

                return psycopg2.Binary(image_data), file.content_type

            try:
                logo_image, logo_image_type = read_edit_theme_image(
                    "logo_image"
                )

                banner_image, banner_image_type = read_edit_theme_image(
                    "banner_image"
                )

                background_image, background_image_type = read_edit_theme_image(
                    "background_image"
                )

            except ValueError as error:
                flash(str(error), "error")
                cur.close()
                conn.close()
                return redirect(url_for("theme_manager"))

            # Make sure the theme actually exists
            cur.execute("""
                SELECT
                    name,
                    logo_image,
                    logo_image_type,
                    banner_image,
                    banner_image_type,
                    background_image,
                    background_image_type
                FROM themes
                WHERE id = %s
            """, (theme_id,))

            existing_theme = cur.fetchone()

            if not existing_theme:
                flash("Theme not found", "error")
                cur.close()
                conn.close()
                return redirect(url_for("theme_manager"))

            # Protect the permanent default theme name
            if existing_theme[0] == "Eternal Emporium Default":
                theme_name = "Eternal Emporium Default"

            # ================= KEEP / REPLACE / REMOVE IMAGES =================

            remove_logo = request.form.get("remove_logo_image") == "yes"
            remove_banner = request.form.get("remove_banner_image") == "yes"
            remove_background = request.form.get("remove_background_image") == "yes"

            # LOGO
            # A newly uploaded image takes priority.
            # Otherwise remove it if requested, or keep the existing image.
            if logo_image is None:
                if remove_logo:
                    logo_image = None
                    logo_image_type = None
                else:
                    logo_image = existing_theme[1]
                    logo_image_type = existing_theme[2]

            # BANNER
            if banner_image is None:
                if remove_banner:
                    banner_image = None
                    banner_image_type = None
                else:
                    banner_image = existing_theme[3]
                    banner_image_type = existing_theme[4]

            # BACKGROUND
            if background_image is None:
                if remove_background:
                    background_image = None
                    background_image_type = None
                else:
                    background_image = existing_theme[5]
                    background_image_type = existing_theme[6]

            # If requested, make this the manually active theme
            if activate_now:
                cur.execute("""
                    UPDATE themes
                    SET is_active = FALSE
                """)

            try:
                cur.execute("""
                    UPDATE themes
                    SET
                        name = %s,
                        theme_title = %s,
                        primary_color = %s,
                        accent_color = %s,
                        page_background = %s,
                        card_background = %s,
                        header_background = %s,
                        text_color = %s,
                        muted_text_color = %s,
                        button_color = %s,
                        border_color = %s,

                        banner_image = %s,
                        banner_image_type = %s,

                        background_image = %s,
                        background_image_type = %s,

                        logo_image = %s,
                        logo_image_type = %s,

                        start_date = %s,
                        end_date = %s,

                        login_title = %s,
                        login_message = %s,
                        register_title = %s,
                        register_message = %s,
                        browser_title = %s,

                        is_active = CASE
                            WHEN %s THEN TRUE
                            ELSE is_active
                        END

                    WHERE id = %s
                """, (
                    theme_name,
                    theme_title or "Eternal Emporium",
                    primary_color,
                    accent_color,
                    page_background,
                    card_background,
                    header_background,
                    text_color,
                    muted_text_color,
                    button_color,
                    border_color,

                    banner_image,
                    banner_image_type,

                    background_image,
                    background_image_type,

                    logo_image,
                    logo_image_type,

                    start_date,
                    end_date,

                    login_title or None,
                    login_message or None,
                    register_title or None,
                    register_message or None,
                    browser_title or "Eternal Emporium",

                    activate_now,
                    theme_id
                ))

                conn.commit()

            except psycopg2.IntegrityError:
                conn.rollback()
                flash("A theme with that name already exists", "error")
                cur.close()
                conn.close()
                return redirect(url_for("theme_manager"))

            flash("Theme updated successfully!", "success")

            cur.close()
            conn.close()

            return redirect(url_for("theme_manager"))

    # ================= CREATE THEME =================
    if request.method == "POST" and request.form.get("theme_action") == "create":

        theme_name = request.form.get("theme_name", "").strip()
        theme_title = request.form.get("theme_title", "").strip()
        browser_title = request.form.get("browser_title", "").strip()

        login_title = request.form.get("login_title", "").strip()
        login_message = request.form.get("login_message", "").strip()

        register_title = request.form.get("register_title", "").strip()
        register_message = request.form.get("register_message", "").strip()

        primary_color = request.form.get("primary_color", "#3b82f6")
        accent_color = request.form.get("accent_color", "#22c55e")
        page_background = request.form.get("page_background", "#0f172a")
        card_background = request.form.get("card_background", "#1e293b")
        header_background = request.form.get("header_background", "#020617")
        text_color = request.form.get("text_color", "#e2e8f0")
        muted_text_color = request.form.get("muted_text_color", "#94a3b8")
        button_color = request.form.get("button_color", "#3b82f6")
        border_color = request.form.get("border_color", "#334155")

        start_date_raw = request.form.get("start_date", "").strip()
        end_date_raw = request.form.get("end_date", "").strip()

        activate_now = request.form.get("activate_now") == "yes"

        # Theme name is required
        if not theme_name:
            flash("Theme name is required", "error")
            cur.close()
            conn.close()
            return redirect(url_for("theme_manager"))

        # ================= DATES =================

        start_date = None
        end_date = None

        try:
            if start_date_raw:
                start_date = datetime.fromisoformat(start_date_raw)

            if end_date_raw:
                end_date = datetime.fromisoformat(end_date_raw)

        except ValueError:
            flash("Invalid theme start or end date", "error")
            cur.close()
            conn.close()
            return redirect(url_for("theme_manager"))

        if start_date and end_date and end_date <= start_date:
            flash("Theme end date must be after the start date", "error")
            cur.close()
            conn.close()
            return redirect(url_for("theme_manager"))

        # ================= IMAGE HELPER =================

        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
        max_image_size = 5 * 1024 * 1024

        def read_theme_image(field_name):

            file = request.files.get(field_name)

            if not file or file.filename == "":
                return None, None

            extension = os.path.splitext(file.filename)[1].lower()

            if extension not in allowed_extensions:
                raise ValueError(
                    "Theme images must be JPG, PNG, or WEBP"
                )

            image_data = file.read()

            if len(image_data) > max_image_size:
                raise ValueError(
                    "Each theme image must be smaller than 5 MB"
                )

            return psycopg2.Binary(image_data), file.content_type

        try:
            logo_image, logo_image_type = read_theme_image("logo_image")
            banner_image, banner_image_type = read_theme_image("banner_image")
            background_image, background_image_type = read_theme_image(
                "background_image"
            )

        except ValueError as error:
            flash(str(error), "error")
            cur.close()
            conn.close()
            return redirect(url_for("theme_manager"))

        # ================= ACTIVATE =================

        # Only one theme should be manually active at a time.
        if activate_now:
            cur.execute("""
                UPDATE themes
                SET is_active = FALSE
            """)

        # ================= INSERT THEME =================

        try:
            cur.execute("""
                INSERT INTO themes (
                    name,
                    theme_title,
                    primary_color,
                    accent_color,
                    page_background,
                    card_background,
                    header_background,
                    text_color,
                    muted_text_color,
                    button_color,
                    border_color,

                    banner_image,
                    banner_image_type,

                    background_image,
                    background_image_type,

                    logo_image,
                    logo_image_type,

                    is_active,
                    start_date,
                    end_date,

                    login_title,
                    login_message,
                    register_title,
                    register_message,
                    browser_title
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
            """, (
                theme_name,
                theme_title or "Eternal Emporium",
                primary_color,
                accent_color,
                page_background,
                card_background,
                header_background,
                text_color,
                muted_text_color,
                button_color,
                border_color,

                banner_image,
                banner_image_type,

                background_image,
                background_image_type,

                logo_image,
                logo_image_type,

                activate_now,
                start_date,
                end_date,

                login_title or None,
                login_message or None,
                register_title or None,
                register_message or None,
                browser_title or "Eternal Emporium"
            ))

            conn.commit()

        except psycopg2.IntegrityError:
            conn.rollback()
            flash("A theme with that name already exists", "error")
            cur.close()
            conn.close()
            return redirect(url_for("theme_manager"))

        flash("Theme saved successfully!", "success")

        cur.close()
        conn.close()

        return redirect(url_for("theme_manager"))

    # ================= GET SAVED THEMES =================

    cur.execute("""
        SELECT
            id,
            name,
            theme_title,
            primary_color,
            accent_color,
            page_background,
            card_background,
            header_background,
            text_color,
            muted_text_color,
            button_color,
            border_color,
            is_active,
            start_date,
            end_date,
            created_at,
            login_title,
            login_message,
            register_title,
            register_message,
            browser_title,
            banner_image IS NOT NULL,
            background_image IS NOT NULL,
            logo_image IS NOT NULL
        FROM themes
        ORDER BY
            is_active DESC,
            created_at DESC
    """)

    themes = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "theme_manager.html",
        themes=themes
    )

# ================= STORE =================
@app.route("/events/manage")
@login_required
def event_manager():
    if not role_can_manage_events(current_user.role):
        return redirect(url_for("store"))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            e.id, e.title, e.slug, e.status, e.visibility,
            e.starts_at, e.ends_at, e.updated_at,
            COUNT(DISTINCT s.id) AS stage_count,
            COUNT(DISTINCT p.id) AS puzzle_count
        FROM events e
        LEFT JOIN event_stages s ON s.event_id = e.id
        LEFT JOIN event_puzzles p ON p.stage_id = s.id
        GROUP BY e.id
        ORDER BY e.updated_at DESC, e.id DESC
    """)
    events = cur.fetchall()
    cur.close()
    conn.close()

    counts = {"draft": 0, "scheduled": 0, "published": 0, "archived": 0}
    for event in events:
        counts[event[3]] = counts.get(event[3], 0) + 1

    return render_template("event_manager.html", events=events, counts=counts)


@app.route("/events/manage/new", methods=["GET", "POST"])
@login_required
def create_event():
    if not role_can_manage_events(current_user.role):
        return redirect(url_for("store"))

    if request.method == "POST":
        return save_event_form()

    return render_template("event_editor.html", event=None, rewards={}, stage_count=0)


@app.route("/events/manage/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def edit_event(event_id):
    if not role_can_manage_events(current_user.role):
        return redirect(url_for("store"))

    if request.method == "POST":
        return save_event_form(event_id)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, slug, summary, description, status, visibility,
               starts_at, ends_at, max_hints
        FROM events
        WHERE id = %s
    """, (event_id,))
    event = cur.fetchone()
    if not event:
        cur.close()
        conn.close()
        return render_template("error.html", message="Event not found"), 404

    cur.execute("SELECT COUNT(*) FROM event_stages WHERE event_id = %s", (event_id,))
    stage_count = cur.fetchone()[0]
    cur.execute("""
        SELECT reward_type, points_amount, prize_name, fulfillment_instructions
        FROM event_rewards WHERE event_id = %s
    """, (event_id,))
    rewards = {row[0]: row[1:] for row in cur.fetchall()}
    cur.close()
    conn.close()
    return render_template(
        "event_editor.html", event=event, rewards=rewards, stage_count=stage_count
    )


def save_event_form(event_id=None):
    title = request.form.get("title", "").strip()
    summary = request.form.get("summary", "").strip()
    description = request.form.get("description", "").strip()
    status = request.form.get("status", "draft")
    visibility = request.form.get("visibility", "public")
    starts_at_raw = request.form.get("starts_at", "")
    ends_at_raw = request.form.get("ends_at", "")
    starts_at = parse_event_datetime(starts_at_raw)
    ends_at = parse_event_datetime(ends_at_raw)

    try:
        max_hints = int(request.form.get("max_hints", 3))
        stage_count = int(request.form.get("stage_count", 0))
        points_reward = int(request.form.get("points_reward", 0) or 0)
    except ValueError:
        flash("Hints, stages, and points must be whole numbers", "error")
        return redirect(request.url)

    if not title:
        flash("Event title is required", "error")
        return redirect(request.url)
    if status not in {"draft", "scheduled", "published", "archived"}:
        flash("Invalid event status", "error")
        return redirect(request.url)
    if visibility not in {"public", "hidden"}:
        flash("Invalid event visibility", "error")
        return redirect(request.url)
    if starts_at_raw and starts_at is None or ends_at_raw and ends_at is None:
        flash("Enter valid event dates", "error")
        return redirect(request.url)
    if starts_at and ends_at and ends_at <= starts_at:
        flash("End date must be after the start date", "error")
        return redirect(request.url)
    if not 0 <= max_hints <= 20 or not 0 <= stage_count <= 50 or points_reward < 0:
        flash("Event number settings are outside the allowed range", "error")
        return redirect(request.url)

    prize_name = request.form.get("prize_name", "").strip()
    prize_instructions = request.form.get("prize_instructions", "").strip()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if event_id is None:
            base_slug = event_slug(title)
            slug = base_slug
            suffix = 2
            while True:
                cur.execute("SELECT 1 FROM events WHERE slug = %s", (slug,))
                if not cur.fetchone():
                    break
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            cur.execute("""
                INSERT INTO events (
                    slug, title, summary, description, status, visibility,
                    starts_at, ends_at, max_hints, created_by, updated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                slug, title, summary or None, description or None, status,
                visibility, starts_at, ends_at, max_hints,
                current_user.id, current_user.id
            ))
            event_id = cur.fetchone()[0]
        else:
            cur.execute("SELECT 1 FROM events WHERE id = %s", (event_id,))
            if not cur.fetchone():
                flash("Event not found", "error")
                return redirect(url_for("event_manager"))
            cur.execute("""
                UPDATE events SET
                    title = %s, summary = %s, description = %s, status = %s,
                    visibility = %s, starts_at = %s, ends_at = %s,
                    max_hints = %s, updated_by = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (
                title, summary or None, description or None, status, visibility,
                starts_at, ends_at, max_hints, current_user.id, event_id
            ))

        cur.execute("SELECT COUNT(*) FROM event_stages WHERE event_id = %s", (event_id,))
        existing_stage_count = cur.fetchone()[0]
        if stage_count < existing_stage_count:
            stage_count = existing_stage_count
            flash("Stage count was kept because existing stages are never deleted here", "info")
        for position in range(existing_stage_count + 1, stage_count + 1):
            cur.execute("""
                INSERT INTO event_stages (event_id, position, title)
                VALUES (%s, %s, %s)
            """, (event_id, position, f"Stage {position}"))

        if points_reward > 0:
            cur.execute("""
                INSERT INTO event_rewards (event_id, reward_type, points_amount)
                VALUES (%s, 'points', %s)
                ON CONFLICT (event_id, reward_type)
                DO UPDATE SET points_amount = EXCLUDED.points_amount
            """, (event_id, points_reward))
        else:
            cur.execute("""
                DELETE FROM event_rewards
                WHERE event_id = %s AND reward_type = 'points'
            """, (event_id,))

        if prize_name:
            cur.execute("""
                INSERT INTO event_rewards (
                    event_id, reward_type, prize_name, fulfillment_instructions
                ) VALUES (%s, 'manual_prize', %s, %s)
                ON CONFLICT (event_id, reward_type)
                DO UPDATE SET prize_name = EXCLUDED.prize_name,
                              fulfillment_instructions = EXCLUDED.fulfillment_instructions
            """, (event_id, prize_name, prize_instructions or None))
        else:
            cur.execute("""
                DELETE FROM event_rewards
                WHERE event_id = %s AND reward_type = 'manual_prize'
            """, (event_id,))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

    flash("Event saved", "success")
    return redirect(url_for("edit_event", event_id=event_id))


def get_managed_event(cur, event_id):
    cur.execute("""
        SELECT id, title, slug, summary, description, status, visibility,
               starts_at, ends_at, max_hints
        FROM events WHERE id = %s
    """, (event_id,))
    return cur.fetchone()


def get_player_event(cur, slug):
    cur.execute("""
        SELECT id, title, slug, summary, description, status, visibility,
               starts_at, ends_at, max_hints
        FROM events WHERE slug = %s
    """, (slug,))
    return cur.fetchone()


def get_or_create_participation(cur, event_id, user_id):
    cur.execute("""
        INSERT INTO event_participations (event_id, user_id)
        VALUES (%s, %s)
        ON CONFLICT (event_id, user_id) DO UPDATE
        SET last_activity_at = CURRENT_TIMESTAMP
        RETURNING id, started_at, completed_at
    """, (event_id, user_id))
    return cur.fetchone()


def ordered_event_puzzles(cur, event_id):
    cur.execute("""
        SELECT p.id, p.stage_id, s.position, s.title, s.description,
               p.position, p.title, p.puzzle_type, p.prompt, p.content,
               p.solution, p.hints,
               EXISTS(SELECT 1 FROM event_puzzle_assets a WHERE a.puzzle_id = p.id)
        FROM event_puzzles p
        JOIN event_stages s ON s.id = p.stage_id
        WHERE s.event_id = %s AND p.is_active = TRUE
        ORDER BY s.position, p.position
    """, (event_id,))
    return cur.fetchall()


def finish_event(cur, event, participation, user_id, grant_rewards=True):
    cur.execute("""
        UPDATE event_participations
        SET completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
            last_activity_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (participation[0],))
    cur.execute("""
        SELECT COUNT(*) FROM event_hint_usage WHERE participation_id = %s
    """, (participation[0],))
    hints_used = cur.fetchone()[0]
    cur.execute("""
        INSERT INTO event_completions (
            event_id, user_id, participation_id, elapsed_seconds, hints_used
        ) VALUES (
            %s, %s, %s,
            GREATEST(0, EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - %s))::INTEGER), %s
        )
        ON CONFLICT (event_id, user_id) DO NOTHING
        RETURNING id
    """, (event[0], user_id, participation[0], participation[1], hints_used))
    completion = cur.fetchone()
    if not completion:
        return False
    if not grant_rewards:
        return True

    cur.execute("""
        SELECT id, reward_type, points_amount FROM event_rewards WHERE event_id = %s
    """, (event[0],))
    for reward_id, reward_type, points_amount in cur.fetchall():
        fulfillment = "pending" if reward_type == "manual_prize" else "not_applicable"
        points = points_amount or 0 if reward_type == "points" else 0
        cur.execute("""
            INSERT INTO event_reward_grants (
                event_id, user_id, completion_id, reward_id,
                points_granted, fulfillment_status
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, event_id, reward_id) DO NOTHING
            RETURNING id
        """, (event[0], user_id, completion[0], reward_id, points, fulfillment))
        if cur.fetchone() and points:
            cur.execute("UPDATE users SET points = points + %s WHERE id = %s", (points, user_id))
    return True


@app.route("/events/manage/<int:event_id>/builder", methods=["GET", "POST"])
@login_required
def event_builder(event_id):
    if not role_can_manage_events(current_user.role):
        return redirect(url_for("store"))

    conn = get_db_connection()
    cur = conn.cursor()
    event = get_managed_event(cur, event_id)
    if not event:
        cur.close()
        conn.close()
        return render_template("error.html", message="Event not found"), 404

    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "add_stage":
                title = request.form.get("title", "").strip()
                if not title:
                    raise ValueError("Stage title is required")
                cur.execute(
                    "SELECT COALESCE(MAX(position), 0) + 1 FROM event_stages WHERE event_id = %s",
                    (event_id,),
                )
                position = cur.fetchone()[0]
                cur.execute("""
                    INSERT INTO event_stages (event_id, position, title, description)
                    VALUES (%s, %s, %s, %s)
                """, (event_id, position, title, request.form.get("description", "").strip() or None))
                flash("Stage added", "success")
            elif action == "update_stage":
                stage_id = int(request.form.get("stage_id", 0))
                title = request.form.get("title", "").strip()
                if not title:
                    raise ValueError("Stage title is required")
                cur.execute("""
                    UPDATE event_stages
                    SET title = %s, description = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND event_id = %s
                """, (title, request.form.get("description", "").strip() or None, stage_id, event_id))
                if cur.rowcount != 1:
                    raise ValueError("Stage not found")
                flash("Stage updated", "success")
            else:
                raise ValueError("Unknown builder action")
            conn.commit()
        except (ValueError, TypeError) as exc:
            conn.rollback()
            flash(str(exc), "error")
        finally:
            cur.close()
            conn.close()
        return redirect(url_for("event_builder", event_id=event_id))

    cur.execute("""
        SELECT id, position, title, description
        FROM event_stages WHERE event_id = %s ORDER BY position
    """, (event_id,))
    stages = cur.fetchall()
    cur.execute("""
        SELECT p.id, p.stage_id, p.position, p.title, p.puzzle_type,
               p.prompt, p.is_active, EXISTS(
                   SELECT 1 FROM event_puzzle_assets a
                   WHERE a.puzzle_id = p.id AND a.asset_kind = 'image'
               )
        FROM event_puzzles p
        JOIN event_stages s ON s.id = p.stage_id
        WHERE s.event_id = %s
        ORDER BY s.position, p.position
    """, (event_id,))
    puzzles_by_stage = {}
    for puzzle in cur.fetchall():
        puzzles_by_stage.setdefault(puzzle[1], []).append(puzzle)
    cur.close()
    conn.close()
    return render_template(
        "event_builder.html", event=event, stages=stages,
        puzzles_by_stage=puzzles_by_stage, puzzle_types=PUZZLE_TYPES,
    )


@app.route("/events/manage/<int:event_id>/stages/<int:stage_id>/puzzles/new", methods=["GET", "POST"])
@login_required
def create_event_puzzle(event_id, stage_id):
    if not role_can_manage_events(current_user.role):
        return redirect(url_for("store"))
    return puzzle_editor_response(event_id, stage_id)


@app.route("/events/manage/<int:event_id>/stages/<int:stage_id>/puzzles/<int:puzzle_id>/edit", methods=["GET", "POST"])
@login_required
def edit_event_puzzle(event_id, stage_id, puzzle_id):
    if not role_can_manage_events(current_user.role):
        return redirect(url_for("store"))
    return puzzle_editor_response(event_id, stage_id, puzzle_id)


def puzzle_editor_response(event_id, stage_id, puzzle_id=None):
    conn = get_db_connection()
    cur = conn.cursor()
    event = get_managed_event(cur, event_id)
    cur.execute("""
        SELECT id, position, title, description
        FROM event_stages WHERE id = %s AND event_id = %s
    """, (stage_id, event_id))
    stage = cur.fetchone()
    if not event or not stage:
        cur.close()
        conn.close()
        return render_template("error.html", message="Event stage not found"), 404

    puzzle = None
    has_image = False
    if puzzle_id is not None:
        cur.execute("""
            SELECT id, position, title, puzzle_type, prompt, content,
                   solution, hints, is_active
            FROM event_puzzles WHERE id = %s AND stage_id = %s
        """, (puzzle_id, stage_id))
        puzzle = cur.fetchone()
        if not puzzle:
            cur.close()
            conn.close()
            return render_template("error.html", message="Puzzle not found"), 404
        cur.execute("SELECT 1 FROM event_puzzle_assets WHERE puzzle_id = %s AND asset_kind = 'image'", (puzzle_id,))
        has_image = bool(cur.fetchone())

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        prompt = request.form.get("prompt", "").strip()
        try:
            if not title:
                raise ValueError("Puzzle title is required")
            puzzle_type, content, solution, hints = build_puzzle_configuration(request.form)
            image = request.files.get("puzzle_image")
            image_data = None
            if image and image.filename:
                extension = os.path.splitext(image.filename)[1].lower()
                if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
                    raise ValueError("Puzzle image must be JPG, PNG, or WEBP")
                image_data = image.read(8 * 1024 * 1024 + 1)
                if len(image_data) > 8 * 1024 * 1024:
                    raise ValueError("Puzzle image must be 8 MB or smaller")
            if puzzle_type == "image_hotspot" and image_data is None and not has_image:
                raise ValueError("Image hotspot puzzles need a puzzle image")

            if puzzle_id is None:
                cur.execute(
                    "SELECT COALESCE(MAX(position), 0) + 1 FROM event_puzzles WHERE stage_id = %s",
                    (stage_id,),
                )
                position = cur.fetchone()[0]
                cur.execute("""
                    INSERT INTO event_puzzles (
                        stage_id, position, title, puzzle_type, prompt,
                        content, solution, hints, is_active
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    stage_id, position, title, puzzle_type, prompt or None,
                    Json(content), Json(solution), Json(hints),
                    request.form.get("is_active") == "on",
                ))
                puzzle_id = cur.fetchone()[0]
            else:
                cur.execute("""
                    UPDATE event_puzzles SET
                        title = %s, puzzle_type = %s, prompt = %s,
                        content = %s, solution = %s, hints = %s,
                        is_active = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND stage_id = %s
                """, (
                    title, puzzle_type, prompt or None, Json(content),
                    Json(solution), Json(hints), request.form.get("is_active") == "on",
                    puzzle_id, stage_id,
                ))

            if image_data is not None:
                cur.execute("""
                    INSERT INTO event_puzzle_assets (
                        puzzle_id, asset_kind, filename, content_type, data
                    ) VALUES (%s, 'image', %s, %s, %s)
                    ON CONFLICT (puzzle_id, asset_kind) DO UPDATE SET
                        filename = EXCLUDED.filename,
                        content_type = EXCLUDED.content_type,
                        data = EXCLUDED.data,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    puzzle_id, os.path.basename(image.filename),
                    image.mimetype or "application/octet-stream",
                    psycopg2.Binary(image_data),
                ))
            conn.commit()
            flash("Puzzle saved", "success")
            return redirect(url_for("event_builder", event_id=event_id))
        except ValueError as exc:
            conn.rollback()
            flash(str(exc), "error")
        finally:
            cur.close()
            conn.close()

        return redirect(request.url)

    cur.close()
    conn.close()
    return render_template(
        "puzzle_editor.html", event=event, stage=stage, puzzle=puzzle,
        puzzle_types=PUZZLE_TYPES, has_image=has_image,
    )


@app.route("/event_puzzle_asset/<int:puzzle_id>")
@login_required
def event_puzzle_asset(puzzle_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.data, a.content_type, e.status, e.starts_at, e.ends_at
        FROM event_puzzle_assets a
        JOIN event_puzzles p ON p.id = a.puzzle_id
        JOIN event_stages s ON s.id = p.stage_id
        JOIN events e ON e.id = s.event_id
        WHERE a.puzzle_id = %s AND a.asset_kind = 'image'
    """, (puzzle_id,))
    asset = cur.fetchone()
    cur.close()
    conn.close()
    if not asset:
        return render_template("error.html", message="Puzzle image not found"), 404
    if not role_can_manage_events(current_user.role) and not event_is_open(asset[2], asset[3], asset[4]):
        return render_template("error.html", message="Puzzle image not available"), 403
    return Response(bytes(asset[0]), mimetype=asset[1])


@app.route("/events/manage/<int:event_id>/preview")
@login_required
def preview_event(event_id):
    if not role_can_manage_events(current_user.role):
        return redirect(url_for("store"))
    conn = get_db_connection()
    cur = conn.cursor()
    event = get_managed_event(cur, event_id)
    if not event:
        cur.close()
        conn.close()
        return render_template("error.html", message="Event not found"), 404
    cur.execute("""
        SELECT id, position, title, description
        FROM event_stages WHERE event_id = %s ORDER BY position
    """, (event_id,))
    stages = cur.fetchall()
    cur.execute("""
        SELECT p.id, p.stage_id, p.position, p.title, p.puzzle_type,
               p.prompt, p.content, p.hints, p.is_active,
               EXISTS(SELECT 1 FROM event_puzzle_assets a WHERE a.puzzle_id = p.id)
        FROM event_puzzles p
        JOIN event_stages s ON s.id = p.stage_id
        WHERE s.event_id = %s ORDER BY s.position, p.position
    """, (event_id,))
    puzzles_by_stage = {}
    for puzzle in cur.fetchall():
        puzzles_by_stage.setdefault(puzzle[1], []).append(puzzle)
    cur.close()
    conn.close()
    return render_template(
        "event_preview.html", event=event, stages=stages,
        puzzles_by_stage=puzzles_by_stage, puzzle_types=PUZZLE_TYPES,
    )


@app.route("/events/manage/<int:event_id>/placements", methods=["GET", "POST"])
@login_required
def event_clue_placements(event_id):
    if not role_can_manage_events(current_user.role):
        return redirect(url_for("store"))
    conn = get_db_connection()
    cur = conn.cursor()
    event = get_managed_event(cur, event_id)
    if not event:
        cur.close()
        conn.close()
        return render_template("error.html", message="Event not found"), 404
    if request.method == "POST":
        try:
            if request.form.get("action") == "delete":
                placement_id = int(request.form.get("placement_id", 0))
                cur.execute("DELETE FROM event_clue_placements WHERE id = %s AND event_id = %s", (placement_id, event_id))
                flash("Clue placement removed", "success")
            else:
                name = request.form.get("name", "").strip()
                page_scope = request.form.get("page_scope", "store")
                zone = request.form.get("placement_zone", "content_top")
                display_type = request.form.get("display_type", "text")
                starts_raw = request.form.get("starts_at", "")
                ends_raw = request.form.get("ends_at", "")
                starts_at = parse_event_datetime(starts_raw)
                ends_at = parse_event_datetime(ends_raw)
                if not name:
                    raise ValueError("Placement name is required")
                if page_scope not in {"global", "store", "dashboard", "profile", "purchases"}:
                    raise ValueError("Choose a valid website page")
                if zone not in {"content_top", "theme_banner_hotspot", "floating_corner", "footer"}:
                    raise ValueError("Choose a valid placement zone")
                if display_type not in {"text", "image", "invisible_hotspot"}:
                    raise ValueError("Choose a valid clue appearance")
                if (starts_raw and starts_at is None) or (ends_raw and ends_at is None):
                    raise ValueError("Enter valid placement dates")
                if starts_at and ends_at and ends_at <= starts_at:
                    raise ValueError("Placement end must be after its start")
                x = float(request.form.get("position_x", 50))
                y = float(request.form.get("position_y", 50))
                width = float(request.form.get("width_percent", 12))
                height = float(request.form.get("height_percent", 18))
                if not 0 <= x <= 100 or not 0 <= y <= 100 or not 1 <= width <= 100 or not 1 <= height <= 100:
                    raise ValueError("Placement position or size is outside the page")
                image = request.files.get("clue_image")
                image_data = None
                if image and image.filename:
                    extension = os.path.splitext(image.filename)[1].lower()
                    if extension not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                        raise ValueError("Clue images must be JPG, PNG, WEBP, or GIF")
                    image_data = image.read(5 * 1024 * 1024 + 1)
                    if len(image_data) > 5 * 1024 * 1024:
                        raise ValueError("Clue images must be 5 MB or smaller")
                if display_type == "image" and image_data is None:
                    raise ValueError("Image clues need an uploaded image")
                cur.execute("""
                    INSERT INTO event_clue_placements (
                        event_id, name, page_scope, placement_zone, display_type,
                        label, tooltip, position_x, position_y, width_percent,
                        height_percent, image_filename, image_content_type, image_data,
                        starts_at, ends_at, is_active, created_by, entry_token
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                              %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    event_id, name, page_scope, zone, display_type,
                    request.form.get("label", "").strip() or None,
                    request.form.get("tooltip", "").strip() or None,
                    x, y, width, height,
                    os.path.basename(image.filename) if image_data else None,
                    image.mimetype if image_data else None,
                    psycopg2.Binary(image_data) if image_data else None,
                    starts_at, ends_at, request.form.get("is_active") == "on",
                    current_user.id, secrets.token_urlsafe(32),
                ))
                flash("Website clue placement created", "success")
            conn.commit()
        except (ValueError, TypeError) as exc:
            conn.rollback()
            flash(str(exc), "error")
        finally:
            cur.close()
            conn.close()
        return redirect(url_for("event_clue_placements", event_id=event_id))
    cur.execute("""
        SELECT id, name, page_scope, placement_zone, display_type, label,
               starts_at, ends_at, is_active, image_data IS NOT NULL
        FROM event_clue_placements WHERE event_id = %s
        ORDER BY created_at DESC
    """, (event_id,))
    placements = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("event_clue_placements.html", event=event, placements=placements)


@app.route("/event_clue_image/<int:placement_id>")
@login_required
def event_clue_image(placement_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT image_data, image_content_type FROM event_clue_placements WHERE id = %s", (placement_id,))
    image = cur.fetchone()
    cur.close()
    conn.close()
    if not image or not image[0]:
        return render_template("error.html", message="Clue image not found"), 404
    return Response(bytes(image[0]), mimetype=image[1])


@app.route("/events/manage/<int:event_id>/completions", methods=["GET", "POST"])
@login_required
def event_completions_manager(event_id):
    if not role_can_manage_events(current_user.role):
        return redirect(url_for("store"))
    conn = get_db_connection()
    cur = conn.cursor()
    event = get_managed_event(cur, event_id)
    if not event:
        cur.close()
        conn.close()
        return render_template("error.html", message="Event not found"), 404
    if request.method == "POST":
        try:
            grant_id = int(request.form.get("grant_id", 0))
            cur.execute("""
                UPDATE event_reward_grants g
                SET fulfillment_status = 'fulfilled', fulfilled_by = %s,
                    fulfilled_at = CURRENT_TIMESTAMP
                FROM event_rewards r
                WHERE g.id = %s AND g.event_id = %s
                  AND r.id = g.reward_id AND r.reward_type = 'manual_prize'
            """, (current_user.id, grant_id, event_id))
            if cur.rowcount != 1:
                raise ValueError("Manual prize grant not found")
            conn.commit()
            flash("Manual prize marked fulfilled", "success")
        except (ValueError, TypeError) as exc:
            conn.rollback()
            flash(str(exc), "error")
        finally:
            cur.close()
            conn.close()
        return redirect(url_for("event_completions_manager", event_id=event_id))
    cur.execute("""
        SELECT c.id, u.username, c.completed_at, c.elapsed_seconds, c.hints_used,
               COALESCE(SUM(g.points_granted), 0),
               MAX(CASE WHEN r.reward_type = 'manual_prize' THEN g.fulfillment_status END),
               MAX(CASE WHEN r.reward_type = 'manual_prize' THEN g.id END),
               MAX(CASE WHEN r.reward_type = 'manual_prize' THEN r.prize_name END)
        FROM event_completions c
        JOIN users u ON u.id = c.user_id
        LEFT JOIN event_reward_grants g ON g.completion_id = c.id
        LEFT JOIN event_rewards r ON r.id = g.reward_id
        WHERE c.event_id = %s
        GROUP BY c.id, u.username
        ORDER BY c.completed_at
    """, (event_id,))
    completions = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("event_completions_manager.html", event=event, completions=completions)


@app.route("/events")
@login_required
def player_events():
    return redirect(url_for("store"))


@app.route("/event-entry/<int:placement_id>/<token>")
@login_required
def discover_event(placement_id, token):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT e.id, e.slug, e.status, e.starts_at, e.ends_at
        FROM event_clue_placements c
        JOIN events e ON e.id = c.event_id
        WHERE c.id = %s AND c.entry_token = %s AND c.is_active = TRUE
          AND (c.starts_at IS NULL OR c.starts_at <= CURRENT_TIMESTAMP)
          AND (c.ends_at IS NULL OR c.ends_at > CURRENT_TIMESTAMP)
    """, (placement_id, token))
    entrance = cur.fetchone()
    if not entrance or (not event_is_open(entrance[2], entrance[3], entrance[4]) and not role_can_manage_events(current_user.role)):
        cur.close()
        conn.close()
        return render_template("error.html", message="This entrance is sealed"), 404
    cur.execute("""
        INSERT INTO event_discoveries (event_id, user_id, placement_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (event_id, user_id) DO NOTHING
    """, (entrance[0], current_user.id, placement_id))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("player_event", slug=entrance[1]))


@app.route("/events/<slug>")
@login_required
def player_event(slug):
    conn = get_db_connection()
    cur = conn.cursor()
    event = get_player_event(cur, slug)
    if not event:
        cur.close()
        conn.close()
        return render_template("error.html", message="Event not found"), 404
    manager_preview = role_can_manage_events(current_user.role)
    if not event_is_open(event[5], event[7], event[8]) and not manager_preview:
        cur.close()
        conn.close()
        return render_template("event_unavailable.html", event=event), 403
    if not manager_preview:
        cur.execute("""
            SELECT 1 FROM event_discoveries
            WHERE event_id = %s AND user_id = %s
            UNION ALL
            SELECT 1 FROM event_participations
            WHERE event_id = %s AND user_id = %s
            LIMIT 1
        """, (event[0], current_user.id, event[0], current_user.id))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return render_template("event_unavailable.html", event=event), 403

    participation = get_or_create_participation(cur, event[0], current_user.id)
    puzzles = ordered_event_puzzles(cur, event[0])
    cur.execute("""
        SELECT puzzle_id, solved_at, attempt_count
        FROM event_puzzle_progress WHERE participation_id = %s
    """, (participation[0],))
    progress = {row[0]: row[1:] for row in cur.fetchall()}
    active_puzzle = next((puzzle for puzzle in puzzles if not progress.get(puzzle[0], (None,))[0]), None)

    if puzzles and active_puzzle is None and not participation[2]:
        finish_event(
            cur, event, participation, current_user.id,
            grant_rewards=event_is_open(event[5], event[7], event[8]),
        )
        participation = (participation[0], participation[1], datetime.now())

    cur.execute("""
        SELECT body, created_at FROM event_journal_entries
        WHERE participation_id = %s ORDER BY created_at DESC LIMIT 20
    """, (participation[0],))
    journal_entries = cur.fetchall()
    used_hints = set()
    if active_puzzle:
        cur.execute("""
            SELECT hint_number FROM event_hint_usage
            WHERE participation_id = %s AND puzzle_id = %s
        """, (participation[0], active_puzzle[0]))
        used_hints = {row[0] for row in cur.fetchall()}
    cur.execute("""
        SELECT u.username, c.elapsed_seconds, c.hints_used
        FROM event_completions c JOIN users u ON u.id = c.user_id
        WHERE c.event_id = %s
        ORDER BY c.elapsed_seconds ASC NULLS LAST, c.hints_used ASC, c.completed_at ASC
        LIMIT 10
    """, (event[0],))
    leaderboard = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()
    solved_count = sum(1 for puzzle in puzzles if progress.get(puzzle[0], (None,))[0])
    return render_template(
        "player_event.html", event=event, participation=participation,
        puzzles=puzzles, progress=progress, active_puzzle=active_puzzle,
        solved_count=solved_count, journal_entries=journal_entries,
        used_hints=used_hints, leaderboard=leaderboard,
        manager_preview=manager_preview and not event_is_open(event[5], event[7], event[8]),
    )


@app.route("/events/<slug>/answer", methods=["POST"])
@login_required
def answer_event_puzzle(slug):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        event = get_player_event(cur, slug)
        if not event or (not event_is_open(event[5], event[7], event[8]) and not role_can_manage_events(current_user.role)):
            flash("This event is not currently available", "error")
            return redirect(url_for("player_events"))
        participation = get_or_create_participation(cur, event[0], current_user.id)
        puzzles = ordered_event_puzzles(cur, event[0])
        cur.execute("SELECT puzzle_id, solved_at FROM event_puzzle_progress WHERE participation_id = %s", (participation[0],))
        progress = {row[0]: row[1] for row in cur.fetchall()}
        active = next((puzzle for puzzle in puzzles if not progress.get(puzzle[0])), None)
        submitted_id = int(request.form.get("puzzle_id", 0))
        if not active or active[0] != submitted_id:
            flash("That puzzle is not currently unlocked", "error")
            return redirect(url_for("player_event", slug=slug))

        ordered_items = nonempty_lines(request.form.get("ordered_items", ""))
        hotspot = None
        if request.form.get("hotspot_x") and request.form.get("hotspot_y"):
            hotspot = (request.form.get("hotspot_x"), request.form.get("hotspot_y"))
        correct = puzzle_answer_is_correct(
            active[7], active[10], request.form.get("answer"), ordered_items, hotspot
        )
        cur.execute("""
            INSERT INTO event_puzzle_progress (
                participation_id, puzzle_id, attempt_count, solved_at, updated_at
            ) VALUES (%s, %s, 1, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (participation_id, puzzle_id) DO UPDATE SET
                attempt_count = event_puzzle_progress.attempt_count + 1,
                solved_at = CASE WHEN %s THEN COALESCE(event_puzzle_progress.solved_at, CURRENT_TIMESTAMP)
                                 ELSE event_puzzle_progress.solved_at END,
                updated_at = CURRENT_TIMESTAMP
        """, (participation[0], active[0], datetime.now() if correct else None, correct))
        if correct:
            remaining = [puzzle for puzzle in puzzles if puzzle[0] != active[0] and not progress.get(puzzle[0])]
            if not remaining:
                first_completion = finish_event(
                    cur, event, participation, current_user.id,
                    grant_rewards=event_is_open(event[5], event[7], event[8]),
                )
                flash("Event complete! Your completion has been recorded." if first_completion else "Puzzle solved!", "success")
            else:
                flash("Correct! The next puzzle has unlocked.", "success")
        else:
            flash("That answer did not unlock the puzzle. Try again or reveal a hint.", "error")
        conn.commit()
    except (ValueError, TypeError):
        conn.rollback()
        flash("The submitted answer was not valid", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("player_event", slug=slug))


@app.route("/events/<slug>/hint", methods=["POST"])
@login_required
def reveal_event_hint(slug):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        event = get_player_event(cur, slug)
        if not event or (not event_is_open(event[5], event[7], event[8]) and not role_can_manage_events(current_user.role)):
            raise ValueError("Event unavailable")
        participation = get_or_create_participation(cur, event[0], current_user.id) if event else None
        puzzles = ordered_event_puzzles(cur, event[0]) if event else []
        cur.execute("SELECT puzzle_id, solved_at FROM event_puzzle_progress WHERE participation_id = %s", (participation[0],))
        solved = {row[0]: row[1] for row in cur.fetchall()}
        active = next((puzzle for puzzle in puzzles if not solved.get(puzzle[0])), None)
        if not active:
            raise ValueError("No active puzzle")
        cur.execute("SELECT COUNT(*) FROM event_hint_usage WHERE participation_id = %s AND puzzle_id = %s", (participation[0], active[0]))
        next_hint = cur.fetchone()[0] + 1
        allowed = min(3, event[9], len(active[11]))
        if next_hint > allowed:
            flash("No more hints are available for this puzzle", "error")
        else:
            cur.execute("""
                INSERT INTO event_hint_usage (participation_id, puzzle_id, hint_number)
                VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
            """, (participation[0], active[0], next_hint))
            flash(f"Hint {next_hint} revealed", "success")
        conn.commit()
    except (ValueError, TypeError, IndexError):
        conn.rollback()
        flash("A hint cannot be revealed right now", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("player_event", slug=slug))


@app.route("/events/<slug>/journal", methods=["POST"])
@login_required
def add_event_journal_entry(slug):
    body = request.form.get("body", "").strip()
    if not body or len(body) > 2000:
        flash("Journal entries must be between 1 and 2,000 characters", "error")
        return redirect(url_for("player_event", slug=slug))
    conn = get_db_connection()
    cur = conn.cursor()
    event = get_player_event(cur, slug)
    if event and (event_is_open(event[5], event[7], event[8]) or role_can_manage_events(current_user.role)):
        participation = get_or_create_participation(cur, event[0], current_user.id)
        cur.execute("INSERT INTO event_journal_entries (participation_id, body) VALUES (%s, %s)", (participation[0], body))
        conn.commit()
        flash("Journal entry saved", "success")
    cur.close()
    conn.close()
    return redirect(url_for("player_event", slug=slug))


@app.route("/events/manage/<int:event_id>/reset-test-progress", methods=["POST"])
@login_required
def reset_event_test_progress(event_id):
    if not role_can_manage_events(current_user.role):
        return redirect(url_for("store"))
    conn = get_db_connection()
    cur = conn.cursor()
    event = get_managed_event(cur, event_id)
    if event and not event_is_open(event[5], event[7], event[8]):
        cur.execute("DELETE FROM event_participations WHERE event_id = %s AND user_id = %s", (event_id, current_user.id))
        conn.commit()
        flash("Your staff test progress was reset", "success")
    else:
        flash("Test progress can only be reset while an event is closed to players", "error")
    cur.close()
    conn.close()
    return redirect(url_for("player_event", slug=event[2]) if event else url_for("event_manager"))


@app.route("/store", methods=["GET", "POST"])
@login_required
def store():
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":

        # ================= IMAGE UPLOAD =================
        image_data = None
        image_type = None

        if "image_file" in request.files:
            file = request.files["image_file"]

            if file and file.filename != "":
                extension = os.path.splitext(file.filename)[1].lower()
                allowed_extensions = [".jpg", ".jpeg", ".png", ".webp"]

                if extension not in allowed_extensions:
                    flash("Item image must be JPG, PNG, or WEBP", "error")
                    cur.close()
                    conn.close()
                    return redirect(url_for("store"))

                image_data = file.read()

                if len(image_data) > 5 * 1024 * 1024:
                    flash("Item image must be smaller than 5 MB", "error")
                    cur.close()
                    conn.close()
                    return redirect(url_for("store"))

                image_type = file.content_type

        # ================= CREATE ITEM =================
        if "create_item" in request.form and current_user.role in ["owner", "store_manager"]:

            catalog_id = request.form.get("catalog_id")
            name = request.form.get("name", "").strip()
            cost = int(request.form["cost"])
            quantity = int(request.form["quantity"])

            # If owner selected a saved catalog item
            if catalog_id:
                cur.execute("""
                    SELECT name, image_data, image_type
                    FROM item_catalog
                    WHERE id = %s
                """, (catalog_id,))

                catalog_item = cur.fetchone()

                if not catalog_item:
                    cur.close()
                    conn.close()
                    flash("Catalog item not found", "error")
                    return redirect(url_for("store"))

                name, catalog_image_data, catalog_image_type = catalog_item

                # Use catalog image unless owner uploaded a new one
                if image_data is None:
                    image_data = catalog_image_data
                    image_type = catalog_image_type

            # If adding manually, make sure a name was entered
            if not name:
                cur.close()
                conn.close()
                flash("Item name is required", "error")
                return redirect(url_for("store"))

            cur.execute("""
                INSERT INTO items (
                    name,
                    cost,
                    quantity,
                    image_data,
                    image_type
                )
                VALUES (%s, %s, %s, %s, %s)
            """, (
                name,
                cost,
                quantity,
                psycopg2.Binary(image_data) if image_data else None,
                image_type
            ))

            conn.commit()

            cur.close()
            conn.close()

            flash("Item created!", "success")
            return redirect(url_for("store"))

        # ================= DELETE ITEM =================
        if "delete_item" in request.form and current_user.role in ["owner", "store_manager"]:
            item_id = request.form["item_id"]

            cur.execute(
                "DELETE FROM items WHERE id = %s",
                (item_id,)
            )

            conn.commit()

            cur.close()
            conn.close()

            flash("Item deleted", "success")
            return redirect(url_for("store"))

        # ================= UPDATE ITEM =================
        if "update_item" in request.form and current_user.role in ["owner", "store_manager"]:
            item_id = request.form["item_id"]
            name = request.form["name"]
            cost = int(request.form["cost"])
            quantity = int(request.form["quantity"])

            # If a new image was uploaded, replace the existing image.
            if image_data is not None:
                cur.execute("""
                    UPDATE items
                    SET name = %s,
                        cost = %s,
                        quantity = %s,
                        image_data = %s,
                        image_type = %s
                    WHERE id = %s
                """, (
                    name,
                    cost,
                    quantity,
                    psycopg2.Binary(image_data),
                    image_type,
                    item_id
                ))

            # If no new image was uploaded, keep the existing image.
            else:
                cur.execute("""
                    UPDATE items
                    SET name = %s,
                        cost = %s,
                        quantity = %s
                    WHERE id = %s
                """, (
                    name,
                    cost,
                    quantity,
                    item_id
                ))

            conn.commit()

            cur.close()
            conn.close()

            flash("Item updated!", "success")
            return redirect(url_for("store"))

        # ================= BUY ITEM =================
        if "buy_item" in request.form:

            item_id = request.form["item_id"]
            quantity_to_buy = int(request.form.get("quantity", 1))

            if quantity_to_buy < 1:
                cur.close()
                conn.close()
                flash("Invalid quantity", "error")
                return redirect(url_for("store"))

            cur.execute(
                "SELECT name, cost, quantity FROM items WHERE id = %s",
                (item_id,)
            )
            item = cur.fetchone()

            cur.execute(
                "SELECT points, rsn FROM users WHERE id = %s",
                (current_user.id,)
            )
            user = cur.fetchone()

            if item and user:
                name, cost, stock = item
                points, rsn = user

                total_cost = cost * quantity_to_buy

                if stock < quantity_to_buy:
                    cur.close()
                    conn.close()
                    flash("Not enough stock", "error")
                    return redirect(url_for("store"))

                if points < total_cost:
                    cur.close()
                    conn.close()
                    flash("Not enough points", "error")
                    return redirect(url_for("store"))

                # UPDATE USER POINTS
                cur.execute(
                    "UPDATE users SET points = points - %s WHERE id = %s",
                    (total_cost, current_user.id)
                )

                # UPDATE ITEM STOCK
                cur.execute(
                    "UPDATE items SET quantity = quantity - %s WHERE id = %s",
                    (quantity_to_buy, item_id)
                )

                # INSERT PURCHASE
                cur.execute("""
                    INSERT INTO purchases
                    (user_id, rsn, item_name, quantity, total_cost)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    current_user.id,
                    rsn,
                    name,
                    quantity_to_buy,
                    total_cost
                ))

                conn.commit()

                # ================= DISCORD ORDER NOTIFICATION =================
                cur.execute("""
                    SELECT discord_id
                    FROM discord_notifications
                    ORDER BY id ASC
                """)

                discord_rows = cur.fetchall()

                discord_ids = [
                    row[0]
                    for row in discord_rows
                    if row[0]
                ]

                send_discord_order_notification(
                    username=current_user.username,
                    rsn=rsn,
                    item_name=name,
                    quantity=quantity_to_buy,
                    total_cost=total_cost,
                    discord_ids=discord_ids
                )

                flash("Purchase successful!", "success")

            cur.close()
            conn.close()

            return redirect(url_for("store"))

    # ================= GET ITEMS =================
    cur.execute("""
        SELECT id, name, cost, quantity, image_data
        FROM items
        ORDER BY id ASC
    """)

    items = cur.fetchall()

    # ================= GET ITEM CATALOG =================
    catalog_items = []

    if current_user.role in ["owner", "store_manager"]:
        cur.execute("""
            SELECT id, name, default_cost, image_data
            FROM item_catalog
            ORDER BY name ASC
        """)

        catalog_rows = cur.fetchall()

        catalog_items = [
            {
                "id": c[0],
                "name": c[1],
                "default_cost": c[2],
                "image": (
                    url_for("catalog_image", catalog_id=c[0])
                    if c[3]
                    else None
                )
            }
            for c in catalog_rows
        ]

    cur.close()
    conn.close()

    return render_template(
        "store.html",
        items=[
            {
                "id": i[0],
                "name": i[1],
                "cost": i[2],
                "quantity": i[3],
                "image": (
                    url_for("item_image", item_id=i[0])
                    if i[4]
                    else None
                )
            }
            for i in items
        ],
        catalog_items=catalog_items,
        can_manage_store=(current_user.role in ["owner", "store_manager"]),
    )

# ================= ADMIN =================
@app.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
    if current_user.role not in ["admin", "store_manager", "owner"]:
        return redirect(url_for("store"))

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":

        user_id = request.form.get("user_id")

        # ❌ BLOCK self edits ONLY for non-admins
        if user_id and int(user_id) == int(current_user.id) and current_user.role not in ["admin", "owner"]:
            flash("You cannot modify yourself", "error")
            return redirect(url_for("admin"))

# ================= BULK APPLY =================
        if request.form.get("bulk_apply"):

            selected_users = request.form.getlist("selected_users")
            if not isinstance(selected_users, list):
                selected_users = [selected_users]
            bulk_amount = request.form.get("bulk_amount")

            if not selected_users or not bulk_amount:
                flash("Select users and enter an amount", "error")
                return redirect(url_for("admin"))

            try:
                bulk_amount = int(bulk_amount)
            except:
                flash("Invalid amount", "error")
                return redirect(url_for("admin"))

            for user_id in selected_users:

                cur.execute(
                    "UPDATE users SET points = points + %s WHERE id = %s",
                    (bulk_amount, user_id)
                )

                cur.execute("""
                    INSERT INTO point_logs (user_id, amount, admin_id)
                    VALUES (%s, %s, %s)
                """, (user_id, bulk_amount, current_user.id))

            conn.commit()

            flash(f"Updated {len(selected_users)} users", "success")
            return redirect(url_for("admin"))
        
        user_id = request.form.get("user_id")
        amount = request.form.get("amount")
        role = request.form.get("role")
        action = request.form.get("action")
        new_pin = request.form.get("new_pin")

        if not user_id:
            flash("Invalid request", "error")
            return redirect(url_for("admin"))

        # POINTS
        if amount not in (None, ""):
            try:
                amount = int(amount)

                cur.execute(
                    "UPDATE users SET points = points + %s WHERE id = %s",
                    (amount, user_id)
                )

                cur.execute("""
                    INSERT INTO point_logs (user_id, amount, admin_id)
                    VALUES (%s, %s, %s)
                """, (user_id, amount, current_user.id))

            except:
                flash("Invalid amount", "error")
                return redirect(url_for("admin"))
    

        # ROLE
        if role:
            if int(user_id) == int(current_user.id):
                flash("You cannot change your own role", "error")
                return redirect(url_for("admin"))

            cur.execute(
                "SELECT role FROM users WHERE id = %s",
                (user_id,)
            )
            target_user = cur.fetchone()

            if not target_user:
                flash("User not found", "error")
                return redirect(url_for("admin"))

            target_role = target_user[0]

            if current_user.role == "store_manager":
                if target_role not in ["user", "admin"]:
                    flash("You cannot modify Owners or Store Managers", "error")
                    return redirect(url_for("admin"))

                if role not in ["user", "admin"]:
                    flash("You may only assign the User or Admin role", "error")
                    return redirect(url_for("admin"))

            elif current_user.role != "owner":
                flash("You do not have permission to change roles", "error")
                return redirect(url_for("admin"))

            if role not in ["user", "admin", "store_manager", "owner"]:
                flash("Invalid role", "error")
                return redirect(url_for("admin"))

            must_change = role in ELEVATED_ROLES and target_role == "user"
            cur.execute("""
                UPDATE users
                SET role = %s,
                    must_change_password = CASE
                        WHEN %s THEN TRUE
                        WHEN %s = 'user' THEN FALSE
                        ELSE must_change_password
                    END
                WHERE id = %s
            """, (role, must_change, role, user_id))

        # SET PIN
        if action == "set_pin":

            cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            target = cur.fetchone()

            if not target:
                flash("User not found", "error")
                return redirect(url_for("admin"))

            if target[0] in ELEVATED_ROLES and not valid_elevated_password(new_pin):
                flash("Elevated passwords need at least 5 characters with a letter, number, and special character", "error")
                return redirect(url_for("admin"))

            if target[0] not in ELEVATED_ROLES and (len(new_pin) != 4 or not new_pin.isdigit()):
                flash("PIN must be 4 digits", "error")
                return redirect(url_for("admin"))

            cur.execute(
                "UPDATE users SET pin = %s, password = %s WHERE id = %s",
                (new_pin, generate_password_hash(new_pin), user_id)
            )

        # RESET PIN
        if action == "reset_pin":
            if current_user.role != "owner":
                flash("Only owners can reset PINs", "error")
                return redirect(url_for("admin"))

            cur.execute(
                "UPDATE users SET pin = NULL WHERE id = %s",
                (user_id,)
            )

        # DELETE
        if action == "delete":
            if int(user_id) == int(current_user.id):
                flash("You cannot delete your own account", "error")
                return redirect(url_for("admin"))

            cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            target = cur.fetchone()

            if not target:
                flash("User not found", "error")
                return redirect(url_for("admin"))

            if current_user.role == "store_manager" and target[0] not in ["admin", "user"]:
                flash("Store Managers may only delete Admin and User accounts", "error")
                return redirect(url_for("admin"))

            if current_user.role not in ["owner", "store_manager"]:
                flash("You do not have permission to delete accounts", "error")
                return redirect(url_for("admin"))

            cur.execute(
                "DELETE FROM users WHERE id = %s",
                (user_id,)
            )

        conn.commit()
        flash("Update applied", "success")

        return redirect(url_for("admin"))


    # ================= GET (ALWAYS RUNS) =================
    cur.execute("""
        SELECT id, username, rsn, points, role, pin, created_at
        FROM users
        ORDER BY id ASC
    """)
    user_rows = cur.fetchall()

    viewer_level = ROLE_LEVELS[current_user.role]
    users = []
    for user in user_rows:
        target_level = ROLE_LEVELS.get(user[4], 99)
        displayed_credential = user[5] if viewer_level >= target_level else "Hidden"
        users.append(user[:5] + (displayed_credential,) + user[6:])

    cur.close()
    conn.close()

    return render_template("admin.html", users=users)
        
# ================= LOGS =================
@app.route("/logs", methods=["GET", "POST"])
@login_required
def ticket_logs():
    if current_user.role not in ["admin", "store_manager", "owner"]:
        return redirect(url_for("store"))

    conn = get_db_connection()
    cur = conn.cursor()
         # ================= CLEAR LOGS (OWNER ONLY) =================
    if request.method == "POST":
        if request.form.get("action") == "clear_logs":

            if current_user.role != "owner":
                flash("Unauthorized", "error")
                return redirect(url_for("logs"))

            cur.execute("DELETE FROM point_logs")
            conn.commit()

            flash("Ticket logs cleared", "success")
            return redirect(url_for("logs"))
        
    cur.execute("""
        SELECT pl.amount, pl.timestamp, u.username, u.rsn, admin.username
        FROM point_logs pl
        LEFT JOIN users u ON pl.user_id = u.id
        LEFT JOIN users admin ON pl.admin_id = admin.id
        ORDER BY pl.timestamp DESC
    """)
    logs = cur.fetchall()

    est = pytz.timezone("US/Eastern")

    converted_logs = []
    for log in logs:
        timestamp = log[1]

        if timestamp:
            timestamp = timestamp.replace(tzinfo=pytz.utc).astimezone(est)

        converted_logs.append((log[0], timestamp, log[2], log[3], log[4]))

    logs = converted_logs

    cur.close()
    conn.close()

    return render_template("logs.html", logs=logs)

@app.context_processor
def inject_user_data():
    if current_user.is_authenticated:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT points, profile_picture_data FROM users WHERE id = %s",
            (current_user.id,)
        )
        result = cur.fetchone()

        cur.close()
        conn.close()

        user_points = 0
        user_profile_picture = None

        if result:
            user_points = result[0] if result[0] is not None else 0

            if result[1]:
                user_profile_picture = url_for(
                    "profile_picture_image",
                    user_id=current_user.id
                )

        return dict(
            user_points=user_points,
            user_profile_picture=user_profile_picture
        )

    return dict(
        user_points=0,
        user_profile_picture=None
    )


@app.context_processor
def inject_event_clues():
    if not current_user.is_authenticated:
        return {"event_clues": []}
    scope = request_page_scope()
    if not scope:
        return {"event_clues": []}
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.name, c.page_scope, c.placement_zone, c.display_type,
               c.label, c.tooltip, c.position_x, c.position_y,
               c.width_percent, c.height_percent, c.image_data IS NOT NULL,
               e.slug, e.title, c.entry_token
        FROM event_clue_placements c
        JOIN events e ON e.id = c.event_id
        WHERE c.is_active = TRUE
          AND c.page_scope IN ('global', %s)
          AND (c.starts_at IS NULL OR c.starts_at <= CURRENT_TIMESTAMP)
          AND (c.ends_at IS NULL OR c.ends_at > CURRENT_TIMESTAMP)
          AND (
              %s = TRUE OR (
                  e.status IN ('published', 'scheduled')
                  AND (e.starts_at IS NULL OR e.starts_at <= CURRENT_TIMESTAMP)
                  AND (e.ends_at IS NULL OR e.ends_at > CURRENT_TIMESTAMP)
              )
          )
        ORDER BY c.created_at
    """, (scope, role_can_manage_events(current_user.role)))
    clues = cur.fetchall()
    cur.close()
    conn.close()
    return {"event_clues": clues}

@app.context_processor
def inject_active_theme():
    conn = get_db_connection()
    cur = conn.cursor()

        # ================= FIND CURRENT THEME =================
    # Scheduled themes take priority while their date/time window is active.
    # Times entered in the Theme Manager are treated as Eastern Time.

    eastern = pytz.timezone("US/Eastern")
    now_eastern = datetime.now(eastern).replace(tzinfo=None)

    cur.execute("""
        SELECT
            id,
            name,
            theme_title,
            primary_color,
            accent_color,
            page_background,
            card_background,
            header_background,
            text_color,
            muted_text_color,
            button_color,
            border_color,
            banner_image,
            banner_image_type,
            background_image,
            background_image_type,
            logo_image,
            logo_image_type,
            login_title,
            login_message,
            register_title,
            register_message,
            browser_title
        FROM themes
        WHERE
            start_date IS NOT NULL
            AND end_date IS NOT NULL
            AND start_date <= %s
            AND end_date >= %s
        ORDER BY start_date DESC, id DESC
        LIMIT 1
    """, (now_eastern, now_eastern))

    theme = cur.fetchone()

    # If no scheduled theme is currently in its date range,
    # use the manually activated theme.
    if not theme:
        cur.execute("""
            SELECT
                id,
                name,
                theme_title,
                primary_color,
                accent_color,
                page_background,
                card_background,
                header_background,
                text_color,
                muted_text_color,
                button_color,
                border_color,
                banner_image,
                banner_image_type,
                background_image,
                background_image_type,
                logo_image,
                logo_image_type,
                login_title,
                login_message,
                register_title,
                register_message,
                browser_title
            FROM themes
            WHERE is_active = TRUE
            ORDER BY id DESC
            LIMIT 1
        """)

        theme = cur.fetchone()


    # Fall back to Eternal Emporium Default if no theme is active
    if not theme:
        cur.execute("""
            SELECT
                id,
                name,
                theme_title,
                primary_color,
                accent_color,
                page_background,
                card_background,
                header_background,
                text_color,
                muted_text_color,
                button_color,
                border_color,
                banner_image,
                banner_image_type,
                background_image,
                background_image_type,
                logo_image,
                logo_image_type,
                login_title,
                login_message,
                register_title,
                register_message,
                browser_title
            FROM themes
            WHERE name = 'Eternal Emporium Default'
            LIMIT 1
        """)

        theme = cur.fetchone()

    cur.close()
    conn.close()

    if not theme:
        return {"active_theme": None}

    active_theme = {
        "id": theme[0],
        "name": theme[1],
        "theme_title": theme[2] or "Eternal Emporium",
        "primary_color": theme[3],
        "accent_color": theme[4],
        "page_background": theme[5],
        "card_background": theme[6],
        "header_background": theme[7],
        "text_color": theme[8],
        "muted_text_color": theme[9],
        "button_color": theme[10],
        "border_color": theme[11],

        "has_banner": theme[12] is not None,
        "banner_type": theme[13],

        "has_background": theme[14] is not None,
        "background_type": theme[15],

        "has_logo": theme[16] is not None,
        "logo_type": theme[17],

        "login_title": theme[18] or "Welcome Back",
        "login_message": theme[19],
        "register_title": theme[20] or "Create Account",
        "register_message": theme[21],
        "browser_title": theme[22] or "Eternal Emporium"
    }

    return {"active_theme": active_theme}

# ================= STORE ORDERS LOG =================
@app.route("/store_orders", methods=["GET", "POST"])
@login_required
def store_orders():

    if current_user.role not in ["admin", "store_manager", "owner"]:
        return redirect(url_for("store"))

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        if request.form.get("action") == "clear_purchases":
            if current_user.role != "owner":
                flash("Unauthorized", "error")
                return redirect(url_for("store_orders"))

            cur.execute("DELETE FROM purchases")
            conn.commit()
            flash("Store purchases cleared", "success")
            return redirect(url_for("store_orders"))
        
    cur.execute("""
        SELECT u.username, p.rsn, p.item_name, p.quantity, p.total_cost, p.timestamp
        FROM purchases p
        LEFT JOIN users u ON p.user_id = u.id
        ORDER BY p.timestamp DESC
    """)

    orders = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("store_orders.html", orders=orders)

# ================= PURCHASES =================
@app.route("/purchases")
@login_required
def purchases():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT item_name, quantity, total_cost, timestamp
        FROM purchases
        WHERE user_id = %s
        ORDER BY timestamp DESC
    """, (current_user.id,))

    purchases = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("purchases.html", purchases=purchases)


# ================= LOGOUT =================
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

if app.config["INITIALIZE_DATABASE"]:
    if app.config["RUN_DB_MIGRATIONS"]:
        run_database_migrations()

    # Preserve the existing production bootstrap until each legacy table has
    # been captured in a versioned migration.
    if app.config["LEGACY_SCHEMA_BOOTSTRAP"]:
        ensure_discord_notification_table()
        ensure_item_catalog_table()
        ensure_store_image_columns()
        ensure_profile_picture_column()
        ensure_profile_picture_data_column()
        ensure_theme_tables()
        ensure_theme_text_columns()
        ensure_password_security_columns()

if __name__ == "__main__":
    app.run(debug=True)
