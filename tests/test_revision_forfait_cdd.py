import shutil
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from gestion import create_app
from gestion.extensions import db
from gestion.models import ContratHistorique, Jalon, Mission, Personne

from .test_missions import J, affecter, base, creer, iso  # noqa: F401
from .test_regles import app, client, donnees  # noqa: F401


def creer_forfait(client, base, **kw):
    d = dict(mode_facturation="forfait", montant_forfait="10000000", livrable="Mise en service ligne 2",
             jours_vendus="40")
    d.update(kw)
    return creer(client, base, **d)


# ---------------------------------------------------------------- Forfait

def test_forfait_champs_obligatoires(client, app, base):
    html = creer(client, base, mode_facturation="forfait").get_data(as_text=True)
    assert "Le montant est obligatoire" in html and "Décrivez le livrable" in html
    creer_forfait(client, base)
    creer(client, base, intitule="Régie", montant_forfait="999", livrable="ignoré")
    with app.app_context():
        f, r = Mission.query.order_by(Mission.code).all()
        assert (f.est_forfait, f.montant_forfait) == (True, 10_000_000)
        assert (r.est_forfait, r.montant_forfait, r.livrable) == (False, None, None)


def test_forfait_affectation_sans_tjm_et_marge(client, app, base):
    creer_forfait(client, base)
    debut, fin = date(2026, 11, 2), date(2026, 11, 13)  # 10 jours ouvrés
    client.post("/missions/MIS0001/modifier", data=dict(
        client_id=base["client"], intitule="Mission test", mode_facturation="forfait",
        montant_forfait="10000000", livrable="Mise en service", date_debut=iso(debut), date_fin=iso(fin)))
    affecter(client, "MIS0001", base["Salarie"], debut, fin, tjm="")          # coût 100 000 / j
    affecter(client, "MIS0001", base["Soustraitant"], debut, fin, tjm="")     # coût 150 000 / j
    with app.app_context():
        m = Mission.query.one()
        assert len(m.affectations) == 2 and all(a.tjm_vente == 0 for a in m.affectations)
        assert m.cout_previsionnel == 2_500_000
        assert m.ca_previsionnel == 10_000_000
        assert m.marge_previsionnelle == 7_500_000


def test_regie_tjm_toujours_obligatoire(client, app, base):
    creer(client, base)
    html = affecter(client, "MIS0001", base["Salarie"], J, J + timedelta(days=5), tjm="").get_data(as_text=True)
    assert "TJM de vente est obligatoire" in html


def test_mode_verrouille_apres_affectation(client, app, base):
    creer_forfait(client, base)
    affecter(client, "MIS0001", base["Salarie"], J, J + timedelta(days=5), tjm="")
    r = client.post("/missions/MIS0001/modifier", data=dict(
        client_id=base["client"], intitule="Mission test", mode_facturation="regie",
        date_debut=iso(J - timedelta(days=10)), date_fin=iso(J + timedelta(days=100))))
    assert "ne peut plus changer" in r.get_data(as_text=True)


def test_jalons(client, app, base):
    creer_forfait(client, base)
    client.post("/missions/MIS0001/jalons", data={"libelle": "Acompte", "pourcentage": "30", "date_prevue": iso(J)})
    client.post("/missions/MIS0001/jalons", data={"libelle": "Livraison", "montant": "4000000"})
    r = client.post("/missions/MIS0001/jalons", data={"libelle": "Réception", "montant": "4000000"},
                    follow_redirects=True)
    assert "dépasse le forfait" in r.get_data(as_text=True)
    r = client.post("/missions/MIS0001/jalons", data={"libelle": "Vide"}, follow_redirects=True)
    assert "Indiquez un montant ou un pourcentage" in r.get_data(as_text=True)
    with app.app_context():
        m = Mission.query.one()
        assert [j.montant for j in m.jalons] == [3_000_000, 4_000_000, 4_000_000]
        assert m.reste_a_planifier == -1_000_000
        acompte = [j for j in m.jalons if j.libelle == "Acompte"][0]
        acompte_id, reception_id = acompte.id, [j for j in m.jalons if j.libelle == "Réception"][0].id
    client.post(f"/missions/MIS0001/jalons/{acompte_id}/statut", data={"statut": "atteint"})
    client.post(f"/missions/MIS0001/jalons/{acompte_id}/supprimer")      # refusé : atteint
    client.post(f"/missions/MIS0001/jalons/{reception_id}/supprimer")    # accepté : prévu
    with app.app_context():
        assert db.session.get(Jalon, acompte_id).statut == "atteint"
        assert db.session.get(Jalon, acompte_id).date_atteint == date.today()
        assert db.session.get(Jalon, reception_id) is None
    assert client.post(f"/missions/MIS0001/jalons/{acompte_id}/statut",
                       data={"statut": "facture"}).status_code == 400


