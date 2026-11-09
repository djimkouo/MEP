from datetime import date, datetime, timedelta, timezone

from flask import current_app
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .crypto import EncryptedString
from .extensions import db


def maintenant():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------- Listes de valeurs

CATEGORIES = {"management": "Management", "operationnel": "Opérationnel"}
STATUTS = {"salarie": "Salarié", "sous_traitant": "Sous-traitant"}
TYPES_CONTRAT = {"cdi": "CDI", "cdd": "CDD"}
TYPES_PIECE = {
    "cni": "Carte nationale d'identité",
    "passeport": "Passeport",
    "titre_sejour": "Titre de séjour",
    "permis": "Permis de conduire",
}
DISPONIBILITES = {  # états affichés et filtrables (calculés)
    "disponible": "Disponible",
    "en_mission": "En mission",
    "indisponible": "Indisponible",
}
DISPONIBILITES_MANUELLES = {"disponible": "Disponible", "indisponible": "Indisponible"}
MOBILITES = {"sur_site": "Sur site", "teletravail": "Télétravail", "hybride": "Hybride"}
CATEGORIES_COMPETENCE = {
    "technique": "Technique",
    "fonctionnel": "Fonctionnel",
    "metier": "Métier",
    "langue": "Langue",
}
NIVEAUX = {1: "Notions", 2: "Opérationnel", 3: "Confirmé", 4: "Expert"}


# ---------------------------------------------------------------- Utilisateurs

class Utilisateur(UserMixin, db.Model):
    __tablename__ = "utilisateur"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    nom = db.Column(db.String(120), nullable=False)
    mot_de_passe_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="admin")
    actif = db.Column(db.Boolean, nullable=False, default=True)

    def definir_mot_de_passe(self, mdp):
        self.mot_de_passe_hash = generate_password_hash(mdp)

    def verifier_mot_de_passe(self, mdp):
        return check_password_hash(self.mot_de_passe_hash, mdp)

    @property
    def est_admin(self):
        return self.role == "admin"

    @property
    def is_active(self):
        return self.actif


# ---------------------------------------------------------------- Personnel

class Personne(db.Model):
    __tablename__ = "personne"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(7), unique=True, nullable=False, index=True)  # MEP0001
    categorie = db.Column(db.String(20), nullable=False)

    # Identification
    nom = db.Column(db.String(120), nullable=False)
    prenom = db.Column(db.String(120), nullable=False)
    date_naissance = db.Column(db.Date)
    nationalite = db.Column(db.String(80))
    email = db.Column(db.String(255), unique=True, nullable=False)
    telephone = db.Column(db.String(40))
    ville = db.Column(db.String(120))
    linkedin = db.Column(db.String(255))

    # Pièce d'identité (le numéro est chiffré en base)
    piece_type = db.Column(db.String(20), nullable=False)
    piece_numero = db.Column(EncryptedString, nullable=False)
    piece_date_delivrance = db.Column(db.Date)
    piece_date_expiration = db.Column(db.Date)
    piece_pays = db.Column(db.String(80))

    # Statut contractuel — montants en XAF
    # Depuis la spécialisation industrielle, tout le personnel est salarié (statut = "salarie").
    # tjm_achat, raison_sociale et num_immatriculation ne sont plus utilisés (conservés pour l'historique).
    statut = db.Column(db.String(20), nullable=False, default="salarie")
    salaire_mensuel_brut = db.Column(db.Integer)
    tjm_achat = db.Column(db.Integer)
    raison_sociale = db.Column(db.String(200))
    num_immatriculation = db.Column(db.String(80))
    date_entree = db.Column(db.Date, nullable=False)
    date_sortie = db.Column(db.Date)
    # Contrat en cours d'un salarié (révision : CDD). Les contrats précédents sont dans ContratHistorique.
    type_contrat = db.Column(db.String(10))           # cdi / cdd (salarié uniquement)
    date_debut_contrat = db.Column(db.Date)           # vide = date d'entrée
    date_fin_contrat = db.Column(db.Date)             # CDD uniquement
    motif_cdd = db.Column(db.String(255))
    mission_liee_id = db.Column(db.Integer, db.ForeignKey("mission.id"))

    # Profil
    annees_experience = db.Column(db.Integer)
    disponibilite = db.Column(db.String(20), nullable=False, default="disponible")
    disponible_le = db.Column(db.Date)  # obsolète depuis le module 3 (calculé), conservé pour compatibilité
    mobilite = db.Column(db.String(20))
    zones_mobilite = db.Column(db.String(255))

    # Cycle de vie
    archive = db.Column(db.Boolean, nullable=False, default=False)
    date_archivage = db.Column(db.DateTime)
    cree_le = db.Column(db.DateTime, nullable=False, default=maintenant)
    cree_par_id = db.Column(db.Integer, db.ForeignKey("utilisateur.id"))
    modifie_le = db.Column(db.DateTime, default=maintenant, onupdate=maintenant)
    modifie_par_id = db.Column(db.Integer, db.ForeignKey("utilisateur.id"))

    cree_par = db.relationship("Utilisateur", foreign_keys=[cree_par_id])
    modifie_par = db.relationship("Utilisateur", foreign_keys=[modifie_par_id])
    competences = db.relationship(
        "PersonneCompetence", back_populates="personne", cascade="all, delete-orphan"
    )
    certifications = db.relationship(
        "Certification", back_populates="personne", cascade="all, delete-orphan",
        order_by="Certification.date_obtention.desc()",
    )
    notes = db.relationship(
        "NoteInterne", back_populates="personne", cascade="all, delete-orphan",
        order_by="NoteInterne.cree_le.desc()",
    )
    affectations = db.relationship("Affectation", back_populates="personne",
                                   order_by="Affectation.date_debut.desc()")
    mission_liee = db.relationship("Mission", foreign_keys=[mission_liee_id])
    contrats_precedents = db.relationship(
        "ContratHistorique", back_populates="personne", cascade="all, delete-orphan",
        order_by="ContratHistorique.date_debut.desc()",
    )

    # -- Contrat
    @property
    def est_cdd(self):
        return self.type_contrat == "cdd"

    @property
    def contrat_libelle(self):
        return TYPES_CONTRAT.get(self.type_contrat or "cdi")

    @property
    def salaire_manquant(self):
        """Personne reprise d'une ancienne version (ex-sous-traitant) sans salaire renseigné."""
        return not self.salaire_mensuel_brut

    @property
    def debut_contrat(self):
        return self.date_debut_contrat or self.date_entree

    @property
    def etat_contrat(self):
        """None | 'echu' (date de fin passée) | 'bientot' (fin sous 30 jours)"""
        if not self.est_cdd or not self.date_fin_contrat:
            return None
        if self.date_fin_contrat < date.today():
            return "echu"
        if self.date_fin_contrat <= date.today() + timedelta(days=current_app.config["ALERTE_CDD_JOURS"]):
            return "bientot"
        return None

    @property
    def cdd_successifs(self):
        """(nombre de CDD successifs jusqu'au contrat en cours, durée cumulée en jours)."""
        if not self.est_cdd:
            return 0, 0
        nombre, jours = 1, ((self.date_fin_contrat or date.today()) - self.debut_contrat).days + 1
        for c in self.contrats_precedents:  # du plus récent au plus ancien
            if c.type_contrat != "cdd":
                break
            nombre += 1
            jours += (c.date_fin - c.date_debut).days + 1 if c.date_fin else 0
        return nombre, jours

    # -- Affichage
    @property
    def nom_complet(self):
        return f"{self.prenom} {self.nom.upper()}"

    @property
    def categorie_libelle(self):
        return CATEGORIES.get(self.categorie, self.categorie)

    @property
    def statut_libelle(self):
        return STATUTS.get(self.statut, self.statut)

    @property
    def piece_type_libelle(self):
        return TYPES_PIECE.get(self.piece_type, self.piece_type)

    @property
    def piece_numero_masque(self):
        n = self.piece_numero or ""
        return "•" * max(len(n) - 3, 3) + n[-3:] if len(n) > 3 else "•••"

    @property
    def competences_principales(self):
        return sorted(self.competences, key=lambda pc: (-pc.niveau, pc.competence.nom))[:3]

    # -- Alertes
    @property
    def etat_piece(self):
        """None | 'expiree' | 'bientot'"""
        if not self.piece_date_expiration:
            return None
        today = date.today()
        if self.piece_date_expiration < today:
            return "expiree"
        seuil = current_app.config["ALERTE_PIECE_JOURS"]
        if self.piece_date_expiration <= today + timedelta(days=seuil):
            return "bientot"
        return None

    # -- Disponibilité (module 3) : calculée à partir des affectations des missions en cours.
    # Le champ « disponibilite » ne sert plus qu'à marquer manuellement une personne indisponible.
    def _affectations_en_cours(self):
        return [a for a in self.affectations if a.mission.statut == "en_cours"]

    @property
    def affectation_courante(self):
        today = date.today()
        courantes = [a for a in self._affectations_en_cours() if a.date_debut <= today <= a.date_fin]
        return max(courantes, key=lambda a: a.date_fin) if courantes else None

    @property
    def libre_le(self):
        """Lendemain de la fin des affectations en cours qui se suivent sans interruption."""
        if not self.affectation_courante:
            return None
        fin = max(a.date_fin for a in self._affectations_en_cours()
                  if a.date_debut <= date.today() <= a.date_fin)
        prolonge = True
        while prolonge:
            prolonge = False
            for a in self._affectations_en_cours():
                if a.date_debut <= fin + timedelta(days=1) and a.date_fin > fin:
                    fin, prolonge = a.date_fin, True
        return fin + timedelta(days=1)

    @property
    def etat_disponibilite(self):
        """'indisponible' | 'en_mission' | 'bientot' | 'disponible'"""
        if self.disponibilite == "indisponible":
            return "indisponible"
        libre = self.libre_le
        if libre:
            seuil = current_app.config["ALERTE_FIN_MISSION_JOURS"]
            return "bientot" if libre <= date.today() + timedelta(days=seuil) else "en_mission"
        return "disponible"

    @property
    def badge_disponibilite(self):
        """(libellé, classe CSS) pour la liste et la fiche."""
        if self.archive:
            return "Archivé", "badge-archive"
        etat = self.etat_disponibilite
        if etat == "indisponible":
            return "Indisponible", "badge-rouge"
        if etat == "bientot":
            return f"Libre le {self.libre_le:%d/%m/%Y}", "badge-orange"
        if etat == "en_mission":
            return "En mission", "badge-gris"
        return "Disponible", "badge-vert"


