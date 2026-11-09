import shutil
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from gestion import create_app
from gestion.extensions import db
from gestion.models import Affectation, Client, Mission, Parametre, Personne, jours_ouvres

from .test_regles import app, client, donnees  # noqa: F401  (fixtures partagées)

J = date.today()


def iso(d):
    return d.isoformat()


@pytest.fixture
def base(client, app):
    """Un client prospect avec un contact, un salarié et un sous-traitant."""
    client.post("/clients/nouveau", data=dict(raison_sociale="Banque A", secteur="banque",
                                              statut="prospect", delai_paiement="30"))
    client.post("/clients/CLI0001/contacts", data={"nom": "Contact", "email": "c@a.cm", "role": "decideur",
                                                   "actif": "y"})
    client.post("/personnel/nouveau", data=donnees(email="sal@x.cm", nom="Salarie",
                                                   salaire_mensuel_brut="2167000"))
    # Ex-« sous-traitant » : désormais salarié ; 3 250 500 / 21,67 = 150 000 XAF par jour
    client.post("/personnel/nouveau", data=donnees(email="st@x.cm", nom="Soustraitant",
                                                   salaire_mensuel_brut="3250500"))
    with app.app_context():
        ids = {p.nom: p.id for p in Personne.query.all()}
        cid = Client.query.one().id
    return {"client": cid, **ids}


def creer(client, base, **kw):
    d = dict(client_id=base["client"], intitule="Mission test", date_debut=iso(J - timedelta(days=10)),
             date_fin=iso(J + timedelta(days=100)))
    d.update(kw)
    return client.post("/missions/nouvelle", data=d)


def affecter(client, code, personne_id, debut, fin, tjm="250000", taux="100"):
    return client.post(f"/missions/{code}/affectations", data=dict(
        personne_id=personne_id, date_debut=iso(debut), date_fin=iso(fin), tjm_vente=tjm,
        taux_occupation=taux), follow_redirects=True)


def test_jours_ouvres():
    assert jours_ouvres(date(2026, 11, 2), date(2026, 11, 8)) == 5   # lundi → dimanche
    assert jours_ouvres(date(2026, 11, 7), date(2026, 11, 8)) == 0   # week-end
    assert jours_ouvres(date(2026, 11, 2), date(2026, 11, 30)) == 21


def test_code_mission_et_controles_client(client, app, base):
    creer(client, base)
    creer(client, base, intitule="Deuxième")
    with app.app_context():
        assert sorted(m.code for m in Mission.query.all()) == ["MIS0001", "MIS0002"]
        assert all(m.statut == "preparation" for m in Mission.query.all())
    r = creer(client, base, date_fin=iso(J - timedelta(days=20)))
    assert "doit suivre la date de début" in r.get_data(as_text=True)
    client.post("/clients/nouveau", data=dict(raison_sociale="Autre", secteur="banque", statut="actif",
                                              delai_paiement="30"))
    client.post("/clients/CLI0002/contacts", data={"nom": "Autre contact", "email": "o@b.cm", "role": "decideur",
                                                   "actif": "y"})
    with app.app_context():
        autre_contact = Client.query.filter_by(code="CLI0002").one().contacts[0].id
    r = creer(client, base, contact_id=autre_contact)
    assert "n&#39;appartient pas au client" in r.get_data(as_text=True)
    client.post("/clients/CLI0002/statut", data={"statut": "inactif"})
    with app.app_context():
        inactif = Client.query.filter_by(code="CLI0002").one().id
    creer(client, base, client_id=inactif)  # client inactif : absent de la liste, création refusée
    with app.app_context():
        assert Mission.query.filter_by(client_id=inactif).count() == 0


