# Contribuer

La référence complète est [`prompt/11-GIT-ET-CONVENTIONS.md`](prompt/11-GIT-ET-CONVENTIONS.md).
Ce fichier en est le résumé opérationnel.

## Avant tout : `prompt/` est normatif

Le dossier [`prompt/`](prompt/) n'est pas de la documentation d'intention, c'est
la **spécification**. Quand un de ses fichiers écrit « obligatoire », « jamais »
ou « exactement », c'est une contrainte qui a coûté un bug dans une version
antérieure de l'application ; [`prompt/13`](prompt/13-PIEGES-CONNUS.md) en tient
la liste. Si une contrainte vous paraît fausse, **dites-le avec la preuve**,
proposez l'alternative et écrivez une ADR — ne la contournez pas en silence.

## Branches

Jamais de travail direct sur `main`, qui reste déployable. Branches courtes
(moins de deux jours), nommées `<type>/<portée>-<sujet-en-kebab>` :

```
feat/backend-comptage-lignes
fix/backend-progression-sse-tamponnee
refactor/frontend-etat-geometrie-reducer
docs/adr-python-312
```

Un sujet = une branche. Un correctif découvert en chemin mérite sa propre
branche : un diff qui mélange deux intentions ne peut pas être relu.

`git pull --rebase` pour rester à jour. Jamais de merge de `main` dans la branche
en boucle. Jamais de `--force` sur une branche partagée.

## Commits — Conventional Commits, portée obligatoire

```
<type>(<portée>): <sujet à l'impératif, minuscule, sans point final>

<corps : POURQUOI, ce qui a été écarté, ce qui reste>
```

Types : `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `chore`, `build`,
`ci`, `style`, `revert`.

Portées : `backend/counting`, `backend/jobs`, `backend/models`,
`backend/benchmark`, `backend/realtime`, `backend/api`, `backend/db`,
`backend/core`, `frontend/studio`, `frontend/geometry`, `frontend/transport`,
`frontend/results`, `frontend/registry`, `frontend/benchmark`,
`frontend/shared`, `repo`, `docs`, `ci`.

Le corps explique **pourquoi**. `fix: bug`, `wip`, `maj` et un commit de
40 fichiers touchant trois features sont refusés en revue.

### Granularité

- Un commit compile, passe le lint, les types et les tests. **Aucun commit
  cassé, même intermédiaire.**
- Le refactoring préparatoire est un commit séparé de la fonctionnalité qu'il
  prépare.
- Une migration Alembic va dans **le même** commit que le changement de modèle
  qui la provoque.
- Les tests d'une fonctionnalité vont avec elle, pas dans un commit « ajoute des
  tests » deux jours plus tard.
- `git add -p` plutôt que `git add .` : on committe ce qu'on a relu.

## Avant chaque commit

```bash
git status && git diff --staged        # relire son propre diff

cd backend  && uv run ruff check . && uv run ruff format --check . \
            && uv run mypy src && uv run pytest
cd frontend && bun run lint && bun run typecheck && bun run test
```

Vérifier en particulier : aucun `print`, aucun `console.log`, aucun `TODO` sans
référence, aucun secret, aucun fichier de plus de 5 Mo, aucun `.env`, aucun poids.

**Ne jamais utiliser `--no-verify`.** Un hook contourné une fois le sera toujours ;
si un hook bloque, la bonne réaction est de corriger la cause.

## Ce qui n'entre jamais dans l'historique

`*.pt`, `*.onnx`, `*.engine`, `*.mp4`, `data/`, `*.db`, `.env`, `node_modules/`,
`.venv/`, et du code commenté « pour plus tard » (git le garde déjà).

## Pull requests

Le modèle est [`.github/pull_request_template.md`](.github/pull_request_template.md).
Environ 400 lignes de diff utile maximum : une PR qu'on ne peut pas relire est une
PR qu'on approuve sans lire. La CI est obligatoire avant merge.

Alimenter `## [Non publié]` du [`CHANGELOG.md`](CHANGELOG.md) à chaque PR — une
ligne, en français, orientée utilisateur.

## Langue

**Le code parle français à l'utilisateur, anglais au compilateur.** Identifiants
et types en anglais ; docstrings, commentaires et copie d'interface en français.
