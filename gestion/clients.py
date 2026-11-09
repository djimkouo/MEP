"""Module 2 : référentiel des clients."""
import csv
import io

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_

from .auth import admin_requis
from .extensions import db
from .forms import ClientForm, ContactForm, NoteForm
from .models import (
    SECTEURS, STATUTS_CLIENT, Client, ContactClient, JournalAudit, NoteClient,
)
from .services import CHAMPS_CLIENT, creer_client, decrire_changements, instantane, journaliser

bp = Blueprint("clients", __name__, url_prefix="/clients")

LIBELLES_ACTIONS = {
    "creation": "Création", "modification": "Modification", "statut": "Changement de statut",
    "export": "Export",
}


def _client(code):
    c = db.session.scalar(db.select(Client).filter_by(code=code.upper()))
    if c is None:
        abort(404)
    return c


def _contact(client, cid):
    ct = db.get_or_404(ContactClient, cid)
    if ct.client_id != client.id:
        abort(404)
    return ct


def _normaliser_rccm(v):
    v = " ".join((v or "").split()).upper()
    return v or None


def _controler_unicite(form, sauf_id=None):
    ok = True
    q = db.select(Client.code).filter(
        Client.raison_sociale_normalisee == Client.normaliser(form.raison_sociale.data))
    if sauf_id:
        q = q.filter(Client.id != sauf_id)
    doublon = db.session.scalar(q)
    if doublon:
        form.raison_sociale.errors.append(f"Un client porte déjà cette raison sociale ({doublon}).")
        ok = False
    rccm = _normaliser_rccm(form.rccm.data)
    if rccm:
        q = db.select(Client.code).filter(Client.rccm == rccm)
        if sauf_id:
            q = q.filter(Client.id != sauf_id)
        doublon = db.session.scalar(q)
        if doublon:
            form.rccm.errors.append(f"Ce RCCM est déjà utilisé par le client {doublon}.")
            ok = False
    return ok


def _appliquer(form, c):
    form.populate_obj(c)
    c.raison_sociale = " ".join(c.raison_sociale.split())
    c.raison_sociale_normalisee = Client.normaliser(c.raison_sociale)
    c.rccm = _normaliser_rccm(c.rccm)
    c.niu = (c.niu or "").strip().upper() or None
    c.email_facturation = (c.email_facturation or "").strip().lower() or None
    for champ in ("sigle", "site_web", "telephone", "adresse", "ville", "pays", "adresse_facturation"):
        setattr(c, champ, (getattr(c, champ) or "").strip() or None)


# ---------------------------------------------------------------- Liste

def _requete(args):
    q = db.select(Client)
    statut = args.get("statut")
    if statut in STATUTS_CLIENT:
        q = q.filter(Client.statut == statut)
    elif not args.get("inactifs"):
        q = q.filter(Client.statut != "inactif")
    if args.get("secteur") in SECTEURS:
        q = q.filter(Client.secteur == args["secteur"])
    terme = (args.get("q") or "").strip()
    if terme:
        like = f"%{terme}%"
        q = q.filter(or_(
            Client.raison_sociale.ilike(like), Client.sigle.ilike(like), Client.code.ilike(like),
            Client.ville.ilike(like), Client.rccm.ilike(like),
            Client.contacts.any(or_(ContactClient.nom.ilike(like), ContactClient.prenom.ilike(like),
                                    ContactClient.email.ilike(like))),
        ))
    return q.order_by(Client.raison_sociale)


@bp.route("/")
@admin_requis
def liste():
    clients = db.session.scalars(_requete(request.args)).all()
    tous = db.session.scalars(db.select(Client)).all()
    stats = {k: sum(1 for c in tous if c.statut == k) for k in STATUTS_CLIENT}
    filtres_actifs = any(request.args.get(k) for k in ("q", "statut", "secteur", "inactifs"))
    return render_template("clients/liste.html", clients=clients, stats=stats, secteurs=SECTEURS,
                           statuts=STATUTS_CLIENT, filtres_actifs=filtres_actifs)


@bp.route("/export.csv")
@admin_requis
def export_csv():
    clients = db.session.scalars(_requete(request.args)).all()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Code", "Raison sociale", "Sigle", "Secteur", "Statut", "Ville", "Pays", "RCCM", "NIU",
                "Délai de paiement (j)", "E-mail facturation", "Contact principal", "E-mail contact",
                "Téléphone contact"])
    for c in clients:
        cp = c.contact_principal
        w.writerow([c.code, c.raison_sociale, c.sigle or "", c.secteur_libelle, c.statut_libelle,
                    c.ville or "", c.pays or "", c.rccm or "", c.niu or "", c.delai_paiement,
                    c.email_facturation or "", cp.nom_complet if cp else "",
                    (cp.email or "") if cp else "", (cp.telephone or "") if cp else ""])
    journaliser("export", details=f"Export CSV de {len(clients)} client(s)")
    db.session.commit()
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=clients.csv"})


# ---------------------------------------------------------------- Création / modification

@bp.route("/nouveau", methods=["GET", "POST"])
@admin_requis
def nouveau():
    form = ClientForm()
    if request.method == "GET":
        form.statut.data = "prospect"
        form.secteur.data = "banque"
    if form.validate_on_submit() and _controler_unicite(form):
        c = Client(cree_par_id=current_user.id, modifie_par_id=current_user.id)
        _appliquer(form, c)
        creer_client(c)
        flash(f"{c.raison_sociale} a été enregistré sous le code {c.code}.", "success")
        return redirect(url_for(".fiche", code=c.code))
    return render_template("clients/formulaire.html", form=form, client=None)