def test_prolongation_forfait_avec_avenant(client, app, base):
    fin = J + timedelta(days=20)
    creer_forfait(client, base, date_fin=iso(fin))
    affecter(client, "MIS0001", base["Salarie"], J, fin, tjm="")
    with app.app_context():
        aid = Mission.query.one().affectations[0].id
    client.post("/missions/MIS0001/prolonger", data={
        "date_fin": iso(fin + timedelta(days=30)), f"prolonger_{aid}": "1", "montant_sup": "2000000"})
    with app.app_context():
        m = Mission.query.one()
        assert m.montant_forfait == 12_000_000 and len(m.affectations) == 2
        assert all(a.tjm_vente == 0 for a in m.affectations)


# ---------------------------------------------------------------- CDD

def donnees_cdd(**kw):
    d = donnees(email="cdd@x.cm", nom="Temporaire", type_contrat="cdd",
                date_entree=iso(J - timedelta(days=100)), date_fin_contrat=iso(J + timedelta(days=20)),
                motif_cdd="Chantier")
    d.update(kw)
    return d


def test_cdd_creation_et_controles(client, app):
    html = client.post("/personnel/nouveau", data=donnees_cdd(date_fin_contrat="")).get_data(as_text=True)
    assert "obligatoire pour un CDD" in html
    client.post("/personnel/nouveau", data=donnees_cdd())
    client.post("/personnel/nouveau", data=donnees(email="cdi@x.cm", nom="Permanent", type_contrat="cdi",
                                                   date_fin_contrat=iso(J), motif_cdd="ignoré"))
    with app.app_context():
        cdd = Personne.query.filter_by(nom="Temporaire").one()
        cdi = Personne.query.filter_by(nom="Permanent").one()
        assert cdd.est_cdd and cdd.etat_contrat == "bientot" and cdd.cdd_successifs[0] == 1
        assert not cdi.est_cdd and cdi.date_fin_contrat is None and cdi.motif_cdd is None
    html = client.get("/personnel/?contrat=alerte").get_data(as_text=True)
    assert "<strong>Jean TEMPORAIRE</strong>" in html and "<strong>Jean PERMANENT</strong>" not in html


def test_cdd_renouvellement_puis_cdi(client, app):
    client.post("/personnel/nouveau", data=donnees_cdd())
    fin1 = J + timedelta(days=20)
    client.post("/personnel/MEP0101/contrat", data={
        "action": "renouveler", "date_debut": iso(fin1 + timedelta(days=1)),
        "date_fin": iso(fin1 + timedelta(days=180)), "motif": "Prolongation chantier",
        "salaire_mensuel_brut": "900000"})
    with app.app_context():
        p = Personne.query.one()
        assert p.date_fin_contrat == fin1 + timedelta(days=180) and p.salaire_mensuel_brut == 900_000
        assert len(p.contrats_precedents) == 1
        assert p.contrats_precedents[0].date_fin == fin1
        nb, jours = p.cdd_successifs
        assert nb == 2 and jours == 100 + 20 + 1 + 180
    client.post("/personnel/MEP0101/contrat", data={"action": "cdi", "date_debut": iso(J + timedelta(days=60))})
    with app.app_context():
        p = Personne.query.one()
        assert p.type_contrat == "cdi" and p.date_fin_contrat is None and not p.est_cdd
        hist = sorted(p.contrats_precedents, key=lambda c: c.date_debut)
        assert [c.type_contrat for c in hist] == ["cdd", "cdd"]
        assert hist[1].date_fin == J + timedelta(days=59)  # CDD écourté au passage en CDI
        assert ContratHistorique.query.count() == 2


