from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .extensions import db
from .forms import ConnexionForm
from .models import Utilisateur

bp = Blueprint("auth", __name__)


def admin_requis(vue):
    @wraps(vue)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.est_admin:
            abort(403)
        return vue(*args, **kwargs)
    return wrapper


@bp.route("/connexion", methods=["GET", "POST"])
def connexion():
    if current_user.is_authenticated:
        return redirect(url_for("personnel.liste"))
    form = ConnexionForm()
    if form.validate_on_submit():
        u = db.session.scalar(db.select(Utilisateur).filter_by(email=form.email.data.lower().strip()))
        if u and u.actif and u.verifier_mot_de_passe(form.mot_de_passe.data):
            login_user(u)
            suivant = request.args.get("next")
            if not suivant or not suivant.startswith("/") or suivant.startswith("//"):
                suivant = url_for("personnel.liste")
            return redirect(suivant)
        flash("Identifiants incorrects.", "danger")
    return render_template("auth/connexion.html", form=form)


@bp.route("/deconnexion", methods=["POST"])
@login_required
def deconnexion():
    logout_user()
    return redirect(url_for("auth.connexion"))
