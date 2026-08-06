"""Client WebSocket de test.

**Pourquoi ce module existe plutôt qu'un simple import.** `httpx.AsyncClient`, que
tout le reste des tests d'intégration utilise, ne sait pas parler WebSocket : il n'y a
pas d'API pour cela. Le seul client capable de piloter un WebSocket ASGI en mémoire
est le `TestClient` de Starlette.

Or la version de Starlette installée ici **déprécie `httpx` au profit de `httpx2`** et
lève une `StarletteDeprecationWarning` à l'import — ce qui, avec la configuration
`filterwarnings = error` du projet, empêche la collecte du fichier de test entier.

Le choix : neutraliser l'avertissement **à cet import précis**, plutôt que d'ajouter
`httpx2` aux dépendances. Trois raisons, dans cet ordre :

1. c'est un avertissement de dépréciation, **pas** une incompatibilité — le client
   fonctionne, vérifié ;
2. ajouter `httpx2` mettrait deux implémentations HTTP dans l'environnement pour un
   seul fichier de test ;
3. le jour où Starlette retire vraiment le support, l'import échouera avec un
   `ModuleNotFoundError` explicite plutôt qu'un comportement dégradé silencieux —
   c'est-à-dire au bon moment, avec le bon message.

La neutralisation est **locale à cet import** : le reste de la suite garde
`filterwarnings = error`, qui est ce qui transforme une dépréciation en travail à
faire plutôt qu'en bruit à ignorer.
"""

from __future__ import annotations

import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from starlette.testclient import TestClient as _TestClient

#: Réexport sous le nom attendu, pour que les tests n'aient pas à connaître la ruse.
TestClient = _TestClient

__all__ = ["TestClient"]
