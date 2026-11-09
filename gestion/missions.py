"""Module 3 : gestion des missions et des affectations."""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_

from .auth import admin_requis
from .extensions import db
from .forms import AffectationForm, JalonForm, MissionForm, ParametresForm
from .models import (
    MOBILITES, STATUTS_MISSION, Affectation, Client, Competence, ContactClient, Jalon, JournalAudit,
    Mission, Parametre, Personne,
)
from .services import (
    CHAMPS_MISSION, activer_client_si_prospect, charge_maximale, creer_mission, decrire_changements,
    instantane, journaliser,
)

bp = Blueprint("missions", __name__, url_prefix="/missions")
bp_parametres = Blueprint("parametres", __name__, url_prefix="/parametres")

LIBELLES_ACTIONS = {
    "creation": "Création", "modification": "Modification", "statut": "Changement de statut",
    "affectation": "Affectation", "prolongation": "Prolongation", "export": "Export", "jalon": "Jalon",
}

# Transitions de statut autorisées : statut actuel -> {nouveau statut: libellé du bouton}
TRANSITIONS = {
    "preparation": {"en_cours": "Démarrer la mission", "annulee": "Annuler"},
    "en_cours": {"terminee": "Clôturer", "annulee": "Annuler"},
    "terminee": {"en_cours": "Rouvrir"},
    "annulee": {"preparation": "Rétablir"},
}


def _mission(code):
    m = db.session.scalar(db.select(Mission).filter_by(code=code.upper()))
    if m is None:
        abort(404)
    return m


def _affectation(m, aid):
    a = db.get_or_404(Affectation, aid)
    if a.mission_id != m.id:
        abort(404)
    return a


# ---------------------------------------------------------------- Liste

def _requete(args):
    q = db.select(Mission)
    statut = args.get("statut")
    if statut in STATUTS_MISSION:
        q = q.filter(Mission.statut == statut)
    elif statut != "toutes":
        q = q.filter(Mission.statut.in_(("preparation", "en_cours")))
    if args.get("client", type=int):
        q = q.filter(Mission.client_id == args.get("client", type=int))
    if args.get("personne", type=int):
        q = q.filter(Mission.affectations.any(Affectation.personne_id == args.get("personne", type=int)))
    terme = (args.get("q") or "").strip()
    if terme:
        like = f"%{terme}%"
        q = q.filter(or_(Mission.code.ilike(like), Mission.intitule.ilike(like),
                         Mission.reference_commande.ilike(like),
                         Mission.client.has(or_(Client.raison_sociale.ilike(like), Client.sigle.ilike(like))),
                         Mission.affectations.any(Affectation.personne.has(
                             or_(Personne.nom.ilike(like), Personne.prenom.ilike(like),
                                 Personne.code.ilike(like))))))
    return q.order_by(Mission.date_fin)


def _missions_filtrees(args):
    missions = db.session.scalars(_requete(args)).all()
    alerte = args.get("alerte")
    if alerte in ("bientot", "depassee"):
        missions = [m for m in missions if m.alerte_fin == alerte]
    return missions


@bp.route("/")
@admin_requis
def liste():
    missions = _missions_filtrees(request.args)
    actives = db.session.scalars(db.select(Mission).filter(
        Mission.statut.in_(("preparation", "en_cours")))).all()
    stats = {
        "en_cours": sum(1 for m in actives if m.statut == "en_cours"),
        "preparation": sum(1 for m in actives if m.statut == "preparation"),
        "bientot": sum(1 for m in actives if m.alerte_fin == "bientot"),
        "depassee": sum(1 for m in actives if m.alerte_fin == "depassee"),
    }
    clients = db.session.scalars(db.select(Client).filter(Client.missions.any())
                                 .order_by(Client.raison_sociale)).all()
    personnes = db.session.scalars(db.select(Personne).filter(Personne.affectations.any())
                                   .order_by(Personne.nom)).all()
    filtres_actifs = any(request.args.get(k) for k in ("q", "statut", "client", "personne", "alerte"))
    return render_template("missions/liste.html", missions=missions, stats=stats, statuts=STATUTS_MISSION,
                           clients=clients, personnes=personnes, filtres_actifs=filtres_actifs)


@bp.route("/export.csv")
@admin_requis
def export_csv():
    missions = _missions_filtrees(request.args)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Code", "Intitulé", "Client", "Statut", "Mode", "Montant forfait (XAF)", "Début", "Fin",
                "Personne", "Code personne",
                "Affectation du", "Affectation au", "Occupation %", "TJM vente (XAF)", "Jours prévus",
                "CA prévisionnel (XAF)", "Réf. commande"])
    for m in missions:
        lignes = m.affectations or [None]
        for a in lignes:
            w.writerow([
                m.code, m.intitule, m.client.raison_sociale, m.statut_libelle, m.mode_libelle,
                m.montant_forfait or "", m.date_debut.strftime("%d/%m/%Y"), m.date_fin.strftime("%d/%m/%Y"),
                a.personne.nom_complet if a else "", a.personne.code if a else "",
                a.date_debut.strftime("%d/%m/%Y") if a else "", a.date_fin.strftime("%d/%m/%Y") if a else "",
                a.taux_occupation if a else "", (a.tjm_vente or "") if a else "",
                str(round(a.jours_prevus, 1)).replace(".", ",") if a else "",
                round(a.ca_previsionnel) if a else "", m.reference_commande or "",
            ])
    journaliser("export", details=f"Export CSV de {len(missions)} mission(s)")
    db.session.commit()
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=missions.csv"})


# ---------------------------------------------------------------- Création / modification

def _preparer_formulaire(form, mission=None):
    q = db.select(Client).order_by(Client.raison_sociale)
    clients = [c for c in db.session.scalars(q).all()
               if c.statut != "inactif" or (mission and c.id == mission.client_id)]
    form.client_id.choices = [(0, "— Choisir —")] + [(c.id, f"{c.raison_sociale} ({c.code})") for c in clients]
    contacts = db.session.scalars(db.select(ContactClient).filter(
        ContactClient.client_id.in_([c.id for c in clients])).order_by(ContactClient.nom)).all()
    form.contact_id.choices = [("", "— Aucun —")] + [(ct.id, ct.nom_complet) for ct in contacts]
    # Pour filtrer les interlocuteurs selon le client choisi (JavaScript)
    carte = {}
    for ct in contacts:
        if ct.actif or (mission and ct.id == mission.contact_id):
            carte.setdefault(ct.client_id, []).append(
                {"id": ct.id, "nom": ct.nom_complet + (f" — {ct.fonction}" if ct.fonction else ""),
                 "principal": ct.principal})
    competences = db.session.scalars(db.select(Competence).filter_by(actif=True).order_by(Competence.nom)).all()
    return carte, competences


def _controler_formulaire(form, mission=None):
    ok = True
    client = db.session.get(Client, form.client_id.data) if form.client_id.data else None
    if not client:
        form.client_id.errors.append("Choisissez le client.")
        return False, None
    if client.statut == "inactif" and not (mission and mission.client_id == client.id):
        form.client_id.errors.append("Ce client est inactif : réactivez-le avant de créer une mission.")
        ok = False
    if form.contact_id.data:
        ct = db.session.get(ContactClient, form.contact_id.data)
        if not ct or ct.client_id != client.id:
            form.contact_id.errors.append("Cet interlocuteur n'appartient pas au client choisi.")
            ok = False
    if mission and mission.affectations and form.date_debut.data and form.date_fin.data:
        hors = [a for a in mission.affectations
                if a.date_debut < form.date_debut.data or a.date_fin > form.date_fin.data]
        if hors:
            noms = ", ".join(sorted({a.personne.nom_complet for a in hors}))
            form.date_fin.errors.append(
                f"Des affectations sortent de ces dates ({noms}) : modifiez-les d'abord.")
            ok = False
    if (mission and mission.affectations
            and (mission.mode_facturation or "regie") != form.mode_facturation.data):
        form.mode_facturation.errors.append(
            "Le mode de facturation ne peut plus changer une fois des personnes affectées.")
        ok = False
    if mission and mission.jalons and form.mode_facturation.data != "forfait":
        form.mode_facturation.errors.append("Supprimez d'abord les jalons de facturation.")
        ok = False
    if mission and mission.client_id != client.id and mission.affectations:
        form.client_id.errors.append("Le client ne peut plus changer une fois des personnes affectées.")
        ok = False
    return ok, client


def _appliquer(form, m):
    for champ in form:
        if champ.name not in ("duree_jours", "csrf_token"):
            champ.populate_obj(m, champ.name)
    m.intitule = " ".join(m.intitule.split())
    m.mode = m.mode or None
    if m.mode_facturation != "forfait":
        m.montant_forfait = None
        m.livrable = None
    for champ in ("description", "lieu", "reference_commande", "livrable"):
        setattr(m, champ, (getattr(m, champ) or "").strip() or None)
    ids = [int(i) for i in request.form.getlist("competences") if i.isdigit()]
    m.competences = db.session.scalars(db.select(Competence).filter(Competence.id.in_(ids))).all() if ids else []


@bp.route("/nouvelle", methods=["GET", "POST"])
@admin_requis
def nouvelle():
    form = MissionForm()
    carte, competences = _preparer_formulaire(form)
    if request.method == "GET":
        code_client = request.args.get("client")
        if code_client:
            c = db.session.scalar(db.select(Client).filter_by(code=code_client.upper()))
            if c:
                form.client_id.data = c.id
                form.contact_id.data = c.contact_principal.id if c.contact_principal else None
                form.lieu.data = c.ville
        form.date_debut.data = date.today()
        form.mode_facturation.data = "forfait"  # secteur industriel : le forfait est le cas courant
    if form.validate_on_submit():
        ok, client = _controler_formulaire(form)
        if ok:
            m = Mission(statut="preparation", cree_par_id=current_user.id)
            _appliquer(form, m)
            creer_mission(m)
            flash(f"Mission {m.code} créée. Affectez maintenant les personnes.", "success")
            return redirect(url_for(".fiche", code=m.code) + "#affectations")
    return render_template("missions/formulaire.html", form=form, mission=None, carte=carte,
                           competences=competences, choisies=set(map(int, request.form.getlist("competences")))
                           if request.method == "POST" else set())


@bp.route("/<code>/modifier", methods=["GET", "POST"])
@admin_requis
def modifier(code):
    m = _mission(code)
    form = MissionForm(obj=m)
    if request.method == "GET":
        form.duree_jours.data = (m.date_fin - m.date_debut).days + 1
    carte, competences = _preparer_formulaire(form, m)
    if form.validate_on_submit():
        ok, _ = _controler_formulaire(form, m)
        if ok:
            avant = instantane(m, CHAMPS_MISSION)
            avant_comp = {c.nom for c in m.competences}
            _appliquer(form, m)
            changements = decrire_changements(avant, instantane(m, CHAMPS_MISSION), sensibles=())
            apres_comp = {c.nom for c in m.competences}
            if avant_comp != apres_comp:
                changements += ("\n" if changements else "") + "compétences recherchées : " + (
                    ", ".join(sorted(apres_comp)) or "aucune")
            if changements:
                journaliser("modification", mission=m, details=changements)
            db.session.commit()
            flash("Mission mise à jour." if changements else "Aucune modification.", "success")
            return redirect(url_for(".fiche", code=m.code))
    choisies = ({int(i) for i in request.form.getlist("competences")} if request.method == "POST"
                else {c.id for c in m.competences})
    return render_template("missions/formulaire.html", form=form, mission=m, carte=carte,
                           competences=competences, choisies=choisies)


