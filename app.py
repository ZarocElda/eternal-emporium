print("APP STARTING")

import os
from flask import Flask, request, redirect, url_for, render_template, flash
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
            from werkzeug.utils import secure_filename
            import uuid

            filename = secure_filename(file.filename)
            extension = os.path.splitext(filename)[1].lower()

            allowed_extensions = [".jpg", ".jpeg", ".png", ".webp"]

            if extension not in allowed_extensions:
                flash("Profile picture must be JPG, PNG, or WEBP", "error")
                return redirect(url_for("profile"))

            os.makedirs("static/uploads/profiles", exist_ok=True)

            unique_filename = f"user_{current_user.id}_{uuid.uuid4().hex}{extension}"
            filepath = os.path.join(
                "static/uploads/profiles",
                unique_filename
            )

            file.save(filepath)

            profile_picture = f"/static/uploads/profiles/{unique_filename}"

            cur.execute(
                "UPDATE users SET profile_picture = %s WHERE id = %s",
                (profile_picture, current_user.id)
            )

            conn.commit()

            flash("Profile picture updated", "success")
            return redirect(url_for("profile"))

        # ================= OWNER ITEM CATALOG =================
        if "catalog_action" in request.form:

            # OWNER ONLY
            if current_user.role != "owner":
                flash("Unauthorized", "error")
                return redirect(url_for("profile"))

            catalog_action = request.form.get("catalog_action")

            # ================= ADD CATALOG ITEM =================
            if catalog_action == "add":

                name = request.form.get("catalog_name", "").strip()
                cost = request.form.get("catalog_cost")
                image_filename = None

                if not name or not cost:
                    flash("Item name and default cost are required", "error")
                    return redirect(url_for("profile"))

                try:
                    cost = int(cost)
                except ValueError:
                    flash("Default cost must be a number", "error")
                    return redirect(url_for("profile"))

                # IMAGE UPLOAD
                if "catalog_image" in request.files:
                    file = request.files["catalog_image"]

                    if file and file.filename != "":
                        from werkzeug.utils import secure_filename

                        filename = secure_filename(file.filename)
                        filepath = os.path.join("static/uploads", filename)
                        file.save(filepath)

                        image_filename = f"/static/uploads/{filename}"

                try:
                    cur.execute("""
                        INSERT INTO item_catalog (name, default_cost, image)
                        VALUES (%s, %s, %s)
                    """, (name, cost, image_filename))

                    conn.commit()
                    flash("Item added to Store Catalog", "success")

                except psycopg2.IntegrityError:
                    conn.rollback()
                    flash("That item is already in the catalog", "error")

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

                return redirect(url_for("profile"))

        # ================= CHANGE PIN =================
        if "current_pin" in request.form:

            current_pin = request.form["current_pin"]
            new_pin = request.form["new_pin"]
            confirm_pin = request.form["confirm_pin"]

            cur.execute("SELECT pin FROM users WHERE id = %s", (current_user.id,))
            stored_pin = cur.fetchone()[0]

            if current_pin != stored_pin:
                flash("Current PIN is incorrect", "error")
                return redirect(url_for("profile"))

            if new_pin != confirm_pin:
                flash("New PINs do not match", "error")
                return redirect(url_for("profile"))

            if len(new_pin) != 4 or not new_pin.isdigit():
                flash("PIN must be 4 digits", "error")
                return redirect(url_for("profile"))

            cur.execute(
                "UPDATE users SET pin = %s, password = %s WHERE id = %s",
                (new_pin, new_pin, current_user.id)
            )
            conn.commit()

            flash("PIN updated successfully", "success")
            return redirect(url_for("profile"))

        # ================= UPDATE RSN (YOUR ORIGINAL LOGIC) =================
        if "rsn" in request.form:

            new_rsn = request.form["rsn"]

            cur.execute("SELECT id FROM users WHERE rsn = %s AND id != %s", (new_rsn, current_user.id))
            if cur.fetchone():
                flash("RSN already in use", "error")
                return redirect(url_for("profile"))

            cur.execute("UPDATE users SET rsn = %s WHERE id = %s", (new_rsn, current_user.id))
            conn.commit()

            flash("RSN updated", "success")
            return redirect(url_for("profile"))

        cur.execute("UPDATE users SET rsn = %s WHERE id = %s", (new_rsn, current_user.id))
        conn.commit()
        flash("RSN updated", "success")

    # USER INFO
    cur.execute(
        "SELECT rsn, points, profile_picture FROM users WHERE id = %s",
        (current_user.id,)
    )
    rsn, points, profile_picture = cur.fetchone()

    # TOTAL PURCHASES
    cur.execute("SELECT COUNT(*) FROM purchases WHERE user_id = %s", (current_user.id,))
    total_purchases = cur.fetchone()[0]

    # LAST PURCHASE
    cur.execute("""
        SELECT item_name, total_cost
        FROM purchases
        WHERE user_id = %s
        ORDER BY timestamp DESC
        LIMIT 1
    """, (current_user.id,))
    last_purchase = cur.fetchone()

        # RECENT PURCHASES
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
            SELECT id, name, default_cost, image
            FROM item_catalog
            ORDER BY name ASC
        """)
        catalog_items = cur.fetchall()

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

# ================= STORE =================
@app.route("/store", methods=["GET", "POST"])
@login_required
def store():
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":

        # ================= IMAGE UPLOAD =================
        image_filename = None

        if "image_file" in request.files:
            file = request.files["image_file"]

            if file and file.filename != "":
                from werkzeug.utils import secure_filename
                filename = secure_filename(file.filename)
                filepath = os.path.join("static/uploads", filename)
                file.save(filepath)

                image_filename = f"/static/uploads/{filename}"

                        # ================= CREATE ITEM =================
        if "create_item" in request.form and current_user.role == "owner":

            catalog_id = request.form.get("catalog_id")
            name = request.form.get("name", "").strip()
            cost = int(request.form["cost"])
            quantity = int(request.form["quantity"])

            # If owner selected a saved catalog item
            if catalog_id:

                cur.execute("""
                    SELECT name, image
                    FROM item_catalog
                    WHERE id = %s
                """, (catalog_id,))

                catalog_item = cur.fetchone()

                if not catalog_item:
                    flash("Catalog item not found", "error")
                    return redirect(url_for("store"))

                name, catalog_image = catalog_item

                # Use catalog image unless owner uploaded a new one
                if not image_filename:
                    image_filename = catalog_image

            # If adding manually, make sure a name was entered
            if not name:
                flash("Item name is required", "error")
                return redirect(url_for("store"))

            cur.execute("""
                INSERT INTO items (name, cost, quantity, image)
                VALUES (%s, %s, %s, %s)
            """, (name, cost, quantity, image_filename))

            conn.commit()

            flash("Item created!", "success")
            return redirect(url_for("store"))

        # ================= DELETE ITEM =================
        if "delete_item" in request.form and current_user.role == "owner":
            item_id = request.form["item_id"]

            cur.execute("DELETE FROM items WHERE id = %s", (item_id,))
            conn.commit()

            flash("Item deleted", "success")
            return redirect(url_for("store"))

        # ================= UPDATE ITEM =================
        if "update_item" in request.form and current_user.role == "owner":
            item_id = request.form["item_id"]
            name = request.form["name"]
            cost = int(request.form["cost"])
            quantity = int(request.form["quantity"])

            cur.execute("""
                UPDATE items
                SET name = %s,
                    cost = %s,
                    quantity = %s
                WHERE id = %s
            """, (name, cost, quantity, item_id))

            conn.commit()
            flash("Item updated!", "success")
            return redirect(url_for("store"))

        # ================= BUY ITEM =================
        if "buy_item" in request.form:

            item_id = request.form["item_id"]
            quantity_to_buy = int(request.form.get("quantity", 1))

            if quantity_to_buy < 1:
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
                    flash("Not enough stock", "error")
                    return redirect(url_for("store"))

                if points < total_cost:
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
                    INSERT INTO purchases (user_id, rsn, item_name, quantity, total_cost)
                    VALUES (%s, %s, %s, %s, %s)
                """, (current_user.id, rsn, name, quantity_to_buy, total_cost))

                conn.commit()
                flash("Purchase successful!", "success")

            return redirect(url_for("store"))

    # ================= GET ITEMS =================
    cur.execute("""
        SELECT id, name, cost, quantity, image
        FROM items
        ORDER BY id ASC
    """)
    items = cur.fetchall()

    # ================= GET ITEM CATALOG =================
    catalog_items = []

    if current_user.role == "owner":
        cur.execute("""
            SELECT id, name, default_cost, image
            FROM item_catalog
            ORDER BY name ASC
        """)
        catalog_items = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "store.html",
        items=[
            {"id": i[0], "name": i[1], "cost": i[2], "quantity": i[3], "image": i[4]}
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
            "SELECT points, profile_picture FROM users WHERE id = %s",
            (current_user.id,)
        )
        result = cur.fetchone()

        cur.close()
        conn.close()

        return dict(
            user_points=result[0] if result and result[0] is not None else 0,
            user_profile_picture=result[1] if result else None
        )

    return dict(
        user_points=0,
        user_profile_picture=None
    )

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
ensure_profile_picture_column()
ensure_profile_picture_data_column()

if __name__ == "__main__":
    app.run(debug=True)