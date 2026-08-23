"""Le filet qui empêche l'architecture de se dissoudre en six mois.

Une règle de dépendance écrite dans un document est une intention ; une règle
vérifiée par un test est une contrainte. Celle-ci est la plus rentable du projet :
c'est la pureté du domaine qui permet à la CI de tourner **sans GPU, sans poids et
sans ultralytics**, en injectant un moteur factice. Le jour où quelqu'un importe
`cv2` dans le comptage « juste pour un redimensionnement », toute cette propriété
disparaît d'un coup — et rien d'autre ne le signalerait.

L'analyse se fait avec `ast` sur le source, sans importer les modules : importer
`features/models_registry/infrastructure` chargerait justement `ultralytics`, ce
que ce test existe pour éviter.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "traffic_analysis"
PACKAGE = "traffic_analysis"

# Interdits dans `features/*/domain/**`. `numpy` n'y figure pas volontairement :
# un descripteur de ré-identification est du calcul, pas de l'infrastructure.
FORBIDDEN_IN_DOMAIN = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "ultralytics",
    "cv2",
    "torch",
    "pydantic",
)

# Interdits dans `features/*/application/**` : la couche d'orchestration parle à
# des ports, pas à des bibliothèques concrètes.
FORBIDDEN_IN_APPLICATION = ("fastapi", "starlette", "sqlalchemy", "ultralytics", "cv2")


class Import(NamedTuple):
    """Un import, avec de quoi produire un message d'échec exploitable."""

    module: str
    line: int


def _python_files(*parts: str) -> list[Path]:
    root = SOURCE_ROOT.joinpath(*parts) if parts else SOURCE_ROOT
    return sorted(root.rglob("*.py")) if root.exists() else []


def _imports_of(path: Path) -> list[Import]:
    """Modules importés par un fichier, sans l'exécuter."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[Import] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(Import(alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append(Import(node.module, node.lineno))
    return found


def _root_of(module: str) -> str:
    return module.split(".")[0]


def _relative(path: Path) -> str:
    return path.relative_to(SOURCE_ROOT.parent.parent).as_posix()


def _feature_of(path: Path) -> str | None:
    """Nom de la feature à laquelle appartient un fichier, s'il y en a une."""
    parts = path.relative_to(SOURCE_ROOT).parts
    return parts[1] if len(parts) > 2 and parts[0] == "features" else None


def _layer_files(layer: str) -> list[Path]:
    """Tous les fichiers d'une couche donnée, toutes features confondues."""
    features_root = SOURCE_ROOT / "features"
    if not features_root.exists():
        return []
    return sorted(features_root.glob(f"*/{layer}/**/*.py"))


@pytest.mark.parametrize("path", _layer_files("domain"), ids=_relative)
def test_le_domaine_n_importe_aucune_infrastructure(path: Path) -> None:
    """`features/*/domain/**` reste pur.

    C'est la contrainte qui rend le domaine testable sans matériel, et elle est
    absolue : pas d'exception « juste pour ce module ».
    """
    offenders = [
        imported
        for imported in _imports_of(path)
        if _root_of(imported.module) in FORBIDDEN_IN_DOMAIN
    ]

    assert not offenders, (
        f"{_relative(path)} importe de l'infrastructure dans le domaine : "
        + ", ".join(f"{item.module} (ligne {item.line})" for item in offenders)
    )


@pytest.mark.parametrize("path", _layer_files("application"), ids=_relative)
def test_l_application_parle_a_des_ports_et_non_a_des_bibliotheques(path: Path) -> None:
    """`features/*/application/**` orchestre, elle n'adapte pas.

    `pydantic` y est toléré (les DTO en profitent) ; les bibliothèques de
    transport, de persistance et de vision ne le sont pas.
    """
    offenders = [
        imported
        for imported in _imports_of(path)
        if _root_of(imported.module) in FORBIDDEN_IN_APPLICATION
    ]

    assert not offenders, f"{_relative(path)} contourne ses ports : " + ", ".join(
        f"{item.module} (ligne {item.line})" for item in offenders
    )