@bp.route("/<code>/statut", methods=["POST"])
@admin_requis
def changer_statut(code):
    m = _mission(code)
    nouveau = request.form.get("statut")
    if nouveau not in TRANSITIONS.get(m.statut, {}):
        abort(400)
    if nouveau == "en_cours" and not m.affectations:
        flash("Affectez au moins une personne avant de démarrer la mission.", "warning")
        return redirect(url_for(".fiche", code=m.code) + "#affectations")
    journaliser("statut", mission=m, details=f"{m.statut_libelle} → {STATUTS_MISSION[nouveau]}")
    m.statut = nouveau
    if nouveau == "en_cours" and activer_client_si_prospect(m):
        flash(f"{m.client.raison_sociale} est passé de prospect à client actif.", "success")
    db.session.commit()
    flash(f"Mission « {STATUTS_MISSION[nouveau]} ».", "success")
    return redirect(url_for(".fiche", code=m.code))


# ---------------------------------------------------------------- Fiche

def _choix_personnes(m, inclure_id=None):
    """Personnes proposées : d'abord celles qui ont le plus de compétences recherchées, puis les plus libres."""
    personnes = db.session.scalars(db.select(Personne).filter(
        or_(Personne.archive.is_(False), Personne.id == (inclure_id or 0)))).all()
    recherchees = {c.id for c in m.competences}
    lignes = []
    for p in personnes:
        nb = len(recherchees & {pc.competence_id for pc in p.competences})
        charge, _ = charge_maximale(p.id, m.date_debut, m.date_fin)
        if p.disponibilite == "indisponible":
            etat = "indisponible"
        elif charge == 0:
            etat = "libre sur la période"
        else:
            etat = f"déjà occupé(e) jusqu'à {charge} %"
        libelle = f"{p.nom_complet} ({p.code}) — {etat}"
        if recherchees:
            libelle += f" — {nb}/{len(recherchees)} compétence{'s' if len(recherchees) > 1 else ''}"
        lignes.append(((-nb, charge, p.disponibilite == "indisponible", p.nom), p.id, libelle))
    lignes.sort()
    return [(0, "— Choisir —")] + [(pid, lib) for _, pid, lib in lignes]


@bp.route("/<code>")
@admin_requis
def fiche(code):
    m = _mission(code)
    form = AffectationForm(formdata=None)
    form.personne_id.choices = _choix_personnes(m)
    form.date_debut.data, form.date_fin.data = m.date_debut, m.date_fin
    form.taux_occupation.data = 100
    historique = db.session.scalars(db.select(JournalAudit).filter_by(mission_id=m.id)
                                    .order_by(JournalAudit.horodatage.desc()).limit(20)).all()
    jalon_form = JalonForm(formdata=None)
    return render_template("missions/fiche.html", m=m, form=form, historique=historique, jalon_form=jalon_form,
                           actions=LIBELLES_ACTIONS, transitions=TRANSITIONS.get(m.statut, {}),
                           mobilites=MOBILITES, jours_mois=Parametre.jours_ouvres_mois())


# ---------------------------------------------------------------- Affectations

def _controler_affectation(form, m, affectation=None):
    ok = True
    p = db.session.get(Personne, form.personne_id.data) if form.personne_id.data else None
    if not p:
        form.personne_id.errors.append("Choisissez une personne.")
        return False, None
    if p.archive and not (affectation and affectation.personne_id == p.id):
        form.personne_id.errors.append("Cette personne est archivée.")
        ok = False
    if form.date_debut.data and form.date_debut.data < m.date_debut:
        form.date_debut.errors.append(f"La mission commence le {m.date_debut:%d/%m/%Y}.")
        ok = False
    if form.date_fin.data and form.date_fin.data > m.date_fin:
        form.date_fin.errors.append(f"La mission se termine le {m.date_fin:%d/%m/%Y}.")
        ok = False
    if not m.est_forfait and not form.tjm_vente.data:
        form.tjm_vente.errors.append("Le TJM de vente est obligatoire pour une mission en régie.")
        ok = False
    if ok:
        for a in m.affectations:
            if a is affectation or a.personne_id != p.id:
                continue
            if a.date_debut <= form.date_fin.data and a.date_fin >= form.date_debut.data:
                form.date_debut.errors.append(
                    f"{p.nom_complet} est déjà affecté(e) à cette mission du {a.date_debut:%d/%m/%Y} "
                    f"au {a.date_fin:%d/%m/%Y}.")
                ok = False
                break
    return ok, p


