"""retire la mesure de vitesse

Revision ID: 7c1f4b2ae903
Revises: 5d1c7b9042ae
Create Date: 2026-08-21 00:00:00.000000

La fonctionnalité de vitesse est retirée de l'application : plus d'échelle px/m
globale, plus de longueur réelle par ligne, plus de vitesse au registre ni au
CSV. Les deux colonnes qui la portaient disparaissent.

Rien à transposer : ces colonnes étaient les seules à porter la mesure, et un
`downgrade` les recrée vides — une vitesse ne se recalcule pas sans le trajet,
qui n'est pas persisté en base.

`batch_alter_table` est obligatoire sur SQLite, dont l'`ALTER TABLE` ne sait pas
supprimer une colonne : Alembic reconstruit la table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Les types personnalisés du projet sont rendus par Alembic avec leur chemin
# complet : sans cet import, la migration lève un NameError à l'exécution.
import traffic_analysis.core.db.types  # noqa: F401

revision: str = "7c1f4b2ae903"
down_revision: str | None = "5d1c7b9042ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job_vehicles", schema=None) as batch_op:
        batch_op.drop_column("avg_speed_px_s")
        batch_op.drop_column("avg_speed_kmh")


def downgrade() -> None:
    with op.batch_alter_table("job_vehicles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("avg_speed_kmh", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("avg_speed_px_s", sa.Float(), nullable=True))
