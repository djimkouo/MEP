from datetime import date, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from gestion import create_app
from gestion.extensions import db
from gestion.models import JournalAudit, Personne, Utilisateur
from gestion.services import PlageEpuisee, formater_code, prochain_code


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True, "WTF_CSRF_ENABLED": False, "SECRET_KEY": "test",
        "FERNET_KEY": Fernet.generate_key().decode(),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path/'t.db'}",
    })
    with app.app_context():
        u = Utilisateur(email="a@a.cm", nom="Admin", role="admin")
        u.definir_mot_de_passe("x")
        db.session.add(u)
        db.session.commit()
    return app


@pytest.fixture
def client(app):
    c = app.test_client()
    c.post("/connexion", data={"email": "a@a.cm", "mot_de_passe": "x"})
    return c


def donnees(**kw):
    d = dict(categorie="operationnel", nom="Doe", prenom="Jean", email="jean@x.cm",
             piece_type="cni", piece_numero="cm123456", statut="salarie",
             salaire_mensuel_brut="800000", date_entree=date.today().isoformat(),
             disponibilite="disponible")
    d.update(kw)
    return d


def test_format_code():
    assert formater_code(1) == "MEP0001"
    assert formater_code(101) == "MEP0101"


def test_plages(client, app):
    client.post("/personnel/nouveau", data=donnees(email="o1@x.cm"))
    client.post("/personnel/nouveau", data=donnees(email="m1@x.cm", categorie="management"))
    client.post("/personnel/nouveau", data=donnees(email="o2@x.cm"))
    client.post("/personnel/nouveau", data=donnees(email="m2@x.cm", categorie="management"))
    with app.app_context():
        codes = {p.email: p.code for p in Personne.query.all()}
    assert codes == {"o1@x.cm": "MEP0101", "o2@x.cm": "MEP0102",
                     "m1@x.cm": "MEP0001", "m2@x.cm": "MEP0002"}


def test_plage_management_epuisee(app):
    with app.app_context():
        db.session.execute(text(
            "INSERT INTO personne (code, categorie, nom, prenom, email, piece_type, piece_numero, "
            "statut, date_entree, disponibilite, archive, cree_le) VALUES ('MEP0100','management',"
            "'X','Y','z@z.cm','cni','x','salarie','2025-01-01','disponible',0,'2025-01-01')"))
        with pytest.raises(PlageEpuisee):
            prochain_code("management")
        assert prochain_code("operationnel") == "MEP0101"


def test_code_conserve_au_changement_de_categorie_et_non_reutilise(client, app):
    client.post("/personnel/nouveau", data=donnees(email="o1@x.cm"))
    r = client.post("/personnel/MEP0101/modifier", data=donnees(email="o1@x.cm", categorie="management"))
    assert r.status_code == 302
    client.post("/personnel/MEP0101/archiver")
    client.post("/personnel/nouveau", data=donnees(email="o2@x.cm"))
    with app.app_context():
        p1 = Personne.query.filter_by(email="o1@x.cm").one()
        p2 = Personne.query.filter_by(email="o2@x.cm").one()
        assert (p1.code, p1.categorie, p1.archive) == ("MEP0101", "management", True)
        assert p2.code == "MEP0102"


def test_salarie_uniquement_salaire_obligatoire(client, app):
    r = client.post("/personnel/nouveau", data=donnees(salaire_mensuel_brut=""))
    assert "salaire mensuel brut est obligatoire" in r.get_data(as_text=True)
    html = client.get("/personnel/nouveau").get_data(as_text=True)
    assert "TJM" not in html and "sous-traitant" not in html.lower()
    # Même si un ancien formulaire envoie « sous_traitant », la personne est enregistrée comme salariée.
    client.post("/personnel/nouveau", data=donnees(statut="sous_traitant", tjm_achat="150000"))
    with app.app_context():
        p = Personne.query.one()
        assert p.statut == "salarie" and p.salaire_mensuel_brut == 800000 and p.tjm_achat is None
        assert p.type_contrat == "cdi"


def test_piece_obligatoire_et_chiffree(client, app):
    r = client.post("/personnel/nouveau", data=donnees(piece_numero=""))
    assert r.status_code == 200
    client.post("/personnel/nouveau", data=donnees())
    with app.app_context():
        brut = db.session.execute(text("SELECT piece_numero FROM personne")).scalar()
        assert "CM123456" not in brut
        assert Personne.query.one().piece_numero == "CM123456"


def test_email_unique(client, app):
    client.post("/personnel/nouveau", data=donnees())
    r = client.post("/personnel/nouveau", data=donnees(nom="Autre"))
    assert "déjà utilisée" in r.get_data(as_text=True)


def test_donnees_sensibles_masquees_et_tracees(client, app):
    client.post("/personnel/nouveau", data=donnees())
    html = client.get("/personnel/MEP0101").get_data(as_text=True)
    assert "CM123456" not in html and "800" not in html
    html = client.get("/personnel/MEP0101/donnees-sensibles").get_data(as_text=True)
    assert "CM123456" in html
    with app.app_context():
        assert JournalAudit.query.filter_by(action="consultation_sensible").count() == 1


def test_export_sans_donnees_sensibles(client):
    client.post("/personnel/nouveau", data=donnees())
    csv = client.get("/personnel/export.csv").get_data(as_text=True)
    assert "MEP0101" in csv and "CM123456" not in csv and "800000" not in csv


def test_alerte_piece(client, app):
    client.post("/personnel/nouveau", data=donnees(
        piece_date_expiration=(date.today() + timedelta(days=20)).isoformat()))
    html = client.get("/personnel/?piece=alerte").get_data(as_text=True)
    assert "MEP0101" in html


def test_acces_protege(app):
    assert app.test_client().get("/personnel/").status_code == 302
