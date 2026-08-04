# ADR 0005 — `torch` en variante CPU par défaut, extra `gpu` explicite

- **Statut** : accepté
- **Date** : 2026-08-05

## Contexte

La roue `torch` par défaut de PyPI embarque les bibliothèques CUDA : ~2,5 Go
installés. La machine de développement de ce projet n'a **aucun GPU NVIDIA**
(`nvidia-smi` absent), donc ces 2,3 Go de CUDA seraient téléchargés, écrits sur
le disque, et jamais exécutés.

## Décision

`backend/pyproject.toml` déclare l'index `pytorch-cpu`
(`https://download.pytorch.org/whl/cpu`) comme source de `torch` et
`torchvision`. L'installation par défaut (`uv sync`) pèse donc ~250 Mo.

Un extra documenté couvre la machine GPU :

```bash
uv sync --extra gpu      # roues CUDA depuis l'index cu124
```

Le code ne contient **aucune branche** liée à ce choix. `ModelRegistry.device()`
résout `"auto"` une seule fois — `"0"` si `torch.cuda.is_available()`, sinon
`"cpu"` — et `half()` ne rend `True` que sur GPU, parce qu'en fp16 sur CPU
l'inférence *ralentit*. Passer sur une machine NVIDIA ne demande donc rien
d'autre que le `--extra gpu`.

## Conséquences

- Les paliers `large` et `xlarge` sont lents sur cette machine : plusieurs
  centaines de millisecondes par image. Ce n'est pas une régression, et le
  benchmark doit afficher le device pour qu'un chiffre ne soit jamais lu hors de
  son contexte matériel.
- L'ANPR ajoute une inférence **par piste et par frame** (~880 ms mesuré avec
  3 pistes) : sur CPU l'option est utilisable pour vérifier la chaîne, pas pour
  traiter un clip long. L'infobulle de l'option doit le dire.
- Un run de benchmark persisté porte son `device` et sa version d'Ultralytics :
  comparer une mesure CPU à une mesure GPU sans ce contexte serait trompeur.
