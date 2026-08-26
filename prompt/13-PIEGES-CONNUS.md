# 13 — Pièges connus (déjà payés une fois)

À relire **avant** de déboguer quoi que ce soit, et avant de clore le lot 14.
Chaque entrée décrit un bug réellement survenu dans la version précédente de
l'application, ou une contrainte d'environnement qui a fait perdre du temps.

---

## A. Comptage — un véhicule compté deux fois

1. **Le garde ne peut pas être porté par la piste.** Quand le suivi perd un
   véhicule plus longtemps que `max_lost_ms`, la piste est **détruite** et sa
   remplaçante démarre avec un état vierge. Le garde de déduplication doit donc
   porter sur l'**identité** (`globalId`), pas sur la piste. Reproduit avant
   correction : un véhicule qui franchit, disparaît 15 frames et revient avec une
   boîte qui tremble sur la ligne comptait **2**.
   *La clé exacte a changé depuis : elle est `(identité, génération)` et non plus
   `(ligne, identité, sens)` — un véhicule compte une fois, toutes lignes et tous
   sens confondus ([ADR 0009](../docs/adr/0009-un-comptage-par-vehicule.md)). Le
   piège, lui, est intact : rien de ce garde ne doit vivre sur la piste. C'est
   pourquoi `_LineState` ne porte plus que de la géométrie.*
2. **Le badge ✓ appartient au compteur, pas au tracker.** Écrire `counted` depuis
   la détection de franchissement peignait ✓ pour un franchissement que le garde
   d'identité supprimait ensuite : l'overlay affirmait qu'un véhicule était compté
   alors que le compteur n'avait pas bougé. C'est exactement ainsi que le bug a
   été rapporté. Symétriquement, le ✓ ne doit **jamais se rétracter** :
   `counted_identities()` accumule les générations, donc un véhicule ré-identifié
   reste marqué compté en attendant de recroiser.
3. **Relâcher avant d'admettre.** Le tracker détruit une piste morte et crée sa
   remplaçante **dans le même appel** ; relâcher les identités après
   `admit_batch` laisse l'ancienne marquée vivante quand la remplaçante la
   demande, l'exclusivité refuse le match, et le véhicule devient un nouveau
   véhicule. Mesuré : 2 uniques / 0 ré-id avec le mauvais ordre, 1 / 1 avec le bon.
4. **`min_gap_ms` doit valoir 0** pour la même raison : un écart minimum non nul
   refuserait le match légitime survenant dans le même appel.
5. **Un véhicule = une boîte.** `car`/`motorcycle`/`bus`/`truck` sont mutuellement
   exclusives sur un objet physique. Une camionnette scorée `car 0.52` **et**
   `truck 0.41` survivait comme deux boîtes, devenait deux pistes, deux identités,
   et comptait deux fois. Côté serveur, `classes=[2,3,5,7]` passé à
   `model.track()` et le NMS d'Ultralytics traitent le cas ; si tu ajoutes un
   post-traitement, il doit être **class-agnostique**.
6. **Boîte englobante vs boîte partielle.** Sur un bus ou un semi-remorque, le
   détecteur émet parfois une boîte sur la cabine **et** une sur le véhicule
   entier ; leur IoU est ~0,3, sous n'importe quel seuil raisonnable. Le critère
   qui les attrape est la **containment** (`intersection / min(area)`), avec un
   seuil sévère de **0,9** : le cas cible atteint 1,0, tandis qu'une voiture
   roulant devant un camion peut être à 0,8 dans sa boîte et ne doit **pas** être
   supprimée (supprimer un vrai véhicule sous-compte, l'erreur la plus difficile à
   remarquer).

## B. Comptage — un véhicule manqué

7. **Le seul changement de signe compte au-delà de la ligne tracée.** Sans le test
   d'intersection de segments, un véhicule qui passe hors des extrémités est
   compté.
8. **Une piste née de l'autre côté ne doit jamais compter** : elle n'a pas été
   observée franchir.
9. **Un franchissement pendant la montée en confiance doit être différé, pas
   jeté.** Le jeter perd tout véhicule qui franchit dans ses premières frames —
   fréquent avec une ligne près du bord de l'image. Idem pour l'entrée en zone :
   c'est **l'écriture de l'état** qu'il faut différer, sinon le front
   dehors→dedans est consommé pendant que la piste est encore provisoire, et
   l'entrée est perdue silencieusement.
