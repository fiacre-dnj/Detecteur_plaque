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
30. **fp16 seulement sur GPU** : sur CPU, `half=True` ralentit.
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