class Competence(db.Model):
    __tablename__ = "competence"

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(120), nullable=False)
    nom_normalise = db.Column(db.String(120), unique=True, nullable=False)  # anti-doublons
    categorie = db.Column(db.String(20), nullable=False, default="technique")
    actif = db.Column(db.Boolean, nullable=False, default=True)

    personnes = db.relationship("PersonneCompetence", back_populates="competence")

    @staticmethod
    def normaliser(nom):
        return " ".join(nom.lower().split())

    @property
    def categorie_libelle(self):
        return CATEGORIES_COMPETENCE.get(self.categorie, self.categorie)


class PersonneCompetence(db.Model):
    __tablename__ = "personne_competence"
    __table_args__ = (db.UniqueConstraint("personne_id", "competence_id"),)

    id = db.Column(db.Integer, primary_key=True)
    personne_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    competence_id = db.Column(db.Integer, db.ForeignKey("competence.id"), nullable=False)
    niveau = db.Column(db.Integer, nullable=False)  # 1 à 4
    annees = db.Column(db.Integer)

    personne = db.relationship("Personne", back_populates="competences")
    competence = db.relationship("Competence", back_populates="personnes")

    @property
    def niveau_libelle(self):
        return NIVEAUX.get(self.niveau, "?")


class Certification(db.Model):
    __tablename__ = "certification"

    id = db.Column(db.Integer, primary_key=True)
    personne_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    nom = db.Column(db.String(200), nullable=False)
    organisme = db.Column(db.String(200))
    date_obtention = db.Column(db.Date)
    date_expiration = db.Column(db.Date)

    personne = db.relationship("Personne", back_populates="certifications")

    @property
    def expiree(self):
        return bool(self.date_expiration and self.date_expiration < date.today())


