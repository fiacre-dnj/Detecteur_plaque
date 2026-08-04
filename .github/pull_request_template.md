## Ce que fait cette PR

<!-- Une à trois phrases. Ce que voit l'utilisateur, pas la liste des fichiers. -->

## Pourquoi

<!-- Le problème résolu, pas la solution. Si une contrainte de prompt/ a été
     mise en défaut, le dire ici avec la preuve et renvoyer vers l'ADR. -->

## Comment vérifier

1.
2.

## Captures / sorties de commandes

<!-- Sortie de pytest, capture d'écran de l'interface, chiffres avant/après.
     Une affirmation sans preuve se relit mal. -->

## Liste de contrôle

- [ ] Lint, types et tests verts localement des deux côtés
- [ ] Tests ajoutés pour le comportement nouveau ou corrigé
- [ ] `CHANGELOG.md` — une ligne dans `## [Non publié]`, orientée utilisateur
- [ ] ADR écrite si une décision a été prise ou une contrainte écartée
- [ ] Migration Alembic incluse **et réversible** si le schéma a changé
- [ ] Miroir TypeScript (`shared/api/contracts.ts`) à jour si un schéma a changé
- [ ] Aucun secret, aucun poids, aucune vidéo, aucun fichier > 5 Mo
- [ ] Aucun `print`, aucun `console.log`, aucun `TODO` sans référence
