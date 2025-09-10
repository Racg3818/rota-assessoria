from functools import wraps
from flask import session, redirect, url_for, current_app, request

def is_logged():
    user = session.get("user")
    if not user:
        return False
    email = user.get("email", "").lower()
    allowed = current_app.config.get("ALLOWED_DOMAIN", "svninvest.com.br").lower()
    return user.get("nome") and email.endswith("@" + allowed)

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_logged():
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped
