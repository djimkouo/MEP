from datetime import date, timedelta

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField, DateField, DecimalField, IntegerField, PasswordField, SelectField, StringField,
    TextAreaField,
)
from wtforms.validators import URL, DataRequired, Email, Length, NumberRange, Optional

from .models import (
    CATEGORIES, CATEGORIES_COMPETENCE, DISPONIBILITES_MANUELLES, MOBILITES, ROLES_CONTACT, SECTEURS,
    STATUTS_CLIENT, TYPES_CONTRAT, TYPES_PIECE, MODES_FACTURATION,
)


def choix(d, vide=None):
    items = list(d.items())
    return ([("", vide)] if vide else []) + items


class FormulaireFr(FlaskForm):
    class Meta:
        locales = ["fr_FR", "fr"]  # messages d'erreur WTForms en français


class ConnexionForm(FormulaireFr):
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    mot_de_passe = PasswordField("Mot de passe", validators=[DataRequired()])


class PersonneForm(FormulaireFr):
    # Identification
    categorie = SelectField("Catégorie", choices=choix(CATEGORIES), validators=[DataRequired()])
    nom = StringField("Nom", validators=[DataRequired(), Length(max=120)])
    prenom = StringField("Prénom", validators=[DataRequired(), Length(max=120)])
    date_naissance = DateField("Date de naissance", validators=[Optional()])
    nationalite = StringField("Nationalité", validators=[Optional(), Length(max=80)])
    email = StringField("E-mail", validators=[DataRequired(), Email(), Length(max=255)])
    telephone = StringField("Téléphone", validators=[Optional(), Length(max=40)])
    ville = StringField("Ville", validators=[Optional(), Length(max=120)])
    linkedin = StringField("Profil LinkedIn", validators=[Optional(), URL(), Length(max=255)])

    # Pièce d'identité
    piece_type = SelectField("Type de pièce", choices=choix(TYPES_PIECE, "— Choisir —"),
                             validators=[DataRequired(message="Choisissez le type de pièce.")])
    piece_numero = StringField("Numéro de la pièce", validators=[DataRequired(), Length(max=60)])
    piece_date_delivrance = DateField("Délivrée le", validators=[Optional()])
    piece_date_expiration = DateField("Expire le", validators=[Optional()])
    piece_pays = StringField("Pays de délivrance", validators=[Optional(), Length(max=80)])

    # Contrat : tout le personnel est salarié (CDI ou CDD)
    salaire_mensuel_brut = IntegerField("Salaire mensuel brut (XAF)",
                                        validators=[DataRequired(message="Le salaire mensuel brut est obligatoire."),
                                                    NumberRange(min=1)])
    date_entree = DateField("Date d'entrée", validators=[DataRequired()])
    date_sortie = DateField("Date de sortie", validators=[Optional()])
    type_contrat = SelectField("Type de contrat", choices=choix(TYPES_CONTRAT), default="cdi",
                               validators=[DataRequired()])
    date_debut_contrat = DateField("Début du contrat en cours", validators=[Optional()])
    date_fin_contrat = DateField("Fin du CDD", validators=[Optional()])
    motif_cdd = StringField("Motif du CDD", validators=[Optional(), Length(max=255)])
    mission_liee_id = SelectField("Mission liée au CDD", coerce=lambda v: int(v) if v else None,
                                  validators=[Optional()], validate_choice=False)

    # Profil
    annees_experience = IntegerField("Années d'expérience",
                                     validators=[Optional(), NumberRange(min=0, max=60)])
    disponibilite = SelectField("Disponibilité", choices=choix(DISPONIBILITES_MANUELLES))
    mobilite = SelectField("Mode de travail", choices=choix(MOBILITES, "— Non précisé —"),
                           validators=[Optional()])
    zones_mobilite = StringField("Zones géographiques acceptées",
                                 validators=[Optional(), Length(max=255)])

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators)

        if self.type_contrat.data == "cdd":
            if not self.date_fin_contrat.data:
                self.date_fin_contrat.errors.append("La date de fin est obligatoire pour un CDD.")
                ok = False
            debut = self.date_debut_contrat.data or self.date_entree.data
            if debut and self.date_fin_contrat.data and self.date_fin_contrat.data < debut:
                self.date_fin_contrat.errors.append("La fin du CDD doit suivre son début.")
                ok = False
        if self.date_naissance.data and self.date_naissance.data >= date.today():
            self.date_naissance.errors.append("La date de naissance doit être dans le passé.")
            ok = False
        if (self.piece_date_delivrance.data and self.piece_date_expiration.data
                and self.piece_date_expiration.data <= self.piece_date_delivrance.data):
            self.piece_date_expiration.errors.append("La date d'expiration doit suivre la date de délivrance.")
            ok = False
        if self.date_entree.data and self.date_sortie.data and self.date_sortie.data < self.date_entree.data:
            self.date_sortie.errors.append("La date de sortie ne peut pas précéder la date d'entrée.")
            ok = False
        return ok