@bp.route("/<code>/modifier", methods=["GET", "POST"])
@admin_requis
def modifier(code):
    c = _client(code)
    form = ClientForm(obj=c)
    if form.validate_on_submit() and _controler_unicite(form, sauf_id=c.id):
        avant = instantane(c, CHAMPS_CLIENT)
        _appliquer(form, c)  # le code client n'est jamais modifié
        c.modifie_par_id = current_user.id
        changements = decrire_changements(avant, instantane(c, CHAMPS_CLIENT), sensibles=())
        if changements:
            journaliser("modification", client=c, details=changements)
        db.session.commit()
        flash("Fiche client mise à jour." if changements else "Aucune modification.", "success")
        return redirect(url_for(".fiche", code=c.code))
    return render_template("clients/formulaire.html", form=form, client=c)


@bp.route("/<code>/statut", methods=["POST"])
@admin_requis
def changer_statut(code):
    c = _client(code)
    nouveau_statut = request.form.get("statut")
    if nouveau_statut not in STATUTS_CLIENT:
        abort(400)
    if nouveau_statut != c.statut:
        journaliser("statut", client=c,
                    details=f"{STATUTS_CLIENT[c.statut]} → {STATUTS_CLIENT[nouveau_statut]}")
        c.statut = nouveau_statut
        c.modifie_par_id = current_user.id
        db.session.commit()
        flash(f"Statut passé à « {STATUTS_CLIENT[nouveau_statut]} ».", "success")
    return redirect(url_for(".fiche", code=c.code))


# ---------------------------------------------------------------- Fiche

@bp.route("/<code>")
@admin_requis
def fiche(code):
    c = _client(code)
    historique = db.session.scalars(
        db.select(JournalAudit).filter_by(client_id=c.id)
        .order_by(JournalAudit.horodatage.desc()).limit(15)).all()
    contact_form = ContactForm(formdata=None)
    contact_form.actif.data = True
    contact_form.principal.data = not c.contacts_actifs
    return render_template("clients/fiche.html", c=c, contact_form=contact_form,
                           note_form=NoteForm(formdata=None), historique=historique,
                           actions=LIBELLES_ACTIONS, statuts=STATUTS_CLIENT)


# ---------------------------------------------------------------- Contacts

def _rendre_principal(client, contact):
    for autre in client.contacts:
        autre.principal = autre is contact


def _enregistrer_contact(form, ct):
    form.populate_obj(ct)
    ct.nom = ct.nom.strip()
    ct.prenom = (ct.prenom or "").strip() or None
    ct.email = (ct.email or "").strip().lower() or None
    ct.fonction = (ct.fonction or "").strip() or None
    ct.telephone = (ct.telephone or "").strip() or None
    if not ct.actif:
        ct.principal = False


@bp.route("/<code>/contacts", methods=["POST"])
@admin_requis
def ajouter_contact(code):
    c = _client(code)
    form = ContactForm()
    if form.validate_on_submit():
        ct = ContactClient()
        _enregistrer_contact(form, ct)
        c.contacts.append(ct)
        if ct.principal or not any(x.principal and x.actif for x in c.contacts if x is not ct):
            if ct.actif:
                _rendre_principal(c, ct)
        journaliser("modification", client=c, details=f"Contact ajouté : {ct.nom_complet}")
        db.session.commit()
        flash("Contact ajouté.", "success")
    else:
        erreurs = "; ".join(e for f in form for e in f.errors)
        flash(f"Contact non enregistré : {erreurs}", "danger")
    return redirect(url_for(".fiche", code=c.code) + "#contacts")


@bp.route("/<code>/contacts/<int:cid>/modifier", methods=["GET", "POST"])
@admin_requis
def modifier_contact(code, cid):
    c = _client(code)
    ct = _contact(c, cid)
    form = ContactForm(obj=ct)
    if form.validate_on_submit():
        _enregistrer_contact(form, ct)
        if ct.principal:
            _rendre_principal(c, ct)
        journaliser("modification", client=c, details=f"Contact modifié : {ct.nom_complet}")
        db.session.commit()
        flash("Contact mis à jour.", "success")
        return redirect(url_for(".fiche", code=c.code) + "#contacts")
    return render_template("clients/contact.html", form=form, c=c, contact=ct)


@bp.route("/<code>/contacts/<int:cid>/principal", methods=["POST"])
@admin_requis
def definir_principal(code, cid):
    c = _client(code)
    ct = _contact(c, cid)
    if ct.actif:
        _rendre_principal(c, ct)
        journaliser("modification", client=c, details=f"Contact principal : {ct.nom_complet}")
        db.session.commit()
    return redirect(url_for(".fiche", code=c.code) + "#contacts")


@bp.route("/<code>/contacts/<int:cid>/activation", methods=["POST"])
@admin_requis
def basculer_contact(code, cid):
    c = _client(code)
    ct = _contact(c, cid)
    ct.actif = not ct.actif
    if not ct.actif:
        ct.principal = False
    journaliser("modification", client=c,
                details=f"Contact {'réactivé' if ct.actif else 'désactivé'} : {ct.nom_complet}")
    db.session.commit()
    return redirect(url_for(".fiche", code=c.code) + "#contacts")


@bp.route("/<code>/notes", methods=["POST"])
@admin_requis
def ajouter_note(code):
    c = _client(code)
    form = NoteForm()
    if form.validate_on_submit():
        c.notes.append(NoteClient(texte=form.texte.data.strip(), auteur_id=current_user.id))
        db.session.commit()
    else:
        flash("La note est vide.", "warning")
    return redirect(url_for(".fiche", code=c.code) + "#notes")
