"""compte les objets suivis

Revision ID: 5d1c7b9042ae
Revises: 209be6775284
Create Date: 2026-08-13 10:20:00.000000

Suit ADR 0016, qui supprime la ré-identification : un objet suivi est un véhicule.

Trois conséquences en base, et une seule est un simple renommage :

- `jobs.unique_vehicles` → `jobs.tracked_vehicles`. Le nom promettait une unicité
  que la galerie d'apparence ne tenait pas — c'est le bug qui a motivé l'ADR. La
  colonne garde sa valeur : un job archivé avant cette migration a bien compté
  quelque chose, simplement pas la même chose (voir la note de compatibilité) ;
- `jobs.reid_hits` disparaît. Il comptait les ré-identifications, qui n'existent
  plus. Aucune donnée n'est perdue au sens utile du terme : le chiffre décrivait un
  rouage interne, pas un résultat ;
- `job_vehicles.reid_count` → `job_vehicles.crossings_count`. **Ce n'est pas un
  renommage** : les deux comptent des choses différentes, donc la colonne est
  recréée à zéro et non transposée. Elle est dénormalisée depuis
  `crossed_lines_json` pour rendre indexable « montre-moi les véhicules qui n'ont
  franchi aucune ligne », qui est la question devenue courante depuis qu'un objet
  suivi compte.

**Compatibilité des résultats archivés.** Les jobs antérieurs gardent leur
`result.json.gz` inchangé, donc avec les anciennes clés (`uniqueVehicles`,
`reidHits`, `byDirection` en entiers). Le studio ne sait plus les relire, et c'est
assumé : ADR 0014 avait déjà établi que les chiffres d'avant et d'après un
changement de sémantique de comptage ne sont pas comparables. La liste
d'historique, elle, reste lisible — elle ne lit que les colonnes dénormalisées.

`batch_alter_table` est obligatoire sur SQLite, dont l'`ALTER TABLE` ne sait ni
renommer ni supprimer une colonne : Alembic reconstruit la table. Toutes les
migrations précédentes l'utilisent déjà.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Les types personnalisés du projet sont rendus par Alembic avec leur chemin
# complet : sans cet import, la migration lève un NameError à l'exécution.
import traffic_analysis.core.db.types  # noqa: F401

revision: str = "5d1c7b9042ae"
down_revision: str | None = "209be6775284"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.alter_column(
            "unique_vehicles",
            new_column_name="tracked_vehicles",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.drop_column("reid_hits")

    with op.batch_alter_table("job_vehicles", schema=None) as batch_op:
        # Supprimée puis recréée, jamais renommée : `reid_count` comptait des
        # ré-identifications et `crossings_count` compte des franchissements.
        # Transposer l'une sur l'autre remplirait la nouvelle colonne de chiffres
        # plausibles et faux — la pire des reprises de données.
        batch_op.drop_column("reid_count")
        batch_op.add_column(
            sa.Column("crossings_count", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("job_vehicles", schema=None) as batch_op:
        batch_op.drop_column("crossings_count")
        batch_op.add_column(
            sa.Column("reid_count", sa.Integer(), nullable=False, server_default="0")
        )

    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("reid_hits", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.alter_column(
            "tracked_vehicles",
            new_column_name="unique_vehicles",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
