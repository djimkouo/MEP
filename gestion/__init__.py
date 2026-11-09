import os
import secrets
from datetime import date, datetime

import click
from cryptography.fernet import Fernet
from flask import Flask, redirect, url_for

from . import crypto
from .extensions import csrf, db, login_manager


def _secret_instance(app, nom, generateur):
    """Lit (ou crée au premier lancement) un secret de développement dans instance/."""
    chemin = os.path.join(app.instance_path, nom)
    if os.path.exists(chemin):
        with open(chemin) as f:
            return f.read().strip()
    valeur = generateur()
    with open(chemin, "w") as f:
        f.write(valeur)
    os.chmod(chemin, 0o600)
    app.logger.warning("Secret de développement généré : %s (à remplacer en production)", chemin)
    return valeur


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.from_object("gestion.config.Config")
    if config:
        app.config.update(config)

    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _secret_instance(app, "secret_key", lambda: secrets.token_hex(32))
    if not app.config.get("FERNET_KEY"):
        app.config["FERNET_KEY"] = _secret_instance(
            app, "fernet.key", lambda: Fernet.generate_key().decode())
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
            app.instance_path, "gestion.db")

    crypto.init_app(app)
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .models import Utilisateur

    @login_manager.user_loader
    def charger_utilisateur(uid):
        return db.session.get(Utilisateur, int(uid))

    from .auth import bp as auth_bp
    from .clients import bp as clients_bp
    from .competences import bp as competences_bp
    from .missions import bp as missions_bp
    from .missions import bp_parametres
    from .personnel import bp as personnel_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(personnel_bp)
    app.register_blueprint(competences_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(missions_bp)
    app.register_blueprint(bp_parametres)

    @app.route("/")
    def accueil():
        return redirect(url_for("personnel.liste"))

    _filtres(app)
    _commandes(app)

    with app.app_context():
        from .migrations import mettre_a_niveau
        db.create_all()
        mettre_a_niveau(app)
    return app


def _filtres(app):
    @app.template_filter("xaf")
    def xaf(montant):
        if montant is None:
            return "—"
        return f"{montant:,}".replace(",", " ") + " XAF"

    @app.template_filter("date_fr")
    def date_fr(valeur):
        if not valeur:
            return "—"
        if isinstance(valeur, datetime):
            return valeur.strftime("%d/%m/%Y %H:%M")
        if isinstance(valeur, date):
            return valeur.strftime("%d/%m/%Y")
        return valeur

    @app.template_filter("nombre")
    def nombre(valeur, decimales=0):
        if valeur is None:
            return "—"
        texte = f"{valeur:,.{decimales}f}".replace(",", "\u202f").replace(".", ",")
        return texte

    @app.context_processor
    def injecter():
        return {"aujourdhui": date.today()}


def _commandes(app):
    @app.cli.command("creer-admin")
    @click.option("--email", prompt="E-mail")
    @click.option("--nom", prompt="Nom")
    @click.password_option("--mot-de-passe", prompt="Mot de passe")
    def creer_admin(email, nom, mot_de_passe):
        """Crée un compte administrateur."""
        from .models import Utilisateur
        u = Utilisateur(email=email.lower().strip(), nom=nom, role="admin")
        u.definir_mot_de_passe(mot_de_passe)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Administrateur {email} créé.")

    @app.cli.command("demo")
    def demo():
        """Charge des données de démonstration."""
        from .demo import charger
        charger()
        click.echo("Données de démonstration chargées.")
