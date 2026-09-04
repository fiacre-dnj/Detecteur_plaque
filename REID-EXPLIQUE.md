# Reconnaître un véhicule — ce que fait le système, ce qui a cassé, ce qu'on a réparé

Document d'explication, sans code. Il décrit ce que la fonctionnalité promet, les
pannes qu'on a réellement rencontrées à l'usage, ce qu'on a corrigé, et — c'est la
partie la plus utile — **ce qu'elle ne saura jamais faire**.

> Le sigle « ReID » veut dire *ré-identification* : reconnaître qu'un véhicule vu à un
> endroit est le même que celui vu ailleurs ou plus tôt. Dans ce document on dira
> simplement « reconnaître un véhicule ».

---

## 1. Deux questions différentes, un même moteur

L'application répond à **deux** questions qui se ressemblent mais ne se confondent pas.

| | La question | Ce qu'on lui donne | Où ça s'affiche |
|---|---|---|---|
| **Recherche par photo** | « Cette voiture-là est-elle passée ? » | une photo que **vous** importez | colonne « Ressemblance » du registre, et une alerte |
| **Véhicule déjà vu** | « Ce véhicule est-il déjà passé plus tôt ? » | rien — la vidéo est comparée à elle-même | colonne « Déjà vu », et une alerte |

La première compare la vidéo à **votre photo**. La seconde compare la vidéo à
**elle-même**. Un même véhicule peut porter les deux pourcentages en même temps, et
ils ne veulent pas dire la même chose.

**Et une troisième chose qui n'est ni l'une ni l'autre : le comptage.** Il ne dépend
d'aucune des deux. Voir le point 3, c'est important.

---

## 2. Le principe, en clair

Le système ne lit **pas** la plaque pour cela. Il regarde **l'apparence** du véhicule :
sa silhouette, sa couleur, ses reflets, la forme de son toit.

Concrètement, pour chaque véhicule il découpe une vignette sur l'image, et il en tire
une **signature** — une sorte d'empreinte de l'apparence. Comparer deux véhicules
revient alors à comparer deux signatures, ce qui donne **un pourcentage de
ressemblance**.

### Pourquoi c'est plus difficile qu'il n'y paraît

Le système ramène chaque vignette à un **petit carré** de taille fixe avant d'en tirer
la signature. Or un véhicule loin de la caméra tient dans un rectangle large et plat,
et le même véhicule de près tient dans un rectangle presque carré. **Ramenés au même
carré, les deux ne sont pas déformés de la même façon** — la même voiture n'a donc pas
tout à fait la même signature selon l'instant où on la photographie.

C'est mesuré, et le chiffre surprend :

- deux photos du **même** véhicule peuvent tomber à **39 %** de ressemblance ;
- deux véhicules **différents** peuvent monter à **89 %**.

**Les deux plages se chevauchent.** Il n'existe donc aucun seuil qui soit à la fois sûr
et utile. C'est pourquoi l'écran promet **des candidats à vérifier, jamais un
verdict** — et pourquoi un clic ouvre toujours les deux photos côte à côte : c'est
votre œil qui tranche, pas le pourcentage.

---

## 3. La garantie à ne jamais perdre de vue : les chiffres ne bougent pas

**Reconnaître un véhicule ne change aucun comptage.** Un véhicule reconnu comme « déjà
vu » reste un véhicule **de plus** dans les totaux, et son passage reste compté. Le
système **signale**, il ne fusionne pas.

Ce n'est pas un détail de principe : une version antérieure de l'application faisait
l'inverse — elle réattribuait au second véhicule le numéro du premier — et les totaux
s'en trouvaient faussés, le même numéro réapparaissant au milieu d'une vidéo. La
fonctionnalité avait été retirée pour cette raison.

