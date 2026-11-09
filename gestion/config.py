import os


class Config:
    # En production, ces trois valeurs DOIVENT être fournies par variables d'environnement.
    # En développement, si elles sont absentes, elles sont générées dans le dossier instance/.
    SECRET_KEY = os.environ.get("SECRET_KEY")
    FERNET_KEY = os.environ.get("FERNET_KEY")  # clé de chiffrement des numéros de pièce
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    WTF_I18N_ENABLED = False  # utilise les traductions intégrées de WTForms (Meta.locales)
    DEVISE = "XAF"
    ALERTE_PIECE_JOURS = 60        # alerte quand une pièce expire dans moins de N jours
    ALERTE_FIN_MISSION_JOURS = 30
    ALERTE_CDD_JOURS = 30          # alerte quand un CDD se termine dans moins de N jours  # badge orange quand la personne se libère dans moins de N jours
