# ADR 0017 — L'analyse peut être bridée sur le temps de la scène, et le rattrapage est borné

- **Statut** : accepté
- **Date** : 2026-08-14
- **Complète** : [ADR 0006](0006-apercu-live-des-analyses.md) — l'aperçu live, dont ce
  document corrige le défaut d'affichage sans toucher à son mécanisme

## Contexte

L'aperçu live d'ADR 0006 n'est pas une vidéo : le client **cale** sa balise `<video>`
sur le temps de scène de chaque échantillon (`useFollowAnalysis`), il ne la lit pas. Ce
choix est bon — il garantit que les boîtes dessinées correspondent exactement à l'image
affichée — mais il a une conséquence arithmétique que rien ne compensait.

Les échantillons sont espacés en **temps mural** : au plus un toutes les 200 ms. Le
curseur avance donc, par seconde réelle, de `fps_analyse / fps_vidéo` seconde de scène.
Mesuré contre le vrai serveur sur un clip de 8,0 s à 30 fps, `yolov8n` sur Quadro P1000 :

| cadence d'analyse | durée murale | scène par seconde réelle |
|---|---|---|
| libre (52,1 img/s) | 4,68 s | **1,70×** |

L'aperçu défilait donc à 170 % de la vitesse réelle. Ce n'est pas un défaut de l'aperçu,
c'est le GPU qui va plus vite que la scène — et le symptôme empire à mesure que le
matériel s'améliore.

## Décision — une cadence maximale, choisie par requête

`analysisSpeed` borne la cadence d'analyse en multiples de la vitesse réelle de la
scène. La boucle attend entre deux images pour que le temps de scène n'avance jamais
plus vite que ce multiple. `null` — le défaut — n'impose aucune borne.

**Par requête et non par déploiement**, comme les classes à compter et pour la même
raison : c'est un arbitrage que seul l'utilisateur devant sa vidéo peut trancher —
regarder l'analyse, ou obtenir ses chiffres au plus vite. Le défaut est le comportement
historique, donc qui ne touche à rien garde son débit.

L'interface propose trois cadences et pas un curseur continu : « illimitée », « temps
réel » et « 2× ». Un curseur inviterait à régler 1,37×, un chiffre qui ne répond à
aucune question.

Mesuré, même clip, même machine :

| cadence | durée murale | scène / s réelle | cadence servie | aperçus reçus |
|---|---|---|---|---|
| illimitée | 4,68 s | 1,70× | 52,1 img/s | 16 |
| **temps réel** | **8,07 s** | **0,99×** | **30,0 img/s** | **61** |
| 2× | 4,37 s | 1,82× | 56,0 img/s | 33 |

`2×` rend 1,82× et non 2,00× : le travail par image (14,8 ms) approche la période
(16,7 ms), donc la borne n'est plus atteignable. C'est bien une cadence **maximale**.

Le bridage resserre aussi l'intervalle d'aperçu (`TRAFFIC_PREVIEW_INTERVAL_PACED_MS`,
100 ms), sans jamais l'élargir. À 200 ms, une analyse à 1× ne montrerait que cinq images
de scène par seconde : la vitesse serait juste et l'aperçu resterait un diaporama. Brider
*est* la décision de regarder, donc celle d'accepter plus de trames — elles ne portent
que des boîtes et des compteurs, jamais de pixels.

## Décision — le rattrapage est autorisé, borné à trois périodes

C'est le point qui ne se devine pas, et il a coûté une mesure.

La première version du cadenceur n'autorisait **aucun** rattrapage : toute image ayant
dépassé son échéance repoussait le calendrier d'autant. La règle paraissait
prudente — elle interdit qu'un à-coup soit suivi d'une rafale d'images sans attente,
donc d'une accélération visible de l'aperçu. Elle était fausse.

Le coût d'une image est très irrégulier. Sur le clip de test, 240 images à 15 ms de
moyenne, mais **60 d'entre elles dépassent la période de 33,3 ms**. Chaque dépassement
était perdu définitivement, et la somme se voyait :

| cadenceur | attente totale | durée murale | scène / s réelle |
|---|---|---|---|
| sans rattrapage | 5,44 s | 9,58 s | **0,82×** |
| rattrapage borné à 3 périodes | 4,28 s | **8,01 s** | **1,00×** |

Un bridage annoncé à « 1× » servait donc 0,82× — 18 % trop lent, dans l'autre sens que
le bug d'origine. Deux fausses pistes ont été écartées par la mesure avant d'arriver là,
et elles valent d'être notées parce qu'elles étaient plausibles :

- **la gigue de `sleep`** : mesurée à 0,4 ms de surcoût sur cette machine, pour des
  consignes de 1 à 33 ms. Négligeable ;
- **le coût de l'aperçu resserré** : à 100 ms d'intervalle, l'analyse libre monte à
  49,2 img/s contre 45,9 à 200 ms. Publier plus d'aperçus ne coûte rien de mesurable.

La borne, elle, reste indispensable : au-delà de trois périodes de retard l'échéance
repart du temps écoulé. Un vrai décrochage — chargement de poids, passe ANPR chère — ne
se rattrape donc pas, et le temps perdu se retrouve dans la durée totale. C'est voulu :
le rattraper demanderait la rafale que la première version cherchait à interdire. Trois
périodes, c'est au pire une centaine de millisecondes de scène rendues à pleine
vitesse — invisible.

## Conséquences

- **`processing_fps` d'une analyse bridée mesure le bridage, pas la machine.** Le temps
  d'attente n'est pas retranché, contrairement au temps de pause : c'est du travail que
  l'analyse a choisi de faire, et le déduire donnerait une échéance annoncée fausse d'un
  facteur égal au bridage. Ne comparer que des runs de même cadence ; le banc
  (`scripts/anpr_bench.py`) et la feature `benchmark` ne bridant jamais, leurs chiffres
  restent comparables entre eux.
- **Aucun compteur ne change.** Le bridage n'ajoute qu'une attente entre deux images :
  la même vidéo rend les mêmes véhicules, les mêmes passages et la même timeline,
  verrouillé par `test_le_bridage_ne_change_aucun_chiffre`.
- **L'horloge murale est utilisée, légitimement.** Comme la mesure de cadence, le
  cadenceur ne produit aucun horodatage métier : il ne décide que d'une attente. Tous
  les temps de scène restent `frame_index / fps × 1000` (invariant 1).
- **Sans effet en direct**, où c'est le client qui cadence son envoi. Le champ traverse
  `AnalysisRequestSchema`, partagé par les deux modes, comme `frameStride` avant lui.
- **Une source qui ne déclare pas sa cadence n'est pas bridée**, et le journal le dit.
  Le cas est défensif : `probe()` de l'adaptateur retombe sur sa cadence de repli avant
  d'en arriver là.