Elle est revenue parce qu'elle est désormais **une aide à la consultation, branchée
sur rien**. Et ce n'est pas une promesse verbale : un contrôle automatique rejoue la
même vidéo avec et sans reconnaissance, et vérifie que les totaux, les répartitions
**et les horodatages** sont identiques au chiffre près. Si ce contrôle échouait un
jour, la bonne décision serait de retirer la fonctionnalité, pas de la corriger.

---

## 4. Les pannes rencontrées, et ce qu'on a fait

### Panne 1 — « il désigne le mauvais véhicule, et annonce 27 % »

**Ce qu'on a vu.** Test sur une vidéo dupliquée bout à bout, où la bonne réponse est
forcément proche de 100 %. Sur sept véhicules, trois annonçaient 42 %, 60 % et 27 % —
et le dernier désignait **une autre voiture**.

**Pourquoi.** Un véhicule franchit plusieurs lignes de comptage, donc il est comparé
plusieurs fois — et **à chaque fois avec une photo différente de lui-même**. Le
système gardait la **dernière** comparaison au lieu de la **meilleure**. Comme deux
photos du même véhicule se ressemblent parfois mal (le point 2), la dernière était
souvent la pire. Et comme il ne mémorisait qu'**une seule** photo par véhicule, la
comparaison dépendait du hasard : celle qu'il avait retenue correspondait-elle à celle
qu'on lui présentait ?

**Ce qu'on a fait.** Il retient maintenant la **meilleure** comparaison, et il mémorise
**plusieurs** photos par véhicule. Le numéro suit toujours le score : jamais le
meilleur pourcentage d'un véhicule avec le numéro d'un autre.

**Résultat.** Nouveau test, même genre de vidéo : **21 correspondances, toutes justes,
à 95–99 %**.

### Panne 2 — « une page entière de correspondances fausses »

**Ce qu'on a vu.** Des véhicules qui n'ont, par construction, aucun antécédent
affichaient quand même un numéro : « comme #1 — 2 % », « comme #7 — 31 % », en gris.
L'écran se lisait comme « le système se trompe partout ».

**Pourquoi.** Le serveur publie toujours le meilleur candidat qu'il a trouvé, quel
qu'en soit le score, et l'écran l'affichait tel quel. L'intention était bonne — laisser
voir qu'on est passé à côté de peu — mais **une identité affirmée à 2 % n'est pas une
information nuancée, c'est une affirmation fausse**.

**Ce qu'on a fait.** Sous le seuil de confiance, la case affiche « — ». Le pourcentage
exact reste dans l'infobulle et dans l'export, où il sert au réglage sans rien
prétendre. Et la colonne n'apparaît plus du tout si aucun véhicule n'a réellement été
reconnu.

**Une exception assumée.** Pour la **recherche par photo**, le pourcentage sous le
seuil reste affiché. La raison : là, vous avez un curseur, et ce nombre est
précisément ce qui vous dit de le baisser. Appliquer la même règle des deux côtés vous
aurait retiré votre outil de réglage.

### Panne 3 — « la recherche par photo pouvait perdre un véhicule »

**Ce qu'on a vu.** Rien de visible — c'est le problème. Un véhicule qui ressemblait
franchement à la photo cherchée disparaissait parfois des résultats, **tout en gardant
la photo qui servait à le vérifier**.

**Pourquoi.** Le même défaut que la panne 1, en pire. Quand la dernière comparaison
tombait sous le plancher du serveur, elle n'était pas seulement ignorée : elle
**effaçait** le bon score obtenu plus tôt.

**Ce qu'on a fait.** C'est la meilleure mesure qui compte, et une mesure refusée
n'efface plus rien. Le plancher décide de ce qu'on **publie**, jamais de ce qu'on
**supprime**.

### Panne 4 — « le cadrage envoyé n'était pas celui qu'on voyait »

**Ce qu'on a vu.** Rien non plus, et c'était le plus sournois. Vous encadrez la voiture
sur votre photo, le rectangle bleu s'affiche exactement là où vous avez glissé — et le
serveur reçoit **une autre zone**, décalée et redimensionnée. Le cas se produisait sur
toute photo plus haute que large, c'est-à-dire sur **une photo de téléphone**.

