import sys
import os
import csv
import sqlite3
import datetime
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_models import get_connection, hash_password, init_db


def log_audit_action(user: str, action: str, details: str):
    """Helper utility to log actions into the system audit trail."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO audit_logs (timestamp, performed_by, action, details) VALUES (?, ?, ?, ?)",
                (now, user, action, details)
            )
            conn.commit()
    except Exception as e:
        print(f"Failed to log audit action: {e}")


# =========================================================
# Hardware Inventory Operations
# =========================================================

def get_stock_level(qty: int) -> str:
    if qty <= 0:
        return "NO_STOCK"
    elif 1 <= qty <= 3:
        return "LOW_STOCK"
    else:
        return "IN_STOCK"


def fetch_categories() -> list:
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT category FROM inventory WHERE category IS NOT NULL AND category != ''")
            categories = [row[0] for row in cursor.fetchall()]
        categories.sort()
        return categories
    except Exception as e:
        print(f"Error populating categories: {e}")
        return []


def load_inventory(search_keyword: str = "", category_filter: str = "ALL", status_filter: str = "ALL", stock_filter: str = "ALL") -> list:
    keyword = f"%{search_keyword.strip()}%"
    query = """
        SELECT id, item_name, category, serial_number, quantity, location, status, added_by, added_at 
        FROM inventory 
        WHERE (item_name LIKE ? OR serial_number LIKE ? OR location LIKE ?)
    """
    params = [keyword, keyword, keyword]

    if category_filter != "ALL":
        query += " AND category = ?"
        params.append(category_filter)

    if status_filter != "ALL":
        query += " AND status = ?"
        params.append(status_filter)

    query += " ORDER BY added_at DESC"

    inventory_list = []
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            for row in rows:
                item_id, name, cat, serial, qty, loc, status, added_by, added_at = row
                stock_level = get_stock_level(qty)

                if stock_filter != "ALL" and stock_level != stock_filter:
                    continue

                formatted_row = (item_id, name, cat, serial, qty, stock_level.replace("_", " "), loc, status, added_by, added_at)
                inventory_list.append(formatted_row)
    except Exception as e:
        print(f"Error loading inventory: {e}")

    return inventory_list


def add_inventory_item(item_name: str, category: str, serial_number: str, quantity: int, location: str, current_user: str) -> bool:
    if not item_name or not category or not serial_number or not location:
        raise ValueError("All fields are required.")

    if quantity < 0:
        raise ValueError("Quantity must be a non-negative integer.")

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO inventory (item_name, category, serial_number, quantity, location, status, added_by, added_at)
                VALUES (?, ?, ?, ?, ?, 'AVAILABLE', ?, ?)
            """, (item_name, category, serial_number, quantity, location, current_user, now))
            conn.commit()

        log_audit_action(current_user, "ADD_INVENTORY", f"Added item: {item_name} (Qty: {quantity}, Serial: {serial_number})")
        return True
    except sqlite3.IntegrityError:
        raise ValueError("Serial number must be unique.")


def update_inventory_item(item_id: int, item_name: str, category: str, serial_number: str, quantity: int, location: str, status: str, current_user: str) -> bool:
    if not item_name or not category or not serial_number or not location:
        raise ValueError("All fields are required.")

    if quantity < 0:
        raise ValueError("Quantity must be a non-negative integer.")

    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE inventory 
                SET item_name=?, category=?, serial_number=?, quantity=?, location=?, status=?
                WHERE id=?
            """, (item_name, category, serial_number, quantity, location, status, item_id))
            conn.commit()

        log_audit_action(current_user, "UPDATE_INVENTORY", f"Updated ID #{item_id}: {item_name} (Qty: {quantity}, Status: {status})")
        return True
    except sqlite3.IntegrityError:
        raise ValueError("Serial number must be unique.")


def delete_inventory_item(item_id: int, item_name: str, current_user: str) -> bool:
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM inventory WHERE id=?", (item_id,))
        conn.commit()

    log_audit_action(current_user, "DELETE_INVENTORY", f"Deleted Item ID #{item_id}: {item_name}")
    return True


# =========================================================
# Borrow & Return Management Operations
# =========================================================

def submit_borrow_request(item_id: int, item_name: str, requested_qty: int, available_qty: int, current_user: str) -> bool:
    if requested_qty <= 0 or requested_qty > available_qty:
        raise ValueError(f"Please enter a quantity between 1 and {available_qty}.")

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO borrow_requests (item_id, requested_by, quantity, status, requested_at)
            VALUES (?, ?, ?, 'PENDING_BORROW', ?)
        """, (item_id, current_user, requested_qty, now))
        conn.commit()

    log_audit_action(current_user, "SUBMIT_BORROW_REQUEST", f"Requested {requested_qty}x '{item_name}' (Item ID #{item_id})")
    return True


