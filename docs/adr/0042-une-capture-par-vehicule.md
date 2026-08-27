# ADR 0042 — Une capture par véhicule, et la meilleure lecture gagne

- **Statut** : accepté
- **Date** : 2026-08-27
- **Complète** : [ADR 0010](0010-etranglement-du-detecteur-de-plaques.md) et
  [ADR 0036](0036-la-confiance-de-lecture-devient-un-reglage-de-l-utilisateur.md).

## Contexte

Le registre dit qu'une plaque a été lue et avec quelle confiance. Il ne montre pas
**ce qui a été lu**. « `TAR606L` à 85 % » est un chiffre qu'on croit ou qu'on ne
croit pas ; la photo du véhicule et de sa plaque est une preuve qu'on **vérifie**.
C'est exactement la raison qui a fait naître le registre lui-même face aux cartes de
comptage.

Le besoin est devenu pressant avec la recherche de plaque
([ADR 0041](0041-les-alertes-se-calculent-cote-client.md)) : une alerte « plaque
recherchée » demande à être confirmée à l'œil avant d'engager quoi que ce soit, et
[ADR 0029](0029-la-plaque-perdait-son-premier-caractere.md) documente que l'OCR perd
régulièrement un caractère.

## Décision — une capture, la meilleure **lecture**, et rien d'autre

Chaque véhicule dont une plaque est **lue** reçoit deux JPEG : le recadrage du
véhicule, et celui de sa plaque, pris sur **la même image**. Une seule capture par
véhicule, et c'est la lecture la plus sûre qui la détermine — à 0,80 on capture, à
0,90 on remplace, à 0,85 ensuite on ne touche plus à rien. Une comparaison stricte,
donc monotone croissante.

**Le score est celui de l'image, jamais celui du vote.** `PlateTextVote.score` est
une moyenne sur toute la vie du véhicule : il bouge quand une *autre* image est lue,
donc l'utiliser ferait recapturer pour une raison sans rapport avec la qualité de
l'image courante. Mesuré sur une vraie analyse, l'écart est net et va dans le sens
attendu — capture 0,982 pour un vote à 0,852.

## Décision — le seuil de déclenchement n'existe pas, il est déjà là