**Pourquoi.** L'aperçu ajoutait des bandes vides de chaque côté pour caser l'image dans
son cadre, et les coordonnées de votre glissement étaient mesurées sur le cadre, bandes
comprises. Le rectangle bleu étant dessiné dans le même repère faux, tout paraissait
juste.

**Ce qu'on a fait.** L'aperçu épouse maintenant exactement la photo : plus de bandes,
donc plus d'écart possible. Et si quelqu'un réintroduit un jour une largeur imposée,
l'aperçu se **déformera visiblement** au lieu de décaler le cadrage en silence — on a
échangé une panne muette contre une panne criante.

**Au passage.** Le découpage reproduit désormais la petite marge que le serveur ajoute
autour des véhicules qu'il détecte dans la vidéo. Sans elle, votre voiture occupait
100 % de la vignette envoyée là où celles de la vidéo n'en occupent que 89 % : le même
véhicule y paraissait 12 % plus gros, et la comparaison s'en ressentait.

### Panne 5 — « les alertes n'affichaient aucun pourcentage »

Le chiffre était calculé, il était même contrôlé automatiquement… et il n'atteignait
jamais l'écran. Les cartes « Véhicule recherché » et « Véhicule déjà vu » annonçaient
une ressemblance sans jamais dire à quel point. Corrigé.

### Panne 6 — « deux "ressemblances" sous le même mot »

La fenêtre de comparaison affichait « Ressemblance 100 % » en titre (ressemblance au
véhicule jumeau) au-dessus de « ressemblance 34 % » en légende (ressemblance à la photo
cherchée). Deux mesures différentes, un seul mot, et les deux chiffres plausibles. La
légende dit maintenant à quoi elle se compare.

---

## 5. Ce que la mesure a appris — et qui va contre l'intuition

### Une vidéo dupliquée n'est pas identique

On croyait tester sur un cas parfait : la même vidéo deux fois, donc des images
identiques, donc 100 % de ressemblance attendus. **C'est faux.** Quand un logiciel de
montage exporte le fichier, il **recompresse** : les deux copies se ressemblent
énormément mais ne sont plus identiques.

Vérifié sur le fichier réel :

| | |
|---|---|
| Décalage entre les deux copies | 51,4 secondes, exactement le même partout |
| Différence entre deux images censées être identiques | faible mais **non nulle** |
| La même image comparée à elle-même | **100,0000 %** — le système est parfaitement stable |
| Deux images correspondantes des deux copies | **96,9 % à 99,7 %** (médiane 99,1 %) |
| Nombre de comparaisons atteignant 100 % | **zéro sur 48** |

**Conclusion : 95–99 % sur une vidéo dupliquée puis réexportée est un succès, pas un
manque.** Le pour-cent qui manque, c'est la compression vidéo — pas la reconnaissance.
Pour obtenir 100,0 % il faudrait assembler le fichier **sans le recompresser**.

### Les trois véhicules « non reconnus » avaient raison de l'être

Sur le dernier test, trois véhicules n'affichaient aucune correspondance. Vérification :
ils passent tous les trois **après la fin de la portion réellement dupliquée** — dans
les six dernières secondes du montage, qui n'existent qu'une seule fois. Ils n'ont
aucun antécédent. Leur signaler une correspondance aurait été une erreur.

**Bilan du test : 24 décisions, 24 justes.**

### Donner plus de photos par véhicule ne sert à rien

Le levier semblait évident : mémoriser 4 photos par véhicule au lieu de 2. Mesuré : la
ressemblance moyenne des vrais couples monte, **mais celle des faux couples monte
autant**, et surtout **le système ne change aucune de ses décisions**. Pour un coût de
20 à 40 secondes de calcul par vidéo.

