from functools import wraps
from flask import session, redirect, url_for, current_app, request

def is_logged():
    user = session.get("user")
    if not user:
        current_app.logger.debug("IS_LOGGED: Sem user na sessão")
        return False

    email = user.get("email", "").lower()
    nome = user.get("nome")
    allowed = current_app.config.get("ALLOWED_DOMAIN", "svninvest.com.br").lower()

    has_nome = bool(nome)
    has_email_domain = email.endswith("@" + allowed)

    current_app.logger.info("IS_LOGGED: email=%s, nome=%s, has_nome=%s, has_email_domain=%s",
                           email, nome, has_nome, has_email_domain)

    return has_nome and has_email_domain

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_logged():
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped
