// Fork of .ds-sync/lib/css.mjs — repo-local override (see .ds-sync/package-build.mjs's
// loadLib(): a `.design-sync/overrides/<name>.mjs` of the same name replaces the
// bundled module wholesale). Re-exports everything from the bundled lib unchanged,
// then overrides rewriteBundleFontFaces (the one bundled-css postprocessing hook
// package-build.mjs actually calls) to also strip/annotate Tailwind v4 internals
// that the claude.ai/design token classifier can't categorize — see
// annotateUnclassifiableTokens below. Needed every re-sync: cfg.cssEntry appends the
// *whole* compiled app CSS verbatim, so these always reappear after a rebuild.
export * from '../../.ds-sync/lib/css.mjs';
import { rewriteBundleFontFaces as bundledRewriteBundleFontFaces } from '../../.ds-sync/lib/css.mjs';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

// Properties with no color/spacing/radius/etc. shape for the classifier to
// infer — mark each intentionally uncategorized at its one canonical
// declaration site (first match only, so re-running this is idempotent-safe
// even though `next build` always regenerates a fresh, unmarked bundle).
const KIND_OTHER_PROPS = [
  '--animate-spin',
  '--animate-pulse',
  '--default-transition-duration',
  '--default-transition-timing-function',
];

export function annotateUnclassifiableTokens(css) {
  let out = css;

  // --tw-space-y-reverse is already zeroed once globally by Tailwind's
  // preflight reset (`*,::backdrop,:after,:before{...}`); the per-utility
  // redeclaration inside every `:where(.space-y-*)` rule is redundant and is
  // what the classifier flags as "not registered as a design-system token"
  // (compound utility selectors aren't a token-scope it recognizes). Drop the
  // redeclaration and register the value once under :root instead.
  let strippedSpaceYReverse = false;
  out = out.replace(/(:where\(\.space-y-[^{]*\)\{)--tw-space-y-reverse:0;/g, (_m, sel) => {
    strippedSpaceYReverse = true;
    return sel;
  });
  if (strippedSpaceYReverse) out = `:root{--tw-space-y-reverse:0}` + out;

  // --tw-border-style is registered via @property (its real declaration site;
  // the universal-reset and .border-dashed usages are just consumers).
  out = out.replace(/(@property --tw-border-style\{[^}]*\})/, '$1/* @kind other */');

  // The remaining four are plain theme vars declared once in the :root,:host
  // block — annotate that single declaration.
  for (const prop of KIND_OTHER_PROPS) {
    const esc = prop.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    out = out.replace(new RegExp(`(${esc}:[^;}]+)`), '$1/* @kind other */');
  }
  return out;
}

export function rewriteBundleFontFaces(opts) {
  bundledRewriteBundleFontFaces(opts);
  const p = opts.bundleCss ?? join(opts.out, '_ds_bundle.css');
  if (!existsSync(p)) return;
  const css = readFileSync(p, 'utf8');
  const next = annotateUnclassifiableTokens(css);
  if (next !== css) writeFileSync(p, next);
}
