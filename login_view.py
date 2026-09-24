import sys
import os
import sqlite3
import datetime
import tkinter as tk
from tkinter import messagebox
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_models import (
    get_connection, 
    hash_password, 
    UserRegisterSchema, 
    ResetRequestSchema
)

class AuthController:
    def login_user(self, username, password):
        if not username or not password:
            return False, "Username and password cannot be empty.", None, False

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT username, role, password_hash, salt, failed_attempts, is_locked, hint FROM users WHERE username=?",
                (username,)
            )
            user = cursor.fetchone()

            if not user:
                return False, "Invalid username or password.", None, False

            uname, role, stored_hash, salt, failed_attempts, is_locked, hint = user

            if is_locked:
                return False, "Account is locked due to too many failed attempts.", None, True

            calc_hash, _ = hash_password(password, salt)
            if calc_hash == stored_hash:
                cursor.execute("UPDATE users SET failed_attempts=0 WHERE username=?", (username,))
                conn.commit()
                return True, "Login successful!", {"username": uname, "role": role}, False
            else:
                new_attempts = failed_attempts + 1
                hint_msg = f"\nPassword Hint: {hint}" if hint and new_attempts >= 1 else ""
                
                if new_attempts >= 3:
                    cursor.execute("UPDATE users SET failed_attempts=?, is_locked=1 WHERE username=?", (new_attempts, username))
                    conn.commit()
                    return False, f"Account locked! Exceeded maximum login attempts.{hint_msg}", None, True
                else:
                    cursor.execute("UPDATE users SET failed_attempts=? WHERE username=?", (new_attempts, username))
                    conn.commit()
                    return False, f"Invalid password. Attempts remaining: {3 - new_attempts}{hint_msg}", None, False

    def register_user(self, username, email, password, hint, role):
        try:
            validated_data = UserRegisterSchema(
                username=username,
                email=email,
                password=password,
                role=role
            )
        except ValidationError as e:
            error_msg = e.errors()[0]['msg']
            return False, error_msg

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM users WHERE LOWER(username) = LOWER(?)", (validated_data.username,))
            if cursor.fetchone():
                return False, "Username is already taken. Please choose another."

            cursor.execute("SELECT email FROM users WHERE LOWER(email) = LOWER(?)", (validated_data.email,))
            if cursor.fetchone():
                return False, "An account with this email address already exists."

            p_hash, salt = hash_password(validated_data.password)
            try:
                cursor.execute(
                    "INSERT INTO users (username, email, password_hash, salt, hint, role) VALUES (?, ?, ?, ?, ?, ?)",
                    (validated_data.username, validated_data.email, p_hash, salt, hint, validated_data.role)
                )
                conn.commit()
                return True, "User registered successfully!"
            except sqlite3.IntegrityError:
                return False, "Registration error: Account details violate system constraints."

    def request_password_reset(self, username, email, proposed_pass, reason):
        try:
            validated_data = ResetRequestSchema(
                username=username,
                email=email,
                proposed_password=proposed_pass,
                reason=reason
            )
        except ValidationError as e:
            error_msg = e.errors()[0]['msg']
            return False, error_msg

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO reset_requests (username, email, proposed_password, reason, requested_at) VALUES (?, ?, ?, ?, ?)",
                (validated_data.username, validated_data.email, validated_data.proposed_password, validated_data.reason, now)
            )
            conn.commit()
        return True, "Unlock/Reset request submitted to system admin."