Le levier a donc été **mesuré puis écarté**, et la mesure est archivée — pour qu'on ne
le repropose pas dans six mois faute de trace.

---

## 6. Ce que ça ne saura pas faire

À lire avant de conclure à une panne.

- **Un véhicule trop petit ou trop flou n'obtient aucune réponse**, plutôt qu'une
  fausse. En dessous d'environ 96 pixels de largeur à l'écran, la vignette ne contient
  plus d'information exploitable : le système se tait délibérément.
- **Deux voitures identiques resteront indiscernables.** Même modèle, même couleur : la
  ressemblance sera très élevée et elle aura raison de l'être. C'est la **plaque** qui
  tranche, et c'est pour cela qu'elle est affichée sous chaque photo dans la fenêtre de
  comparaison.
- **Deux véhicules visibles en même temps ne sont jamais rapprochés**, si ressemblants
  soient-ils : ils ne peuvent pas être le même objet physique. C'est ce qui écarte le
  faux positif le plus fréquent en trafic dense, deux voitures qui se suivent.
- **Un véhicule qui ne franchit aucune ligne n'entre pas dans « déjà vu »** : la
  comparaison a lieu au moment du passage sur un trait.
- **Le cas vraiment difficile n'est pas encore mesuré** : un véhicule qui repasse des
  heures plus tard, sous un autre angle et une autre lumière. Une vidéo dupliquée ne le
  simule pas — elle ne fait varier ni la lumière, ni la trajectoire, ni le point de vue.
  C'est la prochaine mesure à faire, et elle demande du métrage réel.
- **Les seuils ne sont pas des vérités.** 75 % pour « déjà vu », 55 % par défaut pour la
  recherche par photo. Les plages se chevauchant de 3 % à 90 %, ces seuils manqueront
  parfois un vrai couple et en accepteront parfois un faux. Ils sont réglables, et la
  photo est là pour vérifier.

---

## 7. Comment lire l'écran

- **Colonne « Déjà vu »** du registre : « comme #12 — 87 % » signifie « ce véhicule
  ressemble à 87 % au véhicule numéro 12, passé plus tôt ». Un tiret signifie « rien ne
  lui ressemble assez » — pas « la fonctionnalité n'a pas marché ».
- **Cliquez sur cette case** : les deux véhicules s'ouvrent **côte à côte**, avec leur
  plaque quand elle a été lue. C'est là que vous décidez. Le plus ancien est à gauche.
- **Colonne « Ressemblance »** : la ressemblance à la photo que **vous** avez importée.
  Rien à voir avec la précédente.
- **La cloche** signale les deux familles avec leur pourcentage et leur photo. Un clic
  sur une alerte amène la vidéo à l'instant concerné.
- **Le curseur de la recherche par photo** se déplace **sans relancer l'analyse** : le
  serveur publie le score brut, vous choisissez où couper.

---

## 8. En résumé

| | |
|---|---|
| Sur quoi ça se base | l'**apparence** du véhicule, jamais la plaque |
| Ce que ça rend | un **pourcentage de ressemblance**, à vérifier sur les photos |
| Ce que ça ne change jamais | **les comptages** — contrôlé automatiquement |
| Ce qui a été réparé | la meilleure comparaison au lieu de la dernière ; plusieurs photos mémorisées ; plus d'identité affirmée à 2 % ; plus de score effacé par erreur ; le cadrage envoyé est celui qu'on voit ; les pourcentages atteignent l'écran |
| Ce qui plafonne à 95–99 % | la **compression vidéo**, pas la reconnaissance |
| Ce qui reste à mesurer | le même véhicule des heures plus tard, sous un autre angle |

---

*Le détail technique — décisions, mesures, chiffres bruts — vit dans les fiches de
décision du dossier `docs/adr/` (numéros 0048, 0050, 0051 et 0055) et dans le
`CHANGELOG.md`. Ce document-ci n'en est que la lecture en clair.*
