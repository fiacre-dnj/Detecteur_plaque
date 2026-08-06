"""Machine à états d'un job d'analyse.

Une machine explicite, avec des transitions validées, plutôt qu'une chaîne libre.
Un statut qui saute une étape — `queued` → `done` sans passer par `running` —
signale un chemin de code cassé, et il vaut mieux qu'il **lève** que de produire
un résultat incohérent que personne ne remarquera.
"""

from __future__ import annotations

from typing import Literal, get_args

type JobStatus = Literal["queued", "running", "paused", "done", "error", "cancelled"]

JOB_STATUSES: tuple[JobStatus, ...] = get_args(JobStatus.__value__)

# Un job terminal est **immuable**. Relancer une analyse crée un nouveau job, ce
# qui rend les comparaisons possibles — et évite qu'un historique se réécrive.
TERMINAL_STATUSES: frozenset[JobStatus] = frozenset({"done", "error", "cancelled"})

#: `paused` est un état **vivant**, pas un état terminal : le thread worker existe
#: toujours, il attend entre deux images. C'est ce qui permet de reprendre là où
#: l'on s'est arrêté — et ce qui explique que la place de calcul et le bail du
#: modèle restent pris pendant la pause. Un job suspendu occupe le serveur ; c'est
#: le prix d'une reprise exacte, et l'interface doit le dire.
PAUSABLE_STATUSES: frozenset[JobStatus] = frozenset({"running"})

_ALLOWED: dict[JobStatus, frozenset[JobStatus]] = {
    "queued": frozenset({"running", "cancelled", "error"}),
    # `running` → `queued` n'existe pas : une analyse reprise repart d'un nouveau
    # job, sinon sa progression et ses agrégats partiels mentiraient.
    "running": frozenset({"paused", "done", "error", "cancelled"}),
    # Depuis la pause, on reprend ou on renonce. Pas de `done` : l'analyse est
    # arrêtée entre deux images, elle ne peut pas se terminer sans repasser par
    # `running`.
    "paused": frozenset({"running", "error", "cancelled"}),
    "done": frozenset(),
    "error": frozenset(),
    "cancelled": frozenset(),
}


class InvalidJobTransition(Exception):
    """Transition de statut refusée par la machine à états."""

    def __init__(self, current: JobStatus, target: JobStatus) -> None:
        super().__init__(f"Transition impossible : {current} → {target}.")
        self.current = current
        self.target = target


def is_terminal(status: JobStatus) -> bool:
    return status in TERMINAL_STATUSES


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    return target in _ALLOWED[current]


def ensure_transition(current: JobStatus, target: JobStatus) -> JobStatus:
    """Valide une transition et rend le statut cible, ou lève.

    Lever plutôt que d'ignorer : une transition refusée est un bug d'orchestration,
    et l'ignorer laisserait un job éternellement `running` sans que rien ne le
    signale.
    """
    if not can_transition(current, target):
        raise InvalidJobTransition(current, target)
    return target
