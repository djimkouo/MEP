from flask import Blueprint, flash, redirect, render_template, url_for

from .auth import admin_requis
from .extensions import db
from .forms import CompetenceForm
from .models import CATEGORIES_COMPETENCE, Competence

bp = Blueprint("competences", __name__, url_prefix="/competences")


@bp.route("/", methods=["GET", "POST"])
@admin_requis
def liste():
    form = CompetenceForm()
    if form.validate_on_submit():
        norm = Competence.normaliser(form.nom.data)
        if db.session.scalar(db.select(Competence).filter_by(nom_normalise=norm)):
            flash(f"La compétence « {form.nom.data.strip()} » existe déjà.", "warning")
        else:
            db.session.add(Competence(nom=" ".join(form.nom.data.split()), nom_normalise=norm,
                                      categorie=form.categorie.data, actif=True))
            db.session.commit()
            flash("Compétence ajoutée.", "success")
        return redirect(url_for(".liste"))
    competences = db.session.scalars(
        db.select(Competence).order_by(Competence.categorie, Competence.nom)).all()
    groupes = {k: [c for c in competences if c.categorie == k] for k in CATEGORIES_COMPETENCE}
    return render_template("competences/liste.html", form=form, groupes=groupes,
                           categories=CATEGORIES_COMPETENCE)


@bp.route("/<int:cid>/modifier", methods=["GET", "POST"])
@admin_requis
def modifier(cid):
    c = db.get_or_404(Competence, cid)
    form = CompetenceForm(obj=c)
    if form.validate_on_submit():
        norm = Competence.normaliser(form.nom.data)
        doublon = db.session.scalar(db.select(Competence).filter(
            Competence.nom_normalise == norm, Competence.id != c.id))
        if doublon:
            form.nom.errors.append("Une autre compétence porte déjà ce nom.")
        else:
            c.nom = " ".join(form.nom.data.split())
            c.nom_normalise = norm
            c.categorie = form.categorie.data
            c.actif = form.actif.data
            db.session.commit()
            flash("Compétence mise à jour.", "success")
            return redirect(url_for(".liste"))
    return render_template("competences/modifier.html", form=form, competence=c)