class NoteInterne(db.Model):
    __tablename__ = "note_interne"

    id = db.Column(db.Integer, primary_key=True)
    personne_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    texte = db.Column(db.Text, nullable=False)
    auteur_id = db.Column(db.Integer, db.ForeignKey("utilisateur.id"))
    cree_le = db.Column(db.DateTime, nullable=False, default=maintenant)

    personne = db.relationship("Personne", back_populates="notes")
    auteur = db.relationship("Utilisateur")


class JournalAudit(db.Model):
    """Trace des créations, modifications, archivages, exports et consultations sensibles."""

    __tablename__ = "journal_audit"

    id = db.Column(db.Integer, primary_key=True)
    horodatage = db.Column(db.DateTime, nullable=False, default=maintenant, index=True)
    utilisateur_id = db.Column(db.Integer, db.ForeignKey("utilisateur.id"))
    action = db.Column(db.String(40), nullable=False)
    personne_id = db.Column(db.Integer, db.ForeignKey("personne.id"))
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"))  # ajouté au module 2
    mission_id = db.Column(db.Integer, db.ForeignKey("mission.id"))  # ajouté au module 3
    details = db.Column(db.Text)
    adresse_ip = db.Column(db.String(64))

    utilisateur = db.relationship("Utilisateur")
    personne = db.relationship("Personne")
    client = db.relationship("Client")
    mission = db.relationship("Mission")


# ================================================================ Module 2 : clients

SECTEURS = {
    "banque": "Banque",
    "microfinance": "Microfinance",
    "assurance": "Assurance",
    "telecom": "Télécom",
    "administration": "Administration",
    "industrie": "Industrie",
    "agroalimentaire": "Agroalimentaire",
    "autre": "Autre",
}
STATUTS_CLIENT = {"prospect": "Prospect", "actif": "Actif", "inactif": "Inactif"}
ROLES_CONTACT = {"decideur": "Décideur", "operationnel": "Opérationnel", "facturation": "Facturation"}


class Client(db.Model):
    __tablename__ = "client"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(12), unique=True, nullable=False, index=True)  # CLI0001

    # Identification
    raison_sociale = db.Column(db.String(200), nullable=False)
    raison_sociale_normalisee = db.Column(db.String(200), unique=True, nullable=False)
    sigle = db.Column(db.String(60))
    secteur = db.Column(db.String(20), nullable=False, default="banque")
    statut = db.Column(db.String(20), nullable=False, default="prospect")
    site_web = db.Column(db.String(255))
    telephone = db.Column(db.String(40))
    adresse = db.Column(db.String(255))
    ville = db.Column(db.String(120))
    pays = db.Column(db.String(80))

    # Légal et facturation
    rccm = db.Column(db.String(80), unique=True)  # NULL autorisé plusieurs fois
    niu = db.Column(db.String(80))
    adresse_facturation = db.Column(db.Text)
    delai_paiement = db.Column(db.Integer, nullable=False, default=30)  # jours
    email_facturation = db.Column(db.String(255))

    cree_le = db.Column(db.DateTime, nullable=False, default=maintenant)
    cree_par_id = db.Column(db.Integer, db.ForeignKey("utilisateur.id"))
    modifie_le = db.Column(db.DateTime, default=maintenant, onupdate=maintenant)
    modifie_par_id = db.Column(db.Integer, db.ForeignKey("utilisateur.id"))

    cree_par = db.relationship("Utilisateur", foreign_keys=[cree_par_id])
    modifie_par = db.relationship("Utilisateur", foreign_keys=[modifie_par_id])
    contacts = db.relationship(
        "ContactClient", back_populates="client", cascade="all, delete-orphan",
        order_by="(ContactClient.actif.desc(), ContactClient.principal.desc(), ContactClient.nom)",
    )
    notes = db.relationship(
        "NoteClient", back_populates="client", cascade="all, delete-orphan",
        order_by="NoteClient.cree_le.desc()",
    )
    missions = db.relationship("Mission", back_populates="client", order_by="Mission.date_debut.desc()")

    @staticmethod
    def normaliser(nom):
        return " ".join(nom.lower().split())

    @property
    def nom_affiche(self):
        return f"{self.raison_sociale} ({self.sigle})" if self.sigle else self.raison_sociale

    @property
    def secteur_libelle(self):
        return SECTEURS.get(self.secteur, self.secteur)

    @property
    def statut_libelle(self):
        return STATUTS_CLIENT.get(self.statut, self.statut)

    @property
    def badge_statut(self):
        return {"actif": "badge-vert", "prospect": "badge-accent", "inactif": "badge-gris"}.get(
            self.statut, "badge-gris")

    @property
    def contact_principal(self):
        return next((c for c in self.contacts if c.principal and c.actif), None)

    @property
    def contacts_actifs(self):
        return [c for c in self.contacts if c.actif]


