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

### Corrigé

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
