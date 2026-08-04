# ADR 0002 — Aucun poids de modèle dans l'historique git

- **Statut** : accepté
- **Date** : 2026-08-05

## Contexte

La version précédente de l'application committait ses poids `.onnx` par décision
explicite : l'inférence tournait dans le navigateur, et le modèle devait être
servi avec l'application. Résultat mesuré : ~700 Mo dans l'historique git.

Un objet dans l'historique git y est **pour toujours**. Chaque clone les
télécharge, y compris les clones de CI, y compris les clones de quelqu'un qui ne
veut que corriger une faute de frappe. Le nettoyage rétroactif (`git filter-repo`)
réécrit tous les SHA et casse tous les forks et toutes les branches ouvertes : ce
n'est pas une correction, c'est un événement.

Le dépôt contient par ailleurs un dossier `yolo/` avec 9 fichiers `.onnx`
(~606 Mo) issus de cette version antérieure.

## Décision

Aucun `*.pt`, `*.onnx`, `*.engine` ni `*.mp4` n'entre dans l'historique. Trois
mécanismes, parce qu'une seule ligne de `.gitignore` s'oublie :

1. `.gitignore` liste les extensions **et** le dossier `yolo/` ;
2. `.pre-commit-config.yaml` porte `check-added-large-files --maxkb=5000` : c'est
   ce hook qui attrape le fichier renommé, celui que le `.gitignore` ne voit pas ;
3. un job de CI vérifie qu'aucun de ces motifs n'apparaît dans le diff.

À la place :

- les poids véhicules sont des `.pt` **téléchargés à la demande** par le registre
  de modèles dans `TRAFFIC_WEIGHTS_DIR` (`.weights/`, ignoré) ;
- `backend/scripts/fetch_weights.py` pré-télécharge un sous-ensemble choisi pour
  travailler hors ligne ;
- le modèle de plaques est récupéré par `backend/scripts/fetch_plate_model.py`
  depuis une URL configurable, avec **vérification d'une somme SHA-256** ;
- une vidéo de démonstration se dépose à la main dans
  `frontend/public/demo/traffic.mp4`, et le README dit où.

## Conséquences

- Un clone frais ne compte aucun véhicule avant un premier téléchargement de
  poids. L'UI doit donc distinguer *au catalogue* / *téléchargé* / *résident*, et
  annoncer « premier usage : téléchargement ~N Mo ». C'est un travail d'interface
  supplémentaire, assumé.
- Les vidéos de trafic peuvent contenir des plaques réelles — donnée personnelle.
  Les tenir hors du dépôt est aussi une décision de conformité, pas seulement de
  poids.