Une `PlateDetection` n'existe qu'au-dessus de « Confiance plaques », et l'adaptateur
d'OCR ne rend un `PlateText` qu'au-dessus de « Confiance lecture » (ADR 0036, le
filtre vit dans l'adaptateur et nulle part ailleurs).

**Toute plaque qui arrive avec un texte a donc déjà franchi les deux seuils de
l'utilisateur.** La capture hérite des réglages gratuitement, et aucun troisième
seuil n'est ajouté — un réglage de plus serait un réglage capable de contredire les
deux autres.

## Décision — jamais depuis une boîte reprojetée

Le détecteur de plaques est étranglé (ADR 0010) : les images sautées reçoivent
l'ancre de la dernière détection réelle, reprojetée sur la boîte courante du
véhicule. La règle absolue de cette ADR — « l'OCR ne lit jamais une boîte
reprojetée, et une reprojection ne nourrit aucun agrégat » — vaut ici mot pour mot.

Le point d'accroche est donc la branche **mesure fraîche** de `_detect_plates`,
celle-là même qui appelle `_read_plate_text` : la seule où la boîte du véhicule, la
boîte de plaque mesurée, le texte lu et les pixels coexistent. Une capture prise sur
une ancre projetée donnerait une vignette de plaque décalée — et la donner pour la
meilleure preuve d'un véhicule serait un faux témoignage.

## Décision — encoder à l'amélioration, écrire à la fin

Trois coûts, traités séparément :

- **le recadrage** est un `slice` numpy, donc gratuit — mais c'est une **vue** : la
  garder retiendrait toute l'image parente, 6 Mo en 1080p, par véhicule retenu ;
- **l'encodage JPEG** a lieu **uniquement quand le score bat le précédent** ;
- **l'écriture disque** ne touche pas la boucle : les octets sont tenus en mémoire
  (~23 Ko par véhicule mesuré) et écrits en une passe à la fin, là où
  `result.json.gz` est déjà écrit, dans un thread worker (invariant 11).

L'encodage immédiat règle du même coup le problème de la vue : il copie les pixels
au moment où ils sont valides.

### Ce que cela coûte — mesuré, pas supposé

Sur une analyse réelle (1080p, `yolo11n`, ANPR et OCR actives, 1 800 images en
176 s) :

| | |
|---|---|
| encodages demandés | **41** |
| captures gardées | 6 |
| coût total de l'encodage | **98 ms** |
| part du temps d'analyse | **0,056 %** |
| coût par encodage (p50 / p90 / max) | 1,88 / 2,29 / 5,21 ms |

**Un banc de bout en bout ne peut pas résoudre 0,056 %.** Cette machine varie de
±20 % selon son état thermique (piège 59 de `prompt/13`) : un `pipeline_bench`
apparié aurait rendu du bruit qu'on aurait été tenté de lire comme un signal. La
mesure porte donc sur le poste lui-même, instrumenté dans une vraie course.

Les 41 appels pour 1 800 images sont le chiffre qui compte : c'est la règle monotone
qui protège le chemin critique, pas l'encodeur qui serait rapide. Un code qui
encoderait à chaque lecture puis jetterait le résultat rendrait exactement le même
registre pour un coût sans rapport — et aucun test portant sur le seul résultat ne
le verrait. D'où un test qui compte les appels.

Borne défensive : `MAX_SNAPSHOTS = 500` (~12 Mo), **annoncée** quand elle est
atteinte. Une analyse qui cesserait silencieusement de capturer se lirait comme une
panne de l'OCR.

## Décision — deux fichiers, pas une image composite

Le véhicule et la plaque sont deux JPEG ; la mise en page « la plaque sous la
voiture » est faite en CSS.

Composer côté serveur figerait une décision d'affichage dans la donnée stockée, alors
que la vignette de plaque a sa propre vie : c'est elle qui valide une alerte, et on
veut pouvoir la montrer seule, plus grande, à côté du texte cherché. Le coût est
nul — la table ne charge que le véhicule, la modale charge les deux.

Le véhicule est réduit à 480 px de côté et la plaque à 320 px de large
(`INTER_AREA`), avec 6 % de marge autour du véhicule : le détecteur cadre au plus
juste, et un recadrage collé à sa boîte coupe le pare-chocs.

## Décision — les captures sont purgées avec la vidéo

`delete_input` justifie déjà le TTL court de la vidéo : « la donnée la plus lourde
**et la plus sensible** — une scène de trafic contient des plaques réelles et des
visages ». Un recadrage sur une voiture et sa plaque est exactement cela, en plus
concentré. Le laisser survivre à la vidéo dont il est extrait inverserait la règle
que ce TTL existe pour appliquer.

`delete_input` balaie donc `snapshots/`, et l'interface sait afficher une capture
absente — un repère muet et non une image cassée, parce que c'est le cas **normal**
après le TTL.

## Ce qui ne change pas

- **Aucun chiffre.** Le comptage, les plaques publiées et le registre sont
  identiques avec ou sans encodeur ; un `snapshot_encoder` absent désactive
  proprement la fonctionnalité. Un test le verrouille.
- **Aucune migration.** Les captures sont des fichiers dans le répertoire du job,
  que `delete` emporte déjà d'un `rmtree`.
- **Aucune URL côté serveur.** `VehicleRecord` porte `snapshotScore` et
  `snapshotMs` ; leur non-nullité **est** le drapeau « il existe une photo », et le
  client construit l'adresse lui-même — la convention d'`inputVideoUrl`.

## Conséquences

- **Le cas le plus utile n'était pas celui qu'on visait.** Sur l'analyse mesurée, 7
  véhicules ont une capture pour 6 plaques publiées : le septième porte
  `no_consensus`, c'est-à-dire que l'OCR a refusé de publier. Sa photo permet de
  lire la plaque que le serveur n'a pas voulu affirmer — un refus honnête devient un
  fait vérifiable.
- **Pas de vignette pendant l'analyse.** Les fichiers sont écrits à la fin ; la
  colonne n'existe qu'ensuite. Transporter les images dans l'aperçu SSE
  multiplierait sa charge par ~30 alors qu'ADR 0026 se bat pour 350 octets par
  véhicule. Même règle, et même raison, que les exports masqués tant que le résultat
  n'existe pas.
- **Le registre passe à 48 px de rangée, mais seulement quand des captures
  existent.** `visibleWindow` acceptait déjà une hauteur en paramètre. Attention :
  le `height` d'une rangée n'est qu'un **minimum** en CSS — la cellule de capture
  supprime son rembourrage vertical, faute de quoi la rangée rendue faisait 57 px là
  où la virtualisation en calculait 48, et les rangées dérivaient au-delà de 200
  lignes.