10. **Une zone trop serrée coûte des comptages.** Avec « ignorer hors zone », un
    véhicule dont le *centroïde* sort du polygone cesse d'être détecté, et une
    ligne liée à une zone rejette les franchissements qui ont lieu dehors. L'UI
    doit conseiller de dessiner large.
11. **Le côté doit être mis à jour même quand le franchissement est rejeté** (hors
    zone, sens déjà compté). Sinon la piste regarde dans le mauvais sens et le
    franchissement suivant compte à l'envers.

## C. Ré-identification

12. **Descripteur non centré = plage utile écrasée.** Toutes les composantes étant
    des intensités positives, deux véhicules sans rapport scorent ~0,7 sans
    centrage. Après centrage : même objet 1,00, objets différents ≈ 0,01.
13. **Vignette 8×8 = descripteur instable** : chaque cellule moyennait 4 pixels,
    à peine au-dessus du bruit ; les retours légitimes échouaient, chaque échec
    devenant une identité neuve et un second franchissement. 16×16 pour le même
    coût.
14. **`release()` daté de la mort de la piste affame le gate de déplacement.** La
    piste ne meurt qu'après `max_lost_ms` : dater « maintenant » sous-estime
    l'écart de jusqu'à 2,5 s et rejette le retour légitime. Dater du **dernier
    instant vu**.
15. **L'apparence seule rend deux sosies interchangeables.** Sans gate de
    déplacement, une voiture rouge entrant en haut hérite de l'identité d'une
    voiture rouge sortie en bas, et le vrai second véhicule n'est jamais compté.
16. **`reacquire` ne doit incrémenter que sur une vraie récupération.** Re-lier une
    identité déjà vivante est de la tenue de registre ; le compter ferait mentir la
    carte « Ré-identifications ».
17. **L'élagage ne doit pas faire baisser les totaux.** `size` et `count_by_class`
    sont des compteurs d'émission ; les identités trop vieilles sont retirées de la
    galerie mais les véhicules qu'elles représentent restent comptés.
18. **`aspectPenaltyWeight` est ce qui sépare les classes**, pas la pénalité de
    classe : celle-ci doit rester petite parce que car/bus/truck sont réellement
    confondus, tandis qu'une moto est séparée par sa **forme**.

## D. Temps, cadence, débit

19. **Ne jamais mélanger horloge murale et temps de scène.** Côté serveur, le
    temps de scène est vrai par construction (`frame_index / fps`) : introduire
    `time.time()` dans un calcul métier casse tout — débit, vitesses, gates. Le
    seul usage légitime de l'horloge murale est la **mesure de performance**
    (FPS de traitement, durée d'un job).
20. **Le débit se divise par le temps de scène analysé**, pas par la durée du
    traitement.
21. **Sous 3 s de flux, le débit n'est pas publiable** : il oscille. Rendre `0`
    et le dire dans l'UI.
22. **La progression doit être en images analysées** : avec `frame_stride = 3`,
    diviser par `frame_count` fait plafonner la barre à 33 %.
23. **`elapsed_ms` ne doit compter que le temps réellement travaillé.** Un
    horodatage de départ unique traversant les pauses gonfle la mesure.

## E. Timeline, sérialisation, mémoire

24. **`snapshot()` ou toutes les frames convergent.** La session mute la même
    instance de piste ; stocker la référence vivante fait que **chaque ligne de la
    timeline affiche l'état final**. Et le snapshot doit être pris **après** la
    passe ANPR, sinon les plaques manquent.
25. **Un résultat de 30 minutes ne reste pas en mémoire.** Écrire en `json.gz`,
    servir en fichier, arrondir les nombres à la sérialisation (scores 4
    décimales, pixels et ms 1 décimale) : la taille tombe de près de moitié.
26. **Ne pas insérer 5 000 franchissements un par un dans SQLite.** Une
    transaction, des inserts en lot.
27. **Ne pas persister la progression à chaque frame** : SQLite a un seul
    écrivain.

## F. Modèles et GPU

28. **Un bail par usage.** Deux `track()` simultanés sur la même instance
    partagent l'état de suivi et **mélangent deux vidéos** — chiffres plausibles,
    complètement faux.
29. **Plafond de modèles résidents.** Dix sessions résidentes épuisent la mémoire :
    c'est la leçon du benchmark de la version précédente, qui libérait chaque
    modèle après mesure sauf celui utilisé. Le benchmark serveur doit faire pareil.
30. **fp16 seulement sur un GPU qui le calcule vite** : sur CPU, `half=True`
    ralentit — et **avant Volta aussi**. Sans cœurs tensoriels (capability < 7.0),
    le fp16 tourne à une fraction du débit fp32 : mesuré sur la Quadro P1000
    (6.1) du poste de développement, yolov8n passe de **38,9 à 48,9 ms par image**
    en demi-précision. « Sur GPU » ne suffit donc pas à justifier le réglage, et
    l'erreur est silencieuse — le service reste 3× plus rapide que le CPU, donc
    rien n'a l'air cassé.
31. **Le premier appel d'un modèle inclut son téléchargement** (jusqu'à 137 Mo) et
    sa fusion : sans préchauffage ni indication dans l'UI, ça se lit comme un
    blocage. Écarter aussi ce premier run de toute moyenne de latence.
