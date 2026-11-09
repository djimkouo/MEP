# Gestion du personnel — Modules 1 à 3 (+ révision forfait / CDD)

Application Flask (Python 3.10+). Base SQLite par défaut, montants en XAF.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt

flask --app run creer-admin        # crée votre compte administrateur
flask --app run run                # http://127.0.0.1:5000
```

Pour tester avec des données fictives : `flask --app run demo`
(compte `admin@exemple.cm` / `admin1234`, à ne pas utiliser en production).

Tests : `pytest`

## Règles de gestion implémentées

| Règle | Détail |
|---|---|
| Code unique | `MEP` + 4 chiffres, généré à l'enregistrement, non modifiable |
| Plages | MEP0001–MEP0100 : management · MEP0101–MEP9999 : reste du personnel |
| Changement de catégorie | La personne garde son code |
| Réutilisation | Jamais : pas de suppression, seulement l'archivage |
| Statut | Salarié → salaire mensuel brut · Sous-traitant → TJM convenu avec lui (+ raison sociale, RCCM/NIU) |
| Pièce d'identité | Type et numéro obligatoires ; numéro chiffré en base ; alerte 60 jours avant expiration |
| Données sensibles | N° de pièce et rémunération masqués par défaut ; chaque affichage est tracé |
| Export CSV | Sans données sensibles ; l'export est tracé |
| E-mail | Unique |

## Module 2 : clients

| Règle | Détail |
|---|---|
| Code client | `CLI` + incrément (CLI0001, CLI0002…), généré, non modifiable, jamais réutilisé |
| Statuts | Prospect → Actif → Inactif ; pas de suppression, l'inactif sert d'archivage |
| Unicité | Raison sociale (sans tenir compte des majuscules ni des espaces) et RCCM s'il est renseigné |
| Interlocuteurs | Plusieurs par client, un seul principal, désactivation au lieu de suppression ; e-mail ou téléphone obligatoire |
| Facturation | RCCM, NIU, adresse et e-mail de facturation, délai de paiement en jours (utilisés au module 6) |

## Module 3 : missions

| Règle | Détail |
|---|---|
| Code mission | `MIS` + incrément (MIS0001…), généré, non modifiable, jamais réutilisé |
| Statuts | En préparation → En cours → Terminée, ou Annulée ; pas de suppression |
| Démarrage | Au moins une personne affectée ; un client prospect passe automatiquement en actif |
| Affectation | Dates incluses dans celles de la mission, TJM de vente, taux d'occupation ; pas de chevauchement pour une même personne sur une même mission |
| Surcharge | Alerte si une personne dépasse 100 % sur une période (missions en préparation ou en cours) |
| Retrait | Possible seulement tant que la mission est en préparation ; ensuite on raccourcit la période |
| Prolongation | Nouvelle date de fin ; chaque personne prolongée reçoit une nouvelle période (TJM éventuellement revalorisé), l'ancienne est conservée |
| Disponibilité | Calculée : « En mission » si affectation en cours sur une mission en cours ; « Libre le… » en orange sous 30 jours ; « Indisponible » reste manuel |
| Marge (option B) | Salarié : salaire mensuel brut ÷ jours ouvrés par mois (21,67 par défaut, écran Paramètres) ; sous-traitant : TJM convenu. Jours fériés non déduits |
| Alertes | Mission en cours qui se termine sous 30 jours ; date de fin dépassée sans clôture |

## Révision : forfait et CDD

| Règle | Détail |
|---|---|
| Mode de facturation | Régie (TJM × jours) ou Forfait (montant fixe pour un livrable) ; non modifiable une fois des personnes affectées |
| Forfait | Montant et livrable obligatoires ; budget en jours facultatif ; affectations sans TJM de vente |
| Marge au forfait | Montant du forfait − coût prévu (jours prévus × coût journalier) ; alerte si le coût dépasse le montant ou si les jours prévus dépassent le budget |
| Jalons | Libellé, montant ou % du forfait, date prévue ; Prévu → Atteint (→ Facturé par le module Facturation) ; alerte si le total dépasse le forfait ; suppression seulement s'il est prévu |
| Avenant | À la prolongation d'un forfait, un montant supplémentaire peut être ajouté |
| Contrat d'un salarié | CDI ou CDD ; pour un CDD : début, fin (obligatoire), motif, mission liée |
| Alertes CDD | Échéance sous 30 jours ou dépassée (liste, fiche) ; affectation au-delà de la fin du CDD signalée |
| Renouvellement | Renouveler le CDD ou passer en CDI : le contrat en cours est archivé dans l'historique ; nombre de CDD successifs et durée cumulée affichés |
| Règles légales | Non bloquées par l'application (nombre de renouvellements, durée maximale) : à vérifier selon le code du travail applicable |

## Spécialisation industrielle

| Règle | Détail |
|---|---|
| Personnel | Uniquement des salariés, en CDI ou en CDD, avec un salaire mensuel brut obligatoire ; plus de sous-traitants ni de TJM sur les fiches |
| Coût journalier | Salaire mensuel brut ÷ jours ouvrés par mois (Paramètres) |
| Reprise des données | Un ex-sous-traitant devient salarié en CDI ; « Salaire à renseigner » s'affiche tant que son salaire n'est pas saisi (son coût compte pour 0) |
| Mission : durée | Durée (jours calendaires, début et fin inclus) = fin − début + 1 ; modifier la durée recalcule la date de fin |
| Mission : mode | Forfait proposé par défaut ; la régie reste possible (prix par jour × jours travaillés) |

## Mise à jour d'une base existante

Au démarrage, l'application crée les nouvelles tables et ajoute automatiquement les colonnes
manquantes (`gestion/migrations.py`). Une base créée avec une version précédente continue donc
de fonctionner après un déploiement, sans perte de données.

## Production

Définir les variables d'environnement (sinon des secrets de développement sont créés dans `instance/`) :

- `SECRET_KEY` : clé de session Flask
- `FERNET_KEY` : clé de chiffrement des numéros de pièce
  (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
  **À sauvegarder : sans elle, les numéros de pièce sont illisibles.**
- `DATABASE_URL` : ex. `postgresql://user:mdp@hote/base` (installer `psycopg[binary]`)

Lancer derrière un serveur WSGI, par exemple `gunicorn "run:app"`, avec HTTPS.

## Structure

```
gestion/
  models.py       Personne, Competence, Certification, NoteInterne, JournalAudit, Utilisateur
  services.py     génération du code MEP, journal d'audit
  personnel.py    liste, fiche, création, modification, archivage, export, journal
  clients.py      référentiel des clients et de leurs interlocuteurs
  missions.py     missions, affectations, prolongations, paramètres
  migrations.py   mise à niveau automatique de la base
  competences.py  référentiel des compétences
  forms.py        formulaires et règles de validation
  templates/      écrans (Jinja)
tests/            tests des règles de gestion
```
