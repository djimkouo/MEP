"""Données fictives pour tester l'application."""
from datetime import date, timedelta

from .extensions import db
from .models import (
    Affectation, Certification, Client, Competence, ContactClient, Jalon, Mission, Personne,
    PersonneCompetence, Utilisateur,
)
from .services import creer_client, creer_mission, creer_personne

COMPETENCES = [
    ("ISO 20022", "metier"), ("Swift MT", "metier"), ("Monétique", "metier"),
    ("Core banking (T24)", "fonctionnel"), ("Business analysis", "fonctionnel"),
    ("Gestion de projet", "fonctionnel"), ("Java", "technique"), ("Python", "technique"),
    ("SQL", "technique"), ("Oracle", "technique"), ("Anglais", "langue"), ("Français", "langue"),
    ("Maintenance industrielle", "metier"), ("Automatisme", "technique"),
]

j = date.today()
PERSONNES = [
    dict(categorie="management", nom="Ndongo", prenom="Armel", email="armel.ndongo@exemple.cm",
         ville="Douala", statut="salarie", salaire_mensuel_brut=2_500_000, piece_type="cni",
         piece_numero="CM1029384756", piece_date_expiration=j + timedelta(days=900),
         disponibilite="indisponible", date_entree=date(2021, 3, 1), annees_experience=18,
         comp=[("Gestion de projet", 4), ("Anglais", 3)]),
    dict(categorie="management", nom="Biyong", prenom="Sandrine", email="sandrine.biyong@exemple.cm",
         ville="Yaoundé", statut="salarie", salaire_mensuel_brut=1_900_000, piece_type="passeport",
         piece_numero="AA0478123", piece_date_expiration=j + timedelta(days=40),
         disponibilite="indisponible", date_entree=date(2022, 1, 10), annees_experience=14,
         comp=[("Business analysis", 4)]),
    dict(categorie="operationnel", nom="Tchoua", prenom="Hervé", email="herve.tchoua@exemple.cm",
         ville="Douala", statut="salarie", salaire_mensuel_brut=950_000, piece_type="cni",
         piece_numero="CM5566778899", piece_date_expiration=j + timedelta(days=1200),
         disponibilite="disponible", mobilite="hybride",
         date_entree=date(2023, 5, 2), annees_experience=7,
         comp=[("ISO 20022", 4), ("Swift MT", 3), ("SQL", 3)]),
    dict(categorie="operationnel", nom="Mballa", prenom="Christelle", email="christelle.mballa@exemple.cm",
         ville="Yaoundé", statut="salarie", salaire_mensuel_brut=1_800_000,
         num_immatriculation="RC/YAO/2020/B/1234", piece_type="cni", piece_numero="CM1122334455",
         piece_date_expiration=j + timedelta(days=700), disponibilite="disponible", mobilite="teletravail",
         date_entree=date(2024, 2, 1), annees_experience=10,
         comp=[("Core banking (T24)", 4), ("Business analysis", 3), ("Anglais", 3)]),
    dict(categorie="operationnel", nom="Ekane", prenom="Joël", email="joel.ekane@exemple.cm",
         ville="Libreville", statut="salarie", salaire_mensuel_brut=780_000, piece_type="passeport",
         piece_numero="GA9988776", piece_date_expiration=j - timedelta(days=12),
         disponibilite="disponible", mobilite="sur_site",
         date_entree=date(2024, 9, 16), annees_experience=4, comp=[("Java", 3), ("Oracle", 2)]),
    dict(categorie="operationnel", nom="Fotso", prenom="Laure", email="laure.fotso@exemple.cm",
         ville="Douala", statut="salarie", salaire_mensuel_brut=1_500_000, type_contrat="cdd",
         date_fin_contrat=j + timedelta(days=300), motif_cdd="Projet monétique",
         piece_type="cni", piece_numero="CM6677889900", piece_date_expiration=j + timedelta(days=500),
         disponibilite="disponible", mobilite="hybride",
         date_entree=date(2025, 6, 1), annees_experience=6,
         comp=[("Monétique", 4), ("ISO 20022", 2), ("Python", 3)]),
    dict(categorie="operationnel", nom="Ngo Bassa", prenom="Ruth", email="ruth.ngobassa@exemple.cm",
         ville="Douala", statut="salarie", salaire_mensuel_brut=650_000, piece_type="cni",
         piece_numero="CM2233445566", piece_date_expiration=j + timedelta(days=1500),
         disponibilite="disponible", mobilite="sur_site",
         date_entree=date(2025, 1, 6), annees_experience=3, comp=[("SQL", 3), ("Python", 2)]),
    dict(categorie="operationnel", nom="Ngando", prenom="Patrick", email="patrick.ngando@exemple.cm",
         ville="Douala", statut="salarie", salaire_mensuel_brut=450_000, type_contrat="cdd",
         date_debut_contrat=j - timedelta(days=95), date_fin_contrat=j + timedelta(days=25),
         motif_cdd="Chantier ligne d'embouteillage n° 2", piece_type="cni", piece_numero="CM7788990011",
         piece_date_expiration=j + timedelta(days=1100), disponibilite="disponible", mobilite="sur_site",
         date_entree=j - timedelta(days=95), annees_experience=5,
         comp=[("Maintenance industrielle", 4), ("Automatisme", 3)]),
]


