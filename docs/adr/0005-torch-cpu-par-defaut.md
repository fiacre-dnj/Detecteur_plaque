# ADR 0005 — `torch` dans la variante de la machine

- **Statut** : accepté, **amendé le 2026-08-06** (voir « Amendement » en fin)
- **Date** : 2026-08-05

## Contexte

La roue `torch` par défaut de PyPI embarque les bibliothèques CUDA : ~2,5 Go
installés. La machine de développement de ce projet n'a **aucun GPU NVIDIA**
(`nvidia-smi` absent), donc ces 2,3 Go de CUDA seraient téléchargés, écrits sur
le disque, et jamais exécutés.

## Décision (telle qu'écrite le 2026-08-05 — **remplacée**, voir l'amendement)

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

## Amendement — 2026-08-06

**L'extra `gpu` décrit ci-dessus n'a jamais été implémenté, et ne le sera pas.**
Ce qui a été écrit à sa place est meilleur, mais la décision d'origine est restée
dans ce document et dans le README pendant huit lots, où elle documentait une
commande qui échoue.

`backend/pyproject.toml` déclare :

```toml
[tool.uv]
torch-backend = "auto"
```

`uv` choisit la variante d'après le matériel de la machine qui installe : roue CPU
(~250 Mo) ici, roue CUDA correspondant au pilote détecté sur une machine NVIDIA.
Le lockfile porte les deux univers.

Pourquoi c'est mieux qu'un extra :

- **il n'y a rien à savoir.** Un extra suppose que celui qui installe sait quel
  matériel il a et pense à le déclarer ; l'oubli donne une installation CPU sur
  une machine GPU, qui *fonctionne* — simplement dix fois plus lentement, sans que
  rien ne le signale ;
- un extra `gpu` fige une version de CUDA dans le manifeste. `auto` suit le
  pilote réellement installé.

Ce que l'amendement **ne** change **pas** : le corps de la décision reste exact.
Le code ne contient aucune branche liée à ce choix, `device()` résout `"auto"` une
seule fois, et `half()` ne rend `True` que sur GPU.

Pour forcer une variante — build reproductible, ou machine dont le pilote n'est
pas celui de la cible :

```bash
UV_TORCH_BACKEND=cpu uv sync      # ou cu124, cu126…
```

C'est ce que fait `backend/Dockerfile` : sans le forçage, la détection choisirait
déjà le CPU pendant un build, mais par accident.