# Seule couche d'une feature qu'une **autre** feature peut importer : son contrat
# publié (ports, DTO, services d'application, sérialiseurs).
PUBLISHED_LAYER = "application"


@pytest.mark.parametrize("path", _python_files("features"), ids=_relative)
def test_une_feature_n_importe_qu_une_autre_par_son_contrat_publie(path: Path) -> None:
    """Deux features ne se parlent que par la couche `application` de l'autre.

    Certaines dépendances entre features sont légitimes et voulues : `jobs`
    orchestre une analyse, donc il a besoin de `counting`. Ce qui doit rester
    interdit, c'est de **fouiller dans les internes** — importer un `domain`, une
    `infrastructure` ou une route d'une autre feature.

    La couche `application` est le contrat : ses ports, ses DTO et ses
    sérialiseurs sont ce que la feature s'engage à maintenir. Le reste peut
    changer sans prévenir. C'est aussi pour cela que
    `counting/application/dto.py` réexporte le vocabulaire minimal dont un
    appelant a besoin — sans quoi la frontière ne tiendrait pas en pratique.
    """
    own_feature = _feature_of(path)
    if own_feature is None:
        pytest.skip("fichier hors d'une feature")

    prefix = f"{PACKAGE}.features."
    offenders: list[Import] = []
    for imported in _imports_of(path):
        if not imported.module.startswith(prefix):
            continue
        parts = imported.module[len(prefix) :].split(".")
        target_feature = parts[0]
        if target_feature == own_feature:
            continue
        target_layer = parts[1] if len(parts) > 1 else ""
        if target_layer != PUBLISHED_LAYER:
            offenders.append(imported)

    assert not offenders, (
        f"{_relative(path)} (feature « {own_feature} ») fouille dans les internes "
        f"d'une autre feature — n'importer que sa couche « {PUBLISHED_LAYER} » : "
        + ", ".join(f"{item.module} (ligne {item.line})" for item in offenders)
    )


@pytest.mark.parametrize("path", _python_files("core"), ids=_relative)
def test_le_coeur_n_importe_aucune_feature(path: Path) -> None:
    """`core` est le socle : tout le monde en dépend, il ne dépend de personne.

    Un `core` qui importe une feature crée un cycle et rend l'ordre d'import
    dépendant du hasard.
    """
    offenders = [
        imported
        for imported in _imports_of(path)
        if imported.module.startswith(f"{PACKAGE}.features")
    ]

    assert not offenders, (
        f"{_relative(path)} : le socle ne doit dépendre d'aucune feature — "
        + ", ".join(f"{item.module} (ligne {item.line})" for item in offenders)
    )


@pytest.mark.parametrize("path", _python_files(), ids=_relative)
def test_aucun_print_dans_le_code_de_production(path: Path) -> None:
    """Un `print` échappe au journal structuré, donc à toute corrélation.

    Ruff l'attrape déjà (règle `T20`) ; ce test le redit ici parce que la liste
    des règles ruff, elle, peut être modifiée sans que personne ne s'en aperçoive.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]

    assert not offenders, f"{_relative(path)} contient un print (lignes {offenders})"


def test_le_domaine_du_comptage_existe_et_est_analyse() -> None:
    """Garde-fou des tests paramétrés ci-dessus.

    Si `_layer_files` cessait de trouver les fichiers — un dossier renommé, une
    arborescence déplacée — tous les tests d'architecture passeraient
    silencieusement sur une liste vide, ce qui est bien pire que de les voir échouer.
    """
    domain_files = {path.name for path in _layer_files("domain")}

    assert {
        "geometry.py",
        "models.py",
        "line_counter.py",
        "zone_counter.py",
        "track_numbering.py",
        "tracking_session.py",
    } <= domain_files
