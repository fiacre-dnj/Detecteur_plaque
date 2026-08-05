"""Vérification de l'`Origin` d'un handshake WebSocket.

**Pourquoi ce module existe, et pourquoi CORS ne suffit pas.** Un WebSocket n'est
**pas** protégé par la politique de même origine : le navigateur envoie bien un
en-tête `Origin`, mais il n'applique aucun préflight et n'exige aucune réponse
`Access-Control-Allow-Origin`. Le `CORSMiddleware` de Starlette ne voit donc jamais
passer un handshake WebSocket. Concrètement : sans cette vérification, n'importe
quelle page web ouverte dans le navigateur de l'utilisateur peut se connecter à ce
WebSocket, envoyer ses propres frames, et consommer le GPU du serveur — la variante
WebSocket du CSRF.

La vérification est donc explicite, et elle se fait **avant `accept()`** : accepter
puis fermer laisserait une trame de handshake aboutir, ce qui suffit à certaines
attaques de sonde.
"""

from __future__ import annotations

from traffic_analysis.core.logging import get_logger

logger = get_logger("traffic_analysis.realtime")


def is_origin_allowed(
    origin: str | None,
    allowed: tuple[str, ...],
    *,
    allow_missing: bool = True,
) -> bool:
    """L'origine du handshake est-elle autorisée ?

    `origin=None` est **accepté par défaut**, et ce choix mérite d'être défendu :
    un en-tête `Origin` absent signifie que la requête ne vient pas d'un navigateur
    — `curl`, un script de test, un client natif. Or ce sont précisément les clients
    qui ne sont pas soumis au risque que cette vérification adresse : il n'y a pas
    de page tierce, donc pas de confusion d'autorité à exploiter. Refuser
    casserait tous les outils de diagnostic sans rien protéger de plus.

    La comparaison est **exacte**, pas par préfixe : `http://localhost:5173` ne doit
    pas autoriser `http://localhost:5173.evil.com`, que `startswith` accepterait.
    """
    if origin is None:
        return allow_missing
    return origin in allowed


def rejection_reason(origin: str | None) -> str:
    """Message de fermeture pour une origine refusée.

    L'origine reçue est **citée** : sans elle, un développeur qui a oublié
    d'ajouter son port au `TRAFFIC_CORS_ORIGINS` cherche pendant une heure. Avec
    elle, la cause est immédiate.
    """
    return f"Origine non autorisée : {origin or 'absente'}."
