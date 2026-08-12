# ADR 0012 — `torch` CUDA sur Windows : cu126, épinglé, et fp16 seulement à partir de Volta

- **Statut** : accepté
- **Date** : 2026-08-12
- **Amende** : [ADR 0005](0005-torch-cpu-par-defaut.md), dont une phrase était fausse

## Contexte

Le poste de développement a désormais un GPU : une **Quadro P1000** (4 Go,
pilote 582.78). Le service ne le voyait pas. `/health` annonçait
`device: "cpu"`, `deviceReason: "aucun GPU CUDA détecté"` — un diagnostic exact,
sur une machine où `nvidia-smi` liste pourtant la carte.

Trois faits se superposaient, dont deux invisibles.

### 1. `torch-backend = "auto"` joue à la résolution, pas à l'installation

L'amendement d'ADR 0005 affirme : « Le lockfile porte les deux univers. »
**C'est faux, et c'est la cause racine.** Le lock ne portait qu'un seul torch :

```toml
[[package]]
name = "torch"
version = "2.13.0"
source = { registry = "https://pypi.org/simple" }
```

`auto` choisit la variante d'après le matériel de la machine qui **résout**. Le
lock a été produit sur une machine sans GPU, il a donc figé la roue PyPI — qui,
sur Windows, est CPU-only. `uv sync` ne re-résout pas : il repose ce choix.

Le mode de défaillance est exactement celui qu'ADR 0005 voulait éviter en
refusant l'extra `gpu` : « une installation CPU sur une machine GPU, qui
*fonctionne* — simplement dix fois plus lentement, sans que rien ne le signale ».
L'`auto` ne l'a pas évité, il l'a déplacé de l'opérateur vers le lockfile.

### 2. `auto` aurait de toute façon choisi une roue inutilisable

Le pilote annonce **CUDA 13.0**. `auto` suit le pilote : il aurait pris une roue
cu13x. Or **CUDA 13 a supprimé Maxwell, Pascal et Volta**, et la roue cu128
s'arrête à `sm_70`. La P1000 est `sm_61`.

Une telle roue s'installe sans bruit, `torch.cuda.is_available()` répond vrai, et
l'échec n'arrive qu'à la première inférence réelle. C'est précisément le scénario
que le repli de préchauffage (ADR 0011) sait rattraper — mais rattraper en
retombant sur CPU n'est pas utiliser le GPU.

Vérifié sur la roue retenue :

```
arch list   ['sm_50', 'sm_60', 'sm_61', 'sm_70', 'sm_75', 'sm_80', 'sm_86', 'sm_90']
capability  (6, 1)
```

**cu126 est la dernière ligne qui embarque `sm_61`.**

### 3. `half` se déclenchait sur « suis-je sur GPU », pas sur « ce GPU est-il rapide en fp16 »

`half()` rendait `True` dès que `device != "cpu"`. Sans cœurs tensoriels
(capability < 7.0), le fp16 est calculé à une fraction du débit fp32. Mesuré,
yolov8n sur une image 1280×720, moyenne de 12 inférences après rodage :

| configuration | ms/image |
|---|---|
| CPU | 147,8 |
| GPU fp32 | **38,9** |
| GPU fp16 (`half=True`) | 48,9 |

Le réglage censé accélérer coûtait **26 %**, et l'erreur était indétectable à
l'œil : le GPU restait 3× plus rapide que le CPU, donc rien n'avait l'air cassé.

## Décision

**1. `torch` et `torchvision` viennent de l'index cu126 sur Windows**, par source
explicite dans `backend/pyproject.toml` :

```toml
[[tool.uv.index]]
name = "pytorch-cu126"
url = "https://download.pytorch.org/whl/cu126"
explicit = true

[tool.uv.sources]
torch = [{ index = "pytorch-cu126", marker = "sys_platform == 'win32'" }]
torchvision = [{ index = "pytorch-cu126", marker = "sys_platform == 'win32'" }]
```

Le lock porte maintenant **réellement** les deux univers, et le marqueur dit
lequel s'applique où :

```toml
{ name = "torch", version = "2.13.0",       source = { registry = "https://pypi.org/simple" },              marker = "sys_platform != 'win32'" },
{ name = "torch", version = "2.13.0+cu126", source = { registry = "https://download.pytorch.org/whl/cu126" }, marker = "sys_platform == 'win32'" },
```

`torch-backend = "auto"` **reste**, pour les plateformes que le marqueur ne
couvre pas. Les deux réglages cohabitent sans conflit : la source explicite gagne
là où elle s'applique.

**2. `half()` exige la capability ≥ 7.0** en plus du GPU. La règle est inversée
par rapport à l'évidence : on ne désactive le fp16 que sur un GPU **mesurément**
lent, jamais sur une sonde qui échoue. Une capability illisible laisse passer le
réglage de l'opérateur — contredire un `half=True` explicite sur la foi d'un
appel raté rejouerait la panne silencieuse qu'on vient de corriger, dans l'autre
sens. La désactivation est journalisée avec la capability et le nom du GPU.

## Conséquences

- **Toute machine Windows du projet télécharge 2,4 Go de CUDA**, GPU ou non. C'est
  le prix assumé du marqueur : il n'y a qu'un poste Windows sur ce projet, et il a
  un GPU. Un contributeur Windows sans GPU force le CPU par
  `UV_TORCH_BACKEND=cpu uv sync` — la roue CPU reste parfaitement fonctionnelle,
  `device()` résout `"cpu"` et le rapporte.
- **Linux, la CI et l'image Docker ne changent pas.** Le `Dockerfile` garde son
  `UV_TORCH_BACKEND=cpu`, et le marqueur ne l'atteint pas.
- **Le conteneur n'a toujours pas de GPU.** Faire tourner ce service sur la P1000
  *via Docker* demanderait une image CUDA et un runtime NVIDIA — hors périmètre
  ici, et à re-décider avec le même soin sur `sm_61`.
- **Les mesures de benchmark antérieures sont des mesures CPU.** Elles restent
  valables comme telles ; un run persisté porte son `device`, précisément pour ça.
  Les chiffres des ADR 0007, 0008 et 0010 n'ont pas été rejoués sur GPU.
- L'ANPR ne bouge pas : détection de plaques et OCR passent par `onnxruntime`, pas
  par torch. Le GPU ne les accélère pas — et le plancher de lecture de l'OCR
  (~150 px) reste ce qu'il est, un problème de résolution, pas de débit.

## Ce que cette ADR ne change pas

Le corps d'ADR 0005 reste exact : aucune branche du code ne dépend de la
variante installée, `device()` résout `"auto"` une seule fois, et le service dit
ce qu'il a retenu. Seule sa phrase sur le lockfile était fausse.