class ContactClient(db.Model):
    __tablename__ = "contact_client"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    nom = db.Column(db.String(120), nullable=False)
    prenom = db.Column(db.String(120))
    fonction = db.Column(db.String(120))
    email = db.Column(db.String(255))
    telephone = db.Column(db.String(40))
    role = db.Column(db.String(20), nullable=False, default="operationnel")
    principal = db.Column(db.Boolean, nullable=False, default=False)
    actif = db.Column(db.Boolean, nullable=False, default=True)

    client = db.relationship("Client", back_populates="contacts")

    @property
    def nom_complet(self):
        return f"{self.prenom} {self.nom.upper()}" if self.prenom else self.nom.upper()

    @property
    def role_libelle(self):
        return ROLES_CONTACT.get(self.role, self.role)


class NoteClient(db.Model):
    __tablename__ = "note_client"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    texte = db.Column(db.Text, nullable=False)
    auteur_id = db.Column(db.Integer, db.ForeignKey("utilisateur.id"))
    cree_le = db.Column(db.DateTime, nullable=False, default=maintenant)

    client = db.relationship("Client", back_populates="notes")
    auteur = db.relationship("Utilisateur")


# ================================================================ Module 3 : missions

MODES_FACTURATION = {"regie": "Régie", "forfait": "Forfait"}
STATUTS_JALON = {"prevu": "Prévu", "atteint": "Atteint", "facture": "Facturé"}

STATUTS_MISSION = {
    "preparation": "En préparation",
    "en_cours": "En cours",
    "terminee": "Terminée",
    "annulee": "Annulée",
}


def jours_ouvres(debut, fin):
    """Nombre de jours du lundi au vendredi entre deux dates incluses (jours fériés non déduits)."""
    if not debut or not fin or fin < debut:
        return 0
    total = (fin - debut).days + 1
    semaines, reste = divmod(total, 7)
    jours = semaines * 5
    for i in range(reste):
        if (debut + timedelta(days=semaines * 7 + i)).weekday() < 5:
            jours += 1
    return jours


class Parametre(db.Model):
    """Paramètres modifiables depuis l'écran Paramètres."""

    __tablename__ = "parametre"

    cle = db.Column(db.String(60), primary_key=True)
    valeur = db.Column(db.String(255), nullable=False)

    DEFAUTS = {"jours_ouvres_mois": "21.67"}
    LIBELLES = {"jours_ouvres_mois": "Jours ouvrés par mois (coût journalier d'un salarié)"}

    @classmethod
    def lire(cls, cle):
        p = db.session.get(cls, cle)
        return p.valeur if p else cls.DEFAUTS[cle]

    @classmethod
    def jours_ouvres_mois(cls):
        try:
            v = float(cls.lire("jours_ouvres_mois").replace(",", "."))
            return v if v > 0 else 21.67
        except ValueError:
            return 21.67


mission_competence = db.Table(
    "mission_competence",
    db.Column("mission_id", db.Integer, db.ForeignKey("mission.id"), primary_key=True),
    db.Column("competence_id", db.Integer, db.ForeignKey("competence.id"), primary_key=True),
)