def test_affectation_au_dela_du_cdd(client, app, base):
    client.post("/personnel/nouveau", data=donnees_cdd())
    with app.app_context():
        pid = Personne.query.filter_by(nom="Temporaire").one().id
    creer(client, base)
    html = affecter(client, "MIS0001", pid, J, J + timedelta(days=60)).get_data(as_text=True)
    assert "le CDD de" in html and "se termine le" in html
    with app.app_context():
        assert Mission.query.one().affectations[0].depasse_contrat
    assert "Au-delà du CDD" in client.get("/missions/MIS0001").get_data(as_text=True)


def test_pages_revision(client, app, base):
    client.post("/personnel/nouveau", data=donnees_cdd())
    creer_forfait(client, base)
    for url in ("/personnel/MEP0103", "/personnel/MEP0103/contrat", "/personnel/?contrat=cdd",
                "/missions/MIS0001", "/missions/MIS0001/prolonger", "/missions/", "/missions/export.csv",
                "/personnel/export.csv", "/personnel/MEP0103/modifier"):
        assert client.get(url).status_code == 200, url


def test_migration_base_module3(tmp_path):
    source = Path(__file__).parent / "base_module3.db"
    if not source.exists():
        pytest.skip("base de référence du module 3 absente")
    base_db = tmp_path / "m3.db"
    shutil.copy(source, base_db)
    cnx = sqlite3.connect(base_db)
    nb_missions = cnx.execute("SELECT COUNT(*) FROM mission").fetchone()[0]
    cnx.close()
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "FERNET_KEY": Fernet.generate_key().decode(),
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{base_db}"})
    with app.app_context():
        q = lambda sql: db.session.execute(db.text(sql)).scalar()  # noqa: E731
        assert q("SELECT COUNT(*) FROM mission") == nb_missions > 0
        assert q("SELECT COUNT(*) FROM mission WHERE mode_facturation = 'regie'") == nb_missions
        assert q("SELECT COUNT(*) FROM personne WHERE statut='salarie' AND type_contrat IS NULL") == 0
        assert q("SELECT COUNT(*) FROM jalon") == 0
        m = Mission.query.first()
        assert not m.est_forfait and m.ca_previsionnel > 0


# ---------------------------------------------------------------- Spécialisation industrielle

def test_duree_mission_et_date_de_fin(client, app, base):
    debut = date(2026, 12, 1)
    # Durée saisie : la date de fin est recalculée (début + durée − 1), même si une autre fin est envoyée
    creer(client, base, date_debut=iso(debut), duree_jours="30", date_fin=iso(date(2027, 6, 1)))
    # Pas de durée : la date de fin saisie fait foi
    creer(client, base, intitule="Sans durée", date_debut=iso(debut), date_fin=iso(date(2026, 12, 10)))
    html = creer(client, base, intitule="Rien", date_debut=iso(debut), date_fin="").get_data(as_text=True)
    assert "Indiquez la date de fin ou la durée" in html
    with app.app_context():
        m1, m2 = Mission.query.order_by(Mission.code).all()
        assert m1.date_fin == date(2026, 12, 30) and m1.duree_jours == 30
        assert m2.date_fin == date(2026, 12, 10) and m2.duree_jours == 10
    html = client.get("/missions/MIS0002/modifier").get_data(as_text=True)
    assert 'name="duree_jours"' in html and 'value="10"' in html
    assert 'selected value="forfait"' in client.get("/missions/nouvelle").get_data(as_text=True)


def test_migration_sous_traitants_deviennent_salaries(tmp_path):
    source = Path(__file__).parent / "base_module3.db"
    if not source.exists():
        pytest.skip("base de référence du module 3 absente")
    base_db = tmp_path / "m3b.db"
    shutil.copy(source, base_db)
    cnx = sqlite3.connect(base_db)
    nb = cnx.execute("SELECT COUNT(*) FROM personne WHERE statut='sous_traitant'").fetchone()[0]
    cnx.close()
    assert nb > 0
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "FERNET_KEY": Fernet.generate_key().decode(),
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{base_db}"})
    with app.app_context():
        q = lambda sql: db.session.execute(db.text(sql)).scalar()  # noqa: E731
        assert q("SELECT COUNT(*) FROM personne WHERE statut <> 'salarie'") == 0
        assert q("SELECT COUNT(*) FROM personne WHERE tjm_achat IS NOT NULL AND salaire_mensuel_brut IS NULL "
                 "AND type_contrat = 'cdi'") == nb
