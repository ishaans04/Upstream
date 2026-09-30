import axeCore from "axe-core";
import { expect } from "vitest";

/** Run axe-core on a rendered container. Colour contrast needs layout jsdom does not do. */
export async function axe(container: Element) {
  return axeCore.run(container, { rules: { "color-contrast": { enabled: false } } });
}

expect.extend({
  toHaveNoViolations(results: axeCore.AxeResults) {
    const v = results.violations;
    return {
      pass: v.length === 0,
      message: () => v.map((x) => `${x.id}: ${x.help}\n  ${x.nodes.map((n) => n.html).join("\n  ")}`).join("\n\n"),
    };
  },
});

declare module "vitest" {
  interface Assertion { toHaveNoViolations(): void }
}
