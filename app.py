import os
import csv
import io
import datetime
import smtplib 
import random 
from email.mime.text import MIMEText 
from contextlib import closing
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    Response,
)

from db_models import get_connection, hash_password, init_db
from auth_controller import AuthController

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- BREVO SMTP CONFIGURATION --- 
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp-relay.brevo.com") 
SMTP_PORT = int(os.getenv("SMTP_PORT", 587)) 

SMTP_LOGIN = os.getenv("SMTP_LOGIN")        
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")  
SENDER_EMAIL = os.getenv("MAIL_DEFAULT_SENDER", SMTP_LOGIN)

def send_otp_email(receiver_email, otp, intent): 
    """Sends a 6-digit OTP using Brevo SMTP.""" 
    if not SMTP_LOGIN or not SMTP_PASSWORD:
        print("SMTP Warning: Missing SMTP_LOGIN or SMTP_PASSWORD environment variables.")
        return False

    msg = MIMEText(
        f"Your {intent} One-Time Password (OTP) is: {otp}\n\n"
        "Please enter this code to proceed. Do not share this code with anyone."
    ) 
    msg['Subject'] = f"Laboratory System - {intent} OTP" 
    msg['From'] = SENDER_EMAIL if SENDER_EMAIL else SMTP_LOGIN
    msg['To'] = receiver_email 

    try: 
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
                server.login(SMTP_LOGIN, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(SMTP_LOGIN, SMTP_PASSWORD)
                server.send_message(msg)
            
        return True 
    except Exception as e: 
        print(f"SMTP Dispatch Error: {e}") 
        return False 

# Initialize Database on Startup
init_db()

# Instantiating AuthController
auth = AuthController()


def log_audit_action(user: str, action: str, details: str):
    """Helper utility to log actions into the system audit trail."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO audit_logs (timestamp, performed_by, action, details) VALUES (%s, %s, %s, %s)",
                (now, user, action, details),
            )
            conn.commit()
    except Exception as e:
        print(f"Failed to log audit action: {e}")


# =========================================================
# Auth Routes
# =========================================================

@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        success, msg, user_data, is_locked = auth.login_user(username, password)

        if success:
            session["username"] = user_data["username"]
            session["role"] = user_data["role"]
            flash(msg, "success")
            log_audit_action(user_data["username"], "LOGIN", "User logged in successfully")
            return redirect(url_for("inventory"))
        elif is_locked:
            flash(f"{msg} Please submit an unlock request.", "danger")
        else:
            flash(msg, "danger")
            
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"]) 
def register(): 
    if request.method == "GET": 
        return render_template("register.html") 

    username = request.form.get("username", "").strip() 
    email = request.form.get("email", "").strip() 
    password = request.form.get("password", "").strip() 
    hint = request.form.get("hint", "").strip()
    role = request.form.get("role", "VIEWER").strip().upper() 

    if not username or not email or not password: 
        flash("All registration fields are required.", "danger") 
        return redirect(url_for("login")) 

    otp = str(random.randint(100000, 999999)) 
    session['pending_user'] = {
        'username': username, 
        'email': email, 
        'password': password, 
        'hint': hint, 
        'role': role, 
        'otp': otp
    } 

    email_sent = send_otp_email(email, otp, intent="Account Registration")

    if email_sent:
        flash("We sent a 6-digit code to your email. Please verify.", "info")
    else:
        # Fallback in local/testing mode so user can proceed to verification screen
        flash(f"Verification code generated ({otp}). Please verify your account.", "warning")

    return redirect(url_for("verify_otp", action="register"))


@app.route("/reset-request", methods=["GET", "POST"]) 
def reset_request(): 
    if request.method == "GET": 
        return render_template("reset.html") 
        
    username = request.form.get("username", "").strip() 
    email = request.form.get("email", "").strip() 
    new_password = request.form.get("new_password", "").strip() 
    confirm_password = request.form.get("confirm_password", "").strip() 

    if not username or not email or not new_password or not confirm_password: 
        flash("All reset fields are required.", "danger") 
        return redirect(url_for("reset_request")) 

    if new_password != confirm_password: 
        flash("New passwords do not match.", "danger") 
        return redirect(url_for("reset_request")) 
        
    otp = str(random.randint(100000, 999999)) 
    session['pending_reset'] = {
        'username': username, 
        'email': email, 
        'new_password': new_password, 
        'otp': otp
    } 

    email_sent = send_otp_email(email, otp, intent="Password Reset")

    if email_sent:
        flash("We sent a 6-digit code to your email. Please verify.", "info")
    else:
        flash(f"Reset OTP code generated ({otp}). Please enter to verify.", "warning")

    return redirect(url_for("verify_otp", action="reset"))


@app.route("/verify-otp/<action>", methods=["GET", "POST"]) 
def verify_otp(action): 
    session_key = 'pending_user' if action == "register" else 'pending_reset' 
    if session_key not in session: 
        flash("Session expired. Please try again.", "warning") 
        return redirect(url_for("login")) 
         
    if request.method == "POST": 
        user_otp = request.form.get("otp_code", "").strip() 
        data = session[session_key] 

        if user_otp == data['otp']: 
            if action == "register": 
                ok, msg = auth.register_user(
                    username=data['username'], 
                    email=data['email'], 
                    password_raw=data['password'], 
                    hint=data.get('hint', ''), 
                    role=data['role']
                ) 
                session.pop(session_key, None) 
                flash("Account successfully verified and created!", "success" if ok else "warning") 
                return redirect(url_for("login")) 

            elif action == "reset": 
                ok, msg = auth.request_password_reset(
                    username=data['username'], 
                    email=data['email'], 
                    proposed_pass=data['new_password'], 
                    reason="OTP Verified Password Reset"
                ) 
                session.pop(session_key, None) 
                flash("Email verified! Your password reset request has been submitted.", "success" if ok else "danger") 
                return redirect(url_for("login")) 
                
        else: 
            flash("Invalid OTP code. Try again.", "danger") 
            
    try:
        return render_template("otp_verify.html", action_url=url_for('verify_otp', action=action))
    except Exception as e:
        print(f"Template load error: {e}")
        # Inline HTML fallback to prevent HTTP 500 crash if otp_verify.html is missing
        return f'''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Verify Email</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        </head>
        <body class="bg-light d-flex align-items-center justify-content-center vh-100">
            <div class="card p-4 shadow-sm" style="max-width: 400px; width: 100%;">
                <h4 class="text-center fw-bold mb-3">Verify Your Email</h4>
                <p class="text-muted small text-center">Enter the 6-digit verification code sent to your email.</p>
                <form method="POST" action="{url_for('verify_otp', action=action)}">
                    <div class="mb-3">
                        <input type="text" name="otp_code" maxlength="6" class="form-control text-center fw-bold fs-4" placeholder="123456" required autofocus>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Verify Code &rarr;</button>
                </form>
                <div class="text-center mt-3">
                    <a href="{url_for('login')}" class="small text-decoration-none">&larr; Back to Login</a>
                </div>
            </div>
        </body>
        </html>
        '''

@app.route("/logout")
def logout():
    username = session.get("username", "Guest")
    log_audit_action(username, "LOGOUT", "User logged out")
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# =========================================================
# Main Dashboard / Inventory Routes
# =========================================================

@app.route("/inventory")
def inventory():
    if "username" not in session:
        return redirect(url_for("login"))

    search = request.args.get("search", "").strip()
    cat_filter = request.args.get("category", "ALL")
    stat_filter = request.args.get("status", "ALL")
    stock_filter = request.args.get("stock", "ALL")

    query = """
        SELECT id, item_name, category, serial_number, quantity, min_stock, max_stock, location, status, added_by, added_at 
        FROM inventory 
        WHERE (item_name LIKE %s OR serial_number LIKE %s OR location LIKE %s)
    """
    params = [f"%{search}%", f"%{search}%", f"%{search}%"]

    if cat_filter != "ALL":
        query += " AND category = %s"
        params.append(cat_filter)

    if stat_filter != "ALL":
        query += " AND status = %s"
        params.append(stat_filter)

    query += " ORDER BY added_at DESC"

    inventory_items = []
    categories = []

    with closing(get_connection()) as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT DISTINCT category FROM inventory WHERE category IS NOT NULL AND category != ''")
        categories = [row[0] for row in cursor.fetchall()]
        categories.sort()

        cursor.execute(query, params)
        rows = cursor.fetchall()

        for row in rows:
            item_id, name, cat, serial, qty, min_s, max_s, loc, status, added_by, added_at = row
            
            if qty <= 0:
                stock_level = "NO_STOCK"
            elif qty <= min_s:
                stock_level = "LOW_STOCK"
            else:
                stock_level = "IN_STOCK"

            if stock_filter != "ALL" and stock_level != stock_filter:
                continue

            inventory_items.append({
                "id": item_id,
                "item_name": name,
                "category": cat,
                "serial_number": serial,
                "quantity": qty,
                "min_stock": min_s,
                "max_stock": max_s,
                "stock_level": stock_level,
                "location": loc,
                "status": status,
                "added_by": added_by,
                "added_at": added_at,
            })

    return render_template(
        "inventory.html",
        items=inventory_items,
        categories=categories,
        search=search,
        cat_filter=cat_filter,
        stat_filter=stat_filter,
        stock_filter=stock_filter,
    )


@app.route("/inventory/add", methods=["POST"])
def add_inventory():
    if session.get("role") not in ["ADMIN", "INVENTORY_SPECIALIST"]:
        flash("Unauthorized action.", "danger")
        return redirect(url_for("inventory"))

    item_name = request.form.get("item_name", "").strip()
    category = request.form.get("category", "").strip()
    serial = request.form.get("serial_number", "").strip()
    qty = int(request.form.get("quantity", 1))
    min_stock = int(request.form.get("min_stock", 1))
    max_stock = int(request.form.get("max_stock", 10))
    location = request.form.get("location", "").strip()

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO inventory (item_name, category, serial_number, quantity, min_stock, max_stock, location, status, added_by, added_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'AVAILABLE', %s, %s)
            """, (item_name, category, serial, qty, min_stock, max_stock, location, session["username"], now))
            conn.commit()

        log_audit_action(session["username"], "ADD_INVENTORY", f"Added item: {item_name} (Qty: {qty}, Serial: {serial})")
        flash("Hardware item added successfully!", "success")
    except Exception as e:
        flash(f"Error adding item: {e}", "danger")

    return redirect(url_for("inventory"))