class CompetenceForm(FormulaireFr):
    nom = StringField("Nom de la compétence", validators=[DataRequired(), Length(max=120)])
    categorie = SelectField("Catégorie", choices=choix(CATEGORIES_COMPETENCE))
    actif = BooleanField("Active", default=True)


class NoteForm(FormulaireFr):
    texte = TextAreaField("Nouvelle note", validators=[DataRequired(), Length(max=5000)])


# ================================================================ Module 2 : clients

class ClientForm(FormulaireFr):
    raison_sociale = StringField("Raison sociale", validators=[DataRequired(), Length(max=200)])
    sigle = StringField("Sigle / nom commercial", validators=[Optional(), Length(max=60)])
    secteur = SelectField("Secteur", choices=choix(SECTEURS), validators=[DataRequired()])
    statut = SelectField("Statut", choices=choix(STATUTS_CLIENT), validators=[DataRequired()])
    site_web = StringField("Site web", validators=[Optional(), URL(), Length(max=255)])
    telephone = StringField("Téléphone (standard)", validators=[Optional(), Length(max=40)])
    adresse = StringField("Adresse", validators=[Optional(), Length(max=255)])
    ville = StringField("Ville", validators=[Optional(), Length(max=120)])
    pays = StringField("Pays", validators=[Optional(), Length(max=80)])

    rccm = StringField("RCCM", validators=[Optional(), Length(max=80)])
    niu = StringField("NIU", validators=[Optional(), Length(max=80)])
    adresse_facturation = TextAreaField("Adresse de facturation", validators=[Optional(), Length(max=1000)])
    delai_paiement = IntegerField("Délai de paiement (jours)",
                                  validators=[DataRequired(), NumberRange(min=0, max=365)], default=30)
    email_facturation = StringField("E-mail de réception des factures",
                                    validators=[Optional(), Email(), Length(max=255)])


class ContactForm(FormulaireFr):
    prenom = StringField("Prénom", validators=[Optional(), Length(max=120)])
    nom = StringField("Nom", validators=[DataRequired(), Length(max=120)])
    fonction = StringField("Fonction", validators=[Optional(), Length(max=120)])
    email = StringField("E-mail", validators=[Optional(), Email(), Length(max=255)])
    telephone = StringField("Téléphone", validators=[Optional(), Length(max=40)])
    role = SelectField("Rôle", choices=choix(ROLES_CONTACT))
    principal = BooleanField("Contact principal")
    actif = BooleanField("Actif", default=True)

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators)
        if not (self.email.data or self.telephone.data):
            self.email.errors.append("Renseignez au moins un e-mail ou un téléphone.")
            ok = False
        return ok


# ================================================================ Module 3 : missions

