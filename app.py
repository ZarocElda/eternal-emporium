print("APP STARTING")

import os
from flask import Flask, request, redirect, url_for, render_template, flash, Response
import psycopg2
from dotenv import load_dotenv
from datetime import timedelta
from datetime import datetime
import pytz

from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
print("DATABASE_URL =", DATABASE_URL)

if not DATABASE_URL:
    raise Exception("DAfTABASE_URL is NOT set.")

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.permanent_session_lifetime = timedelta(minutes=15)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


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

class User(UserMixin):
    def __init__(self, id, username, password, role):
        self.id = id
        self.username = username
        self.password = password
        self.role = role


@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, password, role FROM users WHERE id = %s", (user_id,))
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

        cur.execute(
            "SELECT id, username, password, role FROM users WHERE username = %s",
            (username,)
        )
        user = cur.fetchone()

        cur.close()
        conn.close()

        if user and user[2] == password:
            from flask import session
            session.permanent = True
            login_user(User(*user))
            return redirect(url_for("store"))

        flash("Invalid credentials", "error")
        return render_template("login.html")

    return render_template("login.html")


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

            if current_user.role != "owner":
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

            if len(new_pin) != 4 or not new_pin.isdigit():
                flash("PIN must be 4 digits", "error")
                cur.close()
                conn.close()
                return redirect(url_for("profile"))

            cur.execute(
                "UPDATE users SET pin = %s, password = %s WHERE id = %s",
                (new_pin, new_pin, current_user.id)
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

    if current_user.role == "owner":
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
        catalog_items=catalog_items
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
        if "create_item" in request.form and current_user.role == "owner":

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
        if "delete_item" in request.form and current_user.role == "owner":
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
        if "update_item" in request.form and current_user.role == "owner":
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

    if current_user.role == "owner":
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
        is_owner=(current_user.role == "owner"),
    )

# ================= ADMIN =================
@app.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
    if current_user.role not in ["admin", "owner"]:
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
            if current_user.role != "owner":
                flash("Only owners can change roles", "error")
                return redirect(url_for("admin"))

            cur.execute(
                "UPDATE users SET role = %s WHERE id = %s",
                (role, user_id)
            )

        # SET PIN
        if action == "set_pin":

            if len(new_pin) != 4 or not new_pin.isdigit():
                flash("PIN must be 4 digits", "error")
                return redirect(url_for("admin"))

            cur.execute(
                "UPDATE users SET pin = %s, password = %s WHERE id = %s",
                (new_pin, new_pin, user_id)
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
            if current_user.role != "owner":
                flash("Only owners can delete users", "error")
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
    users = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("admin.html", users=users)
        
# ================= LOGS =================
@app.route("/logs", methods=["GET", "POST"])
@login_required
def ticket_logs():
    if current_user.role not in ["admin", "owner"]:
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

    if current_user.role not in ["admin", "owner"]:
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

ensure_item_catalog_table()
ensure_store_image_columns()
ensure_profile_picture_column()
ensure_profile_picture_data_column()
ensure_theme_tables()
ensure_theme_text_columns()

if __name__ == "__main__":
    app.run(debug=True)