@app.route("/inventory/update/<int:item_id>", methods=["POST"])
def update_inventory_item(item_id):
    if session.get("role") not in ["ADMIN", "INVENTORY_SPECIALIST"]:
        flash("Unauthorized action.", "danger")
        return redirect(url_for("inventory"))

    item_name = request.form.get("item_name", "").strip()
    category = request.form.get("category", "").strip()
    serial_number = request.form.get("serial_number", "").strip()
    quantity = int(request.form.get("quantity", 0))
    min_stock = int(request.form.get("min_stock", 0))
    max_stock = int(request.form.get("max_stock", 0))
    location = request.form.get("location", "").strip()

    new_status = 'OUT_OF_STOCK' if quantity == 0 else 'AVAILABLE'

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE inventory 
            SET item_name = %s, category = %s, serial_number = %s, quantity = %s, min_stock = %s, max_stock = %s, location = %s, status = %s
            WHERE id = %s
        """, (item_name, category, serial_number, quantity, min_stock, max_stock, location, new_status, item_id))
        conn.commit()

    log_audit_action(session["username"], "UPDATE_INVENTORY", f"Updated inventory item #{item_id} ({item_name})")
    flash("Inventory item updated successfully!", "success")
    return redirect(url_for("inventory"))


@app.route("/inventory/delete/<int:item_id>", methods=["POST"])
def delete_inventory(item_id):
    if session.get("role") not in ["ADMIN", "INVENTORY_SPECIALIST"]:
        flash("Unauthorized action.", "danger")
        return redirect(url_for("inventory"))

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM inventory WHERE id=%s", (item_id,))
        conn.commit()

    log_audit_action(session["username"], "DELETE_INVENTORY", f"Deleted Item ID #{item_id}")
    flash("Item deleted successfully.", "info")
    return redirect(url_for("inventory"))


# =========================================================
# Borrow & Return System Routes
# =========================================================

@app.route("/borrow")
def borrow_logs():
    if "username" not in session:
        return redirect(url_for("login"))

    role = session.get("role", "VIEWER")
    status_filter = request.args.get("status", "ALL")
    
    query = """
        SELECT id, item_id, item_name, serial_number, borrower_name, borrower_contact, quantity_borrowed, borrow_date, expected_return_date, actual_return_date, status, issued_by
        FROM borrow_logs
    """
    params = []
    where_clauses = []

    if role == "VIEWER":
        where_clauses.append("borrower_name = %s")
        params.append(session["username"])

    if status_filter != "ALL":
        where_clauses.append("status = %s")
        params.append(status_filter)

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    query += " ORDER BY borrow_date DESC"

    borrows = []
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        for row in cursor.fetchall():
            borrows.append({
                "id": row[0],
                "item_id": row[1],
                "item_name": row[2],
                "serial_number": row[3],
                "borrower_name": row[4],
                "borrower_contact": row[5],
                "quantity_borrowed": row[6],
                "borrow_date": row[7],
                "expected_return_date": row[8],
                "actual_return_date": row[9] or "N/A",
                "status": row[10],
                "issued_by": row[11] or "Pending Approval",
            })

    return render_template("borrow.html", borrows=borrows, status_filter=status_filter)


@app.route("/borrow/request", methods=["POST"])
def request_borrow():
    if "username" not in session:
        return redirect(url_for("login"))

    item_id = int(request.form.get("item_id", 0))
    borrower_contact = request.form.get("borrower_contact", "").strip()
    qty_borrowed = int(request.form.get("quantity_borrowed", 1))
    expected_return = request.form.get("expected_return_date", "").strip()
    
    role = session.get("role", "VIEWER")
    borrower_name = session["username"]

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT item_name, serial_number, quantity FROM inventory WHERE id = %s", (item_id,))
        item = cursor.fetchone()

        if not item:
            flash("Selected inventory item does not exist.", "danger")
            return redirect(url_for("inventory"))

        item_name, serial_number, current_qty = item

        if current_qty < qty_borrowed:
            flash(f"Insufficient stock available. Only {current_qty} remaining.", "danger")
            return redirect(url_for("inventory"))

        if role in ["ADMIN", "INVENTORY_SPECIALIST"]:
            status = "BORROWED"
            issued_by = session["username"]
            
            new_qty = current_qty - qty_borrowed
            new_inv_status = 'OUT_OF_STOCK' if new_qty == 0 else 'AVAILABLE'
            cursor.execute("UPDATE inventory SET quantity = %s, status = %s WHERE id = %s", (new_qty, new_inv_status, item_id))
        else:
            status = "PENDING"
            issued_by = "Pending"

        cursor.execute("""
            INSERT INTO borrow_logs (item_id, item_name, serial_number, borrower_name, borrower_contact, quantity_borrowed, borrow_date, expected_return_date, status, issued_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (item_id, item_name, serial_number, borrower_name, borrower_contact, qty_borrowed, now, expected_return, status, issued_by))
        conn.commit()

    if status == "BORROWED":
        log_audit_action(session["username"], "DIRECT_ISSUE", f"Directly issued {qty_borrowed} x {item_name} to {borrower_name}")
        flash("Item successfully issued!", "success")
    else:
        log_audit_action(session["username"], "REQUEST_BORROW", f"Requested {qty_borrowed} x {item_name}")
        flash("Borrow request submitted successfully! Pending approval.", "success")
        
    return redirect(url_for("borrow_logs"))


