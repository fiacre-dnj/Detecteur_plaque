# ADR 0046 — Les captures s'écrivent pendant l'analyse

- **Statut** : accepté
- **Date** : 2026-08-28
- **Amende** : [ADR 0042](0042-une-capture-par-vehicule.md), sur sa seule
  conséquence « Pas de vignette pendant l'analyse ». Ses deux règles dures — jamais
  depuis une boîte reprojetée, encodage à l'amélioration seulement — sont
  **conservées mot pour mot**.

## Contexte

ADR 0042 encode une capture dès qu'une lecture bat la précédente, garde les octets
en mémoire (~23 Ko par véhicule, borné à 500) et les **écrit en une passe à la
fin**, là où `result.json.gz` est déjà écrit.

La conséquence était énoncée et acceptée : « Pas de vignette pendant l'analyse. »
Elle coûte plus cher qu'il n'y paraissait, parce qu'elle prive de photo les deux
moments où la photo sert le plus :

- **le registre se remplit pendant l'analyse** depuis ADR 0026. Sa colonne
  « Capture » restait donc vide pendant tout le temps où on le regarde se remplir,
  et n'apparaissait qu'une fois qu'on avait fini de le regarder ;
- **une alerte de plaque recherchée demande à être confirmée à l'œil** (ADR 0041,
  et ADR 0029 documente que l'OCR perd régulièrement un caractère). Elle tombait
  sans sa preuve, et la preuve arrivait quand l'alerte n'était plus d'actualité.

L'argument d'origine visait le **SSE** : transporter les images dans l'aperçu
multiplierait sa charge par ~30, alors qu'ADR 0026 se bat pour 350 octets par
véhicule. Il est intact — et il ne s'applique pas à ce qui suit.

## Décision — avancer l'écriture, sans rien mettre dans le flux

**Rien ne transite par le SSE.** Le navigateur demande les JPEG comme il le fait
déjà : en `GET /jobs/{id}/vehicles/{n}/snapshot.jpg`, une route exemptée de la
limite de débit depuis ADR 0027, sur une balise `<img loading="lazy">` qui ne
demande que les rangées visibles.

Seule l'**écriture** avance. `run_video` reçoit un rappel `on_snapshot`, de la même
forme qu'`on_preview`, appelé exactement là où l'encodeur vient de rendre les deux
JPEG. `JobManager` y branche `write_snapshots`.

Trois points qui ne se devinent pas :

- **le rappel est appelé depuis le thread worker**, comme `on_progress` et
  `on_preview`, donc l'écriture ne bloque pas la boucle d'événements (invariant 11).
  Aucune bascule vers la boucle n'est nécessaire, contrairement à `on_progress` qui
  persiste en base ;
- **il vient après `record_snapshot`, jamais à sa place.** Le fichier existe donc
  déjà quand l'aperçu suivant publie le `snapshotScore` qui l'annonce au client.
  L'ordre inverse afficherait une image cassée le temps d'un aperçu ;
- **il suit la règle monotone**, pas les lectures : une écriture par **amélioration
  retenue**, soit les 41 mesurées sur 1 800 images d'ADR 0042. Un rappel posé sur
  chaque lecture réécrirait le fichier avec les octets d'une image moins bonne, et
  le registre annoncerait un score que la photo ne porte pas.

**L'écriture finale reste.** Elle réécrit les mêmes octets et sert de filet : un
rappel qu'une erreur disque passagère aurait fait échouer est rattrapé, et
`write_snapshots` ne lève jamais — journaliser fichier par fichier était déjà sa
règle. Les octets restent aussi en mémoire : le rappel est un canal **de plus**,
jamais un remplacement, et une analyse sans rappel se comporte exactement comme
avant. Un test le verrouille.

## Décision — le refus « job non terminé » disparaît

`JobManager.snapshot_path` refusait par un 409 `job_not_finished` toute capture d'un
job qui n'était pas `done`. Ce refus énonçait une vérité d'implémentation — « les
captures sont écrites à la fin » — qui n'en est plus une : le garder aurait refusé
des fichiers présents sur le disque.

