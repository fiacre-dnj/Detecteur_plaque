# ADR 0027 — La limite de débit globale exempte la lecture d'un job

- **Statut** : accepté
- **Date** : 2026-08-17
- **Amende** : la limite globale décrite dans
  [`prompt/06` §4](../../prompt/06-SECURITE-CORS-SWAGGER.md) — le principe
  d'une limite globale par IP reste entier, sa portée est corrigée.

## Contexte

L'historique promet de rouvrir une analyse archivée dans le studio, chiffres et
vidéo compris (`title` du bouton « Ouvrir » : « chiffres, géométrie, registre et
timeline, sur la vidéo resservie »). Le code qui fait cela existait déjà et
fonctionne : `session.adopt(jobId)` relit le statut, `fetchResult` télécharge le
résultat complet, `media.selectArchived` pose l'URL de la vidéo.

**Testé en conditions réelles — navigateur piloté contre le vrai serveur, pas
seulement le code lu** — ce parcours échoue par intermittence, en silence. Sur un
essai, « Ouvrir » a navigué vers le studio et n'a strictement rien affiché :
vidéo noire, aucune section de résultat, aucun message d'erreur. La console
portait un `429 Too Many Requests`.

Mesuré précisément, sur ce même parcours : **22 requêtes en 10 secondes** pour
ouvrir une seule analyse —

| requêtes | route |
|---|---|
| 14 | `GET /jobs/{id}/input` (la vidéo, par plages) |
| 1 chacune | `/health`, `/models`, `/models/classes`, `/jobs`, `/jobs/{id}/config`, `/jobs/{id}`, `/jobs/{id}/events`, `/jobs/{id}/result` |

La limite globale (`TRAFFIC_RATE_LIMIT_PER_MINUTE`, 60/minute par défaut) compte
alors qu'aucun préfixe, aucune méthode ne l'exempte : *toute* requête sur *toute*
route y participe. Une seule réouverture d'analyse en consomme donc plus d'un
tiers d'un coup. Deux ou trois réouvertures dans la même minute — un usage tout
à fait normal en parcourant l'historique — épuisent le quota.

**Le mode de panne est le pire possible : silencieux et auto-entretenu.**
`EventSource` n'a aucun traitement de `onerror` (délibéré, documenté dans
`useJobProgress.ts` : « il retente seul, une erreur ici alarmerait pour une
reconnexion normale ») et le sondage de secours retente toutes les 3 secondes.
Si le quota est déjà épuisé au moment de l'ouverture, chaque tentative de
reconnexion consomme elle-même du quota sans jamais réussir à le faire baisser
suffisamment — le studio reste bloqué sur son état d'avant-analyse
indéfiniment, sans qu'aucun texte à l'écran ne le dise.

## Décision

La limite globale exempte les requêtes **`GET`** dont le chemin commence par
`/api/v1/jobs/` (avec le `/` final — donc le statut, la configuration, le
résultat, la vidéo, le flux d'événements et les routes annexes d'un job précis,
mais **pas** la liste paginée `GET /jobs`, qui n'a jamais fait partie de la
rafale mesurée).

**L'exemption ne porte que sur la lecture.** `POST /jobs` (dépôt), `DELETE
/jobs/{id}` (annulation, purge) et `POST /jobs/{id}/{pause,resume}` restent
comptés par la limite globale — et `POST /jobs` reste en plus soumis à sa
propre règle, plus stricte (`TRAFFIC_RATE_LIMIT_JOBS_PER_MINUTE`, 10/minute),
qui est la protection que `prompt/06` §4 visait réellement : l'écriture de
plusieurs centaines de mégaoctets sur le disque, avant même que le sémaphore de
concurrence n'entre en jeu. Aucune lecture d'un job déjà terminé ne coûte cela.

Techniquement, `Rule` gagne un paramètre `exempt_get_prefixes`, vérifié avant
`methods` et `prefixes` : une exemption doit gagner même sur une règle qui,
sinon, matcherait tout.

## Pourquoi pas les deux autres options

- **Augmenter la limite globale** (ex. 60 → 240/minute) aurait été plus simple,
  mais affaiblit la protection *partout*, y compris là où `prompt/06` la
  voulait précise — un déposant, un banc de benchmark. Le problème mesuré est
  localisé (la lecture d'un job), la correction doit l'être aussi.
- **Un quota dédié, plus large, pour les lectures de job** (ex. 120/minute)
  reste une limite arbitraire sur une opération dont le coût réel — servir des
  octets déjà sur disque, ou une lecture SQLite — n'a rien de comparable à ce
  que la limite globale existe pour contenir. Une limite qui ne protège rien
  n'est qu'un délai déguisé.

## Conséquences

- Rouvrir une analyse archivée, y compris plusieurs fois de suite ou avec la
  vidéo abondamment scrutée, ne peut plus épuiser le quota global.
- La protection contre l'abus de l'ingestion est **intacte** : `POST /jobs`
  garde sa règle dédiée à 10/minute, plus la part qui lui reste de la règle
  globale.
- Un client qui interrogerait `GET /jobs/{id}/result` en boucle n'est plus
  borné par ce garde-fou précis. Ce n'est pas un abus nouveau : la même donnée
  est sur disque, servie par un `FileResponse`, et coûte à peu près ce que
  coûte n'importe quel fichier statique — bien moins que ce que la limite
  globale existe pour empêcher.
- Trois tests verrouillent la portée exacte : les lectures d'un job précis
  passent sans compter, la liste paginée reste comptée, les écritures
  (`POST`/`DELETE`) restent comptées. Un test d'intégration rejoue la mesure
  sur l'application réelle : dix lectures d'un job inconnu (404, jamais 429),
  puis le quota de test reste intact pour `/health`.
