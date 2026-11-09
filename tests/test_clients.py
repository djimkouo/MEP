import shutil
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet

from gestion import create_app
from gestion.extensions import db
from gestion.models import Client, ContactClient, JournalAudit

from .test_regles import app, client  # noqa: F401  (fixtures partagées)


def donnees_client(**kw):
    d = dict(raison_sociale="Banque Test", secteur="banque", statut="prospect", delai_paiement="30")
    d.update(kw)
    return d


def test_code_client_increment(client, app):
    client.post("/clients/nouveau", data=donnees_client(raison_sociale="A"))
    client.post("/clients/nouveau", data=donnees_client(raison_sociale="B"))
    client.post("/clients/nouveau", data=donnees_client(raison_sociale="C"))
    with app.app_context():
        assert sorted(c.code for c in Client.query.all()) == ["CLI0001", "CLI0002", "CLI0003"]


def test_unicite_raison_sociale_et_rccm(client, app):
    client.post("/clients/nouveau", data=donnees_client(rccm="rc/dla/1"))
    r = client.post("/clients/nouveau", data=donnees_client(raison_sociale="  banque   TEST "))
    assert "déjà cette raison sociale" in r.get_data(as_text=True)
    r = client.post("/clients/nouveau", data=donnees_client(raison_sociale="Autre", rccm="RC/DLA/1"))
    assert "RCCM est déjà utilisé" in r.get_data(as_text=True)
    # plusieurs clients sans RCCM : autorisé
    client.post("/clients/nouveau", data=donnees_client(raison_sociale="X"))
    client.post("/clients/nouveau", data=donnees_client(raison_sociale="Y"))
    with app.app_context():
        assert Client.query.count() == 3


def test_statut_et_code_conserve(client, app):
    client.post("/clients/nouveau", data=donnees_client())
    client.post("/clients/CLI0001/statut", data={"statut": "actif"})
    client.post("/clients/CLI0001/statut", data={"statut": "inactif"})
    client.post("/clients/nouveau", data=donnees_client(raison_sociale="Suivant"))
    with app.app_context():
        c = Client.query.filter_by(code="CLI0001").one()
        assert c.statut == "inactif"
        assert Client.query.filter_by(raison_sociale="Suivant").one().code == "CLI0002"
        assert JournalAudit.query.filter_by(action="statut", client_id=c.id).count() == 2
    html = client.get("/clients/").get_data(as_text=True)
    assert "<strong>Banque Test</strong>" not in html  # inactif masqué par défaut
    assert "<strong>Banque Test</strong>" in client.get("/clients/?inactifs=1").get_data(as_text=True)


def test_contacts_un_seul_principal(client, app):
    client.post("/clients/nouveau", data=donnees_client())
    client.post("/clients/CLI0001/contacts", data={"nom": "Un", "email": "un@x.cm", "role": "decideur", "actif": "y"})
    client.post("/clients/CLI0001/contacts", data={"nom": "Deux", "email": "deux@x.cm", "role": "operationnel",
                                                   "actif": "y", "principal": "y"})
    r = client.post("/clients/CLI0001/contacts", data={"nom": "Trois", "role": "decideur", "actif": "y"})
    with app.app_context():
        contacts = {c.nom: c for c in ContactClient.query.all()}
        assert set(contacts) == {"Un", "Deux"}  # Trois refusé : ni e-mail ni téléphone
        assert contacts["Deux"].principal and not contacts["Un"].principal
        id_deux = contacts["Deux"].id
    client.post(f"/clients/CLI0001/contacts/{id_deux}/activation")
    with app.app_context():
        deux = db.session.get(ContactClient, id_deux)
        assert not deux.actif and not deux.principal


def test_export_clients(client):
    client.post("/clients/nouveau", data=donnees_client(raison_sociale="Exportée"))
    assert "Exportée" in client.get("/clients/export.csv").get_data(as_text=True)


def test_migration_base_module1(tmp_path):
    """Une base créée par le module 1 (sans colonne client_id) est mise à niveau sans perte."""
    source = Path(__file__).parent / "base_module1.db"
    if not source.exists():
        import pytest
        pytest.skip("base de référence du module 1 absente")
    base = tmp_path / "ancienne.db"
    shutil.copy(source, base)
    colonnes = [r[1] for r in sqlite3.connect(base).execute("PRAGMA table_info(journal_audit)")]
    assert "client_id" not in colonnes
    nb_avant = sqlite3.connect(base).execute("SELECT COUNT(*) FROM personne").fetchone()[0]

    app = create_app({"TESTING": True, "SECRET_KEY": "t", "FERNET_KEY": Fernet.generate_key().decode(),
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{base}"})
    with app.app_context():
        colonnes = [r[1] for r in db.session.execute(db.text("PRAGMA table_info(journal_audit)"))]
        assert "client_id" in colonnes
        assert db.session.execute(db.text("SELECT COUNT(*) FROM personne")).scalar() == nb_avant
        assert db.session.execute(db.text("SELECT COUNT(*) FROM client")).scalar() == 0


def test_secteurs_industrie_agroalimentaire(client, app):
    html = client.get("/clients/nouveau").get_data(as_text=True)
    assert 'value="industrie"' in html and 'value="agroalimentaire"' in html
    client.post("/clients/nouveau", data=donnees_client(raison_sociale="Usine", secteur="industrie"))
    client.post("/clients/nouveau", data=donnees_client(raison_sociale="Brasserie", secteur="agroalimentaire"))
    with app.app_context():
        assert {c.secteur_libelle for c in Client.query.all()} == {"Industrie", "Agroalimentaire"}
