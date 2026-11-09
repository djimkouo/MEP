"""Règles de gestion."""
from datetime import timedelta

from flask import request
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import Affectation, Client, JournalAudit, Mission, Personne

# ---------------------------------------------------------------- Code MEP
# MEP0001 à MEP0100 : réservés au management.
# MEP0101 à MEP9999 : reste du personnel.
# Le code est attribué une fois pour toutes : il ne change pas si la catégorie change,
# et il n'est jamais réutilisé (aucune suppression physique n'est possible dans l'application).

PREFIXE = "MEP"
PLAGES = {"management": (1, 100), "operationnel": (101, 9999)}


class PlageEpuisee(Exception):
    pass


def formater_code(numero):
    return f"{PREFIXE}{numero:04d}"


def prochain_code(categorie):
    debut, fin = PLAGES[categorie]
    dernier = (
        db.session.query(func.max(Personne.code))
        .filter(Personne.code >= formater_code(debut), Personne.code <= formater_code(fin))
        .scalar()
    )
    numero = debut if dernier is None else int(dernier[len(PREFIXE):]) + 1
    if numero > fin:
        libelle = "management" if categorie == "management" else "opérationnelle"
        raise PlageEpuisee(
            f"Plus aucun code disponible dans la plage {libelle} "
            f"({formater_code(debut)} à {formater_code(fin)})."
        )
    return formater_code(numero)


def creer_personne(personne, tentatives=3):
    """Attribue le code MEP et enregistre la personne (gère deux créations simultanées)."""
    for i in range(tentatives):
        with db.session.no_autoflush:
            personne.code = prochain_code(personne.categorie)
        db.session.add(personne)
        try:
            db.session.flush()
            journaliser("creation", personne, f"Code attribué : {personne.code}")
            db.session.commit()
            return personne
        except IntegrityError:
            db.session.rollback()
            if i == tentatives - 1:
                raise
    return personne


# ---------------------------------------------------------------- Audit

def journaliser(action, personne=None, details=None, client=None, mission=None):
    entree = JournalAudit(
        action=action,
        personne_id=personne.id if personne is not None else None,
        client_id=client.id if client is not None else None,
        mission_id=mission.id if mission is not None else None,
        utilisateur_id=current_user.id if current_user and current_user.is_authenticated else None,
        details=details,
        adresse_ip=request.remote_addr if request else None,
    )
    db.session.add(entree)
    return entree


# Champs suivis lors d'une modification ; les valeurs sensibles ne sont jamais écrites dans le journal.
CHAMPS_SUIVIS = [
    "categorie", "nom", "prenom", "date_naissance", "nationalite", "email", "telephone", "ville",
    "linkedin", "piece_type", "piece_numero", "piece_date_delivrance", "piece_date_expiration",
    "piece_pays", "statut", "salaire_mensuel_brut", "date_entree", "date_sortie", "type_contrat", "date_debut_contrat",
    "date_fin_contrat", "motif_cdd", "mission_liee_id", "annees_experience", "disponibilite",
    "disponible_le", "mobilite", "zones_mobilite",
]
CHAMPS_SENSIBLES = {"piece_numero", "salaire_mensuel_brut"}


def instantane(objet, champs=None):
    return {c: getattr(objet, c) for c in (champs or CHAMPS_SUIVIS)}


def decrire_changements(avant, apres, sensibles=CHAMPS_SENSIBLES):
    lignes = []
    for champ in avant:
        if avant.get(champ) != apres.get(champ):
            if champ in sensibles:
                lignes.append(f"{champ} : modifié")
            else:
                lignes.append(f"{champ} : {avant.get(champ) or '—'} → {apres.get(champ) or '—'}")
    return "\n".join(lignes)


# ---------------------------------------------------------------- Module 2 : code client
# CLI0001, CLI0002… simple incrément, jamais réutilisé (aucune suppression de client).

PREFIXE_CLIENT = "CLI"

CHAMPS_CLIENT = [
    "raison_sociale", "sigle", "secteur", "statut", "site_web", "telephone", "adresse", "ville",
    "pays", "rccm", "niu", "adresse_facturation", "delai_paiement", "email_facturation",
]


def _prochain_increment(modele, prefixe):
    codes = db.session.scalars(db.select(modele.code).filter(modele.code.like(f"{prefixe}%"))).all()
    numero = max((int(c[len(prefixe):]) for c in codes), default=0) + 1
    return f"{prefixe}{numero:04d}"


def prochain_code_client():
    return _prochain_increment(Client, PREFIXE_CLIENT)


def creer_client(client, tentatives=3):
    for i in range(tentatives):
        with db.session.no_autoflush:
            client.code = prochain_code_client()
        db.session.add(client)
        try:
            db.session.flush()
            journaliser("creation", client=client, details=f"Code attribué : {client.code}")
            db.session.commit()
            return client
        except IntegrityError:
            db.session.rollback()
            if i == tentatives - 1:
                raise
    return client


# ---------------------------------------------------------------- Module 3 : missions
# MIS0001, MIS0002… simple incrément, jamais réutilisé (aucune suppression de mission).

PREFIXE_MISSION = "MIS"

CHAMPS_MISSION = [
    "intitule", "mode_facturation", "montant_forfait", "livrable", "client_id", "contact_id", "description", "lieu", "mode", "reference_commande",
    "date_debut", "date_fin", "jours_vendus",
]


def creer_mission(mission, tentatives=3):
    for i in range(tentatives):
        with db.session.no_autoflush:
            mission.code = _prochain_increment(Mission, PREFIXE_MISSION)
        db.session.add(mission)
        try:
            db.session.flush()
            journaliser("creation", mission=mission, client=mission.client,
                        details=f"Mission {mission.code} : {mission.intitule}")
            db.session.commit()
            return mission
        except IntegrityError:
            db.session.rollback()
            if i == tentatives - 1:
                raise
    return mission


def activer_client_si_prospect(mission):
    """Un prospect devient client actif dès qu'une de ses missions démarre."""
    c = mission.client
    if c.statut == "prospect":
        c.statut = "actif"
        journaliser("statut", client=c, details=f"Prospect → Actif (démarrage de {mission.code})")
        return True
    return False


def charge_maximale(personne_id, debut, fin, exclure_id=None, taux_ajoute=0):
    """Taux d'occupation cumulé maximal (en %) de la personne sur la période, missions annulées
    et terminées exclues. Renvoie (taux_max, date_du_pic)."""
    q = (db.select(Affectation).join(Mission)
         .filter(Affectation.personne_id == personne_id,
                 Mission.statut.in_(("preparation", "en_cours")),
                 Affectation.date_debut <= fin, Affectation.date_fin >= debut))
    if exclure_id:
        q = q.filter(Affectation.id != exclure_id)
    with db.session.no_autoflush:  # ne pas compter une affectation en cours de création
        autres = db.session.scalars(q).all()
    bornes = sorted({debut} | {a.date_debut for a in autres if a.date_debut >= debut}
                    | {a.date_fin + timedelta(days=1) for a in autres if a.date_fin < fin})
    pic, jour_pic = taux_ajoute, debut
    for jour in bornes:
        if jour > fin:
            continue
        total = taux_ajoute + sum(a.taux_occupation for a in autres if a.date_debut <= jour <= a.date_fin)
        if total > pic:
            pic, jour_pic = total, jour
    return pic, jour_pic