class LoginWindow:
    def __init__(self, root, on_login_success):
        self.root = root
        self.on_login_success = on_login_success
        self.auth = AuthController()

        self.root.title("Campus Hardware System - Login")
        self.root.geometry("400x420")
        self.root.resizable(False, False)

        tk.Label(root, text="Campus Hardware System", font=("Arial", 14, "bold")).pack(pady=15)

        tk.Label(root, text="Username:").pack(anchor="w", padx=40)
        self.entry_user = tk.Entry(root, width=34)
        self.apply_length_limit(self.entry_user, max_len=20)
        self.entry_user.pack(padx=40, pady=(0, 10))

        tk.Label(root, text="Password:").pack(anchor="w", padx=40)
        self.entry_pass = tk.Entry(root, show="*", width=34)
        self.apply_length_limit(self.entry_pass, max_len=20)
        self.entry_pass.pack(padx=40, pady=(0, 2))

        self.show_pass_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            root,
            text="Show Password",
            variable=self.show_pass_var,
            command=self.toggle_password_visibility,
        ).pack(anchor="w", padx=40, pady=(0, 10))

        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=10)

        tk.Button(
            btn_frame, text="Login", command=self.handle_login, bg="#4CAF50", fg="white", width=12
        ).pack(side="left", padx=5)
        tk.Button(
            btn_frame, text="Register", command=self.open_register_modal, bg="#2196F3", fg="white", width=12
        ).pack(side="right", padx=5)

        tk.Button(
            root,
            text="Forgot / Unlock Password",
            command=self.open_reset_modal,
            fg="#D32F2F",
            relief="flat",
        ).pack(pady=10)

    def apply_length_limit(self, entry_widget: tk.Entry, max_len: int):
        def limit_callback(P):
            return len(P) <= max_len

        vcmd = (entry_widget.register(limit_callback), '%P')
        entry_widget.config(validate="key", validatecommand=vcmd)

    def toggle_password_visibility(self):
        show_char = "" if self.show_pass_var.get() else "*"
        self.entry_pass.config(show=show_char)

    def handle_login(self):
        username = self.entry_user.get().strip()
        password = self.entry_pass.get()

        success, msg, user_data, is_locked = self.auth.login_user(username, password)

        if success:
            messagebox.showinfo("Success", msg)
            self.on_login_success(user_data)
        elif is_locked:
            messagebox.showerror(
                "Account Locked",
                f"{msg}\nPlease use the 'Forgot / Unlock Password' feature to submit an unlock request.",
            )
        else:
            messagebox.showerror("Authentication Failed", msg)

    def open_register_modal(self):
        modal = tk.Toplevel(self.root)
        modal.title("Register New Account")
        modal.geometry("400x530")
        modal.grab_set()

        tk.Label(modal, text="Create Account", font=("Arial", 12, "bold")).pack(pady=10)

        tk.Label(modal, text="Username (Max 20):").pack(anchor="w", padx=40)
        reg_user = tk.Entry(modal, width=34)
        self.apply_length_limit(reg_user, max_len=20)
        reg_user.pack(padx=40, pady=(0, 5))

        tk.Label(modal, text="Email (Max 50):").pack(anchor="w", padx=40)
        reg_email = tk.Entry(modal, width=34)
        self.apply_length_limit(reg_email, max_len=50)
        reg_email.pack(padx=40, pady=(0, 5))

        tk.Label(modal, text="Password (8-20 chars):").pack(anchor="w", padx=40)
        reg_pass = tk.Entry(modal, show="*", width=34)
        self.apply_length_limit(reg_pass, max_len=20)
        reg_pass.pack(padx=40, pady=(0, 2))

        show_reg_pass_var = tk.BooleanVar(value=False)
        def toggle_reg_pass():
            reg_pass.config(show="" if show_reg_pass_var.get() else "*")

        tk.Checkbutton(
            modal, text="Show Password", variable=show_reg_pass_var, command=toggle_reg_pass
        ).pack(anchor="w", padx=40, pady=(0, 5))

        tk.Label(modal, text="Password Remembrance Hint:").pack(anchor="w", padx=40)
        reg_hint = tk.Entry(modal, width=34)
        self.apply_length_limit(reg_hint, max_len=100)
        reg_hint.pack(padx=40, pady=(0, 5))

        tk.Label(modal, text="Role Assignment:").pack(anchor="w", padx=40)
        role_var = tk.StringVar(value="VIEWER")
        role_frame = tk.Frame(modal)
        role_frame.pack(anchor="w", padx=40, pady=(0, 10))
        tk.Radiobutton(role_frame, text="Viewer", variable=role_var, value="VIEWER").pack(side="left")
        tk.Radiobutton(role_frame, text="Inventory Specialist", variable=role_var, value="INVENTORY_SPECIALIST").pack(side="left", padx=5)
        tk.Radiobutton(role_frame, text="Admin", variable=role_var, value="ADMIN").pack(side="left")

        def submit():
            success, msg = self.auth.register_user(
                reg_user.get().strip(),
                reg_email.get().strip(),
                reg_pass.get(),
                reg_hint.get().strip(),
                role_var.get(),
            )
            if success:
                messagebox.showinfo("Success", msg, parent=modal)
                modal.destroy()
            else:
                messagebox.showwarning("Registration Error", msg, parent=modal)

        tk.Button(modal, text="Submit Registration", command=submit, bg="#2196F3", fg="white", width=22).pack(pady=10)

    def open_reset_modal(self):
        modal = tk.Toplevel(self.root)
        modal.title("Account Unlock & Reset Request")
        modal.geometry("380x400")
        modal.grab_set()

        tk.Label(modal, text="Unlock / Reset Password Request", font=("Arial", 12, "bold")).pack(pady=10)

        tk.Label(modal, text="Username:").pack(anchor="w", padx=40)
        rst_user = tk.Entry(modal, width=32)
        self.apply_length_limit(rst_user, max_len=20)
        rst_user.pack(padx=40, pady=(0, 5))

        tk.Label(modal, text="Registered Email:").pack(anchor="w", padx=40)
        rst_email = tk.Entry(modal, width=32)
        self.apply_length_limit(rst_email, max_len=50)
        rst_email.pack(padx=40, pady=(0, 5))

        tk.Label(modal, text="New Proposed Password:").pack(anchor="w", padx=40)
        rst_pass = tk.Entry(modal, show="*", width=32)
        self.apply_length_limit(rst_pass, max_len=20)
        rst_pass.pack(padx=40, pady=(0, 5))

        tk.Label(modal, text="Reason / Details (Max 255):").pack(anchor="w", padx=40)
        rst_reason = tk.Entry(modal, width=32)
        self.apply_length_limit(rst_reason, max_len=255)
        rst_reason.pack(padx=40, pady=(0, 10))

        def submit_reset():
            success, msg = self.auth.request_password_reset(
                rst_user.get().strip(), rst_email.get().strip(), rst_pass.get(), rst_reason.get().strip()
            )
            if success:
                messagebox.showinfo("Request Sent", msg, parent=modal)
                modal.destroy()
            else:
                messagebox.showerror("Error", msg, parent=modal)

        tk.Button(modal, text="Submit Request to Admin", command=submit_reset, bg="#E91E63", fg="white", width=22).pack(pady=10)