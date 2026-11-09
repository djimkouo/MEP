import csv
import io
from datetime import date, timedelta

from flask import (
    Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user
from sqlalchemy import or_

from .auth import admin_requis
from .extensions import db
from .forms import ContratForm, NoteForm, PersonneForm
from .models import (
    CATEGORIES, DISPONIBILITES, NIVEAUX, Certification, Competence, ContratHistorique,
    JournalAudit, Mission, NoteInterne, Personne, PersonneCompetence, maintenant,
)
from .services import (
    PlageEpuisee, creer_personne, decrire_changements, instantane, journaliser,
)

bp = Blueprint("personnel", __name__, url_prefix="/personnel")


def _personne(code):
    p = db.session.scalar(db.select(Personne).filter_by(code=code.upper()))
    if p is None:
        abort(404)
    return p


def _appliquer_formulaire(form, p):
    form.populate_obj(p)
    p.email = p.email.lower().strip()
    p.nom = p.nom.strip()
    p.prenom = p.prenom.strip()
    p.piece_numero = p.piece_numero.strip().upper()
    p.mobilite = p.mobilite or None
    # Spécialisation industrielle : tout le personnel est salarié (CDI ou CDD), plus de TJM.
    p.statut = "salarie"
    p.type_contrat = p.type_contrat or "cdi"
    if not p.est_cdd:
        p.date_fin_contrat = None
        p.motif_cdd = None
        p.mission_liee_id = None
    else:
        p.motif_cdd = (p.motif_cdd or "").strip() or None


def _choix_missions(form_champ, actuelle_id=None):
    missions = db.session.scalars(db.select(Mission).filter(
        or_(Mission.statut.in_(("preparation", "en_cours")), Mission.id == (actuelle_id or 0)))
        .order_by(Mission.code.desc())).all()
    form_champ.choices = [("", "— Aucune —")] + [
        (m.id, f"{m.code} · {m.intitule} ({m.client.raison_sociale})") for m in missions]
    return {m.id for m in missions}


def _mission_valide(champ, ids):
    if champ.data and champ.data not in ids:
        champ.errors.append("Mission inconnue ou close.")
        return False
    return True


def _email_pris(email, sauf_id=None):
    q = db.select(Personne.id).filter(Personne.email == email.lower().strip())
    if sauf_id:
        q = q.filter(Personne.id != sauf_id)
    return db.session.scalar(q) is not None


# ---------------------------------------------------------------- Liste

def _requete_filtrée(args):
    q = db.select(Personne)
    if not args.get("archives"):
        q = q.filter(Personne.archive.is_(False))

    terme = (args.get("q") or "").strip()
    if terme:
        like = f"%{terme}%"
        q = q.filter(or_(
            Personne.nom.ilike(like), Personne.prenom.ilike(like), Personne.code.ilike(like),
            Personne.email.ilike(like), Personne.ville.ilike(like),
            Personne.competences.any(PersonneCompetence.competence.has(Competence.nom.ilike(like))),
        ))
    if args.get("categorie") in CATEGORIES:
        q = q.filter(Personne.categorie == args["categorie"])
    if args.get("contrat") in ("cdi",):
        q = q.filter(or_(Personne.type_contrat == "cdi", Personne.type_contrat.is_(None)))

    cid = args.get("competence", type=int)
    if cid:
        nmin = args.get("niveau_min", type=int) or 1
        q = q.filter(Personne.competences.any(
            (PersonneCompetence.competence_id == cid) & (PersonneCompetence.niveau >= nmin)))

    if args.get("contrat") == "cdd":
        q = q.filter(Personne.statut == "salarie", Personne.type_contrat == "cdd")
    if args.get("contrat") == "alerte":
        q = q.filter(Personne.statut == "salarie", Personne.type_contrat == "cdd",
                     Personne.date_fin_contrat <= date.today() + timedelta(
                         days=current_app.config["ALERTE_CDD_JOURS"]))
    if args.get("piece") == "alerte":
        q = q.filter(Personne.piece_date_expiration.isnot(None),
                     Personne.piece_date_expiration <= date.today() + timedelta(
                         days=current_app.config["ALERTE_PIECE_JOURS"]))
    return q.order_by(Personne.nom, Personne.prenom)


def _filtrer_disponibilite(personnes, dispo):
    """La disponibilité est calculée à partir des missions : filtrage en Python."""
    if dispo == "bientot":
        return [p for p in personnes if p.etat_disponibilite == "bientot"]
    if dispo == "en_mission":
        return [p for p in personnes if p.etat_disponibilite in ("en_mission", "bientot")]
    if dispo in DISPONIBILITES:
        return [p for p in personnes if p.etat_disponibilite == dispo]
    return personnes


def _personnes_filtrees(args):
    return _filtrer_disponibilite(db.session.scalars(_requete_filtrée(args)).all(),
                                  args.get("disponibilite"))


@bp.route("/")
@admin_requis
def liste():
    personnes = _personnes_filtrees(request.args)
    competences = db.session.scalars(
        db.select(Competence).filter_by(actif=True).order_by(Competence.nom)).all()

    actifs = db.session.scalars(db.select(Personne).filter_by(archive=False)).all()
    stats = {
        "total": len(actifs),
        "disponibles": sum(1 for p in actifs if p.etat_disponibilite == "disponible"),
        "en_mission": sum(1 for p in actifs if p.etat_disponibilite in ("en_mission", "bientot")),
        "bientot": sum(1 for p in actifs if p.etat_disponibilite == "bientot"),
        "pieces": sum(1 for p in actifs if p.etat_piece),
        "cdd": sum(1 for p in actifs if p.etat_contrat),
    }
    filtres_actifs = any(request.args.get(k) for k in
                         ("q", "categorie", "disponibilite", "competence", "piece", "contrat",
                          "archives"))
    return render_template(
        "personnel/liste.html", personnes=personnes, competences=competences, stats=stats,
        categories=CATEGORIES, disponibilites=DISPONIBILITES, niveaux=NIVEAUX,
        filtres_actifs=filtres_actifs,
    )


@bp.route("/export.csv")
@admin_requis
def export_csv():
    personnes = _personnes_filtrees(request.args)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Code", "Catégorie", "Nom", "Prénom", "E-mail", "Téléphone", "Ville", "Contrat",
                "Fin du CDD", "Date d'entrée", "Disponibilité", "Libre le", "Compétences", "Archivé"])
    for p in personnes:
        w.writerow([
            p.code, p.categorie_libelle, p.nom, p.prenom, p.email, p.telephone or "", p.ville or "",
            p.contrat_libelle,
            p.date_fin_contrat.strftime("%d/%m/%Y") if p.est_cdd and p.date_fin_contrat else "",
            p.date_entree.strftime("%d/%m/%Y"), p.badge_disponibilite[0],
            p.libre_le.strftime("%d/%m/%Y") if p.libre_le else "",
            ", ".join(f"{pc.competence.nom} ({pc.niveau}/4)" for pc in p.competences),
            "Oui" if p.archive else "Non",
        ])
    journaliser("export", details=f"Export CSV de {len(personnes)} personne(s), sans données sensibles")
    db.session.commit()
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=personnel.csv"})


# ---------------------------------------------------------------- Création / modification

@bp.route("/nouveau", methods=["GET", "POST"])
@admin_requis
def nouveau():
    form = PersonneForm()
    ids_missions = _choix_missions(form.mission_liee_id)
    if request.method == "GET":
        form.categorie.data = "operationnel"
        form.type_contrat.data = "cdi"
        form.date_entree.data = date.today()
    if form.validate_on_submit() and _mission_valide(form.mission_liee_id, ids_missions):
        if _email_pris(form.email.data):
            form.email.errors.append("Cette adresse e-mail est déjà utilisée.")
        else:
            p = Personne(cree_par_id=current_user.id, modifie_par_id=current_user.id)
            _appliquer_formulaire(form, p)
            try:
                creer_personne(p)
            except PlageEpuisee as e:
                db.session.rollback()
                flash(str(e), "danger")
            else:
                flash(f"{p.nom_complet} a été enregistré(e) sous le code {p.code}.", "success")
                return redirect(url_for(".fiche", code=p.code))
    return render_template("personnel/formulaire.html", form=form, personne=None)


@bp.route("/<code>/modifier", methods=["GET", "POST"])
@admin_requis
def modifier(code):
    p = _personne(code)
    form = PersonneForm(obj=p)
    ids_missions = _choix_missions(form.mission_liee_id, p.mission_liee_id)
    if request.method == "GET" and not p.type_contrat:
        form.type_contrat.data = "cdi"
    if form.validate_on_submit() and _mission_valide(form.mission_liee_id, ids_missions):
        if _email_pris(form.email.data, sauf_id=p.id):
            form.email.errors.append("Cette adresse e-mail est déjà utilisée.")
        else:
            avant = instantane(p)
            _appliquer_formulaire(form, p)  # le code MEP n'est jamais modifié
            p.modifie_par_id = current_user.id
            changements = decrire_changements(avant, instantane(p))
            if changements:
                journaliser("modification", p, changements)
            db.session.commit()
            flash("Fiche mise à jour." if changements else "Aucune modification.", "success")
            return redirect(url_for(".fiche", code=p.code))
    return render_template("personnel/formulaire.html", form=form, personne=p)