def load_borrow_requests(current_user: str, role: str) -> list:
    requests = []
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            if str(role).upper() in ["ADMIN", "INVENTORY_SPECIALIST"]:
                cursor.execute("""
                    SELECT r.id, r.item_id, i.item_name, r.requested_by, r.quantity, r.status, r.requested_at, r.processed_at
                    FROM borrow_requests r
                    JOIN inventory i ON r.item_id = i.id
                    ORDER BY r.requested_at DESC
                """)
            else:
                cursor.execute("""
                    SELECT r.id, r.item_id, i.item_name, r.requested_by, r.quantity, r.status, r.requested_at, r.processed_at
                    FROM borrow_requests r
                    JOIN inventory i ON r.item_id = i.id
                    WHERE r.requested_by = ?
                    ORDER BY r.requested_at DESC
                """, (current_user,))

            rows = cursor.fetchall()
            for row in rows:
                formatted_row = list(row)
                formatted_row[7] = row[7] if row[7] else "Pending"
                requests.append(formatted_row)
    except Exception as e:
        print(f"Error loading borrow requests: {e}")

    return requests


def submit_return_request(req_id: int, item_name: str, requested_by: str, status: str, current_user: str, user_role: str) -> bool:
    if requested_by != current_user and str(user_role).upper() not in ["ADMIN", "INVENTORY_SPECIALIST"]:
        raise PermissionError("You can only request returns for items you borrowed.")

    if status != "BORROWED":
        raise ValueError(f"Cannot return item with status '{status}'. Only 'BORROWED' items can be returned.")

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE borrow_requests SET status='RETURN_PENDING' WHERE id=?", (req_id,))
        conn.commit()

    log_audit_action(current_user, "SUBMIT_RETURN_REQUEST", f"Requested return for Request #{req_id} ({item_name})")
    return True


def approve_request(req_id: int, item_id: int, item_name: str, requested_by: str, qty: int, status: str, current_user: str) -> bool:
    qty = int(qty)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with closing(get_connection()) as conn:
        cursor = conn.cursor()

        if status == "PENDING_BORROW":
            cursor.execute("SELECT quantity FROM inventory WHERE id=?", (item_id,))
            row = cursor.fetchone()

            if not row or row[0] < qty:
                raise ValueError("Insufficient inventory stock available to fulfill request.")

            cursor.execute("UPDATE inventory SET quantity = quantity - ? WHERE id=?", (qty, item_id))
            cursor.execute("UPDATE borrow_requests SET status='BORROWED', processed_at=? WHERE id=?", (now, req_id))
            conn.commit()

            log_audit_action(current_user, "APPROVE_BORROW", f"Approved borrow request #{req_id} ({qty}x {item_name}) for {requested_by}")

        elif status == "RETURN_PENDING":
            cursor.execute("UPDATE inventory SET quantity = quantity + ? WHERE id=?", (qty, item_id))
            cursor.execute("UPDATE borrow_requests SET status='RETURNED', processed_at=? WHERE id=?", (now, req_id))
            conn.commit()

            log_audit_action(current_user, "APPROVE_RETURN", f"Approved return request #{req_id} ({qty}x {item_name}) from {requested_by}")

        else:
            raise ValueError(f"Cannot approve request with status '{status}'.")

    return True


def reject_request(req_id: int, item_name: str, requested_by: str, status: str, current_user: str) -> bool:
    if status not in ["PENDING_BORROW", "RETURN_PENDING"]:
        raise ValueError(f"Cannot reject request with status '{status}'.")

    new_status = "REJECTED" if status == "PENDING_BORROW" else "BORROWED"

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE borrow_requests SET status=? WHERE id=?", (new_status, req_id))
        conn.commit()

    log_audit_action(current_user, "REJECT_REQUEST", f"Rejected request #{req_id} ({item_name}) from {requested_by}")
    return True


# =========================================================
# Maintenance & Repair Operations
# =========================================================

def load_maintenance_logs(selected_status: str = "ALL") -> list:
    logs = []
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            if selected_status == "ALL":
                cursor.execute("""
                    SELECT id, item_name, serial_number, vendor, repair_cost, status, logged_by, logged_at, resolved_at 
                    FROM maintenance_logs ORDER BY logged_at DESC
                """)
            else:
                cursor.execute("""
                    SELECT id, item_name, serial_number, vendor, repair_cost, status, logged_by, logged_at, resolved_at 
                    FROM maintenance_logs WHERE status=? ORDER BY logged_at DESC
                """, (selected_status,))

            rows = cursor.fetchall()
            for row in rows:
                formatted_row = list(row)
                formatted_row[4] = f"${row[4]:,.2f}" if row[4] is not None else "$0.00"
                formatted_row[8] = row[8] if row[8] else "N/A"
                logs.append(formatted_row)
    except Exception as e:
        print(f"Error loading maintenance logs: {e}")

    return logs


