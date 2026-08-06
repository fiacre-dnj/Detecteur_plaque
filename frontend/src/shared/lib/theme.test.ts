/**
 * Le thème : défaut assumé, préférence retenue, et jamais d'exception.
 *
 * Ce que ces tests protègent avant tout : **le sombre reste le défaut**. C'est
 * l'apparence pour laquelle le système de design a été conçu, et le clair une
 * préférence explicite. Un défaut qui glisserait vers « ce que dit le système »
 * ferait démarrer en clair la moitié des postes sans que personne ne l'ait
 * demandé.
 */

import { describe, expect, it } from "bun:test";

import {
  DEFAULT_THEME,
  THEME_ATTRIBUTE,
  THEME_SWITCHING_ATTRIBUTE,
  applyTheme,
  loadTheme,
  nextTheme,
  normaliseTheme,
  saveTheme,
  switchTheme,
  themeActionLabel,
} from "./theme";

/** Stockage de test, avec un mode « lève à chaque accès ». */
function fakeStorage(initial: string | null = null, { throws = false } = {}) {
  let value = initial;
  return {
    getItem: (): string | null => {
      if (throws) throw new Error("stockage inaccessible");
      return value;
    },
    setItem: (_key: string, next: string): void => {
      if (throws) throw new Error("stockage inaccessible");
      value = next;
    },
    read: (): string | null => value,
  };
}

describe("le défaut", () => {
  it("est le thème sombre", () => {
    expect(DEFAULT_THEME).toBe("dark");
  });

  it("s'applique quand rien n'est enregistré", () => {
    expect(loadTheme(fakeStorage(null))).toBe("dark");
  });

  it("s'applique quand la valeur enregistrée n'a pas de sens", () => {
    // Une version antérieure a pu écrire autre chose ; on ne devine pas.
    expect(loadTheme(fakeStorage("sépia"))).toBe("dark");
  });

  it("s'applique quand le stockage est inaccessible", () => {
    // Navigation privée verrouillée, iframe restreint : lire `localStorage`
    // **lève**. Une interface ne doit pas rester blanche pour une couleur.
    expect(loadTheme(fakeStorage("light", { throws: true }))).toBe("dark");
    expect(loadTheme(null)).toBe("dark");
  });
});

describe("la préférence", () => {
  it("est relue telle qu'elle a été posée", () => {
    expect(loadTheme(fakeStorage("light"))).toBe("light");
    expect(loadTheme(fakeStorage("dark"))).toBe("dark");
  });

  it("est enregistrée sans lever, même si le stockage refuse", () => {
    const storage = fakeStorage(null, { throws: true });

    expect(() => saveTheme("light", storage)).not.toThrow();
    expect(() => saveTheme("light", null)).not.toThrow();
  });

  it("fait l'aller-retour", () => {
    const storage = fakeStorage();
    saveTheme("light", storage);

    expect(loadTheme(storage)).toBe("light");
  });
});

describe("normaliseTheme", () => {
  it("n'accepte que les deux thèmes existants", () => {
    expect(normaliseTheme("light")).toBe("light");
    expect(normaliseTheme("dark")).toBe("dark");
    expect(normaliseTheme(null)).toBe("dark");
    expect(normaliseTheme(42)).toBe("dark");
  });
});

describe("nextTheme", () => {
  it("bascule d'un thème à l'autre", () => {
    expect(nextTheme("dark")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
  });

  it("revient à son point de départ en deux clics", () => {
    expect(nextTheme(nextTheme("dark"))).toBe("dark");
  });
});

describe("applyTheme", () => {
  it("pose l'attribut lu par le CSS **et** `color-scheme`", () => {
    // `color-scheme` fait suivre ce que la page ne peint pas : barres de
    // défilement, menus natifs, champs de formulaire. Sans lui, un thème clair
    // garde des déroulants noirs.
    const attributes = new Map<string, string>();
    const root = {
      setAttribute: (name: string, value: string) => void attributes.set(name, value),
      style: { colorScheme: "" },
    };

    applyTheme("light", root);

    expect(attributes.get(THEME_ATTRIBUTE)).toBe("light");
    expect(root.style.colorScheme).toBe("light");
  });
});

describe("switchTheme", () => {
  it("coupe les transitions le temps de la bascule, puis les rend", () => {
    // Le défaut observé : les éléments qui animent leurs couleurs restaient sur
    // l'ancienne teinte après le changement, alors qu'un élément neuf prenait la
    // bonne — donc une entête à moitié dans l'ancien thème.
    const attributes = new Map<string, string>();
    const root = {
      setAttribute: (name: string, value: string) => void attributes.set(name, value),
      removeAttribute: (name: string) => void attributes.delete(name),
      style: { colorScheme: "" },
    };
    let afterPaint: (() => void) | null = null;

    switchTheme("light", root, (run) => {
      afterPaint = run;
    });

    // Pendant la bascule : marque posée, thème déjà appliqué.
    expect(attributes.has(THEME_SWITCHING_ATTRIBUTE)).toBe(true);
    expect(attributes.get(THEME_ATTRIBUTE)).toBe("light");

    // Après la peinture : la coupure est levée. Elle ne doit pas être
    // définitive, sinon plus aucune transition ne fonctionnerait de la session.
    (afterPaint as unknown as () => void)();

    expect(attributes.has(THEME_SWITCHING_ATTRIBUTE)).toBe(false);
  });
});

describe("le libellé du bouton", () => {
  it("annonce l'action, pas l'état", () => {
    // Un bouton dit ce qu'il fera : « passer en clair » sur une interface
    // sombre. Afficher l'état courant n'apprendrait rien à qui regarde l'écran.
    expect(themeActionLabel("dark")).toBe("Passer en thème clair");
    expect(themeActionLabel("light")).toBe("Passer en thème sombre");
  });
});