def _alerter_surcharge(p, debut, fin, taux, exclure_id=None):
    pic, jour = charge_maximale(p.id, debut, fin, exclure_id=exclure_id, taux_ajoute=taux)
    if pic > 100:
        flash(f"Attention : {p.nom_complet} est occupé(e) à {pic} % le {jour:%d/%m/%Y} "
              f"(plusieurs missions se chevauchent).", "warning")
    if p.disponibilite == "indisponible":
        flash(f"Attention : {p.nom_complet} est marqué(e) indisponible sur sa fiche.", "warning")
    if p.est_cdd and p.date_fin_contrat and fin > p.date_fin_contrat:
        flash(f"Attention : le CDD de {p.nom_complet} se termine le {p.date_fin_contrat:%d/%m/%Y}, "
              f"avant la fin de l'affectation ({fin:%d/%m/%Y}).", "warning")


@bp.route("/<code>/affectations", methods=["POST"])
@admin_requis
def ajouter_affectation(code):
    m = _mission(code)
    if m.statut not in ("preparation", "en_cours"):
        abort(400)
    form = AffectationForm()
    form.personne_id.choices = _choix_personnes(m)
    if form.validate_on_submit():
        ok, p = _controler_affectation(form, m)
        if ok:
            _alerter_surcharge(p, form.date_debut.data, form.date_fin.data, form.taux_occupation.data)
            a = Affectation(personne=p)
            form.populate_obj(a)
            a.tjm_vente = 0 if m.est_forfait else a.tjm_vente
            m.affectations.append(a)
            journaliser("affectation", mission=m, personne=p,
                        details=f"{p.nom_complet} affecté(e) du {a.date_debut:%d/%m/%Y} au "
                                f"{a.date_fin:%d/%m/%Y}, {a.taux_occupation} %"
                                + ("" if m.est_forfait else f", TJM {a.tjm_vente} XAF"))
            db.session.commit()
            flash(f"{p.nom_complet} affecté(e) à la mission.", "success")
            return redirect(url_for(".fiche", code=m.code) + "#affectations")
    erreurs = "; ".join(e for f in form for e in f.errors)
    flash(f"Affectation non enregistrée : {erreurs}", "danger")
    return redirect(url_for(".fiche", code=m.code) + "#affectations")


@bp.route("/<code>/affectations/<int:aid>/modifier", methods=["GET", "POST"])
@admin_requis
def modifier_affectation(code, aid):
    m = _mission(code)
    a = _affectation(m, aid)
    form = AffectationForm(obj=a)
    form.personne_id.choices = _choix_personnes(m, inclure_id=a.personne_id)
    if request.method == "POST":
        form.personne_id.data = a.personne_id  # la personne d'une affectation ne change pas
    if form.validate_on_submit():
        ok, p = _controler_affectation(form, m, affectation=a)
        if ok:
            avant = (a.date_debut, a.date_fin, a.tjm_vente, a.taux_occupation)
            form.populate_obj(a)
            a.personne_id = p.id
            a.tjm_vente = 0 if m.est_forfait else a.tjm_vente
            apres = (a.date_debut, a.date_fin, a.tjm_vente, a.taux_occupation)
            if avant != apres:
                _alerter_surcharge(p, a.date_debut, a.date_fin, a.taux_occupation, exclure_id=a.id)
                journaliser("affectation", mission=m, personne=p,
                            details=f"{p.nom_complet} : {avant[0]:%d/%m/%Y}–{avant[1]:%d/%m/%Y}, "
                                    f"{avant[3]} %, {avant[2]} XAF → {apres[0]:%d/%m/%Y}–"
                                    f"{apres[1]:%d/%m/%Y}, {apres[3]} %, {apres[2]} XAF")
            db.session.commit()
            flash("Affectation mise à jour.", "success")
            return redirect(url_for(".fiche", code=m.code) + "#affectations")
    return render_template("missions/affectation.html", form=form, m=m, a=a)


