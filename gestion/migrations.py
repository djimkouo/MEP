"""Mise à niveau automatique de la base au démarrage.

db.create_all() crée les nouvelles tables mais n'ajoute pas les colonnes apparues
dans une table existante. Cette fonction ajoute ces colonnes (nullables uniquement),
pour qu'une base créée par une version précédente continue de fonctionner après
un déploiement, sans perte de données.
"""
from sqlalchemy import inspect, text

from .extensions import db


def mettre_a_niveau(app):
    moteur = db.engine
    inspecteur = inspect(moteur)
    tables_existantes = set(inspecteur.get_table_names())
    ajouts = []
    for table in db.metadata.sorted_tables:
        if table.name not in tables_existantes:
            continue
        colonnes = {c["name"] for c in inspecteur.get_columns(table.name)}
        for col in table.columns:
            if col.name in colonnes:
                continue
            if not col.nullable:
                raise RuntimeError(
                    f"Colonne obligatoire {table.name}.{col.name} absente : migration manuelle requise.")
            type_sql = col.type.compile(dialect=moteur.dialect)
            ajouts.append(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {type_sql}')
    if ajouts:
        with moteur.begin() as cnx:
            for ordre in ajouts:
                cnx.execute(text(ordre))
                app.logger.warning("Migration : %s", ordre)

    # Module 3 : « en mission » est désormais calculé à partir des missions ;
    # l'ancienne valeur saisie à la main redevient « disponible ».
    if "personne" in tables_existantes:
        with moteur.begin() as cnx:
            cnx.execute(text("UPDATE personne SET disponibilite = 'disponible' "
                             "WHERE disponibilite = 'en_mission'"))
            # Spécialisation industrielle : plus de sous-traitants, tout le personnel est salarié.
            # Un ex-sous-traitant devient salarié en CDI ; son salaire est à renseigner sur sa fiche.
            cnx.execute(text("UPDATE personne SET statut = 'salarie', type_contrat = COALESCE(type_contrat, 'cdi') "
                             "WHERE statut <> 'salarie'"))
            # Révision CDD : les salariés existants sont en CDI par défaut.
            cnx.execute(text("UPDATE personne SET type_contrat = 'cdi' "
                             "WHERE statut = 'salarie' AND type_contrat IS NULL"))
    # Révision forfait : les missions existantes sont en régie.
    if "mission" in tables_existantes:
        with moteur.begin() as cnx:
            cnx.execute(text("UPDATE mission SET mode_facturation = 'regie' WHERE mode_facturation IS NULL"))