def charger():
    if not db.session.scalar(db.select(Utilisateur).filter_by(email="admin@exemple.cm")):
        u = Utilisateur(email="admin@exemple.cm", nom="Administrateur", role="admin")
        u.definir_mot_de_passe("admin1234")
        db.session.add(u)
    comps = {}
    for nom, cat in COMPETENCES:
        c = db.session.scalar(db.select(Competence).filter_by(nom_normalise=Competence.normaliser(nom)))
        if not c:
            c = Competence(nom=nom, nom_normalise=Competence.normaliser(nom), categorie=cat)
            db.session.add(c)
        comps[nom] = c
    db.session.commit()

    for d in PERSONNES:
        d = dict(d)
        if db.session.scalar(db.select(Personne).filter_by(email=d["email"])):
            continue
        liste = d.pop("comp")
        p = Personne(**d)
        for nom, niv in liste:
            p.competences.append(PersonneCompetence(competence=comps[nom], niveau=niv))
        if d["email"].startswith("herve"):
            p.certifications.append(Certification(nom="Swift Certified Specialist", organisme="Swift",
                                                  date_obtention=date(2024, 4, 10)))
        creer_personne(p)
    charger_clients()
    charger_missions()


CLIENTS = [
    dict(raison_sociale="Banque Atlantique du Littoral", sigle="BAL", secteur="banque", statut="actif",
         ville="Douala", pays="Cameroun", rccm="RC/DLA/2008/B/0451", niu="M040812345678A",
         delai_paiement=45, email_facturation="factures@bal-exemple.cm",
         contacts=[("Paul", "Essomba", "DSI adjoint", "decideur", "p.essomba@bal-exemple.cm", True),
                   ("Inès", "Kamga", "Chef de projet paiements", "operationnel", "i.kamga@bal-exemple.cm", False),
                   ("Marc", "Ondoa", "Comptabilité fournisseurs", "facturation", "compta@bal-exemple.cm", False)]),
    dict(raison_sociale="Crédit Mutuel des Hauts Plateaux", sigle="CMHP", secteur="microfinance",
         statut="actif", ville="Bafoussam", pays="Cameroun", rccm="RC/BAF/2012/B/0098", delai_paiement=30,
         contacts=[("Thérèse", "Fokou", "Directrice des opérations", "decideur", "t.fokou@cmhp-exemple.cm", True)]),
    dict(raison_sociale="Gabon Trust Bank", sigle="GTB", secteur="banque", statut="prospect",
         ville="Libreville", pays="Gabon", delai_paiement=60,
         contacts=[("Serge", "Mba", "Directeur des systèmes d'information", "decideur", "s.mba@gtb-exemple.ga", True)]),
    dict(raison_sociale="Assurances Centrales du Golfe", sigle="ACG", secteur="assurance", statut="prospect",
         ville="Douala", pays="Cameroun", delai_paiement=30, contacts=[]),
    dict(raison_sociale="Société Agro-Industrielle du Moungo", sigle="SAIM", secteur="agroalimentaire",
         statut="actif", ville="Njombé", pays="Cameroun", rccm="RC/NKS/2011/B/0077", delai_paiement=45,
         contacts=[("Jean-Paul", "Ebelle", "Directeur d'usine", "decideur", "jp.ebelle@saim-exemple.cm", True)]),
    dict(raison_sociale="Télécom Équatorial", secteur="telecom", statut="inactif", ville="Yaoundé",
         pays="Cameroun", delai_paiement=30,
         contacts=[("Alain", "Nkoulou", "Responsable achats", "facturation", "achats@te-exemple.cm", True)]),
]