def test_affectations_regles(client, app, base):
    creer(client, base)
    debut, fin = J - timedelta(days=10), J + timedelta(days=100)
    html = affecter(client, "MIS0001", base["Salarie"], debut - timedelta(days=1), fin).get_data(as_text=True)
    assert "La mission commence le" in html
    affecter(client, "MIS0001", base["Salarie"], debut, fin)
    html = affecter(client, "MIS0001", base["Salarie"], debut + timedelta(days=5), fin).get_data(as_text=True)
    assert "déjà affecté(e) à cette mission" in html
    with app.app_context():
        assert Affectation.query.count() == 1


def test_demarrage_disponibilite_et_client_actif(client, app, base):
    creer(client, base)
    r = client.post("/missions/MIS0001/statut", data={"statut": "en_cours"}, follow_redirects=True)
    assert "Affectez au moins une personne" in r.get_data(as_text=True)
    affecter(client, "MIS0001", base["Salarie"], J - timedelta(days=10), J + timedelta(days=100))
    with app.app_context():  # en préparation : la personne reste disponible
        assert db.session.get(Personne, base["Salarie"]).etat_disponibilite == "disponible"
    client.post("/missions/MIS0001/statut", data={"statut": "en_cours"})
    with app.app_context():
        p = db.session.get(Personne, base["Salarie"])
        assert p.etat_disponibilite == "en_mission"
        assert p.libre_le == J + timedelta(days=101)
        assert db.session.get(Client, base["client"]).statut == "actif"
    html = client.get("/personnel/?disponibilite=en_mission").get_data(as_text=True)
    assert "Salarie".upper() in html


def test_libre_bientot_et_indisponible(client, app, base):
    creer(client, base, date_fin=iso(J + timedelta(days=12)))
    affecter(client, "MIS0001", base["Soustraitant"], J - timedelta(days=10), J + timedelta(days=12), tjm="200000")
    client.post("/missions/MIS0001/statut", data={"statut": "en_cours"})
    with app.app_context():
        p = db.session.get(Personne, base["Soustraitant"])
        assert p.etat_disponibilite == "bientot"
        assert p.badge_disponibilite[1] == "badge-orange"
    with app.app_context():
        p = db.session.get(Personne, base["Salarie"])
        p.disponibilite = "indisponible"
        db.session.commit()
        assert p.etat_disponibilite == "indisponible"


def test_marges_option_b_et_parametre(client, app, base):
    creer(client, base)
    affecter(client, "MIS0001", base["Salarie"], J, J + timedelta(days=30), tjm="250000")
    affecter(client, "MIS0001", base["Soustraitant"], J, J + timedelta(days=30), tjm="200000")
    with app.app_context():
        a_sal, a_st = sorted(Mission.query.one().affectations, key=lambda a: a.personne.nom)
        assert a_sal.cout_journalier == 100000            # 2 167 000 / 21,67
        assert a_sal.marge_journaliere == 150000 and a_sal.taux_marge == 60.0
        assert a_st.cout_journalier == 150000 and a_st.marge_journaliere == 50000
    client.post("/parametres/", data={"jours_ouvres_mois": "20"})
    with app.app_context():
        assert Parametre.jours_ouvres_mois() == 20.0
        a_sal = [a for a in Mission.query.one().affectations if a.personne.nom == "Salarie"][0]
        assert a_sal.cout_journalier == 108350


def test_surcharge_signalee(client, app, base):
    creer(client, base)
    creer(client, base, intitule="Autre mission")
    affecter(client, "MIS0001", base["Salarie"], J, J + timedelta(days=30), taux="80")
    html = affecter(client, "MIS0002", base["Salarie"], J + timedelta(days=10), J + timedelta(days=40),
                    taux="50").get_data(as_text=True)
    assert "occupé(e) à 130 %" in html
    html = affecter(client, "MIS0002", base["Soustraitant"], J, J + timedelta(days=5), taux="100").get_data(as_text=True)
    assert "occupé(e) à" not in html