@bp.route("/<code>/affectations/<int:aid>/supprimer", methods=["POST"])
@admin_requis
def supprimer_affectation(code, aid):
    m = _mission(code)
    a = _affectation(m, aid)
    if m.statut != "preparation":
        flash("Une affectation ne peut être retirée que tant que la mission est en préparation. "
              "Sinon, raccourcissez sa date de fin.", "warning")
    else:
        journaliser("affectation", mission=m, personne=a.personne,
                    details=f"{a.personne.nom_complet} retiré(e) de la mission")
        db.session.delete(a)
        db.session.commit()
        flash("Affectation retirée.", "success")
    return redirect(url_for(".fiche", code=m.code) + "#affectations")


# ---------------------------------------------------------------- Jalons (forfait)

def _jalon(m, jid):
    j = db.get_or_404(Jalon, jid)
    if j.mission_id != m.id:
        abort(404)
    return j


@bp.route("/<code>/jalons", methods=["POST"])
@admin_requis
def ajouter_jalon(code):
    m = _mission(code)
    if not m.est_forfait or m.statut in ("terminee", "annulee"):
        abort(400)
    form = JalonForm()
    if form.validate_on_submit():
        montant = form.montant.data or round((m.montant_forfait or 0) * float(form.pourcentage.data) / 100)
        j = Jalon(libelle=" ".join(form.libelle.data.split()), montant=montant, date_prevue=form.date_prevue.data)
        m.jalons.append(j)
        if m.total_jalons > (m.montant_forfait or 0):
            flash(f"Attention : le total des jalons ({m.total_jalons:,} XAF) dépasse le forfait "
                  f"({m.montant_forfait:,} XAF).".replace(",", "\u202f"), "warning")
        journaliser("jalon", mission=m, details=f"Jalon ajouté : {j.libelle}, {montant} XAF")
        db.session.commit()
    else:
        flash("Jalon non enregistré : " + "; ".join(e for f in form for e in f.errors), "danger")
    return redirect(url_for(".fiche", code=m.code) + "#jalons")


@bp.route("/<code>/jalons/<int:jid>/statut", methods=["POST"])
@admin_requis
def statut_jalon(code, jid):
    m = _mission(code)
    j = _jalon(m, jid)
    nouveau = request.form.get("statut")
    if j.statut == "facture" or nouveau not in ("prevu", "atteint"):
        abort(400)  # « facturé » sera positionné par le module Facturation
    j.statut = nouveau
    j.date_atteint = date.today() if nouveau == "atteint" else None
    journaliser("jalon", mission=m, details=f"Jalon « {j.libelle} » : {j.statut_libelle}")
    db.session.commit()
    return redirect(url_for(".fiche", code=m.code) + "#jalons")


@bp.route("/<code>/jalons/<int:jid>/supprimer", methods=["POST"])
@admin_requis
def supprimer_jalon(code, jid):
    m = _mission(code)
    j = _jalon(m, jid)
    if j.statut != "prevu":
        flash("Seul un jalon encore « prévu » peut être supprimé.", "warning")
    else:
        journaliser("jalon", mission=m, details=f"Jalon supprimé : {j.libelle}, {j.montant} XAF")
        db.session.delete(j)
        db.session.commit()
    return redirect(url_for(".fiche", code=m.code) + "#jalons")


# ---------------------------------------------------------------- Prolongation

def _dernieres_affectations(m):
    """Pour chaque personne, sa dernière période sur la mission, si elle va jusqu'à la fin de la mission."""
    par_personne = {}
    for a in m.affectations:
        if a.personne_id not in par_personne or a.date_fin > par_personne[a.personne_id].date_fin:
            par_personne[a.personne_id] = a
    return [a for a in par_personne.values() if a.date_fin == m.date_fin]


