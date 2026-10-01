import psycopg
import datetime
from contextlib import closing
from pydantic import ValidationError
from db_models import (
    get_connection,
    hash_password,
    UserRegisterSchema,
    ResetRequestSchema,
)

class AuthController:
    """Core controller for handling authentication, user registration, 
    and password reset requests without UI framework dependencies."""

    def login_user(self, username: str, password_raw: str):
        if not username or not password_raw:
            return False, "Username and password cannot be empty.", None, False

        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT username, role, password_hash, salt, failed_attempts, is_locked, hint FROM users WHERE username=%s",
                (username,)
            )
            user = cursor.fetchone()

            if not user:
                # Perform dummy hash computation to neutralize timing attacks
                hash_password("dummy_password", "dummy_salt_32bytes_minimum_len_string")
                return False, "Invalid username or password.", None, False

            uname, role, stored_hash, salt, failed_attempts, is_locked, hint = user

            if is_locked:
                return False, "Account is locked due to too many failed attempts.", None, True

            calc_hash, _ = hash_password(password_raw, salt)
            if calc_hash == stored_hash:
                cursor.execute("UPDATE users SET failed_attempts=0 WHERE username=%s", (username,))
                conn.commit()
                return True, "Login successful!", {"username": uname, "role": role}, False
            else:
                new_attempts = failed_attempts + 1
                hint_msg = f"\nPassword Hint: {hint}" if hint and new_attempts >= 1 else ""

                if new_attempts >= 3:
                    cursor.execute("UPDATE users SET failed_attempts=%s, is_locked=1 WHERE username=%s", (new_attempts, username))
                    conn.commit()
                    return False, f"Account locked! Exceeded maximum login attempts.{hint_msg}", None, True
                else:
                    cursor.execute("UPDATE users SET failed_attempts=%s WHERE username=%s", (new_attempts, username))
                    conn.commit()
                    return False, f"Invalid password. Attempts remaining: {3 - new_attempts}{hint_msg}", None, False

    def register_user(self, username: str, email: str, password_raw: str, hint: str, role: str):
        try:
            validated_data = UserRegisterSchema(
                username=username,
                email=email,
                password=password_raw,
                role=role
            )
        except ValidationError as e:
            error_msg = e.errors()[0]['msg']
            return False, error_msg

        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM users WHERE LOWER(username) = LOWER(%s)", (validated_data.username,))
            if cursor.fetchone():
                return False, "Username is already taken. Please choose another."

            cursor.execute("SELECT email FROM users WHERE LOWER(email) = LOWER(%s)", (validated_data.email,))
            if cursor.fetchone():
                return False, "An account with this email address already exists."

            p_hash, salt = hash_password(validated_data.password)
            try:
                cursor.execute(
                    "INSERT INTO users (username, email, password_hash, salt, hint, role) VALUES (%s, %s, %s, %s, %s, %s)",
                    (validated_data.username, validated_data.email, p_hash, salt, hint, validated_data.role)
                )
                conn.commit()
                return True, "User registered successfully!"
            except psycopg.IntegrityError:
                return False, "Registration error: Account details violate system constraints."

    def request_password_reset(self, username: str, email: str, proposed_pass: str, reason: str):
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

        p_hash, salt = hash_password(validated_data.proposed_password)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO reset_requests (username, email, proposed_password, reason, requested_at) VALUES (%s, %s, %s, %s, %s)",
                (validated_data.username, validated_data.email, p_hash, validated_data.reason, now)
            )
            conn.commit()
        return True, "Unlock/Reset request submitted to system admin."