@bp.route("/<code>/contrat", methods=["GET", "POST"])
@admin_requis
def contrat(code):
    """Renouvellement d'un CDD ou passage en CDI : le contrat en cours est archivé dans l'historique."""
    p = _personne(code)
    if not p.est_cdd:
        flash("Cette action concerne uniquement les salariés en CDD.", "warning")
        return redirect(url_for(".fiche", code=p.code))
    form = ContratForm()
    ids_missions = _choix_missions(form.mission_liee_id, p.mission_liee_id)
    if request.method == "GET":
        form.date_debut.data = (p.date_fin_contrat + timedelta(days=1)) if p.date_fin_contrat else date.today()
        form.motif.data = p.motif_cdd
        form.mission_liee_id.data = p.mission_liee_id
    if form.validate_on_submit() and _mission_valide(form.mission_liee_id, ids_missions):
        if form.date_debut.data <= p.debut_contrat:
            form.date_debut.errors.append(
                f"Le nouveau contrat doit commencer après le début du contrat en cours ({p.debut_contrat:%d/%m/%Y}).")
        else:
            ancien = ContratHistorique(
                type_contrat="cdd", date_debut=p.debut_contrat,
                date_fin=min(p.date_fin_contrat, form.date_debut.data - timedelta(days=1))
                if p.date_fin_contrat else form.date_debut.data - timedelta(days=1),
                motif=p.motif_cdd, mission_id=p.mission_liee_id)
            p.contrats_precedents.append(ancien)
            details = [f"Contrat archivé : CDD du {ancien.date_debut:%d/%m/%Y} au {ancien.date_fin:%d/%m/%Y}"]
            p.date_debut_contrat = form.date_debut.data
            if form.action.data == "cdi":
                p.type_contrat = "cdi"
                p.date_fin_contrat = None
                p.motif_cdd = None
                p.mission_liee_id = None
                details.append(f"Passage en CDI au {form.date_debut.data:%d/%m/%Y}")
            else:
                p.date_fin_contrat = form.date_fin.data
                p.motif_cdd = (form.motif.data or "").strip() or None
                p.mission_liee_id = form.mission_liee_id.data
                details.append(f"Nouveau CDD du {form.date_debut.data:%d/%m/%Y} au {form.date_fin.data:%d/%m/%Y}")
            if form.salaire_mensuel_brut.data and form.salaire_mensuel_brut.data != p.salaire_mensuel_brut:
                p.salaire_mensuel_brut = form.salaire_mensuel_brut.data
                details.append("salaire_mensuel_brut : modifié")
            p.modifie_par_id = current_user.id
            journaliser("contrat", p, "\n".join(details))
            db.session.commit()
            nb, _ = p.cdd_successifs
            flash("Contrat mis à jour." + (f" C'est le {nb}e CDD successif." if p.est_cdd and nb > 1 else ""),
                  "success")
            return redirect(url_for(".fiche", code=p.code) + "#contrat")
    return render_template("personnel/contrat.html", form=form, p=p)


@bp.route("/<code>/archiver", methods=["POST"])
@admin_requis
def archiver(code):
    p = _personne(code)
    p.archive = not p.archive
    p.date_archivage = maintenant() if p.archive else None
    journaliser("archivage" if p.archive else "reactivation", p)
    db.session.commit()
    flash(f"{p.nom_complet} a été {'archivé(e)' if p.archive else 'réactivé(e)'}.", "success")
    return redirect(url_for(".fiche", code=p.code))


# ---------------------------------------------------------------- Fiche

def _rendre_fiche(p, sensible):
    competences = db.session.scalars(
        db.select(Competence).filter_by(actif=True).order_by(Competence.nom)).all()
    deja = {pc.competence_id for pc in p.competences}
    historique = db.session.scalars(
        db.select(JournalAudit).filter_by(personne_id=p.id)
        .order_by(JournalAudit.horodatage.desc()).limit(15)).all()
    return render_template(
        "personnel/fiche.html", p=p, sensible=sensible, note_form=NoteForm(), niveaux=NIVEAUX,
        competences_dispo=[c for c in competences if c.id not in deja], historique=historique,
        actions=LIBELLES_ACTIONS,
    )