@app.route("/borrow/approve/<int:borrow_id>", methods=["POST"])
def approve_borrow(borrow_id):
    if session.get("role") not in ["ADMIN", "INVENTORY_SPECIALIST"]:
        flash("Unauthorized action.", "danger")
        return redirect(url_for("borrow_logs"))

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT item_id, quantity_borrowed, status FROM borrow_logs WHERE id = %s", (borrow_id,))
        borrow = cursor.fetchone()

        if not borrow or borrow[2] != "PENDING":
            flash("Invalid or non-pending request.", "warning")
            return redirect(url_for("borrow_logs"))

        item_id, qty_borrowed, _ = borrow

        cursor.execute("SELECT quantity FROM inventory WHERE id = %s", (item_id,))
        stock = cursor.fetchone()

        if not stock or stock[0] < qty_borrowed:
            flash("Cannot approve request. Insufficient inventory stock.", "danger")
            return redirect(url_for("borrow_logs"))

        new_qty = stock[0] - qty_borrowed
        new_status = 'OUT_OF_STOCK' if new_qty == 0 else 'AVAILABLE'

        cursor.execute("UPDATE inventory SET quantity = %s, status = %s WHERE id = %s", (new_qty, new_status, item_id))
        cursor.execute("""
            UPDATE borrow_logs 
            SET status = 'BORROWED', issued_by = %s 
            WHERE id = %s
        """, (session["username"], borrow_id))
        conn.commit()

    log_audit_action(session["username"], "APPROVE_BORROW", f"Approved borrow request ID #{borrow_id}")
    flash("Borrow request approved and stock updated!", "success")
    return redirect(url_for("borrow_logs"))