32. **`lap` manquante ne se voit qu'à l'exécution** : `model.track()` échoue avec
    `No module named 'lap'`, et aucun test à moteur factice ne l'attrape. La garder
    en dépendance de production et la mentionner dans le README.
33. **`boxes.id is None` est normal** sur les premières frames : le tracker n'a
    rien confirmé. Ce n'est pas une erreur.
34. **Ne jamais déduire une caractéristique d'un modèle de son nom de fichier.**
    Le palier vit dans le catalogue.
67. **Le fichier de suivi n'est lu qu'une fois par instance de modèle.**
    `on_predict_start` d'Ultralytics **sort immédiatement** quand `predictor.trackers`
    existe et que `persist` est vrai : le `tracker=…` passé à chaque appel est alors
    ignoré. Comme le registre garde l'instance d'un job à l'autre, **toutes les
    analyses d'un processus tournaient au seuil de la première** — « Confiance
    véhicules » était sans effet dès la deuxième, et le direct héritait du seuil de
    l'analyse précédente. Rien ne lève, et la première analyse après un démarrage — la
    seule qu'on regarde en développement — obéit parfaitement.
    `reset_trackers(model, tracker_config)` **repose** les clés de requête sur les
    trackers vivants ; ne pas « simplifier » en supprimant `predictor.trackers`, ce qui
    ferait ré-enregistrer les rappels par-dessus les anciens et appellerait
    `tracker.update()` deux fois par image (ADR 0035).

## G. Environnement, navigateur, outillage

35. **Le repli SPA de Vite répond `index.html` en HTTP 200** pour une route
    inconnue : un mauvais chemin d'API ne produit jamais de 404. Garder la garde
    `content-type` dans le client HTTP.
36. **`srcObject` masque `src`** : sans `video.srcObject = null` à l'arrêt du flux
    caméra, le fichier suivant ne se charge **jamais**, sans même un événement
    `error`.
37. **Les clips produits par `MediaRecorder` ont des métadonnées de durée
    inutilisables** (1,6 s annoncé 52 s) : ne pas en faire des fixtures de test, et
    masquer la timeline quand `duration` n'est pas fini.
38. **`requestAnimationFrame` est bridé quand l'onglet ne compose pas** : un
    aperçu masqué rapporte 0 FPS. C'est l'environnement, pas le code.
39. **`timeupdate` ne se déclenche que ~4 fois par seconde** : suivre la tête de
    lecture avec lui fait visiblement traîner les boîtes. Utiliser `rAF`.
40. **`playbackRate` est remis à 1 à chaque nouvelle source** : le réappliquer sur
    `loadedmetadata`.
41. **`ended` n'est pas `pause`** : sans écouter `ended`, le bouton reste sur
    « Pause » à la fin d'un clip. Et **pas de `loop`** : un clip qui repart
    recompte les mêmes véhicules.
42. **Le double-clic livre deux `pointerdown` et le `dblclick` dans un seul
    rendu** : le brouillon de polygone doit vivre dans un `ref`, pas dans un
    `state`, sinon on lit une liste périmée.
43. **CORS trop externe cache la vraie erreur** : une exception non gérée sort sans
    en-têtes CORS et le navigateur annonce « erreur CORS ».