class Mission(db.Model):
    __tablename__ = "mission"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(12), unique=True, nullable=False, index=True)  # MIS0001
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey("contact_client.id"))
    intitule = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    lieu = db.Column(db.String(200))
    mode = db.Column(db.String(20))  # sur_site / teletravail / hybride
    reference_commande = db.Column(db.String(120))
    date_debut = db.Column(db.Date, nullable=False)
    date_fin = db.Column(db.Date, nullable=False)
    jours_vendus = db.Column(db.Integer)  # régie : jours vendus ; forfait : budget en jours
    statut = db.Column(db.String(20), nullable=False, default="preparation")
    # Révision : mode de facturation
    mode_facturation = db.Column(db.String(10), default="regie")  # regie / forfait
    montant_forfait = db.Column(db.Integer)  # XAF
    livrable = db.Column(db.Text)

    cree_le = db.Column(db.DateTime, nullable=False, default=maintenant)
    cree_par_id = db.Column(db.Integer, db.ForeignKey("utilisateur.id"))
    modifie_le = db.Column(db.DateTime, default=maintenant, onupdate=maintenant)

    client = db.relationship("Client", back_populates="missions")
    contact = db.relationship("ContactClient")
    cree_par = db.relationship("Utilisateur", foreign_keys=[cree_par_id])
    competences = db.relationship("Competence", secondary=mission_competence, order_by="Competence.nom")
    affectations = db.relationship(
        "Affectation", back_populates="mission", cascade="all, delete-orphan",
        order_by="(Affectation.personne_id, Affectation.date_debut)",
    )
    jalons = db.relationship("Jalon", back_populates="mission", cascade="all, delete-orphan",
                             order_by="(Jalon.date_prevue.is_(None), Jalon.date_prevue, Jalon.id)")

    @property
    def est_forfait(self):
        return self.mode_facturation == "forfait"

    @property
    def mode_libelle(self):
        return MODES_FACTURATION.get(self.mode_facturation or "regie")

    @property
    def total_jalons(self):
        return sum(j.montant for j in self.jalons)

    @property
    def reste_a_planifier(self):
        return (self.montant_forfait or 0) - self.total_jalons

    @property
    def statut_libelle(self):
        return STATUTS_MISSION.get(self.statut, self.statut)

    @property
    def badge_statut(self):
        return {"preparation": "badge-accent", "en_cours": "badge-vert", "terminee": "badge-gris",
                "annulee": "badge-rouge"}.get(self.statut, "badge-gris")

    @property
    def duree_jours(self):
        """Durée calendaire, début et fin inclus."""
        return (self.date_fin - self.date_debut).days + 1

    @property
    def jours_restants(self):
        return (self.date_fin - date.today()).days

    @property
    def alerte_fin(self):
        """None | 'bientot' | 'depassee' (mission en cours dont la date de fin est passée)"""
        if self.statut != "en_cours":
            return None
        if self.date_fin < date.today():
            return "depassee"
        if self.jours_restants <= current_app.config["ALERTE_FIN_MISSION_JOURS"]:
            return "bientot"
        return None

    @property
    def personnes(self):
        vues, res = set(), []
        for a in sorted(self.affectations, key=lambda a: a.date_debut):
            if a.personne_id not in vues:
                vues.add(a.personne_id)
                res.append(a.personne)
        return res

    @property
    def jours_prevus(self):
        return round(sum(a.jours_prevus for a in self.affectations), 1)

    @property
    def cout_previsionnel(self):
        return round(sum(a.cout_previsionnel for a in self.affectations))

    @property
    def ca_previsionnel(self):
        if self.est_forfait:
            return self.montant_forfait or 0
        return round(sum(a.ca_previsionnel for a in self.affectations))

    @property
    def marge_previsionnelle(self):
        return self.ca_previsionnel - self.cout_previsionnel