@app.route("/borrow/return/<int:borrow_id>", methods=["POST"])
def return_borrowed_item(borrow_id):
    if session.get("role") not in ["ADMIN", "INVENTORY_SPECIALIST"]:
        flash("Unauthorized action.", "danger")
        return redirect(url_for("borrow_logs"))

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT item_id, quantity_borrowed, status FROM borrow_logs WHERE id = %s", (borrow_id,))
        borrow = cursor.fetchone()

        if not borrow or borrow[2] != "BORROWED":
            flash("Invalid transaction state for return.", "warning")
            return redirect(url_for("borrow_logs"))

        item_id, qty_borrowed, _ = borrow

        cursor.execute("UPDATE inventory SET quantity = quantity + %s, status = 'AVAILABLE' WHERE id = %s", (qty_borrowed, item_id))
        cursor.execute("UPDATE borrow_logs SET status = 'RETURNED', actual_return_date = %s WHERE id = %s", (now, borrow_id))
        conn.commit()

    log_audit_action(session["username"], "RETURN_ITEM", f"Returned transaction ID #{borrow_id}")
    flash("Item returned successfully and inventory updated!", "success")
    return redirect(url_for("borrow_logs"))


# =========================================================
# Maintenance Routes
# =========================================================

@app.route("/maintenance")
def maintenance():
    if "username" not in session:
        return redirect(url_for("login"))

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, item_name, serial_number, vendor, issue_description, repair_cost, status, logged_by, logged_at, resolved_at FROM maintenance ORDER BY logged_at DESC")
        logs = []
        for row in cursor.fetchall():
            logs.append({
                "id": row[0],
                "item_name": row[1],
                "serial_number": row[2],
                "vendor": row[3],
                "issue_description": row[4],
                "repair_cost": row[5],
                "status": row[6],
                "logged_by": row[7],
                "logged_at": row[8],
                "resolved_at": row[9] or "N/A"
            })
            
        cursor.execute("SELECT id, item_name, serial_number FROM inventory")
        items = cursor.fetchall()

    return render_template("maintenance.html", logs=logs, items=items)