44. **`X-Accel-Buffering: no` sur le SSE**, sinon un proxy tamponne et la barre
    paraît figée.
45. **`expose_headers` est obligatoire** pour lire `Content-Disposition` et
    `X-Request-ID` côté JS.
46. **`localhost` et `127.0.0.1` sont deux origines** : les deux doivent être dans
    la liste CORS de développement.
47. **`PRAGMA foreign_keys` est off par défaut** dans SQLite.
48. **`expire_on_commit=False`** est obligatoire en SQLAlchemy async, sinon lire un
    attribut après commit lève `MissingGreenlet`.
49. **`render_as_batch=True`** pour Alembic sur SQLite, sinon toute modification de
    colonne échoue.
50. **La roue `ultralytics` embarque un paquet `tests`** : nos helpers vont dans
    `tests/support/`, jamais importés via `tests.conftest`.
51. **L'alias `@/*` doit être déclaré dans les trois fichiers** (`tsconfig.json`
    racine pour `bun test`, `tsconfig.app.json` pour `tsc`, `vite.config.ts` pour
    le bundler).
52. **Ne pas remettre COOP/COEP `require-corp`** : ce besoin venait d'ONNX Runtime
    Web (SharedArrayBuffer) et disparaît avec l'analyse backend. COEP casse le
    chargement de ressources sans rien apporter ici.
53. **`torch` pèse ~2,5 Go** installé : prévoir l'espace, ou déplacer
    l'environnement avec `UV_PROJECT_ENVIRONMENT`.

## H. Modèles et imagerie — attentes réalistes

54. **Les détecteurs s'effondrent sur des images synthétiques ou illustrées**
    (schémas, simulations, maquettes vectorielles). Mesuré sur une scène de trafic
    en dessin animé : le modèle de plaques localise correctement mais score
    0,09–0,20 (sous son seuil), et YOLOv8n ne trouve **aucun** véhicule, à
    n'importe quel seuil jusqu'à 0,10. Zéro détection sur une telle image est un
    comportement de modèle **attendu**, pas une panne de pipeline. Avant de
    déboguer « rien n'est détecté », vérifier le type d'imagerie — et ne jamais
    utiliser une scène dessinée comme fixture de qualité de détection.
55. **Une plaque fait ~15 px de large sur un plan large 1920×1080** et ~240 px
    recadrée sur son véhicule : c'est toute la raison d'être de la passe ANPR en
    deux étages.
56. **Le coût de l'ANPR croît avec le nombre de pistes** (une inférence par piste
    et par frame ; ~880 ms mesuré avec 3 pistes). Le dire dans l'UI.
57. **`persist=True` fait aussi persister le tracker entre deux analyses.**
    `register_tracker` d'Ultralytics **sort immédiatement** quand des trackers
    existent déjà, et le registre garde l'instance de modèle d'un job à l'autre.
    La deuxième analyse hérite donc des pistes, du filtre de Kalman et du compteur
    d'images de la première. Mesuré sur un même fichier **octet pour octet**,
    analysé quatre fois de suite dans le même processus : **19, 26, 33** véhicules
    uniques. Rien n'échoue, rien n'est journalisé, les chiffres restent plausibles
    et dérivent toujours **vers le haut**. `reset_trackers(model)` au début de
    chaque `iter_video` et de chaque flux temps réel est la correction.
58. **La compensation de mouvement du tracker peut coûter plus cher que
    l'inférence.** `gmc_method: sparseOptFlow` recalcule un flux optique épars sur
    CPU à chaque image : **20,2 ms mesurées** sur du 720p, contre 17,8 ms pour
    l'inférence GPU — 39 % du budget pour corriger un mouvement de caméra qui
    n'existe pas sur une caméra fixe. Le mettre à `none` double la cadence à
    comptage identique. Ne le rallumer que si la caméra bouge réellement.
59. **Un banc lancé pendant une autre charge ne mesure rien.** Une mesure prise
    pendant les tests unitaires a affiché 1,40× là où le protocole propre donne
    1,93×. L'anomalie ne s'est vue que parce que le banc chiffre *tous* les
    postes : l'inférence GPU, que le changement testé ne pouvait pas ralentir,
    avait bougé de 17,0 à 19,9 ms. Toujours des courses **appariées**, enchaînées,
    machine au repos — cette machine varie de ±20 % selon son état thermique.
