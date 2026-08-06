"""Le port de persistance des presets.

Un seul port : les presets ne touchent ni au matériel, ni au disque, ni à un modèle.
C'est la feature la plus simple du projet, et son port le reflète.

Les types de domaine et de pagination sont importés sous `TYPE_CHECKING` :
`tests/test_architecture.py` interdit `sqlalchemy` dans `application/`, et l'analyse
AST ne distingue pas un import de typage d'un import réel. La session vit donc
entièrement dans l'infrastructure, qui est le seul endroit à la nommer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from traffic_analysis.core.pagination import Page, PageParams
    from traffic_analysis.features.presets.domain.records import Preset


@runtime_checkable
class PresetRepository(Protocol):
    """Persistance des géométries enregistrées.

    `add` et `update` sont distincts alors qu'un `save` unique suffirait
    techniquement. La séparation est délibérée : elle permet au dépôt de refuser un
    `add` sur un nom déjà pris et un `update` sur un identifiant inconnu, deux
    erreurs que l'utilisateur doit voir différemment — « ce nom existe déjà » et
    « ce preset a été supprimé » n'appellent pas la même action.
    """

    async def add(self, preset: Preset) -> None: ...

    async def get(self, preset_id: str) -> Preset | None: ...

    async def get_by_name(self, name: str) -> Preset | None: ...

    async def list(self, page: PageParams) -> Page[Preset]: ...

    async def update(self, preset: Preset) -> bool:
        """Rend `False` quand l'identifiant n'existe pas — sans lever.

        C'est au service de décider si l'absence est une erreur, parce que lui seul
        connaît le geste de l'utilisateur.
        """
        ...

    async def delete(self, preset_id: str) -> bool:
        """Rend `False` quand rien n'a été supprimé.

        Là encore sans lever : un dépôt qui lève sur une suppression idempotente
        obligerait chaque appelant à attraper une exception pour un cas normal.
        """
        ...