def test_prolongation_conserve_historique(client, app, base):
    fin = J + timedelta(days=20)
    creer(client, base, date_fin=iso(fin), jours_vendus="15")
    affecter(client, "MIS0001", base["Salarie"], J - timedelta(days=10), fin, tjm="250000")
    client.post("/missions/MIS0001/statut", data={"statut": "en_cours"})
    with app.app_context():
        aid = Affectation.query.one().id
    nouvelle_fin = fin + timedelta(days=60)
    client.post("/missions/MIS0001/prolonger", data={
        "date_fin": iso(nouvelle_fin), f"prolonger_{aid}": "1", f"tjm_{aid}": "275000", "jours_vendus_sup": "40"})
    with app.app_context():
        m = Mission.query.one()
        assert m.date_fin == nouvelle_fin and m.jours_vendus == 55
        anciennes, nouvelles = sorted(m.affectations, key=lambda a: a.date_debut)
        assert (anciennes.date_fin, anciennes.tjm_vente) == (fin, 250000)
        assert (nouvelles.date_debut, nouvelles.date_fin, nouvelles.tjm_vente) == (
            fin + timedelta(days=1), nouvelle_fin, 275000)
        assert nouvelles.prolongation_de_id == anciennes.id
        assert db.session.get(Personne, base["Salarie"]).libre_le == nouvelle_fin + timedelta(days=1)
    r = client.post("/missions/MIS0001/prolonger", data={"date_fin": iso(J)}, follow_redirects=True)
    assert "doit être après" in r.get_data(as_text=True)


def test_retrait_et_dates_protegees(client, app, base):
    creer(client, base)
    affecter(client, "MIS0001", base["Salarie"], J, J + timedelta(days=90))
    r = client.post("/missions/MIS0001/modifier", data=dict(
        client_id=base["client"], intitule="Mission test", date_debut=iso(J - timedelta(days=10)),
        date_fin=iso(J + timedelta(days=30))), follow_redirects=True)
    assert "Des affectations sortent de ces dates" in r.get_data(as_text=True)
    with app.app_context():
        aid = Affectation.query.one().id
    client.post("/missions/MIS0001/statut", data={"statut": "en_cours"})
    client.post(f"/missions/MIS0001/affectations/{aid}/supprimer")
    with app.app_context():
        assert Affectation.query.count() == 1  # mission en cours : retrait refusé


def test_pages_affichees(client, app, base):
    creer(client, base)
    affecter(client, "MIS0001", base["Salarie"], J, J + timedelta(days=30))
    for url in ("/missions/", "/missions/MIS0001", "/missions/nouvelle", "/missions/MIS0001/modifier",
                "/missions/MIS0001/prolonger", "/parametres/", "/clients/CLI0001", "/personnel/MEP0101",
                "/missions/export.csv", "/personnel/journal", "/missions/?statut=toutes"):
        assert client.get(url).status_code == 200, url


def test_migration_base_module2(tmp_path):
    source = Path(__file__).parent / "base_module2.db"
    if not source.exists():
        pytest.skip("base de référence du module 2 absente")
    base = tmp_path / "m2.db"
    shutil.copy(source, base)
    cnx = sqlite3.connect(base)
    assert cnx.execute("SELECT COUNT(*) FROM personne WHERE disponibilite='en_mission'").fetchone()[0] > 0
    nb_clients = cnx.execute("SELECT COUNT(*) FROM client").fetchone()[0]
    cnx.close()
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "FERNET_KEY": Fernet.generate_key().decode(),
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{base}"})
    with app.app_context():
        colonnes = [r[1] for r in db.session.execute(db.text("PRAGMA table_info(journal_audit)"))]
        assert "mission_id" in colonnes
        assert db.session.execute(db.text(
            "SELECT COUNT(*) FROM personne WHERE disponibilite='en_mission'")).scalar() == 0
        assert db.session.execute(db.text("SELECT COUNT(*) FROM client")).scalar() == nb_clients
        assert db.session.execute(db.text("SELECT COUNT(*) FROM mission")).scalar() == 0
