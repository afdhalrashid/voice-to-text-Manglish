from flask import (
    Blueprint,
    request,
    jsonify,
    render_template,
    redirect,
    url_for,
    flash,
    current_app,
)
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User
from datetime import datetime
import re

auth_bp = Blueprint("auth", __name__)

# Email validation regex
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def validate_password(password):
    """Validate password strength"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r"\d", password):
        return False, "Password must contain at least one digit"
    return True, "Password is valid"


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Handle user registration"""
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "GET":
        return render_template("register.html")

    # Handle POST request (API)
    if request.is_json:
        data = request.get_json()
        username = data.get("username", "").strip()
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
    else:
        # Handle form submission
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

    # Validation
    if not username or not email or not password:
        error_msg = "All fields are required"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 400
        flash(error_msg, "error")
        return render_template("register.html")

    if len(username) < 3 or len(username) > 80:
        error_msg = "Username must be between 3 and 80 characters"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 400
        flash(error_msg, "error")
        return render_template("register.html")

    if not EMAIL_REGEX.match(email):
        error_msg = "Please enter a valid email address"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 400
        flash(error_msg, "error")
        return render_template("register.html")

    is_valid, password_msg = validate_password(password)
    if not is_valid:
        if request.is_json:
            return jsonify({"success": False, "error": password_msg}), 400
        flash(password_msg, "error")
        return render_template("register.html")

    # Check if user already exists
    if User.query.filter_by(username=username).first():
        error_msg = "Username already taken"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 409
        flash(error_msg, "error")
        return render_template("register.html")

    if User.query.filter_by(email=email).first():
        error_msg = "Email already registered"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 409
        flash(error_msg, "error")
        return render_template("register.html")

    # Create new user
    try:
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        success_msg = "Registration successful! Please log in."
        if request.is_json:
            return jsonify({"success": True, "message": success_msg}), 201
        flash(success_msg, "success")
        return redirect(url_for("auth.login"))
    except Exception as e:
        db.session.rollback()
        error_msg = f"Registration failed: {str(e)}"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 500
        flash(error_msg, "error")
        return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Handle user login"""
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "GET":
        return render_template("login.html")

    # Handle POST request (API or form)
    if request.is_json:
        data = request.get_json()
        username_or_email = data.get("username", "").strip()
        password = data.get("password", "")
        remember = data.get("remember", False)
    else:
        username_or_email = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = request.form.get("remember", False) == "on"

    if not username_or_email or not password:
        error_msg = "Please enter both username/email and password"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 400
        flash(error_msg, "error")
        return render_template("login.html")

    # Try to find user by username or email
    user = User.query.filter(
        (User.username == username_or_email) | (User.email == username_or_email)
    ).first()

    if not user or not user.check_password(password):
        error_msg = "Invalid username/email or password"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 401
        flash(error_msg, "error")
        return render_template("login.html")

    # Login successful
    login_user(user, remember=remember)

    success_msg = "Login successful!"
    if request.is_json:
        return jsonify(
            {
                "success": True,
                "message": success_msg,
                "user": {"id": user.id, "username": user.username, "email": user.email},
            }
        )
    flash(success_msg, "success")
    return redirect(url_for("index"))


@auth_bp.route("/logout")
@login_required
def logout():
    """Handle user logout"""
    logout_user()

    if request.is_json or request.headers.get("Accept") == "application/json":
        return jsonify({"success": True, "message": "Logged out successfully"})

    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Handle password reset request"""
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "GET":
        return render_template("forgot_password.html")

    # Handle POST request
    if request.is_json:
        data = request.get_json()
        email = data.get("email", "").strip().lower()
    else:
        email = request.form.get("email", "").strip().lower()

    if not email:
        error_msg = "Please enter your email address"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 400
        flash(error_msg, "error")
        return render_template("forgot_password.html")

    user = User.query.filter_by(email=email).first()

    if user:
        # Generate reset token
        token = user.generate_reset_token()
        db.session.commit()

        # Send reset email
        try:
            from flask_mail import Message

            reset_url = url_for("auth.reset_password", token=token, _external=True)

            msg = Message(
                "Password Reset Request",
                sender=current_app.config["MAIL_DEFAULT_SENDER"],
                recipients=[user.email],
            )
            msg.body = f"""Hello {user.username},

You have requested a password reset for your Voice-to-Text account.

Please click the following link to reset your password:
{reset_url}

This link will expire in 24 hours.

If you did not request this password reset, please ignore this email.

Best regards,
Voice-to-Text Team
"""
            msg.html = f'''<p>Hello {user.username},</p>
<p>You have requested a password reset for your Voice-to-Text account.</p>
<p>Please click the following link to reset your password:</p>
<p><a href="{reset_url}">{reset_url}</a></p>
<p>This link will expire in 24 hours.</p>
<p>If you did not request this password reset, please ignore this email.</p>
<p>Best regards,<br>Voice-to-Text Team</p>
'''

            mail = current_app.extensions.get("mail")
            if mail:
                mail.send(msg)
        except Exception as e:
            current_app.logger.error(f"Failed to send reset email: {str(e)}")

    # Always return success to prevent email enumeration
    success_msg = (
        "If an account exists with that email, you will receive a password reset link."
    )
    if request.is_json:
        return jsonify({"success": True, "message": success_msg})
    flash(success_msg, "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Handle password reset confirmation"""
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    # Find user by token
    user = User.query.filter_by(reset_token=token).first()

    if not user or not user.verify_reset_token(token):
        error_msg = "Invalid or expired reset token"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 400
        flash(error_msg, "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "GET":
        return render_template("reset_password.html", token=token)

    # Handle POST request
    if request.is_json:
        data = request.get_json()
        password = data.get("password", "")
        confirm_password = data.get("confirm_password", "")
    else:
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

    if not password or not confirm_password:
        error_msg = "Please enter both password fields"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 400
        flash(error_msg, "error")
        return render_template("reset_password.html", token=token)

    if password != confirm_password:
        error_msg = "Passwords do not match"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 400
        flash(error_msg, "error")
        return render_template("reset_password.html", token=token)

    is_valid, password_msg = validate_password(password)
    if not is_valid:
        if request.is_json:
            return jsonify({"success": False, "error": password_msg}), 400
        flash(password_msg, "error")
        return render_template("reset_password.html", token=token)

    try:
        user.set_password(password)
        user.clear_reset_token()
        db.session.commit()

        success_msg = "Password reset successful! Please log in."
        if request.is_json:
            return jsonify({"success": True, "message": success_msg})
        flash(success_msg, "success")
        return redirect(url_for("auth.login"))
    except Exception as e:
        db.session.rollback()
        error_msg = f"Password reset failed: {str(e)}"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 500
        flash(error_msg, "error")
        return render_template("reset_password.html", token=token)


@auth_bp.route("/profile")
@login_required
def profile():
    """Get current user profile"""
    return jsonify(
        {
            "success": True,
            "user": {
                "id": current_user.id,
                "username": current_user.username,
                "email": current_user.email,
                "created_at": current_user.created_at.isoformat()
                if current_user.created_at
                else None,
            },
        }
    )


@auth_bp.route("/change-password", methods=["POST"])
@login_required
def change_password():
    """Change user password"""
    if request.is_json:
        data = request.get_json()
        current_password = data.get("current_password", "")
        new_password = data.get("new_password", "")
    else:
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")

    if not current_password or not new_password:
        error_msg = "Both current and new password are required"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 400
        flash(error_msg, "error")
        return redirect(url_for("dashboard"))

    if not current_user.check_password(current_password):
        error_msg = "Current password is incorrect"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 400
        flash(error_msg, "error")
        return redirect(url_for("dashboard"))

    is_valid, password_msg = validate_password(new_password)
    if not is_valid:
        if request.is_json:
            return jsonify({"success": False, "error": password_msg}), 400
        flash(password_msg, "error")
        return redirect(url_for("dashboard"))

    try:
        current_user.set_password(new_password)
        db.session.commit()

        success_msg = "Password changed successfully"
        if request.is_json:
            return jsonify({"success": True, "message": success_msg})
        flash(success_msg, "success")
        return redirect(url_for("dashboard"))
    except Exception as e:
        db.session.rollback()
        error_msg = f"Password change failed: {str(e)}"
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 500
        flash(error_msg, "error")
        return redirect(url_for("dashboard"))