class MissionForm(FormulaireFr):
    client_id = SelectField("Client", coerce=int, validators=[DataRequired(message="Choisissez le client.")])
    contact_id = SelectField("Interlocuteur côté client", coerce=lambda v: int(v) if v else None,
                             validators=[Optional()], validate_choice=False)  # contrôlé dans la vue
    intitule = StringField("Intitulé de la mission", validators=[DataRequired(), Length(max=200)])
    mode_facturation = SelectField("Mode de facturation", choices=choix(MODES_FACTURATION), default="regie")
    montant_forfait = IntegerField("Montant du forfait (XAF)", validators=[Optional(), NumberRange(min=1)])
    livrable = TextAreaField("Livrable attendu", validators=[Optional(), Length(max=5000)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=5000)])
    lieu = StringField("Lieu", validators=[Optional(), Length(max=200)])
    mode = SelectField("Mode de travail", choices=choix(MOBILITES, "— Non précisé —"), validators=[Optional()])
    reference_commande = StringField("Référence bon de commande / contrat",
                                     validators=[Optional(), Length(max=120)])
    date_debut = DateField("Date de début", validators=[DataRequired()])
    duree_jours = IntegerField("Durée de la mission (jours)", validators=[Optional(), NumberRange(min=1, max=3650)])
    date_fin = DateField("Date de fin prévue", validators=[Optional()])
    jours_vendus = IntegerField("Jours vendus / budget en jours",
                                validators=[Optional(), NumberRange(min=1, max=10000)])

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators)
        # Durée et date de fin sont liées : la durée (jours calendaires, début et fin inclus) fait foi
        # quand elle est saisie, la date de fin est alors recalculée.
        if self.date_debut.data and self.duree_jours.raw_data and self.duree_jours.data:
            self.date_fin.data = self.date_debut.data + timedelta(days=self.duree_jours.data - 1)
        if not self.date_fin.data:
            self.date_fin.errors.append("Indiquez la date de fin ou la durée de la mission.")
            ok = False
        if self.date_debut.data and self.date_fin.data and self.date_fin.data < self.date_debut.data:
            self.date_fin.errors.append("La date de fin doit suivre la date de début.")
            ok = False
        if self.mode_facturation.data == "forfait":
            if not self.montant_forfait.data:
                self.montant_forfait.errors.append("Le montant est obligatoire pour une mission au forfait.")
                ok = False
            if not (self.livrable.data or "").strip():
                self.livrable.errors.append("Décrivez le livrable attendu.")
                ok = False
        return ok


class AffectationForm(FormulaireFr):
    personne_id = SelectField("Personne", coerce=int, validators=[DataRequired(message="Choisissez une personne.")])
    date_debut = DateField("Du", validators=[DataRequired()])
    date_fin = DateField("Au", validators=[DataRequired()])
    tjm_vente = IntegerField("TJM de vente (XAF)", validators=[Optional(), NumberRange(min=1)])
    taux_occupation = IntegerField("Occupation (%)", default=100,
                                   validators=[DataRequired(), NumberRange(min=1, max=100)])

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators)
        if self.date_debut.data and self.date_fin.data and self.date_fin.data < self.date_debut.data:
            self.date_fin.errors.append("La date de fin doit suivre la date de début.")
            ok = False
        return ok


class ParametresForm(FormulaireFr):
    jours_ouvres_mois = DecimalField("Jours ouvrés par mois", places=2,
                                     validators=[DataRequired(), NumberRange(min=1, max=31)])



class JalonForm(FormulaireFr):
    libelle = StringField("Jalon", validators=[DataRequired(), Length(max=200)])
    montant = IntegerField("Montant (XAF)", validators=[Optional(), NumberRange(min=1)])
    pourcentage = DecimalField("ou % du forfait", places=2, validators=[Optional(), NumberRange(min=0.01, max=100)])
    date_prevue = DateField("Date prévue", validators=[Optional()])

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators)
        if not self.montant.data and not self.pourcentage.data:
            self.montant.errors.append("Indiquez un montant ou un pourcentage.")
            ok = False
        return ok


class ContratForm(FormulaireFr):
    action = SelectField("Action", choices=[("renouveler", "Renouveler le CDD"), ("cdi", "Passer en CDI")])
    date_debut = DateField("Début du nouveau contrat", validators=[DataRequired()])
    date_fin = DateField("Fin du nouveau CDD", validators=[Optional()])
    motif = StringField("Motif", validators=[Optional(), Length(max=255)])
    mission_liee_id = SelectField("Mission liée", coerce=lambda v: int(v) if v else None,
                                  validators=[Optional()], validate_choice=False)
    salaire_mensuel_brut = IntegerField("Nouveau salaire mensuel brut (XAF)",
                                        validators=[Optional(), NumberRange(min=1)])

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators)
        if self.action.data == "renouveler":
            if not self.date_fin.data:
                self.date_fin.errors.append("La date de fin est obligatoire pour un CDD.")
                ok = False
            elif self.date_debut.data and self.date_fin.data < self.date_debut.data:
                self.date_fin.errors.append("La fin doit suivre le début.")
                ok = False
        return ok