Il ne reste que deux refus, et ils disent tous deux ce qui manque : 404 pour un job
inconnu, `snapshot_missing` pour une capture absente. Ce dernier recouvre désormais
trois causes — jamais produite, **pas encore** écrite, purgée avec la vidéo — et
c'est délibéré : les trois sont normales, aucune n'est une panne, et les distinguer
demanderait à l'utilisateur de comprendre un détail d'implémentation pour lire un
tableau.

## Décision — l'adresse porte l'instant de la capture

Les images sont servies en `private, max-age=31536000, immutable`, ce qui était vrai
tant qu'un fichier était écrit une fois. Il est maintenant **remplacé** dès qu'une
lecture bat la précédente : un navigateur garderait la première version — souvent la
moins bonne — pour un an.

L'interface versionne donc l'adresse : `snapshot.jpg?v=<snapshotMs>`. `snapshotMs`
change exactement quand le fichier change — `record_snapshot` pose le score et
l'instant ensemble — donc l'URL identifie le triplet job + véhicule + **prise de
vue**, qui, lui, est réellement immuable. Le serveur ignore la requête : aucune
route ne change, et l'en-tête redevient juste.

C'est aussi la raison de ne pas avoir choisi l'autre solution évidente, un
`Cache-Control` court pendant l'analyse : elle aurait fait re-télécharger chaque
vignette visible à chaque rendu du tableau, pour un problème que quatre caractères
d'URL suppriment.

## Décision — un seul réessai, et seulement pendant l'analyse

Le fichier est écrit avant que l'aperçu l'annonce, mais les deux voyagent par des
chemins différents : quelques centaines de millisecondes peuvent les séparer. La
vignette réessaie donc **une fois** — avec un paramètre `retry` qui casse le cache
d'échec, sans quoi un second chargement de la même adresse ressusciterait la réponse
en erreur.

Hors analyse, une image absente l'est pour de bon : c'est le cas normal après le TTL
de la vidéo, et réessayer doublerait des requêtes vouées à échouer sur chaque rangée
visible.

## Ce qui ne change pas

- **Aucun chiffre, aucune capture de plus ou de moins.** Même encodeur, même règle
  monotone, même point d'accroche sur la branche « mesure fraîche » de
  `_detect_plates` — une capture n'est **jamais** prise depuis une boîte reprojetée
  (ADR 0010).
- **La purge.** `delete_input` balaie toujours `snapshots/` avec la vidéo : ce sont
  des plaques et des visages, et le TTL court existe pour les effacer.
- **`MAX_SNAPSHOTS = 500`**, annoncé quand il est atteint.
- **Les trois boutons d'export restent masqués tant que `result` est `null`.** Ce
  n'est pas la même règle, et il ne faut pas l'aligner : un CSV à mi-parcours ment
  sur son contenu — amputé sans dire de combien — alors qu'une vignette manquante ne
  ment sur rien.

## Conséquences

- **La colonne « Capture » apparaît d'elle-même**, sans réglage : elle est
  conditionnée à `hasSnapshots(vehicles)`, qui lit `snapshotScore`, que l'aperçu SSE
  porte déjà — `serialise_vehicle` est le **même** sérialiseur pour l'aperçu et le
  résultat. Sans ANPR ni OCR, aucun véhicule ne porte de score, donc aucune colonne.
- **Attention à `ROW_HEIGHT`** : la colonne fait passer la rangée de 36 à 48 px, et
  elle apparaît maintenant **en cours de remplissage**. `snapshotRowHeight` est déjà
  dans les dépendances du mémo de virtualisation ; s'il en sortait, les rangées
  dériveraient sous le curseur au-delà de 200 lignes, et jamais avant.
- **La modale s'ouvre aussi pendant l'analyse.** Son garde était
  `session.result !== null`, ce qui rendait la vignette d'une alerte cliquable et
  sans effet au moment précis où l'on veut vérifier une plaque recherchée.
