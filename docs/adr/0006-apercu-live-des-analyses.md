# ADR 0006 — L'analyse différée se regarde pendant qu'elle tourne

- **Statut** : accepté
- **Date** : 2026-08-06

## Contexte

Jusqu'ici, le flux SSE d'un job ne transportait que des scalaires : `progress`,
`processedFrames`, `processingFps`. Les boîtes, les identités et les
franchissements n'existaient côté client qu'au statut `done`, dans le
`result.json.gz`, rejoué ensuite par `useReplay`.

Conséquence : une analyse ne pouvait pas être **validée** pendant son exécution.
Sur une vidéo de dix minutes analysée à 5 images par seconde — la cadence CPU
réelle de cette machine — cela veut dire dix minutes d'attente devant une barre de
progression avant de découvrir qu'une ligne était mal placée, qu'un masque
mangeait la moitié de la scène, ou que le modèle ne détectait rien. Et devant le
résultat, rien ne distingue « le compte est bon » de « le compte est plausible ».

Ce qui manquait n'était donc pas de la donnée — le résultat final la contient
toute — mais le **moment** où on la voit : au moment où le serveur la produit,
sur l'image qui l'a produite.

## Décision

Le backend publie, pendant l'analyse, un troisième type d'événement SSE
`preview` sur la route existante `GET /jobs/{id}/events`. Le navigateur cale la
balise `<video>` locale sur le temps de scène de l'aperçu et dessine l'overlay du
serveur par-dessus.

Cinq propriétés font tenir l'ensemble.

**1. Même forme que le temps réel.** Le payload est celui du `frameResult` du
WebSocket, produit par les mêmes `serialise_track` / `serialise_crossing` /
`serialise_zone_event` / `serialise_stats`. Le navigateur dessine donc les trois
modes — direct, aperçu, relecture — avec un seul chemin de rendu. Deux chemins
divergeraient, et l'écran montrerait deux vérités selon le mode.

**2. Échantillonné en temps, pas en images.** Au plus un aperçu toutes les
`TRAFFIC_PREVIEW_INTERVAL_MS` (200 ms par défaut, `0` désactive). La cadence
d'analyse varie d'un facteur dix entre CPU et GPU ; ce qu'on borne — le débit du
flux, le travail du navigateur — se mesure en secondes. Mesuré sur une analyse
réelle : ~2 Ko par aperçu, soit ~10 Ko/s.

**3. Les événements sont cumulés depuis l'aperçu précédent.** Une image sur six
est publiée ; ne transporter que les franchissements de celle-là en perdrait cinq
sur six, alors que les compteurs, eux, resteraient justes. Un journal en
désaccord avec son propre total est pire qu'un journal absent.

**4. Un aperçu n'est pas un état de job.** Il n'entre ni en base — SQLite n'a
qu'un écrivain, et on publie cinq fois par seconde — ni dans le « dernier état
connu » du `ProgressHub`, qui sert de réponse immédiate à un client qui se
reconnecte : celui-ci attend de savoir où en est l'analyse, pas de recevoir une
image. Un client peut ignorer `preview` entièrement.

**5. L'aperçu final est obligatoire.** Sans lui, la dernière image affichée
serait un échantillon quelconque dont les compteurs ne correspondent pas au
résultat écrit, et l'écart se lirait comme un bug de comptage. C'est aussi le
contrôle qui valide tout le dispositif, vérifié en test **et** contre le vrai
moteur : dernier aperçu et résultat final annoncent les mêmes
`uniqueVehicles`, `crossings`, `byLine`, `reidHits` et diagnostics.

## Alternatives écartées

**Un flux d'images annotées produites par le serveur.** C'était l'option la plus
directe : le serveur dessine et envoie des JPEG. Écartée parce qu'elle coûte un
encodage par image publiée sur une machine qui peine déjà à l'inférence, qu'un
flux SSE est textuel — donc du base64, un tiers de volume en plus — et surtout
parce que le navigateur possède **déjà** la vidéo : il l'a envoyée. Retransmettre
des pixels qu'il a sous la main pour y superposer des boîtes qu'on peut décrire en
deux kilo-octets est un mauvais échange.

**Ouvrir le mode direct WebSocket aux fichiers**, en faisant émettre au client les
images de sa vidéo locale comme s'il s'agissait d'une caméra. Séduisant — zéro
ligne de backend — mais faux pour l'usage visé : la cadence client abandonne les
images pendant qu'une autre est en vol, donc les chiffres affichés ne seraient
**pas** ceux de l'analyse serveur. On aurait construit une démonstration
convaincante de quelque chose qu'on ne cherchait pas à valider.

## Conséquences

- Le client doit comparer les dimensions annoncées par l'aperçu à celles de sa
  balise `<video>`, et **suspendre le dessin** en cas de désaccord (SAR non carré,
  rotation portée par les métadonnées). Le serveur ne peut pas détecter cet écart :
  il ne sait pas ce que le navigateur affiche. C'est le même filet que
  `dimensionsAgree` en direct, et pour la même raison — des boîtes décalées se
  lisent comme un défaut de détection, jamais comme un défaut de repère.
- Le calage de la vidéo n'est possible que sur une source **fichier** : c'est le
  même fichier des deux côtés, donc le même temps de scène. Une caméra n'a pas de
  temps de scène commun.
- Un `<video>` se cale sur l'image décodable la plus proche : un décalage d'une
  image est possible. L'index de l'image analysée est donc affiché sur la scène —
  un décalage visible s'explique, un décalage caché se lit comme un bug.
- Le tableau de bord affiché pendant l'analyse n'a **ni** histogramme **ni**
  registre : les deux dérivent de la timeline complète, qui n'existe qu'à la fin.
  Un histogramme vide se lirait comme « aucun véhicule ».

## Effet de bord : un bug trouvé par le contrat

Écrire la fixture du contrat frontend a révélé que `AnalysisSession.stats()`
recopiait le dictionnaire `by_line` mais pas ses `LineTally`, qui restaient
partagés avec le compteur vivant. Un bloc de statistiques conservé quelques
millisecondes — exactement ce que fait un aperçu — voyait donc `total` avancer
pendant que le scalaire `crossings`, figé à l'instant du snapshot, ne bougeait
plus : un bloc violant son propre invariant `crossings == Σ by_line[*].total`, sur
des données pourtant justes. Corrigé à la source, dans le domaine.

Le bug était antérieur à cette ADR et inoffensif tant que tous les appelants
sérialisaient immédiatement. Il valait la peine d'être noté ici : c'est le
deuxième cas où la fixture committée détecte une divergence qu'aucun test des deux
côtés ne voyait.