@app.route("/maintenance/add", methods=["POST"])
def add_maintenance():
    if "username" not in session:
        return redirect(url_for("login"))

    item_id = int(request.form.get("item_id", 0))
    vendor = request.form.get("vendor", "N/A").strip()
    issue_description = request.form.get("issue_description", "").strip()
    repair_cost = float(request.form.get("repair_cost", 0.0))
    logged_by = session["username"]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT item_name, serial_number FROM inventory WHERE id = %s", (item_id,))
        item = cursor.fetchone()
        
        if not item:
            flash("Selected item not found.", "danger")
            return redirect(url_for("maintenance"))
            
        item_name, serial_number = item

        cursor.execute("""
            INSERT INTO maintenance (item_name, serial_number, vendor, issue_description, repair_cost, status, logged_by, logged_at)
            VALUES (%s, %s, %s, %s, %s, 'PENDING', %s, %s)
        """, (item_name, serial_number, vendor, issue_description, repair_cost, logged_by, now))
        
        cursor.execute("UPDATE inventory SET status = 'MAINTENANCE' WHERE id = %s", (item_id,))
        conn.commit()

    log_audit_action(session["username"], "REPORT_MAINTENANCE", f"Reported maintenance issue for {item_name}")
    flash("Maintenance ticket submitted successfully!", "success")
    return redirect(url_for("maintenance"))


@app.route("/maintenance/resolve/<int:log_id>", methods=["POST"])
def resolve_maintenance(log_id):
    if session.get("role") not in ["ADMIN", "INVENTORY_SPECIALIST"]:
        flash("Unauthorized action.", "danger")
        return redirect(url_for("maintenance"))

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT serial_number FROM maintenance WHERE id = %s", (log_id,))
        row = cursor.fetchone()
        
        if row:
            serial_number = row[0]
            cursor.execute("""
                UPDATE maintenance 
                SET status = 'COMPLETED', resolved_at = %s 
                WHERE id = %s
            """, (now, log_id))
            
            cursor.execute("UPDATE inventory SET status = 'AVAILABLE' WHERE serial_number = %s", (serial_number,))
            conn.commit()

    log_audit_action(session["username"], "RESOLVE_MAINTENANCE", f"Resolved maintenance ticket ID #{log_id}")
    flash("Maintenance ticket marked as resolved and item restored to inventory!", "success")
    return redirect(url_for("maintenance"))