@bp.route("/<code>/prolonger", methods=["GET", "POST"])
@admin_requis
def prolonger(code):
    m = _mission(code)
    if m.statut not in ("preparation", "en_cours"):
        flash("Seule une mission en préparation ou en cours peut être prolongée.", "warning")
        return redirect(url_for(".fiche", code=m.code))
    candidates = _dernieres_affectations(m)
    erreurs = []
    if request.method == "POST":
        try:
            nouvelle_fin = date.fromisoformat(request.form.get("date_fin", ""))
        except ValueError:
            nouvelle_fin = None
        if not nouvelle_fin or nouvelle_fin <= m.date_fin:
            erreurs.append(f"La nouvelle date de fin doit être après le {m.date_fin:%d/%m/%Y}.")
        nouvelles = []
        for a in candidates:
            if request.form.get(f"prolonger_{a.id}"):
                tjm = 0 if m.est_forfait else request.form.get(f"tjm_{a.id}", type=int)
                if not m.est_forfait and (not tjm or tjm < 1):
                    erreurs.append(f"TJM invalide pour {a.personne.nom_complet}.")
                nouvelles.append((a, tjm))
        if not erreurs:
            ancienne_fin = m.date_fin
            m.date_fin = nouvelle_fin
            details = [f"Fin de mission : {ancienne_fin:%d/%m/%Y} → {nouvelle_fin:%d/%m/%Y}"]
            if m.est_forfait and request.form.get("montant_sup", type=int):
                ajout = request.form.get("montant_sup", type=int)
                m.montant_forfait = (m.montant_forfait or 0) + ajout
                details.append(f"Avenant au forfait : +{ajout} XAF")
            if request.form.get("jours_vendus_sup", type=int):
                ajout = request.form.get("jours_vendus_sup", type=int)
                m.jours_vendus = (m.jours_vendus or 0) + ajout
                details.append(f"Jours vendus : +{ajout}")
            for a, tjm in nouvelles:
                _alerter_surcharge(a.personne, a.date_fin + timedelta(days=1), nouvelle_fin, a.taux_occupation)
                suite = Affectation(personne_id=a.personne_id, date_debut=a.date_fin + timedelta(days=1),
                                    date_fin=nouvelle_fin, tjm_vente=tjm,
                                    taux_occupation=a.taux_occupation, prolongation_de=a)
                m.affectations.append(suite)
                revalo = "" if m.est_forfait or tjm == a.tjm_vente else f" (TJM {a.tjm_vente} → {tjm} XAF)"
                details.append(f"{a.personne.nom_complet} prolongé(e) jusqu'au {nouvelle_fin:%d/%m/%Y}{revalo}")
            journaliser("prolongation", mission=m, details="\n".join(details))
            db.session.commit()
            flash(f"Mission prolongée jusqu'au {nouvelle_fin:%d/%m/%Y}.", "success")
            return redirect(url_for(".fiche", code=m.code))
    return render_template("missions/prolonger.html", m=m, candidates=candidates, erreurs=erreurs,
                           proposition=m.date_fin + timedelta(days=90))


# ---------------------------------------------------------------- Paramètres

@bp_parametres.route("/", methods=["GET", "POST"])
@admin_requis
def index():
    form = ParametresForm()
    if request.method == "GET":
        form.jours_ouvres_mois.data = Decimal(str(Parametre.jours_ouvres_mois()))
    if form.validate_on_submit():
        valeur = str(form.jours_ouvres_mois.data.quantize(Decimal("0.01")))
        ancienne = Parametre.lire("jours_ouvres_mois")
        p = db.session.get(Parametre, "jours_ouvres_mois") or Parametre(cle="jours_ouvres_mois", valeur=valeur)
        p.valeur = valeur
        db.session.add(p)
        if ancienne != valeur:
            journaliser("parametre", details=f"Jours ouvrés par mois : {ancienne} → {valeur}")
        db.session.commit()
        flash("Paramètres enregistrés.", "success")
        return redirect(url_for(".index"))
    return render_template("parametres.html", form=form)
