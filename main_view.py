import sys
import os
import csv
import sqlite3
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_models import get_connection, hash_password, init_db
from login_view import LoginWindow


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
# Hardware Inventory Tab View
# =========================================================

class InventoryTab(tk.Frame):
    def __init__(self, parent, current_user: str, role: str, on_inventory_changed=None):
        super().__init__(parent)
        self.current_user = current_user
        self.user_role = role
        self.on_inventory_changed = on_inventory_changed

        self.setup_ui()
        self.load_inventory()

    def setup_ui(self):
        control_frame = tk.Frame(self)
        control_frame.pack(fill="x", padx=10, pady=10)

        tk.Label(control_frame, text="Hardware Inventory", font=("Arial", 14, "bold")).pack(side="left")

        # Borrow button available for all roles
        tk.Button(
            control_frame, 
            text="Borrow Item", 
            command=self.open_borrow_modal, 
            bg="#FF9800", 
            fg="white", 
            font=("Arial", 9, "bold")
        ).pack(side="right", padx=5)

        if str(self.user_role).upper() in ["ADMIN", "INVENTORY_SPECIALIST"]:
            tk.Button(
                control_frame, 
                text="Delete Selected Item", 
                command=self.delete_inventory_item, 
                bg="#f44336", 
                fg="white", 
                font=("Arial", 9, "bold")
            ).pack(side="right", padx=5)

            tk.Button(
                control_frame, 
                text="Update Selected Item", 
                command=self.open_update_item_modal, 
                bg="#2196F3", 
                fg="white", 
                font=("Arial", 9, "bold")
            ).pack(side="right", padx=5)

            tk.Button(
                control_frame, 
                text="+ Add Hardware Item", 
                command=self.open_add_item_modal, 
                bg="#4CAF50", 
                fg="white", 
                font=("Arial", 9, "bold")
            ).pack(side="right", padx=5)

        filter_frame = tk.LabelFrame(self, text="Advanced Search & Filtering", font=("Arial", 9, "bold"))
        filter_frame.pack(fill="x", padx=10, pady=(0, 5), ipady=3)

        tk.Label(filter_frame, text="Search Keyword:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(filter_frame, textvariable=self.search_var, width=18)
        search_entry.grid(row=0, column=1, padx=5, pady=5)
        search_entry.bind("<KeyRelease>", lambda e: self.load_inventory())

        tk.Label(filter_frame, text="Category:").grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self.category_filter_var = tk.StringVar(value="ALL")
        self.category_dropdown = ttk.Combobox(
            filter_frame, 
            textvariable=self.category_filter_var, 
            state="readonly", 
            width=12
        )
        self.category_dropdown.grid(row=0, column=3, padx=5, pady=5)
        self.category_dropdown.bind("<<ComboboxSelected>>", lambda e: self.load_inventory())

        tk.Label(filter_frame, text="Status:").grid(row=0, column=4, padx=5, pady=5, sticky="w")
        self.status_filter_var = tk.StringVar(value="ALL")
        status_dropdown = ttk.Combobox(
            filter_frame, 
            textvariable=self.status_filter_var, 
            values=["ALL", "AVAILABLE", "IN_USE", "UNDER_MAINTENANCE", "RETIRED"], 
            state="readonly", 
            width=12
        )
        status_dropdown.grid(row=0, column=5, padx=5, pady=5)
        status_dropdown.bind("<<ComboboxSelected>>", lambda e: self.load_inventory())

        tk.Label(filter_frame, text="Stock Level:").grid(row=0, column=6, padx=5, pady=5, sticky="w")
        self.stock_filter_var = tk.StringVar(value="ALL")
        stock_dropdown = ttk.Combobox(
            filter_frame, 
            textvariable=self.stock_filter_var, 
            values=["ALL", "IN_STOCK", "LOW_STOCK", "NO_STOCK"], 
            state="readonly", 
            width=12
        )
        stock_dropdown.grid(row=0, column=7, padx=5, pady=5)
        stock_dropdown.bind("<<ComboboxSelected>>", lambda e: self.load_inventory())

        tk.Button(filter_frame, text="Reset", command=self.reset_filters).grid(row=0, column=8, padx=10, pady=5)

        columns = ("ID", "Item Name", "Category", "Serial No.", "Qty", "Stock Level", "Location", "Status", "Added By", "Added Date")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=13)

        column_widths = {
            "ID": 35, "Item Name": 120, "Category": 90, "Serial No.": 100, 
            "Qty": 40, "Stock Level": 90, "Location": 90, "Status": 90, 
            "Added By": 80, "Added Date": 110
        }

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=column_widths.get(col, 90), anchor="center")

        self.tree.tag_configure("IN_STOCK", background="#e8f5e9", foreground="#2e7d32")
        self.tree.tag_configure("LOW_STOCK", background="#fffde7", foreground="#f57f17")
        self.tree.tag_configure("NO_STOCK", background="#ffebee", foreground="#c62828")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=5)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=5)

    def populate_category_dropdown(self):
        try:
            with closing(get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT category FROM inventory WHERE category IS NOT NULL AND category != ''")
                categories = [row[0] for row in cursor.fetchall()]
            
            categories.sort()
            self.category_dropdown["values"] = ["ALL"] + categories
        except Exception as e:
            print(f"Error populating categories: {e}")

    def reset_filters(self):
        self.search_var.set("")
        self.category_filter_var.set("ALL")
        self.status_filter_var.set("ALL")
        self.stock_filter_var.set("ALL")
        self.load_inventory()

    def get_stock_level(self, qty: int) -> str:
        if qty <= 0:
            return "NO_STOCK"
        elif 1 <= qty <= 3:
            return "LOW_STOCK"
        else:
            return "IN_STOCK"

    def load_inventory(self):
        self.populate_category_dropdown()

        for item in self.tree.get_children():
            self.tree.delete(item)

        keyword = f"%{self.search_var.get().strip()}%"
        cat_filter = self.category_filter_var.get()
        stat_filter = self.status_filter_var.get()
        stock_filter = self.stock_filter_var.get()

        query = """
            SELECT id, item_name, category, serial_number, quantity, location, status, added_by, added_at 
            FROM inventory 
            WHERE (item_name LIKE ? OR serial_number LIKE ? OR location LIKE ?)
        """
        params = [keyword, keyword, keyword]

        if cat_filter != "ALL":
            query += " AND category = ?"
            params.append(cat_filter)

        if stat_filter != "ALL":
            query += " AND status = ?"
            params.append(stat_filter)

        query += " ORDER BY added_at DESC"

        try:
            with closing(get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                for row in rows:
                    item_id, name, cat, serial, qty, loc, status, added_by, added_at = row
                    stock_level = self.get_stock_level(qty)

                    if stock_filter != "ALL" and stock_level != stock_filter:
                        continue

                    formatted_row = (item_id, name, cat, serial, qty, stock_level.replace("_", " "), loc, status, added_by, added_at)
                    self.tree.insert("", "end", values=formatted_row, tags=(stock_level,))
        except Exception as e:
            print(f"Error loading inventory: {e}")

    def open_borrow_modal(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Selection Required", "Please select an item from the table to borrow.")
            return

        item_values = self.tree.item(selected_item[0], "values")
        item_id, item_name, _, _, available_qty, _, _, status, _, _ = item_values

        try:
            available_qty = int(available_qty)
        except ValueError:
            available_qty = 0

        if available_qty <= 0:
            messagebox.showerror("Item Unavailable", f"'{item_name}' is currently out of stock.")
            return

        modal = tk.Toplevel(self)
        modal.title("Submit Borrow Request")
        modal.geometry("340x220")
        modal.grab_set()

        tk.Label(modal, text=f"Borrow: {item_name}", font=("Arial", 11, "bold")).pack(pady=10)
        tk.Label(modal, text=f"Available Quantity: {available_qty}").pack(pady=2)

        tk.Label(modal, text="Quantity to Borrow:").pack(anchor="w", padx=30, pady=(10, 0))
        qty_entry = tk.Entry(modal, width=20)
        qty_entry.insert(0, "1")
        qty_entry.pack(padx=30, pady=5)

        def submit_request():
            try:
                req_qty = int(qty_entry.get().strip())
                if req_qty <= 0 or req_qty > available_qty:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Invalid Quantity", f"Please enter a quantity between 1 and {available_qty}.", parent=modal)
                return

            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                with closing(get_connection()) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO borrow_requests (item_id, requested_by, quantity, status, requested_at)
                        VALUES (?, ?, ?, 'PENDING_BORROW', ?)
                    """, (item_id, self.current_user, req_qty, now))
                    conn.commit()

                log_audit_action(self.current_user, "SUBMIT_BORROW_REQUEST", f"Requested {req_qty}x '{item_name}' (Item ID #{item_id})")
                messagebox.showinfo("Success", "Borrow request submitted for Admin review!", parent=modal)
                modal.destroy()
                if self.on_inventory_changed:
                    self.on_inventory_changed()
            except Exception as e:
                messagebox.showerror("Database Error", f"Failed to submit request: {e}", parent=modal)

        tk.Button(modal, text="Submit Request", command=submit_request, bg="#FF9800", fg="white", width=20).pack(pady=15)

    def open_add_item_modal(self):
        modal = tk.Toplevel(self)
        modal.title("Add Hardware Item")
        modal.geometry("380x380")
        modal.grab_set()

        tk.Label(modal, text="New Hardware Entry", font=("Arial", 11, "bold")).pack(pady=10)

        fields = {}
        labels = [
            ("Item Name:", "item_name"),
            ("Category:", "category"),
            ("Serial Number:", "serial_number"),
            ("Quantity:", "quantity"),
            ("Location:", "location"),
        ]

        for label_text, key in labels:
            tk.Label(modal, text=label_text).pack(anchor="w", padx=30)
            entry = tk.Entry(modal, width=35)
            entry.pack(padx=30, pady=(0, 5))
            fields[key] = entry

        fields["quantity"].insert(0, "1")

        def save_item():
            item_name = fields["item_name"].get().strip()
            category = fields["category"].get().strip()
            serial = fields["serial_number"].get().strip()
            qty_str = fields["quantity"].get().strip()
            location = fields["location"].get().strip()

            if not item_name or not category or not serial or not location:
                messagebox.showerror("Validation Error", "All fields are required.", parent=modal)
                return

            try:
                qty = int(qty_str)
                if qty < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Validation Error", "Quantity must be a non-negative integer.", parent=modal)
                return

            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            try:
                with closing(get_connection()) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO inventory (item_name, category, serial_number, quantity, location, status, added_by, added_at)
                        VALUES (?, ?, ?, ?, ?, 'AVAILABLE', ?, ?)
                    """, (item_name, category, serial, qty, location, self.current_user, now))
                    conn.commit()

                log_audit_action(self.current_user, "ADD_INVENTORY", f"Added item: {item_name} (Qty: {qty}, Serial: {serial})")
                messagebox.showinfo("Success", "Hardware item recorded!", parent=modal)
                modal.destroy()
                self.load_inventory()
            except sqlite3.IntegrityError:
                messagebox.showerror("Database Error", "Serial number must be unique.", parent=modal)

        tk.Button(modal, text="Save Item", command=save_item, bg="#4CAF50", fg="white", width=20).pack(pady=15)

    def open_update_item_modal(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Selection Required", "Please select an item to update.")
            return

        item_values = self.tree.item(selected_item[0], "values")
        item_id, item_name, category, serial_number, quantity, _, location, status, _, _ = item_values

        modal = tk.Toplevel(self)
        modal.title(f"Update Item #{item_id}")
        modal.geometry("380x430")
        modal.grab_set()

        tk.Label(modal, text=f"Update Hardware Record (ID #{item_id})", font=("Arial", 11, "bold")).pack(pady=10)

        fields = {}
        labels = [
            ("Item Name:", "item_name", item_name),
            ("Category:", "category", category),
            ("Serial Number:", "serial_number", serial_number),
            ("Quantity:", "quantity", str(quantity)),
            ("Location:", "location", location),
        ]

        for label_text, key, val in labels:
            tk.Label(modal, text=label_text).pack(anchor="w", padx=30)
            entry = tk.Entry(modal, width=35)
            entry.insert(0, val)
            entry.pack(padx=30, pady=(0, 5))
            fields[key] = entry

        tk.Label(modal, text="Status:").pack(anchor="w", padx=30)
        status_var = tk.StringVar(value=status)
        status_dropdown = ttk.Combobox(
            modal, 
            textvariable=status_var, 
            values=["AVAILABLE", "IN_USE", "UNDER_MAINTENANCE", "RETIRED"], 
            state="readonly", 
            width=32
        )
        status_dropdown.pack(padx=30, pady=(0, 10))

        def save_changes():
            u_name = fields["item_name"].get().strip()
            u_cat = fields["category"].get().strip()
            u_serial = fields["serial_number"].get().strip()
            u_qty_str = fields["quantity"].get().strip()
            u_loc = fields["location"].get().strip()
            u_status = status_var.get()

            if not u_name or not u_cat or not u_serial or not u_loc:
                messagebox.showerror("Validation Error", "All fields are required.", parent=modal)
                return

            try:
                u_qty = int(u_qty_str)
                if u_qty < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Validation Error", "Quantity must be a non-negative integer.", parent=modal)
                return

            try:
                with closing(get_connection()) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE inventory 
                        SET item_name=?, category=?, serial_number=?, quantity=?, location=?, status=?
                        WHERE id=?
                    """, (u_name, u_cat, u_serial, u_qty, u_loc, u_status, item_id))
                    conn.commit()

                log_audit_action(self.current_user, "UPDATE_INVENTORY", f"Updated ID #{item_id}: {u_name} (Qty: {u_qty}, Status: {u_status})")
                messagebox.showinfo("Success", "Hardware item updated successfully!", parent=modal)
                modal.destroy()
                self.load_inventory()
            except sqlite3.IntegrityError:
                messagebox.showerror("Database Error", "Serial number must be unique.", parent=modal)

        tk.Button(modal, text="Update Item", command=save_changes, bg="#2196F3", fg="white", width=20).pack(pady=10)

    def delete_inventory_item(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Selection Required", "Please select an item to delete.")
            return

        item_values = self.tree.item(selected_item[0], "values")
        item_id = item_values[0]
        item_name = item_values[1]

        confirm = messagebox.askyesno(
            "Confirm Deletion", 
            f"Are you sure you want to permanently delete:\n'{item_name}' (ID #{item_id})?"
        )
        if confirm:
            with closing(get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM inventory WHERE id=?", (item_id,))
                conn.commit()

            log_audit_action(self.current_user, "DELETE_INVENTORY", f"Deleted Item ID #{item_id}: {item_name}")
            messagebox.showinfo("Deleted", "Hardware item removed from inventory.")
            self.load_inventory()


# =========================================================
# Borrow & Return Management Tab View
# =========================================================

class BorrowReturnTab(tk.Frame):
    def __init__(self, parent, current_user: str, role: str, on_inventory_updated=None):
        super().__init__(parent)
        self.current_user = current_user
        self.user_role = role
        self.on_inventory_updated = on_inventory_updated

        self.setup_ui()
        self.load_borrow_requests()

    def setup_ui(self):
        control_frame = tk.Frame(self)
        control_frame.pack(fill="x", padx=10, pady=10)

        tk.Label(control_frame, text="Borrow & Return Management", font=("Arial", 14, "bold")).pack(side="left")

        # Admin approvals
        if str(self.user_role).upper() in ["ADMIN", "INVENTORY_SPECIALIST"]:
            tk.Button(
                control_frame, 
                text="Reject Request", 
                command=self.reject_request, 
                bg="#f44336", 
                fg="white", 
                font=("Arial", 9, "bold")
            ).pack(side="right", padx=5)

            tk.Button(
                control_frame, 
                text="Approve Request", 
                command=self.approve_request, 
                bg="#4CAF50", 
                fg="white", 
                font=("Arial", 9, "bold")
            ).pack(side="right", padx=5)

        # Non-admin / general return submission
        tk.Button(
            control_frame, 
            text="Request Return", 
            command=self.submit_return_request, 
            bg="#2196F3", 
            fg="white", 
            font=("Arial", 9, "bold")
        ).pack(side="right", padx=5)

        tk.Button(
            control_frame, 
            text="Refresh Requests", 
            command=self.load_borrow_requests, 
            bg="#607D8B", 
            fg="white"
        ).pack(side="right", padx=5)

        columns = ("Req ID", "Item ID", "Item Name", "Requested By", "Qty", "Status", "Requested At", "Processed At")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=15)

        column_widths = {
            "Req ID": 50, "Item ID": 50, "Item Name": 140, "Requested By": 110,
            "Qty": 40, "Status": 120, "Requested At": 130, "Processed At": 130
        }

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=column_widths.get(col, 100), anchor="center")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=5)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=5)

    def load_borrow_requests(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        try:
            with closing(get_connection()) as conn:
                cursor = conn.cursor()
                if str(self.user_role).upper() in ["ADMIN", "INVENTORY_SPECIALIST"]:
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
                    """, (self.current_user,))

                rows = cursor.fetchall()
                for row in rows:
                    formatted_row = list(row)
                    formatted_row[7] = row[7] if row[7] else "Pending"
                    self.tree.insert("", "end", values=formatted_row)
        except Exception as e:
            print(f"Error loading borrow requests: {e}")

    def submit_return_request(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Selection Required", "Please select a request record to return.")
            return

        item_values = self.tree.item(selected_item[0], "values")
        req_id, _, item_name, requested_by, _, status, _, _ = item_values

        if requested_by != self.current_user and str(self.user_role).upper() not in ["ADMIN", "INVENTORY_SPECIALIST"]:
            messagebox.showerror("Permission Denied", "You can only request returns for items you borrowed.")
            return

        if status != "BORROWED":
            messagebox.showwarning("Action Unavailable", f"Cannot return item with status '{status}'. Only 'BORROWED' items can be returned.")
            return

        confirm = messagebox.askyesno("Confirm Return", f"Submit a return request for '{item_name}' (Request #{req_id})?")
        if confirm:
            with closing(get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE borrow_requests SET status='RETURN_PENDING' WHERE id=?", (req_id,))
                conn.commit()

            log_audit_action(self.current_user, "SUBMIT_RETURN_REQUEST", f"Requested return for Request #{req_id} ({item_name})")
            messagebox.showinfo("Success", "Return request submitted for Admin review!")
            self.load_borrow_requests()

    def approve_request(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Selection Required", "Please select a request to approve.")
            return

        item_values = self.tree.item(selected_item[0], "values")
        req_id, item_id, item_name, requested_by, qty, status, _, _ = item_values
        qty = int(qty)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with closing(get_connection()) as conn:
            cursor = conn.cursor()

            if status == "PENDING_BORROW":
                cursor.execute("SELECT quantity FROM inventory WHERE id=?", (item_id,))
                row = cursor.fetchone()

                if not row or row[0] < qty:
                    messagebox.showerror("Approval Failed", f"Insufficient inventory stock available to fulfill request.")
                    return

                cursor.execute("UPDATE inventory SET quantity = quantity - ? WHERE id=?", (qty, item_id))
                cursor.execute("UPDATE borrow_requests SET status='BORROWED', processed_at=? WHERE id=?", (now, req_id))
                conn.commit()

                log_audit_action(self.current_user, "APPROVE_BORROW", f"Approved borrow request #{req_id} ({qty}x {item_name}) for {requested_by}")
                messagebox.showinfo("Success", f"Borrow request #{req_id} approved!")

            elif status == "RETURN_PENDING":
                cursor.execute("UPDATE inventory SET quantity = quantity + ? WHERE id=?", (qty, item_id))
                cursor.execute("UPDATE borrow_requests SET status='RETURNED', processed_at=? WHERE id=?", (now, req_id))
                conn.commit()

                log_audit_action(self.current_user, "APPROVE_RETURN", f"Approved return request #{req_id} ({qty}x {item_name}) from {requested_by}")
                messagebox.showinfo("Success", f"Return request #{req_id} approved! Inventory updated.")

            else:
                messagebox.showwarning("Action Unavailable", f"Cannot approve request with status '{status}'.")
                return

        self.load_borrow_requests()
        if self.on_inventory_updated:
            self.on_inventory_updated()

    def reject_request(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Selection Required", "Please select a request to reject.")
            return

        item_values = self.tree.item(selected_item[0], "values")
        req_id, _, item_name, requested_by, _, status, _, _ = item_values

        if status not in ["PENDING_BORROW", "RETURN_PENDING"]:
            messagebox.showwarning("Action Unavailable", f"Cannot reject request with status '{status}'.")
            return

        new_status = "REJECTED" if status == "PENDING_BORROW" else "BORROWED"

        confirm = messagebox.askyesno("Confirm Rejection", f"Reject request #{req_id} from {requested_by}?")
        if confirm:
            with closing(get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE borrow_requests SET status=? WHERE id=?", (new_status, req_id))
                conn.commit()

            log_audit_action(self.current_user, "REJECT_REQUEST", f"Rejected request #{req_id} ({item_name}) from {requested_by}")
            messagebox.showinfo("Rejected", f"Request #{req_id} rejected.")
            self.load_borrow_requests()


# =========================================================
# Maintenance & Repair Tab View
# =========================================================

class MaintenanceTab(tk.Frame):
    def __init__(self, parent, current_user: str, role: str):
        super().__init__(parent)
        self.current_user = current_user
        self.user_role = role

        self.setup_ui()
        self.load_maintenance_logs()

    def setup_ui(self):
        control_frame = tk.Frame(self)
        control_frame.pack(fill="x", padx=10, pady=10)

        tk.Label(control_frame, text="Maintenance & Repair Log", font=("Arial", 14, "bold")).pack(side="left")

        if str(self.user_role).upper() in ["ADMIN", "INVENTORY_SPECIALIST"]:
            tk.Button(
                control_frame, 
                text="Delete Selected Log", 
                command=self.delete_maintenance_log, 
                bg="#f44336", 
                fg="white", 
                font=("Arial", 9, "bold")
            ).pack(side="right", padx=5)

            tk.Button(
                control_frame, 
                text="+ Log New Repair", 
                command=self.open_add_log_modal, 
                bg="#4CAF50", 
                fg="white", 
                font=("Arial", 9, "bold")
            ).pack(side="right", padx=5)

            tk.Button(
                control_frame, 
                text="Update Selected Status", 
                command=self.open_update_status_modal, 
                bg="#2196F3", 
                fg="white"
            ).pack(side="right", padx=5)

        filter_frame = tk.Frame(self)
        filter_frame.pack(fill="x", padx=10, pady=(0, 10))

        tk.Label(filter_frame, text="Filter Status:").pack(side="left", padx=(0, 5))
        self.status_filter_var = tk.StringVar(value="ALL")
        status_dropdown = ttk.Combobox(
            filter_frame, 
            textvariable=self.status_filter_var, 
            values=["ALL", "PENDING", "IN_PROGRESS", "COMPLETED", "UNREPAIRABLE"], 
            state="readonly", 
            width=15
        )
        status_dropdown.pack(side="left", padx=5)
        status_dropdown.bind("<<ComboboxSelected>>", lambda e: self.load_maintenance_logs())

        columns = ("ID", "Item", "Serial No.", "Vendor", "Cost ($)", "Status", "Logged By", "Logged Date", "Resolved Date")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=15)

        column_widths = {
            "ID": 40, "Item": 120, "Serial No.": 100, "Vendor": 110, 
            "Cost ($)": 80, "Status": 100, "Logged By": 90, 
            "Logged Date": 120, "Resolved Date": 120
        }

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=column_widths.get(col, 100), anchor="center")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=5)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=5)

    def load_maintenance_logs(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        selected_status = self.status_filter_var.get()

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
                    self.tree.insert("", "end", values=formatted_row)
        except Exception as e:
            print(f"Error loading maintenance logs: {e}")

    def open_add_log_modal(self):
        modal = tk.Toplevel(self)
        modal.title("Log Hardware Maintenance")
        modal.geometry("380x420")
        modal.grab_set()

        tk.Label(modal, text="New Repair Record", font=("Arial", 11, "bold")).pack(pady=10)

        fields = {}
        labels = [
            ("Item Name:", "item_name"),
            ("Serial Number:", "serial_number"),
            ("Repair Vendor / Technician:", "vendor"),
            ("Estimated/Actual Cost ($):", "repair_cost"),
        ]

        for label_text, key in labels:
            tk.Label(modal, text=label_text).pack(anchor="w", padx=30)
            entry = tk.Entry(modal, width=35)
            entry.pack(padx=30, pady=(0, 8))
            fields[key] = entry

        tk.Label(modal, text="Issue Description:").pack(anchor="w", padx=30)
        desc_text = tk.Text(modal, width=35, height=4)
        desc_text.pack(padx=30, pady=(0, 10))

        def save_log():
            item = fields["item_name"].get().strip()
            serial = fields["serial_number"].get().strip()
            vendor = fields["vendor"].get().strip()
            cost_str = fields["repair_cost"].get().strip()
            description = desc_text.get("1.0", tk.END).strip()

            if not item or not serial or not vendor or not description:
                messagebox.showerror("Validation Error", "All fields except cost are required.", parent=modal)
                return

            try:
                cost = float(cost_str) if cost_str else 0.0
            except ValueError:
                messagebox.showerror("Validation Error", "Cost must be a valid number.", parent=modal)
                return

            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            with closing(get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO maintenance_logs (item_name, serial_number, vendor, issue_description, repair_cost, status, logged_by, logged_at)
                    VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)
                """, (item, serial, vendor, description, cost, self.current_user, now))
                conn.commit()

            log_audit_action(self.current_user, "LOG_MAINTENANCE", f"Logged repair for: {item} (Vendor: {vendor})")
            messagebox.showinfo("Success", "Maintenance log recorded!", parent=modal)
            modal.destroy()
            self.load_maintenance_logs()

        tk.Button(modal, text="Save Log Entry", command=save_log, bg="#4CAF50", fg="white", width=20).pack(pady=10)

    def open_update_status_modal(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Selection Required", "Please select a maintenance log entry to update.")
            return

        item_values = self.tree.item(selected_item[0], "values")
        log_id = item_values[0]

        modal = tk.Toplevel(self)
        modal.title("Update Repair Status")
        modal.geometry("300x200")
        modal.grab_set()

        tk.Label(modal, text=f"Update Status (ID #{log_id})", font=("Arial", 11, "bold")).pack(pady=10)

        status_var = tk.StringVar(value=item_values[5])
        status_dropdown = ttk.Combobox(
            modal, 
            textvariable=status_var, 
            values=["PENDING", "IN_PROGRESS", "COMPLETED", "UNREPAIRABLE"], 
            state="readonly", 
            width=20
        )
        status_dropdown.pack(pady=15)

        def save_status():
            new_status = status_var.get()
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

            log_audit_action(self.current_user, "UPDATE_MAINTENANCE_STATUS", f"Updated Log #{log_id} status to {new_status}")
            messagebox.showinfo("Success", "Status updated successfully!", parent=modal)
            modal.destroy()
            self.load_maintenance_logs()

        tk.Button(modal, text="Update Record", command=save_status, bg="#2196F3", fg="white").pack(pady=10)

    def delete_maintenance_log(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Selection Required", "Please select a log entry to delete.")
            return

        item_values = self.tree.item(selected_item[0], "values")
        log_id = item_values[0]
        item_name = item_values[1]

        confirm = messagebox.askyesno(
            "Confirm Deletion", 
            f"Are you sure you want to delete repair log:\n'{item_name}' (Log ID #{log_id})?"
        )
        if confirm:
            with closing(get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM maintenance_logs WHERE id=?", (log_id,))
                conn.commit()

            log_audit_action(self.current_user, "DELETE_MAINTENANCE_LOG", f"Deleted Repair Log ID #{log_id}")
            messagebox.showinfo("Deleted", "Log entry removed.")
            self.load_maintenance_logs()


# =========================================================
# Account Lockout Approval Tab View (ADMIN EXCLUSIVE)
# =========================================================

class LockoutApprovalTab(tk.Frame):
    def __init__(self, parent, current_user: str):
        super().__init__(parent)
        self.current_user = current_user
        self.setup_ui()
        self.load_locked_accounts()

    def setup_ui(self):
        header_frame = tk.Frame(self)
        header_frame.pack(fill="x", padx=10, pady=10)

        tk.Label(header_frame, text="Account Lockout Approvals & Management", font=("Arial", 14, "bold")).pack(side="left")
        
        tk.Button(
            header_frame, 
            text="Unlock Selected Account", 
            command=self.unlock_selected_account, 
            bg="#4CAF50", 
            fg="white", 
            font=("Arial", 9, "bold")
        ).pack(side="right", padx=5)

        tk.Button(
            header_frame, 
            text="Refresh List", 
            command=self.load_locked_accounts, 
            bg="#2196F3", 
            fg="white"
        ).pack(side="right", padx=5)

        columns = ("ID", "Username", "Email", "Role", "Failed Attempts", "Lockout Status")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=15)

        column_widths = {"ID": 50, "Username": 150, "Email": 200, "Role": 130, "Failed Attempts": 120, "Lockout Status": 120}

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=column_widths.get(col, 100), anchor="center")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=5)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=5)

    def load_locked_accounts(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        try:
            with closing(get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, username, email, role, failed_attempts, is_locked FROM users WHERE username != ? AND is_locked = 1 ORDER BY username ASC",
                    (self.current_user,)
                )
                rows = cursor.fetchall()
                for row in rows:
                    u_id, username, email, role, failed_attempts, is_locked = row
                    status = "LOCKED" if is_locked else "ACTIVE"
                    self.tree.insert("", "end", values=(u_id, username, email, role, failed_attempts, status))
        except Exception as e:
            print(f"Error loading locked users: {e}")

    def unlock_selected_account(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Selection Required", "Please select a user account to unlock.")
            return

        item_values = self.tree.item(selected_item[0], "values")
        user_id = item_values[0]
        username = item_values[1]

        confirm = messagebox.askyesno("Confirm Unlock", f"Are you sure you want to approve and unlock the account for user:\n'{username}'?")
        if confirm:
            with closing(get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET is_locked=0, failed_attempts=0 WHERE id=?", (user_id,))
                conn.commit()

            log_audit_action(self.current_user, "UNLOCK_ACCOUNT", f"Approved lockout release for user: {username}")
            messagebox.showinfo("Success", f"Account '{username}' has been successfully unlocked.")
            self.load_locked_accounts()


# =========================================================
# Audit Trail Tab View (ADMIN EXCLUSIVE)
# =========================================================

class AuditLogTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setup_ui()
        self.load_audit_logs()

    def setup_ui(self):
        header_frame = tk.Frame(self)
        header_frame.pack(fill="x", padx=10, pady=10)

        tk.Label(header_frame, text="System Audit Log (Admin Exclusive)", font=("Arial", 14, "bold")).pack(side="left")
        tk.Button(header_frame, text="Refresh Trail", command=self.load_audit_logs, bg="#2196F3", fg="white").pack(side="right")

        columns = ("ID", "Timestamp", "Performed By", "Action", "Details")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=15)

        column_widths = {"ID": 50, "Timestamp": 140, "Performed By": 120, "Action": 160, "Details": 380}

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=column_widths.get(col, 100), anchor="w" if col == "Details" else "center")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=5)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=5)

    def load_audit_logs(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        try:
            with closing(get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, timestamp, performed_by, action, details FROM audit_logs ORDER BY id DESC")
                rows = cursor.fetchall()
                for row in rows:
                    self.tree.insert("", "end", values=row)
        except Exception as e:
            print(f"Error loading audit logs: {e}")


# =========================================================
# User Profile Settings Tab View
# =========================================================

class ProfileSettingsTab(tk.Frame):
    def __init__(self, parent, user_data: dict):
        super().__init__(parent)
        self.user_data = user_data
        self.setup_ui()

    def setup_ui(self):
        tk.Label(self, text="User Profile & Security Settings", font=("Arial", 14, "bold")).pack(anchor="w", padx=20, pady=15)

        info_frame = tk.LabelFrame(self, text="Account Details", font=("Arial", 10, "bold"), padx=15, pady=15)
        info_frame.pack(fill="x", padx=20, pady=10)

        tk.Label(info_frame, text=f"Username: {self.user_data.get('username', 'N/A')}", font=("Arial", 11)).pack(anchor="w", pady=3)
        tk.Label(info_frame, text=f"Email Address: {self.user_data.get('email', 'N/A')}", font=("Arial", 11)).pack(anchor="w", pady=3)
        tk.Label(info_frame, text=f"Role: {self.user_data.get('role', 'N/A')}", font=("Arial", 11)).pack(anchor="w", pady=3)

        pass_frame = tk.LabelFrame(self, text="Change Password", font=("Arial", 10, "bold"), padx=15, pady=15)
        pass_frame.pack(fill="x", padx=20, pady=10)

        tk.Label(pass_frame, text="Current Password:").pack(anchor="w")
        self.old_pass_entry = tk.Entry(pass_frame, show="*", width=35)
        self.old_pass_entry.pack(anchor="w", pady=(0, 10))

        tk.Label(pass_frame, text="New Password:").pack(anchor="w")
        self.new_pass_entry = tk.Entry(pass_frame, show="*", width=35)
        self.new_pass_entry.pack(anchor="w", pady=(0, 10))

        tk.Label(pass_frame, text="Confirm New Password:").pack(anchor="w")
        self.confirm_pass_entry = tk.Entry(pass_frame, show="*", width=35)
        self.confirm_pass_entry.pack(anchor="w", pady=(0, 15))

        tk.Button(
            pass_frame, 
            text="Update Password", 
            command=self.update_password, 
            bg="#2196F3", 
            fg="white", 
            font=("Arial", 9, "bold")
        ).pack(anchor="w")

    def update_password(self):
        old_p = self.old_pass_entry.get().strip()
        new_p = self.new_pass_entry.get().strip()
        conf_p = self.confirm_pass_entry.get().strip()

        if not old_p or not new_p or not conf_p:
            messagebox.showerror("Error", "All password fields are required.")
            return

        if new_p != conf_p:
            messagebox.showerror("Error", "New password and confirmation do not match.")
            return

        if len(new_p) < 6:
            messagebox.showerror("Error", "Password must be at least 6 characters long.")
            return

        username = self.user_data.get("username", "")

        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT password_hash, salt FROM users WHERE username=?", (username,))
            row = cursor.fetchone()

            if not row:
                messagebox.showerror("Error", "User record not found.")
                return

            stored_hash, salt = row
            calc_hash, _ = hash_password(old_p, salt)

            if calc_hash != stored_hash:
                messagebox.showerror("Error", "Incorrect current password.")
                return

            new_hash, new_salt = hash_password(new_p)
            cursor.execute("UPDATE users SET password_hash=?, salt=? WHERE username=?", (new_hash, new_salt, username))
            conn.commit()

        log_audit_action(username, "CHANGE_PASSWORD", "User changed account password")
        messagebox.showinfo("Success", "Password updated successfully!")
        
        self.old_pass_entry.delete(0, tk.END)
        self.new_pass_entry.delete(0, tk.END)
        self.confirm_pass_entry.delete(0, tk.END)


# =========================================================
# Main Application Framework
# =========================================================

class CampusHardwareApp:
    def __init__(self, root, user_data, logout_callback):
        self.root = root
        self.user_data = user_data or {}
        self.logout_callback = logout_callback

        init_db()

        username = self.user_data.get("username", "Guest")
        role = str(self.user_data.get("role", "USER")).upper()

        self.root.title(f"Campus Hardware System - Logged in as: {username} ({role})")
        self.root.geometry("1020x680")

        # Top Bar
        top_bar = tk.Frame(self.root, bg="#eceff1", height=40)
        top_bar.pack(fill="x", side="top")

        tk.Label(
            top_bar, 
            text=f"User: {username} | Role: {role}", 
            bg="#eceff1", 
            font=("Arial", 10, "bold")
        ).pack(side="left", padx=15, pady=8)

        tk.Button(
            top_bar, 
            text="Logout", 
            command=self.handle_logout, 
            bg="#f44336", 
            fg="white", 
            font=("Arial", 9, "bold")
        ).pack(side="right", padx=15, pady=5)

        # Tabbed Notebook Layout
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)

        # Tab 1: Hardware Inventory
        self.inventory_tab = InventoryTab(
            parent=self.notebook,
            current_user=username,
            role=role,
            on_inventory_changed=lambda: self.borrow_tab.load_borrow_requests()
        )
        self.notebook.add(self.inventory_tab, text="Hardware Inventory")

        # Tab 2: Borrow & Return Management
        self.borrow_tab = BorrowReturnTab(
            parent=self.notebook,
            current_user=username,
            role=role,
            on_inventory_updated=lambda: self.inventory_tab.load_inventory()
        )
        self.notebook.add(self.borrow_tab, text="Borrow & Return")

        # Tab 3: Maintenance & Repairs
        self.maintenance_tab = MaintenanceTab(
            parent=self.notebook,
            current_user=username,
            role=role
        )
        self.notebook.add(self.maintenance_tab, text="Maintenance & Repairs")

        # Tab 4: Lockout Approval Tab (ADMIN ONLY)
        if role == "ADMIN":
            try:
                self.lockout_tab = LockoutApprovalTab(parent=self.notebook, current_user=username)
                self.notebook.add(self.lockout_tab, text="Lockout Approvals")
            except Exception as e:
                print(f"Error initializing Lockout Approvals tab: {e}")

        # Tab 5: System Audit Trail (ADMIN ONLY)
        if role == "ADMIN":
            try:
                self.audit_tab = AuditLogTab(parent=self.notebook)
                self.notebook.add(self.audit_tab, text="Audit Trail")
            except Exception as e:
                print(f"Error initializing Audit Trail tab: {e}")

        # Tab 6: Profile Settings
        self.profile_tab = ProfileSettingsTab(parent=self.notebook, user_data=self.user_data)
        self.notebook.add(self.profile_tab, text="Profile Settings")

        # Tab 7: System Exports
        self.export_tab = tk.Frame(self.notebook)
        self.notebook.add(self.export_tab, text="System Exports")
        self.setup_export_ui()

    def handle_logout(self):
        confirm = messagebox.askyesno("Logout", "Are you sure you want to log out?")
        if confirm:
            log_audit_action(self.user_data.get("username", "Guest"), "LOGOUT", "User logged out of application")
            self.logout_callback()

    def setup_export_ui(self):
        tk.Label(self.export_tab, text="System Data Export Utilities", font=("Arial", 12, "bold")).pack(pady=20)
        
        tk.Button(
            self.export_tab, 
            text="Export Users List to CSV", 
            command=self.export_users_to_csv,
            bg="#2196F3", 
            fg="white", 
            width=30
        ).pack(pady=10)

        tk.Button(
            self.export_tab, 
            text="Export Inventory List to CSV", 
            command=self.export_inventory_to_csv,
            bg="#4CAF50", 
            fg="white", 
            width=30
        ).pack(pady=10)

        if str(self.user_data.get("role", "")).upper() == "ADMIN":
            tk.Button(
                self.export_tab, 
                text="Export Audit Logs to CSV", 
                command=self.export_audit_logs_to_csv,
                bg="#9C27B0", 
                fg="white", 
                width=30
            ).pack(pady=10)

    def export_users_to_csv(self):
        self.export_table_to_csv("SELECT id, username, email, role, is_locked FROM users", "registered_users.csv")

    def export_inventory_to_csv(self):
        self.export_table_to_csv("SELECT id, item_name, category, serial_number, quantity, location, status, added_by, added_at FROM inventory", "hardware_inventory.csv")

    def export_audit_logs_to_csv(self):
        self.export_table_to_csv("SELECT id, timestamp, performed_by, action, details FROM audit_logs", "audit_logs.csv")

    def export_table_to_csv(self, query: str, default_filename: str):
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        file_path = filedialog.asksaveasfilename(
            initialdir=desktop_path,
            initialfile=default_filename,
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            title="Save CSV Export"
        )
        if not file_path:
            return

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

            messagebox.showinfo("Export Successful", f"Data exported successfully to:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"An error occurred while saving the file:\n{str(e)}")


def main():
    root = tk.Tk()

    def launch_main_app(user_data):
        root.destroy()
        
        app_root = tk.Tk()
        
        app = CampusHardwareApp(
            app_root, 
            user_data, 
            logout_callback=lambda: relaunch_login(app_root)
        )
        app_root.mainloop()

    def relaunch_login(current_app_root):
        current_app_root.destroy()
        main()

    LoginWindow(root, on_login_success=launch_main_app)
    root.mainloop()


if __name__ == "__main__":
    main()