60. **`BaseTrack._count` d'Ultralytics est un attribut de *classe*, donc partagé par
    tout le processus.** `JobManager` borne à un job simultané et `SessionService` à
    une session temps réel, mais ce sont **deux bornes indépendantes** : ouvrir la
    caméra pendant qu'un fichier s'analyse appelle `reset_trackers()`, remet le
    compteur global à zéro, et l'analyse en cours se remet à émettre des
    identifiants de piste 1, 2, 3 — qu'elle a déjà utilisés. Publier `track_id`
    brut comme numéro de véhicule ferait alors **fusionner deux véhicules
    distincts**, sans exception ni journal, et le total baisserait sans que rien à
    l'écran ne l'explique. C'est pourquoi `TrackNumbering` tient sa propre
    correspondance `track_id → numéro`, locale à la session, et l'oublie
    (`forget`) quand la piste est abandonnée
    ([ADR 0016](../docs/adr/0016-compter-les-objets-suivis.md)).
61. **Numéroter un véhicule à la *confirmation* de sa piste casse deux choses.**
    Tenté, puis abandonné sur mesure : la première lecture de plaque n'avait plus
    d'agrégat où voter, et `first_seen_ms` datait de la confirmation au lieu de la
    première apparition. Le numéro est donc émis dès la **première image**, et seule
    l'entrée dans `tracked_vehicles` attend `min_hits`. La contrepartie assumée est
    que la suite des numéros comptés **a des trous** : un scintillement du détecteur
    consomme un numéro sans jamais être compté. Ne pas « corriger » cela en
    renumérotant — un même véhicule changerait de badge entre sa première et sa
    deuxième image.
62. **Un nom de sens ne doit jamais entrer dans `geometrySignature()`.** Les
    libellés et les rôles entrée/sortie ne changent aucun chiffre : le serveur ne les
    lit pas, et le bilan du carrefour est recalculé côté client à chaque rendu. Les
    inclure ferait apparaître la bannière « résultat obsolète » sur une simple
    correction de vocabulaire, et pousserait à relancer une analyse de trente minutes
    pour rien.
63. **Un ensemble de filtre vide signifie « tout », jamais « rien ».** Dans la
    chronologie, aucune puce n'est active au premier rendu : une intersection naïve
    afficherait donc une liste **vide** sur une analyse qui a compté, et l'utilisateur
    conclurait à une panne du comptage. La convention est verrouillée par
    `timelineFilters.test.ts`.
64. **Un décalage d'étiquette en pixels fixes ne tient que sur une orientation.** Les
    deux libellés de sens étaient posés à 30 px de part et d'autre du trait. Sur une
    ligne horizontale les deux boîtes s'éloignent par leur petit côté — 16 px de haut,
    donc 44 px d'air — et **se chevauchaient dès que la ligne penchait** : sur une
    verticale, le normal est horizontal et deux boîtes de 130 px de large se croisaient
    sur 70 px. L'encombrement d'une boîte alignée sur les axes, mesuré le long d'une
    direction `n`, vaut `|n.x|·w/2 + |n.y|·h/2` : c'est ce terme qu'il faut ajouter au
    dégagement pour que l'espace libre soit **constant quel que soit l'angle**.
    `draw.test.ts` balaie 72 orientations, parce que tester 0° et 90° laissait passer
    tout l'intervalle.
65. **Trois étiquettes ne tiennent pas sur les deux côtés d'un trait.** Le nom de la
    ligne était au milieu, les deux sens de part et d'autre : le nom et le sens négatif
    se disputaient le même axe perpendiculaire et se recouvraient. Le nom vit désormais
    près de la poignée A — même convention que les zones — et le milieu appartient aux
    deux sens.
66. **Une étiquette placée par sa propre ligne ne peut pas voir celles des autres.**
    Deux lignes parallèles proches posaient le libellé « dessous » de l'une sur le
    « dessus » de l'autre. Le placement se fait en **une passe globale**
    (`resolveLabelCollisions`), après tous les traits — ce qui corrige au passage un
    second défaut, les libellés qui finissaient sous le trait de la ligne suivante. Une
    étiquette écartée fuit **le long de son propre normal**, jamais au travers : de
    l'autre côté, elle nommerait le mauvais sens.
