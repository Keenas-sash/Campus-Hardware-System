import sqlite3
import hashlib
import os
import re
from typing import Optional
from contextlib import closing
from pydantic import BaseModel, Field, field_validator
import psycopg
from psycopg.rows import dict_row

# =========================================================
# Database Connection & Initialization
# =========================================================

def get_connection():
    return psycopg.connect(os.getenv("DATABASE_URL"))

def hash_password(password: str, salt: Optional[str] = None):
    if not salt:
        salt = os.urandom(16).hex()
    calc_hash = hashlib.sha256((password + salt).encode('utf-8')).hexdigest()
    return calc_hash, salt

def init_db():
    """Initializes users, reset_requests, inventory, maintenance_logs, borrow_logs, and audit_logs tables."""
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                hint TEXT,
                role TEXT NOT NULL DEFAULT 'VIEWER',
                failed_attempts INTEGER DEFAULT 0,
                is_locked INTEGER DEFAULT 0
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reset_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                email TEXT NOT NULL,
                proposed_password TEXT NOT NULL,
                reason TEXT,
                requested_at TEXT NOT NULL
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                category TEXT NOT NULL,
                serial_number TEXT UNIQUE NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                min_stock INTEGER NOT NULL DEFAULT 1,
                max_stock INTEGER NOT NULL DEFAULT 10,
                location TEXT NOT NULL,
                status TEXT DEFAULT 'AVAILABLE',
                added_by TEXT NOT NULL,
                added_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS maintenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                serial_number TEXT NOT NULL,
                vendor TEXT NOT NULL,
                issue_description TEXT NOT NULL,
                repair_cost REAL NOT NULL DEFAULT 0.0,
                status TEXT CHECK(status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'UNREPAIRABLE')) DEFAULT 'PENDING',
                logged_by TEXT NOT NULL,
                logged_at TEXT NOT NULL,
                resolved_at TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS borrow_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                serial_number TEXT NOT NULL,
                borrower_name TEXT NOT NULL,
                borrower_contact TEXT NOT NULL,
                quantity_borrowed INTEGER NOT NULL DEFAULT 1,
                borrow_date TEXT NOT NULL,
                expected_return_date TEXT NOT NULL,
                actual_return_date TEXT,
                status TEXT CHECK(status IN ('PENDING', 'BORROWED', 'RETURNED', 'OVERDUE')) DEFAULT 'BORROWED',
                issued_by TEXT,
                FOREIGN KEY (item_id) REFERENCES inventory (id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                performed_by TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL
            )
        """)
        conn.commit()

init_db()


# =========================================================
# Validation Schemas
# =========================================================

def validate_strict_email(v: str) -> str:
    v = v.lower().strip()
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.([a-zA-Z]{2,10})$"
    if not re.match(pattern, v):
        raise ValueError("Invalid email format. Must follow name@domain.com format.")

    domain = v.split("@")[-1]
    typo_domains = ["gmail.co", "yahoo.co", "hotmail.co", "outlook.co", "icloud.co"]
    if domain in typo_domains:
        raise ValueError(f"Invalid email domain '{domain}'. Did you mean '{domain}m'?")
        
    return v


class UserRegisterSchema(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)
    email: str = Field(..., min_length=6, max_length=50)
    password: str = Field(..., min_length=8)
    role: str = Field(default="VIEWER")

    @field_validator("username")
    def username_alphanumeric(cls, v):
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("Username must contain only letters, numbers, and underscores.")
        return v

    @field_validator("email")
    def email_validation(cls, v):
        return validate_strict_email(v)

    @field_validator("password")
    def password_validation(cls, x):
        pattern = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&_#])[A-Za-z\d@$!%*?&_#]{8,20}$"
        if not re.match(pattern, x):
            raise ValueError("Password must contain 8-20 characters, 1 uppercase, 1 lowercase, 1 number, and 1 special character.")
        return x

    @field_validator("role")
    def role_validation(cls, r):
        valid_roles = ["ADMIN", "INVENTORY_SPECIALIST", "VIEWER"]
        if r.upper() not in valid_roles:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")
        return r.upper()


class ResetRequestSchema(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)
    email: str = Field(..., min_length=6, max_length=50)
    proposed_password: str = Field(..., min_length=8)
    reason: Optional[str] = Field(default="", max_length=255)

    @field_validator("email")
    def email_validation(cls, v):
        return validate_strict_email(v)

    @field_validator("proposed_password")
    def password_validation(cls, x):
        pattern = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&_#])[A-Za-z\d@$!%*?&_#]{8,20}$"
        if not re.match(pattern, x):
            raise ValueError("New password must contain 8-20 characters, 1 uppercase, 1 lowercase, 1 number, and 1 special character.")
        return x


class BorrowRequestSchema(BaseModel):
    item_id: int = Field(..., gt=0)
    borrower_name: str = Field(..., min_length=2, max_length=50)
    borrower_contact: str = Field(..., min_length=5, max_length=50)
    quantity_borrowed: int = Field(default=1, gt=0)
    expected_return_date: str = Field(...)