class Affectation(db.Model):
    """Une personne sur une mission, pour une période et à un TJM de vente donnés.
    Une prolongation crée une nouvelle affectation : l'historique des périodes et des TJM est conservé."""

    __tablename__ = "affectation"

    id = db.Column(db.Integer, primary_key=True)
    mission_id = db.Column(db.Integer, db.ForeignKey("mission.id"), nullable=False)
    personne_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    date_debut = db.Column(db.Date, nullable=False)
    date_fin = db.Column(db.Date, nullable=False)
    tjm_vente = db.Column(db.Integer, nullable=False, default=0)  # XAF ; 0 = sans objet (forfait)
    taux_occupation = db.Column(db.Integer, nullable=False, default=100)  # %
    prolongation_de_id = db.Column(db.Integer, db.ForeignKey("affectation.id"))

    mission = db.relationship("Mission", back_populates="affectations")
    personne = db.relationship("Personne", back_populates="affectations")
    prolongation_de = db.relationship("Affectation", remote_side=[id])

    @property
    def cout_journalier(self):
        """Option B : salaire mensuel brut / jours ouvrés par mois (0 si le salaire n'est pas renseigné)."""
        p = self.personne
        if p.salaire_mensuel_brut:
            return round(p.salaire_mensuel_brut / Parametre.jours_ouvres_mois())
        return 0

    @property
    def marge_journaliere(self):
        return self.tjm_vente - self.cout_journalier

    @property
    def taux_marge(self):
        return round(100 * self.marge_journaliere / self.tjm_vente, 1) if self.tjm_vente else 0

    @property
    def jours_prevus(self):
        return jours_ouvres(self.date_debut, self.date_fin) * self.taux_occupation / 100

    @property
    def ca_previsionnel(self):
        return 0 if self.mission.est_forfait else self.jours_prevus * self.tjm_vente

    @property
    def cout_previsionnel(self):
        return self.jours_prevus * self.cout_journalier

    @property
    def marge_previsionnelle(self):
        return self.ca_previsionnel - self.cout_previsionnel

    @property
    def depasse_contrat(self):
        """Affectation qui va au-delà de la fin du CDD de la personne."""
        p = self.personne
        return bool(p.est_cdd and p.date_fin_contrat and self.date_fin > p.date_fin_contrat)

    @property
    def est_courante(self):
        return self.mission.statut == "en_cours" and self.date_debut <= date.today() <= self.date_fin


class Jalon(db.Model):
    """Échéance de facturation d'une mission au forfait (acompte, livraison, réception…)."""

    __tablename__ = "jalon"

    id = db.Column(db.Integer, primary_key=True)
    mission_id = db.Column(db.Integer, db.ForeignKey("mission.id"), nullable=False)
    libelle = db.Column(db.String(200), nullable=False)
    montant = db.Column(db.Integer, nullable=False)  # XAF
    date_prevue = db.Column(db.Date)
    statut = db.Column(db.String(10), nullable=False, default="prevu")  # prevu / atteint / facture
    date_atteint = db.Column(db.Date)

    mission = db.relationship("Mission", back_populates="jalons")

    @property
    def pourcentage(self):
        total = self.mission.montant_forfait or 0
        return round(100 * self.montant / total, 1) if total else 0

    @property
    def statut_libelle(self):
        return STATUTS_JALON.get(self.statut, self.statut)

    @property
    def en_retard(self):
        return self.statut == "prevu" and self.date_prevue and self.date_prevue < date.today()


class ContratHistorique(db.Model):
    """Contrat précédent d'un salarié, archivé lors d'un renouvellement de CDD ou d'un passage en CDI."""

    __tablename__ = "contrat_historique"

    id = db.Column(db.Integer, primary_key=True)
    personne_id = db.Column(db.Integer, db.ForeignKey("personne.id"), nullable=False)
    type_contrat = db.Column(db.String(10), nullable=False)
    date_debut = db.Column(db.Date, nullable=False)
    date_fin = db.Column(db.Date)
    motif = db.Column(db.String(255))
    mission_id = db.Column(db.Integer, db.ForeignKey("mission.id"))
    archive_le = db.Column(db.DateTime, nullable=False, default=maintenant)

    personne = db.relationship("Personne", back_populates="contrats_precedents")
    mission = db.relationship("Mission")

    @property
    def type_libelle(self):
        return TYPES_CONTRAT.get(self.type_contrat, self.type_contrat)
