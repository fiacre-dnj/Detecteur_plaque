# 11 — Git : branches, commits, revue, livraison

> **Instruction directe à l'agent qui implémente ce projet** : tu appliques ces
> règles pendant toute l'implémentation, front **et** back. Tu ne travailles
> jamais directement sur `main`. Tu ne produis pas un commit géant en fin de
> parcours. Chaque lot du [plan d'exécution](12-PLAN-EXECUTION.md) se termine par
> au moins un commit atomique dont le message explique **pourquoi**. Si un dépôt
> expose une compétence (*skill*) de flux git, utilise-la.

## 1. Branches

- `main` : toujours dans un état déployable. Protégée : pas de push direct, CI
  verte obligatoire, revue obligatoire.
- Branches courtes (**< 2 jours de travail**), nommées
  `<type>/<portée>-<sujet-en-kebab>` :

```
feat/backend-comptage-lignes
feat/frontend-editeur-geometrie
fix/backend-progression-sse-tamponnee
refactor/frontend-etat-geometrie-reducer
chore/ci-cache-uv
docs/adr-python-312
test/backend-invariants-comptables
```

- Un sujet = une branche. Si en cours de route tu découvres un correctif sans
  rapport, tu fais une branche à part — un diff qui mélange deux intentions ne
  peut pas être relu.
- **Rebase** sur `main` pour rester à jour (`git pull --rebase`), **merge
  squash** ou merge classique pour intégrer, jamais de merge de `main` dans la
  branche en boucle (l'historique devient illisible).

## 2. Commits — Conventional Commits, avec portée

Format :
```
<type>(<portée>): <sujet à l'impératif, minuscule, sans point final>

<corps : POURQUOI ce changement, ce qui a été écarté, ce qui reste à faire>

<pied : Refs #12 / BREAKING CHANGE: …>
```

Types : `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `chore`, `build`,
`ci`, `style`, `revert`.

Portées (obligatoires dans ce projet, elles rendent `git log --oneline` lisible) :
`backend/counting`, `backend/jobs`, `backend/models`, `backend/benchmark`,
`backend/realtime`, `backend/api`, `backend/db`, `backend/core`,
`frontend/studio`, `frontend/geometry`, `frontend/transport`,
`frontend/results`, `frontend/registry`, `frontend/benchmark`,
`frontend/shared`, `repo`, `docs`, `ci`.

Bons exemples :

```
feat(backend/counting): compte les franchissements par ligne et par sens

Le garde de déduplication porte sur (ligne, identité, sens) et non
(ligne, identité) : un véhicule qui tremble sur la ligne ne compte qu'une
fois, mais un aller-retour réel compte une fois dans chaque sens.

Le côté de la piste est mis à jour même quand le franchissement est rejeté
par la zone, sinon la piste « regarde dans le mauvais sens » et le
franchissement suivant compte à l'envers.
```

```
fix(backend/counting): fige les pistes de la timeline après la passe ANPR

La session mute la même instance de piste d'une frame à l'autre : stocker la
référence vivante faisait converger toutes les lignes de la timeline vers
l'état final. Le snapshot est pris après l'ANPR pour ne pas perdre les
plaques.
```

Mauvais exemples : `fix: bug`, `wip`, `maj`, `feat: ajoute des trucs au
frontend`, un commit de 40 fichiers touchant trois features.

### Granularité
- Un commit compile, passe le lint, les types et les tests. **Aucun commit
  cassé, même intermédiaire.**
- Un commit = un changement logique. Le refactoring préparatoire est un commit
  séparé de la fonctionnalité qu'il prépare — c'est ce qui rend la revue
  possible.
- Les migrations Alembic sont dans **le même** commit que le changement de modèle
  qui les provoque.
- Les tests d'une fonctionnalité vont avec la fonctionnalité, pas dans un commit
  « ajoute des tests » deux jours plus tard.
- `git add -p` plutôt que `git add .` : on committe ce qu'on a relu.

## 3. Avant chaque commit

```bash
git status                    # rien d'inattendu dans l'index ?
git diff --staged             # relire son propre diff, ligne par ligne
# backend
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
# frontend
bun run lint && bun run typecheck && bun run test
```

Vérifier en particulier : aucun `console.log`, aucun `print`, aucun `TODO` sans
référence, aucun secret, aucun fichier > 5 Mo, aucun `.env`, aucun poids.

## 4. Ce qui ne doit jamais entrer dans l'historique

| Interdit | Pourquoi | À la place |
|---|---|---|
| `*.pt`, `*.onnx`, `*.engine` | La version précédente a committé ~700 Mo de poids : chaque clone les paie pour toujours, et un `git filter-repo` ultérieur casse tous les forks | Téléchargement à la demande dans `.weights/` + script avec somme SHA-256 |
| Vidéos (`*.mp4`) | Idem, et une vidéo de trafic peut contenir des plaques réelles (donnée personnelle) | `frontend/public/demo/` ignoré, README qui dit où déposer un clip |
| `data/`, `*.db` | Données d'exécution | Volume Docker / dossier ignoré |
| `.env` | Secrets | `.env.example` committé |
| `node_modules/`, `.venv/`, caches | Reproductible depuis les lockfiles | lockfiles committés |
| Code commenté « pour plus tard » | Le git le garde déjà | Le supprimer |

**Différence assumée avec l'ancien dépôt** : il committait les `.onnx` par
décision explicite. Le nouveau projet ne le fait pas, parce que l'inférence est
côté serveur et que les poids véhicules sont des `.pt` téléchargés par
Ultralytics. Écrire cette décision dans `docs/adr/0002-pas-de-poids-dans-git.md`.

## 5. Pull requests

Modèle `.github/pull_request_template.md` :

```markdown
## Ce que fait cette PR
## Pourquoi (le problème résolu, pas la solution)
## Comment vérifier
1. …
## Captures / sorties de commandes
## Liste de contrôle
- [ ] Lint, types, tests verts localement
- [ ] Tests ajoutés pour le comportement nouveau ou corrigé
- [ ] Documentation / ADR mise à jour si une décision a été prise
- [ ] Migration Alembic incluse et réversible si le schéma change
- [ ] Aucun secret, aucun poids, aucun gros fichier
- [ ] Contrat API : miroir TypeScript mis à jour si un schéma a changé
```

Revue : maximum ~400 lignes de diff utile par PR. Au-delà, découper — une PR
qu'on ne peut pas relire est une PR qu'on approuve sans lire.

## 6. Versions et journal

- **SemVer** sur le service (`traffic_analysis.__version__`, source unique lue
  aussi par FastAPI et affichée dans l'UI).
- `CHANGELOG.md` au format *Keep a Changelog*, section `## [Non publié]`
  alimentée **à chaque PR** (une ligne, en français, orientée utilisateur).
- Tags annotés `vX.Y.Z` sur `main`, avec les notes de version extraites du
  changelog.
- Le changelog n'est pas `git log` : il dit ce qui change **pour l'utilisateur**,
  pas quels fichiers ont bougé.

## 7. Discipline d'implémentation attendue de l'agent

1. **Créer la branche avant d'écrire la première ligne.**
2. Un lot du plan = une branche = une ou plusieurs PR atomiques.
3. À la fin de chaque lot : lancer la totalité des vérifications, committer,
   mettre à jour `CHANGELOG.md`, et **dire à l'humain** ce qui a été fait, ce qui
   reste, et ce qui a été volontairement laissé de côté.
4. Ne jamais committer ni pousser sans que l'humain l'ait demandé si l'outillage
   l'exige ; en revanche **préparer** le commit (message inclus) fait partie du
   travail.
5. Si un test échoue, ne pas le désactiver : comprendre, corriger, et si le test
   était faux, expliquer pourquoi dans le message de commit.
6. Ne jamais `--force` sur une branche partagée ; `--force-with-lease` sur sa
   propre branche uniquement, après rebase.
