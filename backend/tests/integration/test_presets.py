"""Les presets à travers HTTP : enregistrer, relire, mettre à l'échelle, supprimer.

Le test unitaire prouve que l'arithmétique de la mise à l'échelle est juste ; ceux-ci
prouvent que la géométrie survit à l'aller-retour en base sans perdre un nom, une
couleur ni un rattachement de zone — et que le drapeau `scaled` dit la vérité.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from httpx import AsyncClient

PRESETS_URL = "/api/v1/presets"


def _messages(payload: dict[str, Any]) -> str:
    """Concatène les messages de `errors[]` d'un Problem Details de validation."""
    return " | ".join(error["message"] for error in payload.get("errors", ()))


def _draft(**overrides: object) -> dict[str, Any]:
    """Un preset valide, que chaque test dégrade à sa façon."""
    draft: dict[str, Any] = {
        "name": "Carrefour nord",
        "description": "Deux voies, comptage entrant",
        "sourceWidth": 1280,
        "sourceHeight": 720,
        "maskOutsideZones": True,
        "lines": [
            {
                "id": "l1",
                "name": "Entrée",
                "color": "#38bdf8",
                "zoneId": "z1",
                "a": {"x": 100.0, "y": 400.0},
                "b": {"x": 1180.0, "y": 400.0},
                "positiveName": "Vers le centre",
                "negativeName": "Vers la rocade",
                "positiveRole": "entry",
                "negativeRole": "exit",
            }
        ],
        "zones": [
            {
                "id": "z1",
                "name": "Carrefour",
                "color": "#f59e0b",
                "points": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 640.0, "y": 0.0},
                    {"x": 640.0, "y": 360.0},
                ],
            }
        ],
    }
    draft.update(overrides)
    return draft