def add_maintenance_log(item: str, serial: str, vendor: str, cost_str: str, description: str, current_user: str) -> bool:
    if not item or not serial or not vendor or not description:
        raise ValueError("All fields except cost are required.")

    try:
        cost = float(cost_str) if cost_str else 0.0
    except ValueError:
        raise ValueError("Cost must be a valid number.")

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO maintenance_logs (item_name, serial_number, vendor, issue_description, repair_cost, status, logged_by, logged_at)
            VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)
        """, (item, serial, vendor, description, cost, current_user, now))
        conn.commit()

    log_audit_action(current_user, "LOG_MAINTENANCE", f"Logged repair for: {item} (Vendor: {vendor})")
    return True


def update_maintenance_status(log_id: int, new_status: str, current_user: str) -> bool:
    resolved_at = None
    if new_status in ["COMPLETED", "UNREPAIRABLE"]:
        resolved_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE maintenance_logs 
            SET status=?, resolved_at=? 
            WHERE id=?
        """, (new_status, resolved_at, log_id))
        conn.commit()

    log_audit_action(current_user, "UPDATE_MAINTENANCE_STATUS", f"Updated Log #{log_id} status to {new_status}")
    return True


def delete_maintenance_log(log_id: int, item_name: str, current_user: str) -> bool:
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM maintenance_logs WHERE id=?", (log_id,))
        conn.commit()

    log_audit_action(current_user, "DELETE_MAINTENANCE_LOG", f"Deleted Repair Log ID #{log_id}")
    return True


# =========================================================
# Account Lockout Operations
# =========================================================

def load_locked_accounts(current_user: str) -> list:
    locked_users = []
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, username, email, role, failed_attempts, is_locked FROM users WHERE username != ? AND is_locked = 1 ORDER BY username ASC",
                (current_user,)
            )
            rows = cursor.fetchall()
            for row in rows:
                u_id, username, email, role, failed_attempts, is_locked = row
                status = "LOCKED" if is_locked else "ACTIVE"
                locked_users.append((u_id, username, email, role, failed_attempts, status))
    except Exception as e:
        print(f"Error loading locked users: {e}")

    return locked_users


def unlock_account(user_id: int, username: str, current_user: str) -> bool:
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_locked=0, failed_attempts=0 WHERE id=?", (user_id,))
        conn.commit()

    log_audit_action(current_user, "UNLOCK_ACCOUNT", f"Approved lockout release for user: {username}")
    return True


# =========================================================
# Audit Trail Operations
# =========================================================

def load_audit_logs() -> list:
    logs = []
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, timestamp, performed_by, action, details FROM audit_logs ORDER BY id DESC")
            logs = cursor.fetchall()
    except Exception as e:
        print(f"Error loading audit logs: {e}")

    return logs


# =========================================================
# User Profile & Security Operations
# =========================================================

def update_user_password(username: str, old_p: str, new_p: str, conf_p: str) -> bool:
    if not old_p or not new_p or not conf_p:
        raise ValueError("All password fields are required.")

    if new_p != conf_p:
        raise ValueError("New password and confirmation do not match.")

    if len(new_p) < 6:
        raise ValueError("Password must be at least 6 characters long.")

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash, salt FROM users WHERE username=?", (username,))
        row = cursor.fetchone()

        if not row:
            raise ValueError("User record not found.")

        stored_hash, salt = row
        calc_hash, _ = hash_password(old_p, salt)

        if calc_hash != stored_hash:
            raise ValueError("Incorrect current password.")

        new_hash, new_salt = hash_password(new_p)
        cursor.execute("UPDATE users SET password_hash=?, salt=? WHERE username=?", (new_hash, new_salt, username))
        conn.commit()

    log_audit_action(username, "CHANGE_PASSWORD", "User changed account password")
    return True


# =========================================================
# System Data Export Utilities
# =========================================================

def export_table_to_csv(query: str, file_path: str) -> bool:
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            headers = [description[0] for description in cursor.description]

        with open(file_path, mode="w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(headers)
            writer.writerows(rows)

        return True
    except Exception as e:
        raise RuntimeError(f"An error occurred while saving the file: {str(e)}")


def export_users_to_csv(file_path: str) -> bool:
    return export_table_to_csv("SELECT id, username, email, role, is_locked FROM users", file_path)


def export_inventory_to_csv(file_path: str) -> bool:
    return export_table_to_csv("SELECT id, item_name, category, serial_number, quantity, location, status, added_by, added_at FROM inventory", file_path)


def export_audit_logs_to_csv(file_path: str) -> bool:
    return export_table_to_csv("SELECT id, timestamp, performed_by, action, details FROM audit_logs", file_path)


if __name__ == "__main__":
    init_db()