# =========================================================
# Admin-Only Routes
# =========================================================

@app.route("/admin/lockouts")
def admin_lockouts():
    if session.get("role") != "ADMIN":
        flash("Access restricted to Admins only.", "danger")
        return redirect(url_for("inventory"))

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, role, failed_attempts, is_locked FROM users WHERE is_locked = 1")
        users = cursor.fetchall()

    return render_template("lockouts.html", users=users)


@app.route("/admin/unlock/<int:user_id>", methods=["POST"])
def unlock_user(user_id):
    if session.get("role") != "ADMIN":
        flash("Unauthorized action.", "danger")
        return redirect(url_for("inventory"))

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_locked=0, failed_attempts=0 WHERE id=%s", (user_id,))
        conn.commit()

    log_audit_action(session["username"], "UNLOCK_ACCOUNT", f"Unlocked User ID #{user_id}")
    flash("User account unlocked!", "success")
    return redirect(url_for("admin_lockouts"))


@app.route("/admin/audit-logs")
def audit_logs():
    if session.get("role") != "ADMIN":
        flash("Access restricted to Admins only.", "danger")
        return redirect(url_for("inventory"))

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, timestamp, performed_by, action, details FROM audit_logs ORDER BY id DESC")
        logs = cursor.fetchall()

    return render_template("audit_logs.html", logs=logs)


# =========================================================
# Profile & Export Routes
# =========================================================

@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    if request.method == "POST":
        old_p = request.form.get("old_password", "").strip()
        new_p = request.form.get("new_password", "").strip()
        conf_p = request.form.get("confirm_password", "").strip()

        if not old_p or not new_p or not conf_p:
            flash("All password fields are required.", "danger")
        elif new_p != conf_p:
            flash("New password and confirmation do not match.", "danger")
        elif len(new_p) < 8:
            flash("Password must be at least 8 characters long.", "danger")
        else:
            with closing(get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT password_hash, salt FROM users WHERE username=%s", (username,))
                row = cursor.fetchone()

                if row:
                    stored_hash, salt = row
                    calc_hash, _ = hash_password(old_p, salt)
                    if calc_hash == stored_hash:
                        new_hash, new_salt = hash_password(new_p)
                        cursor.execute("UPDATE users SET password_hash=%s, salt=%s WHERE username=%s", (new_hash, new_salt, username))
                        conn.commit()
                        log_audit_action(username, "CHANGE_PASSWORD", "User updated password")
                        flash("Password updated successfully!", "success")
                    else:
                        flash("Incorrect current password.", "danger")

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT username, email, role FROM users WHERE username=%s", (username,))
        user_info = cursor.fetchone()

    return render_template("profile.html", user=user_info)


@app.route("/export/<table_name>")
def export_csv(table_name):
    if "username" not in session:
        return redirect(url_for("login"))

    queries = {
        "users": "SELECT id, username, email, role, is_locked FROM users",
        "inventory": "SELECT id, item_name, category, serial_number, quantity, min_stock, max_stock, location, status, added_by, added_at FROM inventory",
        "borrow": "SELECT id, item_id, item_name, serial_number, borrower_name, borrower_contact, quantity_borrowed, borrow_date, expected_return_date, actual_return_date, status, issued_by FROM borrow_logs",
        "audit": "SELECT id, timestamp, performed_by, action, details FROM audit_logs"
    }

    if table_name not in queries:
        flash("Invalid export requested.", "danger")
        return redirect(url_for("inventory"))

    if table_name == "audit" and session.get("role") != "ADMIN":
        flash("Unauthorized export request.", "danger")
        return redirect(url_for("inventory"))

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(queries[table_name])
        rows = cursor.fetchall()
        headers = [desc[0] for desc in cursor.description]

    def generate():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        
        for row in rows:
            writer.writerow(row)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={table_name}_export.csv"}
    )


if __name__ == "__main__":
    app.run(debug=True)
