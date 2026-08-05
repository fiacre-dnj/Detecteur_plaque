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

### Décidé

- L'inférence est exclusivement côté serveur ; il n'y a plus de mode navigateur,
  et les images sont envoyées au serveur — ce que l'interface annonce.
- Aucun poids de modèle n'entre dans l'historique git : ils sont téléchargés à la
  demande, et l'interface distingue *au catalogue* / *téléchargé* / *résident*.
- Python est épinglé en 3.12 : `torch` ne publie pas de roue pour 3.14.
- `torch` s'installe en variante CPU par défaut ; `uv sync --extra gpu` sur une
  machine NVIDIA.
- L'interface suit `DESIGN.md` : thème sombre, accent vert strictement
  fonctionnel, couleur réservée au canvas pour ce qu'elle encode.