@bp.route("/<code>")
@admin_requis
def fiche(code):
    return _rendre_fiche(_personne(code), sensible=False)


@bp.route("/<code>/donnees-sensibles")
@admin_requis
def fiche_sensible(code):
    p = _personne(code)
    journaliser("consultation_sensible", p, "Affichage du numéro de pièce et de la rémunération")
    db.session.commit()
    return _rendre_fiche(p, sensible=True)


@bp.route("/<code>/competences", methods=["POST"])
@admin_requis
def ajouter_competence(code):
    p = _personne(code)
    cid = request.form.get("competence_id", type=int)
    niveau = request.form.get("niveau", type=int)
    annees = request.form.get("annees", type=int)
    c = db.session.get(Competence, cid) if cid else None
    if not c or niveau not in NIVEAUX or (annees is not None and not 0 <= annees <= 60):
        flash("Compétence ou niveau invalide.", "danger")
    elif any(pc.competence_id == c.id for pc in p.competences):
        flash("Cette compétence est déjà sur la fiche.", "warning")
    else:
        p.competences.append(PersonneCompetence(competence=c, niveau=niveau, annees=annees))
        journaliser("modification", p, f"Compétence ajoutée : {c.nom} ({niveau}/4)")
        db.session.commit()
    return redirect(url_for(".fiche", code=p.code) + "#competences")


@bp.route("/<code>/competences/<int:pcid>/supprimer", methods=["POST"])
@admin_requis
def retirer_competence(code, pcid):
    p = _personne(code)
    pc = db.get_or_404(PersonneCompetence, pcid)
    if pc.personne_id != p.id:
        abort(404)
    journaliser("modification", p, f"Compétence retirée : {pc.competence.nom}")
    db.session.delete(pc)
    db.session.commit()
    return redirect(url_for(".fiche", code=p.code) + "#competences")


@bp.route("/<code>/certifications", methods=["POST"])
@admin_requis
def ajouter_certification(code):
    p = _personne(code)
    nom = (request.form.get("nom") or "").strip()
    def _d(champ):
        v = request.form.get(champ)
        try:
            return date.fromisoformat(v) if v else None
        except ValueError:
            return None
    obtention, expiration = _d("date_obtention"), _d("date_expiration")
    if not nom:
        flash("Le nom de la certification est obligatoire.", "danger")
    elif obtention and expiration and expiration <= obtention:
        flash("La date d'expiration doit suivre la date d'obtention.", "danger")
    else:
        p.certifications.append(Certification(
            nom=nom[:200], organisme=(request.form.get("organisme") or "").strip()[:200] or None,
            date_obtention=obtention, date_expiration=expiration))
        journaliser("modification", p, f"Certification ajoutée : {nom}")
        db.session.commit()
    return redirect(url_for(".fiche", code=p.code) + "#certifications")


@bp.route("/<code>/certifications/<int:cid>/supprimer", methods=["POST"])
@admin_requis
def retirer_certification(code, cid):
    p = _personne(code)
    c = db.get_or_404(Certification, cid)
    if c.personne_id != p.id:
        abort(404)
    journaliser("modification", p, f"Certification retirée : {c.nom}")
    db.session.delete(c)
    db.session.commit()
    return redirect(url_for(".fiche", code=p.code) + "#certifications")


@bp.route("/<code>/notes", methods=["POST"])
@admin_requis
def ajouter_note(code):
    p = _personne(code)
    form = NoteForm()
    if form.validate_on_submit():
        p.notes.append(NoteInterne(texte=form.texte.data.strip(), auteur_id=current_user.id))
        db.session.commit()
    else:
        flash("La note est vide.", "warning")
    return redirect(url_for(".fiche", code=p.code) + "#notes")


# ---------------------------------------------------------------- Journal d'audit

LIBELLES_ACTIONS = {
    "creation": "Création", "modification": "Modification", "archivage": "Archivage",
    "reactivation": "Réactivation", "export": "Export", "consultation_sensible": "Consultation sensible",
    "statut": "Changement de statut", "affectation": "Affectation", "prolongation": "Prolongation",
    "parametre": "Paramètre", "contrat": "Contrat", "jalon": "Jalon",
}


@bp.route("/journal")
@admin_requis
def journal():
    action = request.args.get("action")
    q = db.select(JournalAudit).order_by(JournalAudit.horodatage.desc())
    if action in LIBELLES_ACTIONS:
        q = q.filter_by(action=action)
    entrees = db.session.scalars(q.limit(300)).all()
    return render_template("personnel/journal.html", entrees=entrees, actions=LIBELLES_ACTIONS,
                           action=action)