def charger_clients():
    for d in CLIENTS:
        d = dict(d)
        contacts = d.pop("contacts")
        if db.session.scalar(db.select(Client).filter_by(
                raison_sociale_normalisee=Client.normaliser(d["raison_sociale"]))):
            continue
        c = Client(raison_sociale_normalisee=Client.normaliser(d["raison_sociale"]), **d)
        for prenom, nom, fonction, role, email, principal in contacts:
            c.contacts.append(ContactClient(prenom=prenom, nom=nom, fonction=fonction, role=role,
                                            email=email, principal=principal))
        creer_client(c)


def charger_missions():
    if db.session.scalar(db.select(Mission.id)):
        return
    def client(sigle):
        return db.session.scalar(db.select(Client).filter_by(sigle=sigle))
    def personne(email_debut):
        return db.session.scalar(db.select(Personne).filter(Personne.email.like(f"{email_debut}%")))
    def comp(*noms):
        return [db.session.scalar(db.select(Competence).filter_by(nom=n)) for n in noms]

    missions = [
        dict(client="BAL", intitule="Migration ISO 20022 des virements SWIFT", statut="en_cours",
             debut=j - timedelta(days=150), fin=j + timedelta(days=18), jours_vendus=190,
             reference_commande="BC-2026-0142", lieu="Douala, siège BAL", mode="hybride",
             competences=comp("ISO 20022", "Swift MT"),
             affectations=[("herve", 90_000, 100, None), ("ruth", 55_000, 50, None)]),
        dict(client="CMHP", intitule="Paramétrage du core banking T24", statut="en_cours",
             debut=j - timedelta(days=60), fin=j + timedelta(days=140), jours_vendus=None,
             lieu="Bafoussam", mode="sur_site", competences=comp("Core banking (T24)", "Java"),
             affectations=[("joel", 65_000, 100, None)]),
        dict(client="GTB", intitule="Audit de la chaîne monétique", statut="preparation",
             debut=j + timedelta(days=20), fin=j + timedelta(days=80), jours_vendus=40,
             lieu="Libreville", mode="hybride", competences=comp("Monétique", "Business analysis"),
             affectations=[("laure", 175_000, 100, None), ("christelle", 195_000, 50, None)]),
        dict(client="SAIM", intitule="Mise en service de la ligne d'embouteillage n° 2", statut="en_cours",
             debut=j - timedelta(days=40), fin=j + timedelta(days=45), jours_vendus=95, lieu="Njombé, usine",
             mode="sur_site", competences=comp("Maintenance industrielle", "Automatisme"),
             forfait=6_500_000, livrable="Ligne n° 2 installée, testée et réceptionnée par le client (PV de réception).",
             jalons=[("Acompte à la commande", 30, j - timedelta(days=40), True),
                     ("Fin d'installation", 40, j + timedelta(days=15), False),
                     ("Réception de la ligne", 30, j + timedelta(days=45), False)],
             affectations=[("patrick", 0, 100, None), ("ruth", 0, 50, None)]),
    ]
    for d in missions:
        with db.session.no_autoflush:
            m = Mission(client=client(d["client"]), intitule=d["intitule"], statut="preparation",
                        date_debut=d["debut"], date_fin=d["fin"], jours_vendus=d["jours_vendus"],
                        reference_commande=d.get("reference_commande"), lieu=d["lieu"], mode=d["mode"],
                        competences=d["competences"], contact=client(d["client"]).contact_principal)
            if d.get("forfait"):
                m.mode_facturation, m.montant_forfait, m.livrable = "forfait", d["forfait"], d["livrable"]
                for lib, pct, dt, atteint in d["jalons"]:
                    m.jalons.append(Jalon(libelle=lib, montant=d["forfait"] * pct // 100, date_prevue=dt,
                                          statut="atteint" if atteint else "prevu",
                                          date_atteint=dt if atteint else None))
            for qui, tjm, taux, _ in d["affectations"]:
                m.affectations.append(Affectation(personne=personne(qui), date_debut=d["debut"],
                                                  date_fin=d["fin"], tjm_vente=tjm, taux_occupation=taux))
        creer_mission(m)
        if d.get("forfait"):
            p = personne("patrick")
            p.mission_liee_id = m.id
        if d["statut"] == "en_cours":
            m.statut = "en_cours"
            if m.client.statut == "prospect":
                m.client.statut = "actif"
    db.session.commit()