class TestEnregistrement:
    async def test_un_preset_est_cree_en_201_avec_son_identifiant(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(PRESETS_URL, json=_draft())

        assert response.status_code == 201
        assert response.json()["id"]

    async def test_l_en_tete_location_designe_la_ressource_creee(self, client: AsyncClient) -> None:
        response = await client.post(PRESETS_URL, json=_draft())

        preset_id = response.json()["id"]
        assert response.headers["Location"] == f"/api/v1/presets/{preset_id}"

    async def test_la_geometrie_survit_a_l_aller_retour_sans_rien_perdre(
        self, client: AsyncClient
    ) -> None:
        """Noms, couleurs et rattachement de zone compris.

        Un preset qui rendrait des lignes grises et anonymes obligerait à tout
        renommer, ce qui annule l'intérêt de l'avoir enregistré. Et un `zoneId`
        perdu ferait compter la ligne sur toute l'image au lieu de sa zone — un
        changement de résultat, pas de présentation.
        """
        created = await client.post(PRESETS_URL, json=_draft())
        preset_id = created.json()["id"]

        body = (await client.get(f"{PRESETS_URL}/{preset_id}")).json()

        line = body["lines"][0]
        assert line["name"] == "Entrée"
        assert line["color"] == "#38bdf8"
        assert line["zoneId"] == "z1"
        assert line["a"] == {"x": 100.0, "y": 400.0}
        # Les rôles de sens, et c'est le maillon qui manquait : ils étaient
        # acceptés à l'entrée puis jetés avant la persistance, donc tout preset
        # rechargé rendait des lignes `neutral`.
        assert line["positiveRole"] == "entry"
        assert line["negativeRole"] == "exit"
        assert line["positiveName"] == "Vers le centre"
        assert line["negativeName"] == "Vers la rocade"
        assert body["zones"][0]["points"][2] == {"x": 640.0, "y": 360.0}
        assert body["maskOutsideZones"] is True

    async def test_les_dimensions_d_origine_sont_conservees(self, client: AsyncClient) -> None:
        # Sans elles, recharger le preset sur une autre vidéo placerait les lignes
        # au mauvais endroit sans qu'aucune erreur ne le signale.
        created = await client.post(PRESETS_URL, json=_draft())

        body = created.json()
        assert (body["originalWidth"], body["originalHeight"]) == (1280, 720)

    async def test_un_nom_deja_pris_est_refuse_en_409_et_non_ecrase(
        self, client: AsyncClient
    ) -> None:
        """Perdre une géométrie qu'on croyait garder ne se découvre qu'en la rechargeant.

        C'est pourquoi le conflit est explicite : à ce moment-là, le tracé d'origine
        n'existe plus nulle part.
        """
        await client.post(PRESETS_URL, json=_draft())

        response = await client.post(PRESETS_URL, json=_draft(name="Carrefour nord"))

        assert response.status_code == 409
        assert response.json()["code"] == "preset_name_taken"

    async def test_un_preset_sans_forme_est_refuse(self, client: AsyncClient) -> None:
        # Un preset vide dans la liste est un piège : on le charge en croyant
        # récupérer une géométrie et on obtient un canvas nu.
        response = await client.post(PRESETS_URL, json=_draft(lines=[], zones=[]))

        assert response.status_code == 422
        assert "au moins une ligne ou une zone" in _messages(response.json())

    async def test_une_ligne_rattachee_a_une_zone_absente_est_refusee(
        self, client: AsyncClient
    ) -> None:
        """Refusé ici plutôt qu'au lancement de l'analyse.

        Le preset serait rechargeable mais irrecevable par l'analyse, qui refuse un
        `zoneId` inconnu : l'utilisateur verrait un 422 en cliquant sur « Lancer »,
        longtemps après l'erreur réelle.
        """
        response = await client.post(PRESETS_URL, json=_draft(zones=[]))

        assert response.status_code == 422
        assert "zone absente" in _messages(response.json())

    async def test_des_dimensions_nulles_sont_refusees(self, client: AsyncClient) -> None:
        response = await client.post(PRESETS_URL, json=_draft(sourceWidth=0))

        assert response.status_code == 422

    async def test_le_serveur_ne_laisse_pas_choisir_l_identifiant(
        self, client: AsyncClient
    ) -> None:
        # Accepter un `id` fourni permettrait d'écraser un preset existant par un
        # POST, ce qui n'est pas ce que POST veut dire.
        first = await client.post(PRESETS_URL, json=_draft(name="A"))
        second = await client.post(PRESETS_URL, json=_draft(name="B"))

        assert first.json()["id"] != second.json()["id"]


class TestMiseALEchelle:
    async def test_sans_dimensions_demandees_la_geometrie_est_celle_d_origine(
        self, client: AsyncClient
    ) -> None:
        created = await client.post(PRESETS_URL, json=_draft())
        preset_id = created.json()["id"]

        body = (await client.get(f"{PRESETS_URL}/{preset_id}")).json()

        assert body["scaled"] is False
        assert body["lines"][0]["a"] == {"x": 100.0, "y": 400.0}

    async def test_une_autre_resolution_convertit_et_le_dit(self, client: AsyncClient) -> None:
        """`scaled` est ce qui sépare une fonctionnalité utile d'un piège.

        La conversion silencieuse serait pire que pas de conversion : une géométrie
        qui bouge sans prévenir se lit comme un bug de l'application.
        """
        created = await client.post(PRESETS_URL, json=_draft())
        preset_id = created.json()["id"]

        body = (await client.get(f"{PRESETS_URL}/{preset_id}?width=640&height=360")).json()

        assert body["scaled"] is True
        assert body["lines"][0]["a"] == {"x": 50.0, "y": 200.0}
        assert body["zones"][0]["points"][1] == {"x": 320.0, "y": 0.0}

    async def test_la_meme_resolution_ne_declenche_aucune_conversion(
        self, client: AsyncClient
    ) -> None:
        created = await client.post(PRESETS_URL, json=_draft())
        preset_id = created.json()["id"]

        body = (await client.get(f"{PRESETS_URL}/{preset_id}?width=1280&height=720")).json()

        assert body["scaled"] is False
        assert body["lines"][0]["b"] == {"x": 1180.0, "y": 400.0}

    async def test_les_dimensions_d_origine_restent_lisibles_apres_conversion(
        self, client: AsyncClient
    ) -> None:
        # L'interface doit pouvoir dire d'où vient le preset : « tracé pour du
        # 1280×720, adapté à votre 640×360 » est une phrase que l'utilisateur
        # comprend, contrairement à des coordonnées qui ont changé toutes seules.
        created = await client.post(PRESETS_URL, json=_draft())
        preset_id = created.json()["id"]

        body = (await client.get(f"{PRESETS_URL}/{preset_id}?width=640&height=360")).json()

        assert (body["originalWidth"], body["originalHeight"]) == (1280, 720)
        assert (body["sourceWidth"], body["sourceHeight"]) == (640, 360)

    async def test_un_changement_de_rapport_d_aspect_deforme_chaque_axe_a_part(
        self, client: AsyncClient
    ) -> None:
        """Deux facteurs indépendants, jamais une homothétie.

        L'image passée d'un 16/9 à un 4/3 est elle-même déformée : la géométrie doit
        subir la même déformation, sinon les lignes ne recouvrent plus la route.
        """
        created = await client.post(PRESETS_URL, json=_draft())
        preset_id = created.json()["id"]

        body = (await client.get(f"{PRESETS_URL}/{preset_id}?width=640&height=480")).json()

        assert body["lines"][0]["a"]["x"] == 50.0
        assert body["lines"][0]["a"]["y"] == 400.0 * (480 / 720)

    async def test_une_seule_dimension_fournie_ne_convertit_rien(self, client: AsyncClient) -> None:
        # Convertir sur un seul axe déformerait la géométrie d'un facteur inventé.
        created = await client.post(PRESETS_URL, json=_draft())
        preset_id = created.json()["id"]

        body = (await client.get(f"{PRESETS_URL}/{preset_id}?width=640")).json()

        assert body["scaled"] is False
        assert body["lines"][0]["a"] == {"x": 100.0, "y": 400.0}


class TestRolesDeSens:
    """Les rôles de sens survivent au preset, et c'est ce qui le rend rechargeable.

    Depuis ADR 0021 le rôle **est** le libellé affiché et range chaque passage en
    entrée ou en sortie. Un preset qui les perd rend des lignes que le serveur compte
    encore correctement mais que plus rien n'affiche : « Passages en entrée » à « — »,
    comparatifs de Statistique à `null`, registre sans heure d'entrée ni de sortie,
    chronologie retombée sur « sens ↑ ». Aucune erreur nulle part — la forme de panne
    que ce dépôt paie le plus cher.
    """

    async def test_les_roles_survivent_a_une_mise_a_l_echelle(self, client: AsyncClient) -> None:
        """Un rôle décrit le trait, pas sa position : convertir ne le touche pas.

        C'est le parcours réel — on recharge un preset **parce qu'on change de
        vidéo**, donc presque toujours avec conversion.
        """
        created = await client.post(PRESETS_URL, json=_draft())
        preset_id = created.json()["id"]

        body = (await client.get(f"{PRESETS_URL}/{preset_id}?width=640&height=360")).json()

        assert body["scaled"] is True
        line = body["lines"][0]
        assert line["a"] == {"x": 50.0, "y": 200.0}
        assert line["positiveRole"] == "entry"
        assert line["negativeRole"] == "exit"
        assert line["positiveName"] == "Vers le centre"

    async def test_la_liste_porte_les_roles_elle_aussi(self, client: AsyncClient) -> None:
        # La liste et la lecture unitaire passent par le même sérialiseur : deux
        # chemins finiraient par diverger, et l'un des deux montrerait des rôles
        # que l'autre tait.
        await client.post(PRESETS_URL, json=_draft())

        body = (await client.get(PRESETS_URL)).json()

        assert body["items"][0]["lines"][0]["positiveRole"] == "entry"

    async def test_un_remplacement_ecrit_les_nouveaux_roles(self, client: AsyncClient) -> None:
        """`PUT` passe par un autre chemin d'écriture que `POST` — il l'oubliait aussi."""
        created = await client.post(PRESETS_URL, json=_draft())
        preset_id = created.json()["id"]
        inverted = _draft()["lines"][0] | {"positiveRole": "exit", "negativeRole": "entry"}

        await client.put(
            f"{PRESETS_URL}/{preset_id}",
            json=_draft(lines=[inverted]),
        )
        body = (await client.get(f"{PRESETS_URL}/{preset_id}")).json()

        assert body["lines"][0]["positiveRole"] == "exit"
        assert body["lines"][0]["negativeRole"] == "entry"

    async def test_un_preset_sans_role_reste_neutre_et_ne_devine_rien(
        self, client: AsyncClient
    ) -> None:
        """Le cas des presets enregistrés avant ce correctif.

        Ils se rechargent — les refuser viderait la liste de l'utilisateur — et
        rendent `neutral`, jamais une devinette : deviner « entrée » fausserait un
        bilan que personne n'a demandé, alors que `neutral` fait afficher le repère
        « à préciser » du panneau de géométrie.
        """
        bare = {
            key: value
            for key, value in _draft()["lines"][0].items()
            if key not in ("positiveRole", "negativeRole", "positiveName", "negativeName")
        } | {"zoneId": None}

        created = await client.post(PRESETS_URL, json=_draft(lines=[bare], zones=[]))
        body = (await client.get(f"{PRESETS_URL}/{created.json()['id']}")).json()

        line = body["lines"][0]
        assert line["positiveRole"] == "neutral"
        assert line["negativeRole"] == "neutral"
        assert line["positiveName"] == ""


class TestListe:
    async def test_la_liste_rend_les_presets_enregistres(self, client: AsyncClient) -> None:
        await client.post(PRESETS_URL, json=_draft(name="A"))
        await client.post(PRESETS_URL, json=_draft(name="B"))

        body = (await client.get(PRESETS_URL)).json()

        assert body["total"] == 2
        assert {item["name"] for item in body["items"]} == {"A", "B"}

    async def test_la_liste_est_paginee(self, client: AsyncClient) -> None:
        for index in range(3):
            await client.post(PRESETS_URL, json=_draft(name=f"P{index}"))

        body = (await client.get(f"{PRESETS_URL}?limit=2&offset=0")).json()

        assert len(body["items"]) == 2
        assert body["total"] == 3

    async def test_la_liste_rend_les_coordonnees_d_origine(self, client: AsyncClient) -> None:
        # La liste sert à **choisir**, pas à charger : elle ne connaît pas la
        # résolution de la vidéo courante, et inventer une conversion ici serait
        # une conversion vers rien.
        await client.post(PRESETS_URL, json=_draft())

        body = (await client.get(PRESETS_URL)).json()

        assert body["items"][0]["scaled"] is False
        assert body["items"][0]["lines"][0]["a"] == {"x": 100.0, "y": 400.0}

    async def test_une_liste_vide_n_est_pas_une_erreur(self, client: AsyncClient) -> None:
        body = (await client.get(PRESETS_URL)).json()

        assert body["items"] == []
        assert body["total"] == 0


class TestModification:
    async def test_un_preset_est_remplace_integralement(self, client: AsyncClient) -> None:
        created = await client.post(PRESETS_URL, json=_draft())
        preset_id = created.json()["id"]

        # Sans zone, la ligne doit être détachée : le validateur refuse un `zoneId`
        # qui ne correspond à aucune zone du preset.
        detached = _draft()["lines"][0] | {"zoneId": None}
        response = await client.put(
            f"{PRESETS_URL}/{preset_id}",
            json=_draft(name="Carrefour sud", zones=[], lines=[detached]),
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Carrefour sud"
        assert response.json()["zones"] == []

    async def test_renommer_un_preset_en_son_propre_nom_n_est_pas_un_conflit(
        self, client: AsyncClient
    ) -> None:
        # Refuser ce cas rendrait toute modification impossible sans changer de nom.
        created = await client.post(PRESETS_URL, json=_draft())
        preset_id = created.json()["id"]

        response = await client.put(f"{PRESETS_URL}/{preset_id}", json=_draft())

        assert response.status_code == 200

    async def test_prendre_le_nom_d_un_autre_preset_est_refuse_en_409(
        self, client: AsyncClient
    ) -> None:
        await client.post(PRESETS_URL, json=_draft(name="Déjà pris"))
        created = await client.post(PRESETS_URL, json=_draft(name="Le mien"))
        preset_id = created.json()["id"]

        response = await client.put(f"{PRESETS_URL}/{preset_id}", json=_draft(name="Déjà pris"))

        assert response.status_code == 409

    async def test_modifier_un_preset_inconnu_rend_un_404(self, client: AsyncClient) -> None:
        response = await client.put(f"{PRESETS_URL}/inexistant", json=_draft())

        assert response.status_code == 404
        assert response.json()["code"] == "preset_not_found"


class TestSuppression:
    async def test_une_suppression_rend_204_puis_404(self, client: AsyncClient) -> None:
        created = await client.post(PRESETS_URL, json=_draft())
        preset_id = created.json()["id"]

        assert (await client.delete(f"{PRESETS_URL}/{preset_id}")).status_code == 204
        assert (await client.get(f"{PRESETS_URL}/{preset_id}")).status_code == 404

    async def test_supprimer_deux_fois_rend_un_404_explicite(self, client: AsyncClient) -> None:
        created = await client.post(PRESETS_URL, json=_draft())
        preset_id = created.json()["id"]
        await client.delete(f"{PRESETS_URL}/{preset_id}")

        response = await client.delete(f"{PRESETS_URL}/{preset_id}")

        assert response.status_code == 404

    async def test_le_nom_est_libere_par_la_suppression(self, client: AsyncClient) -> None:
        # Sinon un nom serait perdu pour toujours, et l'utilisateur devrait inventer
        # « Carrefour nord 2 » sans comprendre pourquoi.
        created = await client.post(PRESETS_URL, json=_draft())
        await client.delete(f"{PRESETS_URL}/{created.json()['id']}")

        response = await client.post(PRESETS_URL, json=_draft())

        assert response.status_code == 201


class TestPresetInconnu:
    async def test_un_preset_inconnu_rend_un_404_en_problem_details(
        self, client: AsyncClient
    ) -> None:
        response = await client.get(f"{PRESETS_URL}/inexistant")

        assert response.status_code == 404
        assert response.json()["code"] == "preset_not_found"
        assert "inexistant" in response.json()["detail"]


class TestReglesDeLigne:
    """Sens interdit et voie réservée survivent au preset, comme les rôles.

    Même forme de panne, et elle a déjà été payée une fois : `LineSchema` accepte le
    champ, le client l'envoie, et une conversion oubliée le laisse tomber en
    silence. Le preset s'enregistre sans erreur, se recharge sans erreur, et rend une
    voie de bus qui ne signale plus rien — sans qu'aucun compteur soit faux.
    """

    async def test_un_sens_interdit_se_recharge_tel_quel(self, client: AsyncClient) -> None:
        draft = _draft()
        draft["lines"][0]["negativeRole"] = "forbidden"
        created = await client.post(PRESETS_URL, json=draft)

        line = (await client.get(f"{PRESETS_URL}/{created.json()['id']}")).json()["lines"][0]

        assert line["negativeRole"] == "forbidden"

    async def test_une_voie_reservee_se_recharge_telle_quelle(self, client: AsyncClient) -> None:
        draft = _draft()
        draft["lines"][0]["allowedClassIds"] = [5, 7]
        created = await client.post(PRESETS_URL, json=draft)

        line = (await client.get(f"{PRESETS_URL}/{created.json()['id']}")).json()["lines"][0]

        assert line["allowedClassIds"] == [5, 7]

    async def test_une_voie_reservee_survit_a_une_mise_a_l_echelle(
        self, client: AsyncClient
    ) -> None:
        """Une règle décrit le trait, pas sa position — comme un rôle.

        C'est le parcours réel : on recharge un preset **parce qu'on change de
        vidéo**, donc presque toujours avec conversion.
        """
        draft = _draft()
        draft["lines"][0]["negativeRole"] = "forbidden"
        draft["lines"][0]["allowedClassIds"] = [5]
        created = await client.post(PRESETS_URL, json=draft)
        preset_id = created.json()["id"]

        body = (await client.get(f"{PRESETS_URL}/{preset_id}?width=640&height=360")).json()

        assert body["scaled"] is True
        line = body["lines"][0]
        assert line["a"] == {"x": 50.0, "y": 200.0}
        assert line["negativeRole"] == "forbidden"
        assert line["allowedClassIds"] == [5]

    async def test_une_ligne_sans_voie_reservee_rend_null_et_jamais_une_liste_vide(
        self, client: AsyncClient
    ) -> None:
        """`null` dit « rien n'est restreint », `[]` dirait « personne ne passe ».

        Se tromper de repli fabriquerait un écran d'alertes entièrement faux sur une
        géométrie qui n'a jamais rien restreint.
        """
        created = await client.post(PRESETS_URL, json=_draft())

        line = (await client.get(f"{PRESETS_URL}/{created.json()['id']}")).json()["lines"][0]

        assert line["allowedClassIds"] is None
