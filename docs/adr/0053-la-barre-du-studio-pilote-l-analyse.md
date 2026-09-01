# ADR 0053 — La barre du studio pilote l'analyse

- **Statut** : accepté
- **Date** : 2026-09-01
- **S'appuie sur** : [ADR 0052](0052-la-navigation-passe-dans-un-rail-lateral.md), dont
  elle reprend la contrainte de largeur — la rangée plafonne à ~1552 px quelle que soit
  la fenêtre.
- **Amende** : [ADR 0044](0044-les-alertes-deviennent-un-centre-de-notifications.md) sur
  « la pilule ne porte aucun mot », qui devient la règle de **toutes** les pilules et
  non l'exception de la cloche.
- **Ne touche aucun calcul.** Aucun compteur, aucun sérialiseur, aucun contrat.

## Contexte

Les commandes d'une analyse vivaient à **trois** endroits qu'on ne voit pas d'un même
coup d'œil : « Lancer l'analyse » au bas du lecteur, « Suspendre » et « Annuler » dans
un bloc sous la vidéo qui n'apparaissait qu'une fois le job parti, et les réglages dans
la barre. Piloter une analyse demandait donc de chercher le bouton suivant ailleurs que
là où l'on venait de cliquer — et la progression, elle, était sous la vidéo, donc hors
de l'écran dès qu'on lisait le registre.

Les chiffres techniques, eux, n'existaient qu'une fois une analyse lancée : la barre
changeait de forme au moment précis où l'on venait de cliquer, à l'endroit exact où
l'on regardait.

## Décision

**La barre est le seul poste de pilotage.** L'import, les commandes du job et l'anneau
de progression à gauche ; les réglages et les outils au centre, en icônes ; les chiffres
à droite.

Cinq changements :

1. **Toutes les pilules sont en icône seule**, libellé déplié au survol et au focus
   (`shared/ui/ToolbarButton`) — **sauf les commandes du job**, qui ne se déplient
   jamais, voir « Trois ajustements » plus bas. Seul l'import garde son texte.
2. **Les commandes du job entrent dans la barre** : Lancer, puis Suspendre / Reprendre
   et Annuler, chacune avec sa teinte.
3. **Les chiffres sont montés dès qu'une vidéo est chargée**, à « — » tant que rien n'a
   tourné, et **plus petits** — la valeur passe de 14 à 12 px.
4. **La progression est un anneau** portant le %, centré au-dessus du compte d'images
   « 330 / 817 images », **posé juste après les commandes** — il répond au bouton qu'on
   vient de cliquer, et le mettre à l'autre bout avec les chiffres obligeait à
   traverser la barre du regard pour vérifier qu'un lancement avait pris.
5. **Le bloc sous la vidéo est réduit** à ce que la barre ne peut pas porter.

## Ce que la mesure a corrigé, deux fois

**L'animation par `grid-template-columns: 0fr → 1fr` ne fonctionne pas ici.** C'est le
motif habituel pour animer une largeur `auto`, et il a été écrit puis mesuré faux : il
suppose un conteneur qui distribue de l'espace libre, alors que la pilule est un
`inline-flex` **dimensionné par son contenu**. La piste se résout à son minimum et ne
s'ouvre jamais. Relevé en page, `1fr` forcé à la main : bouton **48 px avant, 48 px
après**. La `max-width` animée donne **40 px replié, 138 px déplié**, et supprime au
passage le padding fantôme que la version en grille laissait survivre au repli.

