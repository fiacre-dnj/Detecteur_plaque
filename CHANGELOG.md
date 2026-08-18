# Journal des modifications

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
versionnage suit [SemVer](https://semver.org/lang/fr/).

Ce journal dit ce qui change **pour l'utilisateur**. Il n'est pas un `git log` :
« déplace `geometry.py` » n'y a pas sa place, « les allers-retours ne comptent
plus deux fois dans le même sens » si.

## [Non publié]

### Ajouté

- Socle du dépôt : licence AGPL-3.0, hooks de pré-commit, journal, guide de
  contribution, et les cinq premières décisions d'architecture documentées.
- Le service répond : `GET /api/v1/health/live` (vivacité),
  `/health/ready` (le répertoire de données est-il inscriptible ?) et
  `/health` (version et environnement).
- La documentation interactive de l'API est sur `/api/docs`.
- Toute erreur est une réponse *Problem Details* en français, avec un code
  machine stable et un identifiant de requête à citer en cas d'incident. Une
  erreur interne ne divulgue jamais de détail technique.
- Les journaux portent l'identifiant de la requête qui les a produits : signaler
  un problème en citant cet identifiant suffit à retrouver toute la chaîne.
- **Le comptage existe** : franchissements de lignes par sens, entrées et
  occupation de zones, ré-identification des véhicules qui disparaissent puis
  reviennent, vote de classe majoritaire et estimation de vitesse.
- Un aller-retour compte une fois dans chaque sens ; une boîte qui tremble sur
  une ligne ne compte qu'une fois ; un véhicule occulté puis revenu reste le même
  véhicule.
- Sans échelle px/m fournie, les vitesses restent en px/s plutôt que d'être
  converties à tort en km/h.
- En dessous de trois secondes de flux analysé, le débit estimé est annoncé
  comme indisponible au lieu d'afficher un chiffre qui oscille.
- **On peut déposer une vidéo et suivre son analyse** : `POST /api/v1/jobs`,
  progression en direct par flux SSE, résultat complet téléchargeable, et
  historique paginé des analyses.
- Une analyse s'annule en cours de route, proprement : le traitement s'arrête
  entre deux images plutôt que d'être interrompu de force.
- Une seconde analyse déposée pendant qu'une autre tourne est **acceptée** et
  attend son tour, au lieu d'être refusée.
- Les vidéos et résultats des analyses terminées sont purgés automatiquement
  après leur durée de rétention.
- **Les analyses survivent au redémarrage du service** : jobs, statistiques,
  registre des véhicules et franchissements sont conservés en base.
- Le registre et les franchissements se consultent page par page, avec des
  filtres — par type de véhicule, par ligne, par sens, par fenêtre de temps —
  sans avoir à télécharger le résultat complet.
- **Export CSV** du registre et des franchissements, directement ouvrable dans
  un Excel français : accents corrects, colonnes séparées, nombres reconnus
  comme des nombres. Une vitesse inconnue reste une case vide, jamais un zéro.
- **Vingt détecteurs au catalogue** : quatre familles (YOLOv8, YOLO11, YOLO12,
  YOLO26) dans les cinq paliers, du nano à l'extra large. Chaque modèle indique
  s'il est déjà téléchargé et s'il est chargé en mémoire, pour qu'une première
  analyse n'attende jamais sans explication.
- Un modèle peut être préchargé à l'avance, ou déchargé pour libérer la mémoire.
  Le service n'en garde que deux en mémoire par défaut et évince le plus ancien.
- `/api/v1/health` annonce le device utilisé, la version d'Ultralytics, les
  modèles résidents et la disponibilité de la lecture de plaques.
- Un modèle inconnu est refusé au dépôt, avec la liste des identifiants valides,
  au lieu de faire échouer l'analyse une minute plus tard.
- Deux scripts : `fetch_weights.py` pour pré-télécharger les poids choisis, et
  `fetch_plate_model.py` qui vérifie l'empreinte SHA-256 du modèle de plaques
  avant de l'installer.
- Le service pose une politique de sécurité complète sur toutes ses réponses et
  n'annonce plus quel serveur il utilise.
- Un envoi trop volumineux est refusé dès son annonce, sans être lu.
- La documentation d'API peut être fermée en production (`TRAFFIC_DOCS_ENABLED`),
  et chaque route y porte un résumé, un identifiant lisible et un exemple.
- En production, le service peut servir lui-même l'interface
  (`TRAFFIC_STATIC_DIR`) : une seule adresse, aucun réglage de CORS.
- **L'interface existe.** On choisit une source — fichier, clip de démonstration
  ou caméra —, on trace ses lignes et ses zones directement sur l'image, on lance
  l'analyse et on suit sa progression.
- Les lignes et les zones se dessinent, se déplacent, se renomment et se
  suppriment sur l'image. Une ligne peut être restreinte à une zone.
- Après une analyse, la vidéo se rejoue **avec** ses boîtes, ses trajectoires et
  ses compteurs. Reculer dans la vidéo fait **baisser** les compteurs : ce qui est
  affiché correspond toujours à ce qui a été vu jusqu'à l'instant montré.
- Le registre des véhicules se consulte, se trie et s'exporte en CSV — un CSV qui
  s'ouvre correctement dans Excel en français, accents compris.
- Déplacer une ligne après une analyse affiche un bandeau « résultat obsolète »
  plutôt que de laisser croire que les chiffres décrivent le nouveau tracé.
- **Comptage en direct sur la caméra**, avec les mêmes règles que l'analyse d'un
  fichier. La latence et le nombre d'images abandonnées sont affichés : un
  abandon élevé est normal et signifie que le serveur est le facteur limitant.
- Si le serveur ne reçoit pas des images de la taille que l'interface croit
  envoyer, le direct **s'arrête et le dit**. Compter dans ces conditions
  produirait des chiffres faux mais plausibles.
- L'historique des analyses : rouvrir un résultat **avec sa géométrie**, relancer
  la même configuration — ce qui crée une nouvelle analyse sans toucher à
  l'ancienne — ou supprimer.
- **Presets de géométrie** : enregistrer un tracé sous un nom et le recharger sur
  une autre vidéo. Un preset enregistré pour une autre résolution est adapté
  automatiquement, et l'interface **le dit avant** de le charger, avec les deux
  résolutions.
- Le sélecteur de modèles se parcourt au clavier et annonce, pour chaque modèle,
  sa taille et s'il faudra le télécharger.
- Le tableau de benchmark se trie par colonne et recharge le dernier résultat à
  l'ouverture.
- **`docker compose up` sert l'application complète** sur une seule adresse. Les
  analyses, la base et les poids téléchargés survivent à un redémarrage.
- **La lecture locale d'une analyse en cours reste à vitesse normale par
  défaut.** Sans plus toucher à rien, la vidéo ne défile plus tantôt accélérée,
  tantôt ralentie selon la charge du serveur. Un plafond **absolu**, en 30
  (le défaut) ou 60 images par seconde, reste disponible en plus pour brider
  le débit du serveur lui-même, indépendamment de la cadence de la vidéo.
- **Chaque sens de ligne est désormais obligatoirement « Entrée » ou
  « Sortie ».** Le panneau de géométrie n'offre plus de nom libre à taper, ni
  de menu déroulant par sens : les deux sens s'affichent en lecture seule
  (flèche, libellé) et un seul bouton les **inverse** — inutile de choisir
  deux fois pour une paire qui n'a jamais que deux états possibles. Une ligne
  fraîchement tracée contribue donc tout de suite au bilan entrées/sorties du
  carrefour, sans geste supplémentaire. Les flèches de sens (canvas et
  panneau) pointent désormais **exactement** perpendiculairement à la ligne,
  à n'importe quel angle, au lieu d'un glyphe figé ou arrondi au 45° le plus
  proche.
- **Le nom de la ligne et les libellés de sens s'estompent pendant qu'une
  analyse tourne**, différée ou en direct, pour laisser la place aux boîtes et
  aux compteurs — sauf le sens qui vient tout juste de compter, qui reste net.
- La vidéo locale se cale **toujours** sur l'image que le serveur analyse
  pendant qu'une analyse tourne : la case à décocher pour reprendre la main a
  disparu, le gel est désormais inconditionnel et expliqué à l'écran.
- Le tableau de résultats perd la carte « Véhicules détectés » ; les repères
  « Image … » et « Véhicules : … » affichés en surimpression de la vidéo
  disparaissent aussi — la résolution et la cadence de lecture suffisent. La
  durée de flux analysé devient une carte à part entière plutôt qu'une phrase
  sous le tableau.
- **L'entête de l'application reste visible en défilant**, et les tiroirs
  Détection/Comptage/Affichage & analyse s'ouvrent désormais **par-dessus** la
  page (un clic en dehors ou `Échap` les referme) au lieu de pousser la vidéo
  et les résultats vers le bas. Ils restent grisés tant qu'aucune vidéo n'est
  chargée. La scène vide propose une invite cliquable — glisser-déposer ou
  clic — au lieu d'une simple phrase, et le nom du fichier importé se lit
  désormais à l'autre bout de la barre, plutôt que juste après le bouton.
- **Le bas de l'écran, sous la vidéo, est refondu.** La chronologie cliquable
  et ses cinq onglets (Répartition, Par ligne & sens, Mouvements, Flux,
  Registre) laissent place à trois sections toujours visibles : une
  **Répartition** simplifiée (une carte par type de véhicule, le nombre
  d'entrées — cohérent par construction avec le KPI « Entrées au carrefour »),
  une **Statistique** (le total de véhicules ayant traversé le carrefour, puis
  une rangée compacte par ligne : entrées, sorties, solde et part du trafic),
  et le **Registre**. La navigation par clic dans les franchissements et la
  matrice origine-destination disparaissent sans remplacement — la barre de
  lecture standard suffit à se déplacer dans le temps.
- La Statistique dit désormais **quelle ligne sert le plus à entrer** et
  **laquelle sert le plus à sortir**, en nombre de passages. C'est une autre
  question que « le plus fort afflux », qui parle du solde : une ligne où 10
  véhicules entrent et 9 ressortent est la plus empruntée pour entrer sans
  remplir le carrefour pour autant.
- Le flux par ligne et la répartition par type se lisent en **deux camemberts
  côte à côte** plutôt qu'en barres : la part de chaque ligne et de chaque type
  se voit d'un coup d'œil, sans comparer des barres une à une.
- **Deux franchissements sur trois manquaient à l'appel dans un cas précis, et
  un quatrième était inventé dans un autre.** Un véhicule dont le suivi
  *commence* tout près d'une ligne — parce qu'il entre dans le champ à cet
  endroit, ou parce qu'une occlusion vient de couper sa piste — n'était pas
  compté quand il franchissait : la zone d'insensibilité qui entoure chaque
  trait servait alors de point de départ au lieu de point de passage. C'est le
  cas le plus fréquent en trafic dense. À l'inverse, quand le suivi réattribuait
  le numéro interne d'un véhicule disparu à un nouveau venu, celui-ci héritait
  de la position de son prédécesseur et pouvait se voir attribuer un
  franchissement qu'il n'avait pas fait. Les deux sont corrigés ; les totaux
  d'une même vidéo réanalysée peuvent donc monter **et** descendre.
- **Le suivi ne lâche plus un véhicule dont la détection faiblit un instant.**
  Le détecteur ne rejetait rien en dessous du seuil de confiance choisi, ce qui
  privait le suivi du mécanisme prévu pour traverser une occlusion partielle, un
  flou de mouvement ou un reflet. Un véhicule dont la confiance plongeait le
  temps d'une image voyait sa piste coupée : il était alors compté deux fois, et
  son franchissement pouvait être perdu. Mesuré sur une vidéo de trafic réelle :
  **21 % d'observations suivies en plus, aucun nouveau véhicule inventé, et neuf
  pistes fragmentées en moins** (92 → 83 objets suivis) pour un total de
  franchissements identique. Le seuil de confiance garde exactement le même sens
  pour vous : à partir de quand un objet devient un véhicule suivi.
- **Les vitesses peuvent enfin s'afficher en km/h de façon fiable.** Chaque ligne
  de comptage accepte sa **longueur réelle** (« cette ligne fait 7 m »), ce qui
  donne une échelle mesurée à l'endroit précis où les véhicules la franchissent.
  Une seule échelle pour toute l'image ne pouvait pas convenir : sur une caméra
  inclinée, un mètre vaut quelques pixels au loin et quelques dizaines au premier
  plan — un facteur près de 4 mesuré entre deux lignes d'une même scène. Le
  réglage global existant continue de fonctionner à l'identique si vous ne
  renseignez aucune longueur.
- **Le registre ne liste plus que les véhicules ayant franchi une ligne**, tous
  sens confondus. Les véhicules simplement détectés — à l'arrêt, en
  stationnement, ou vus quelques images dans un coin du champ — n'y figuraient
  qu'avec des « — » dans « Lignes franchies » et « Passages », donc sans rien
  qui permette de les vérifier.
- **« Véhicules ayant traversé le carrefour » compte désormais les véhicules
  entrés**, et non tous les objets suivis. Sur une même analyse, ce chiffre
  annonçait 106 juste au-dessus d'une répartition qui totalisait 28 entrées :
  les deux étaient justes dans leur unité, mais se lisaient comme une
  contradiction. Un véhicule qui entre deux fois compte pour un seul véhicule
  ici, et pour deux passages dans « Entrées au carrefour ».
- Basculer un sens de ligne entre entrée et sortie met à jour ces chiffres
  **immédiatement**, sans relancer l'analyse.
- Le **registre des véhicules** est plus détaillé : durée de présence, zones
  traversées et confiance de *détection* de la plaque (distincte de la
  confiance de lecture) s'ajoutent aux colonnes existantes, le type de véhicule
  s'affiche en français, et les en-têtes du tableau restent visibles pendant le
  défilement.
- Le registre gagne deux colonnes, **Entrée** et **Sortie**, qui donnent
  l'instant du franchissement au dixième de seconde — deux passages du même
  véhicule sur deux lignes voisines tombaient jusqu'ici dans la même seconde
  affichée. Basculer un sens entrée ↔ sortie déplace l'heure de colonne sans
  relancer l'analyse.
- **Le registre et la statistique se remplissent désormais pendant l'analyse**,
  et non plus seulement à la fin : l'aperçu en direct porte le registre des
  véhicules ayant déjà franchi une ligne, à une cadence plus lente que celle des
  boîtes pour ne pas alourdir le flux à mesure qu'il grossit.

### Corrigé

- **La plaque ne perd plus son premier caractère.** Le registre affichait `606L`
  pour une plaque `苏A·R606L`, à 81 % de confiance de lecture : un texte tronqué,
  présenté avec l'assurance d'un texte lu. Le serveur publie désormais `AR606L`.
  Trois causes distinctes, corrigées toutes les trois :
  - **la lecture n'avait pas le droit de recommencer.** Une plaque n'était relue
    que si la nouvelle image de la plaque était nettement meilleure que la
    précédente, ce qui ne laissait que deux ou trois lectures par véhicule —
    jamais assez pour que le vote tranche entre des graphies voisines. C'est le
    changement décisif, et il ne ralentit pas l'analyse : une plaque reconnue plus
    tôt arrête plus tôt le travail coûteux ;
  - **un caractère que le modèle ne connaît pas mangeait la lettre voisine.**
    L'idéogramme de province d'une plaque chinoise n'existe dans aucune classe du
    modèle de lecture, et le caractère juste à côté en faisait les frais. Mesuré
    sur 40 images de plaques réelles : lectures exactes 8 → 17. Le contrôle sur des
    plaques **françaises**, qui n'ont aucun idéogramme, s'améliore aussi — 39 → 43
    lectures justes sur 56, dont 4/8 → 7/8 pour les plaques de 64 px de large ;
  - **une lecture incomplète concurrençait la lecture complète**, et gagnait, parce
    qu'elle sort plus souvent. Elle la renforce désormais : plaques justes 1 sur 6
    → 3 sur 6.

  Le surcoût de lecture est réel (1,9×) et invisible à l'usage : l'analyse tourne à
  la même cadence.
- **La vidéo déposée est réellement supprimée au bout d'une heure.** Le réglage
  l'annonçait depuis le début, mais rien ne l'appliquait : les images restaient
  vingt-quatre heures, comme le reste de l'analyse. Le résultat, lui, se consulte
  toujours aussi longtemps — il ne contient que des boîtes et des chiffres.
- **Une camionnette n'est plus comptée deux fois.** Le détecteur pouvait la
  reconnaître à la fois comme voiture et comme camion, et les deux survivaient.
- **Un semi-remorque non plus.** Le détecteur émet parfois une boîte sur la cabine
  et une sur le véhicule entier ; la plus petite est désormais écartée, et le
  panneau de diagnostic dit combien.
- **Une analyse et un comptage en direct lancés en même temps ne se mélangent
  plus.** Ils partageaient le même modèle et donc le même suivi : les deux
  produisaient des chiffres plausibles et faux.
- Le service refuse de démarrer en production avec sa documentation ouverte, sauf
  choix explicite.
- Le nombre de requêtes par minute est limité, avec un délai d'attente annoncé.

### Décidé

- L'inférence est exclusivement côté serveur ; il n'y a plus de mode navigateur,
  et les images sont envoyées au serveur — ce que l'interface annonce.
- Aucun poids de modèle n'entre dans l'historique git : ils sont téléchargés à la
  demande, et l'interface distingue *au catalogue* / *téléchargé* / *résident*.
- Python est épinglé en 3.12 : `torch` ne publie pas de roue pour 3.14.
- `torch` s'installe dans la variante qui correspond à la machine — roue CPU ici,
  roue CUDA sur une machine NVIDIA — sans extra à choisir. `UV_TORCH_BACKEND`
  force la variante quand on veut un résultat reproductible.
- L'interface suit `DESIGN.md` : thème sombre, accent vert strictement
  fonctionnel, couleur réservée au canvas pour ce qu'elle encode.