Sa contrepartie est assumée : la vitesse *apparente* dépend de la longueur du mot,
l'animation courant jusqu'au plafond et non jusqu'au texte. Le plafond est donc serré
(10 rem, juste au-dessus de « Lancer l'analyse »).

**Le seuil de repli des chiffres redescend de 1560 à 1280 px.** Toutes les pilules
étant passées en icône seule, la rangée au repos pèse **1072 px** — import 219,
commande 48, réglages 169, outils 113, chiffres 491. Mesuré : elle tient sur une ligne
à 1300 px et casse à 1200.

## Ce qui s'est vu à l'usage, et qu'aucun plan n'avait prévu

**Un job en file d'attente affichait « 0 / 0 images · 0.0 img/s ».** C'est exactement le
défaut que la phase `preparing` existait pour éviter — « 0 / 0 » se lit comme une
analyse plantée — et il se rejouait à un endroit qu'on n'avait pas regardé :
`totalFrames` vaut zéro tant que le serveur n'a pas sondé la vidéo.

Observé en conditions réelles, et la cause est instructive : le job de test est resté en
file **derrière une analyse suspendue**, qui garde sa place sur le serveur — la
situation exacte que la phrase de pause explique depuis toujours, sans que rien ne la
dise du côté de celui qui attend. La correction donne donc plus qu'un silence : « En
attente d'une place sur le serveur — une analyse suspendue en occupe une. »

## Quatre ajustements après premier usage

- **Les commandes du job ne se déplient pas au survol**, seules de toute la barre. En
  tête de rangée, leur expansion pousse *tout* ce qui suit — y compris l'anneau et les
  chiffres, qu'on lit précisément au moment où l'on hésite à suspendre. Et elles
  changent de nature en cours de route : une pilule qui s'ouvre sous le curseur à
  l'instant où « Lancer » devient « Suspendre » se lit comme un déplacement.
- **« Lancer » passe au bleu.** En vert, il était la copie du bouton d'import placé
  juste à sa gauche, et les deux se lisaient comme un seul groupe — « Lancer » passait
  pour une variante de « Changer de vidéo ». La règle devient : **la source est verte,
  le job est bleu**. `--color-info` (#539df5 / #1a5fbf) ne servait nulle part ailleurs,
  et `text-accent-ink` lui convient — ce jeton vaut noir en thème sombre et blanc en
  clair, exactement ce que demandent les deux bleus. L'anneau, lui, **reste vert** : il
  encode une donnée, pas une action, ce qui est l'usage auquel ADR 0004 réserve
  l'accent.
- **L'anneau déménage à gauche**, juste après « Annuler ».
- **Son détail perd la cadence**, et le pourcentage se centre sur ce qui reste. La
  ligne disait « 430 / 957 images · 13.6 img/s (serveur) », alors que la rangée de
  chiffres qui suit affiche déjà « Cadence serveur » **avec son libellé** : c'était un
  doublon, et le plus cher qui soit puisqu'il occupait la largeur d'une barre qui doit
  tenir sur une ligne. Mesuré : le bloc passe de ~240 à **110 px**. Le détail ne garde
  que ce que rien d'autre ne dit — où en est le compte d'images.

## Le prix de la discrétion, et ce qu'il a fallu rendre

Ramener la progression à un anneau de 22 px a coûté ce qu'on n'avait pas prévu :
**l'écran a cessé de dire qu'une analyse tournait.** Le rapport est arrivé mot pour
mot — « je n'arrive pas à lancer, j'ai toujours cette erreur *Lecture suspendue* » —
sur une analyse qui tournait à 20 img/s et progressait de 3360 à 3420 images pendant
qu'on la regardait.

Trois causes cumulées, toutes de notre fait :

- **le nom de la phase avait quitté l'écran** pour l'infobulle, au motif qu'« Analyse
  en cours » n'ajoute rien à côté d'un anneau qui tourne et d'un compteur qui monte.
  C'est vrai — **seulement quand le compteur existe**. En file d'attente et à
  l'ouverture de la vidéo, il n'y en a pas : l'anneau montrait « 0 % » et rien d'autre ;
- **la file d'attente était rangée avec « en cours »**, donc le bloc explicatif sous la
  vidéo restait masqué à l'instant précis où il servait — et « Suspendre » était
  proposé sur un job sans thread à arrêter ;
- **« Lecture suspendue : la vidéo se cale sur l'image analysée. »** était devenue le
  texte le plus visible sous la vidéo, le bloc de progression ayant disparu. Seul
  commentaire d'un écran figé, elle se lisait comme le verdict du lancement.

Corrigé : le libellé de phase s'affiche **dès qu'il n'y a pas de compteur**, `queued`
devient une phase à part entière — donc le bloc sous la vidéo reparaît avec la cause de
l'attente, et « Suspendre » disparaît —, et la phrase du dessous commence désormais par
la phase : « **Analyse en cours** — la lecture se cale sur l'image analysée. » Le même
texte, mais qui confirme au lieu d'alarmer.

**La leçon, pour la prochaine compaction d'affichage** : un indicateur peut rétrécir
tant qu'il **bouge**. Dès qu'il est immobile — 0 %, aucune image, aucun mouvement — il
doit écrire ce qu'il attend, sinon il ne dit plus rien du tout.

## Conséquences

- **`analysisProgress` est le seul juge de l'état du job**, et il est **pur et testé**
  (9 cas). Deux surfaces le lisent — la barre et le bloc sous la vidéo — et deux calculs
  séparés finiraient par afficher deux pourcentages du même job sur le même écran.
  C'est aussi la seule façon de vérifier quoi que ce soit ici, le dépôt n'ayant aucun
  test de composant ;
- **`shared/ui/ToolbarButton` est une primitive partagée, et devait l'être** : les
  tiroirs vivent dans `analysis-settings`, les commandes dans `analysis-job`, et une
  feature n'importe jamais une autre. Deux copies de cette pilule auraient divergé sur
  l'état ouvert, c'est-à-dire sur le seul repère qui dit quel tiroir on lit ;
- **l'expansion pousse les voisins**, elle ne flotte pas au-dessus d'eux : un calque
  flottant n'aurait rien décalé mais aurait recouvert la pilule suivante, ce qui est
  pire sur une rangée qu'on parcourt. **Condition de retour** : si la rangée en vient à
  passer sur deux lignes quand un libellé s'ouvre, c'est ce choix qu'il faut défaire ;
- **entre 1280 et ~1500 px, pendant une analyse, le détail de l'anneau se tronque** au
  lieu de faire passer la rangée sur deux lignes. Déplacer les chiffres dans le tiroir
  à ce moment-là aurait été pire : la barre changerait de forme au lancement ;
- **le bloc sous la vidéo ne calcule plus rien** et n'est monté que pour l'envoi, la
  préparation, l'échec et la phrase de pause. Sa barre de progression **reste**, et ce
  n'est pas un doublon de l'anneau : elle ne s'affiche que pendant l'envoi, la seule
  phase où l'anneau n'existe pas encore — il n'y a pas encore de job ;
- **les icônes disent ce que le tiroir produit**, pas ce qu'il est :
  `SquareDashedMousePointer` (la boîte englobante) pour Détection, `Waypoints` (des
  points reliés) pour Géométrie, `ScanSearch` (chercher *dans* une image, ADR 0048) pour
  Recherche. `Radar`, `Spline` et `Search` disaient respectivement un balayage, une
  courbe à poignées et une recherche textuelle — trois choses que le projet ne fait pas.

## Vérifié contre le vrai serveur

Navigateur piloté, backend et frontend réels.

| Contrôle | Relevé |
|---|---|
| Rangée au repos, 1300 px | une ligne, 1024/1196 px |
| Survol de « Détection » | 40 → 138 px, les voisins reculent, une ligne |
| Lancement | pilules « Lancer » → « Suspendre » + « Annuler », anneau monté |
| Annulation | retour à « Lancer », anneau démonté |
| Chiffres sans analyse | cinq « — », largeur 491 px, hauteur de barre inchangée (57 px) |
| Bouton grisé | accent conservé, cause en infobulle |

**Le cycle complet a fini par être vérifié**, une fois le créneau serveur libre — il
était d'abord occupé par une analyse suspendue, ce qui a justement fait découvrir le
« 0 / 0 images » de la file d'attente :

| État | Relevé |
|---|---|
| En cours | anneau vert 15 % → 43 %, « 330 / 817 images · 7.5 img/s (serveur) », chiffres réels (12 suivis, 158 ms) |
| Suspendue | anneau **warning** `#ffa42b`, « suspendue à 320 / 817 images », boutons Reprendre + Annuler, cause en infobulle |
| Reprise | retour au vert et à « Analyse en cours », Suspendre + Annuler |
| Annulée | anneau démonté, retour à « Lancer », chiffres revenus aux tirets |

Plus : « Lancer » à `#539df5` face à l'import `#1ed760` ; survol d'une commande — aucune
expansion, aucun voisin déplacé ; survol d'un tiroir — 40 → 138 px ; ordre de la rangée
`import · commandes · anneau · réglages · outils · chiffres`, sur une seule ligne.
