/**
 * erdInteraction.ts — pure logic extracted from ERDiagramPanel.tsx so Node's
 * built-in test runner can import it directly (a `.tsx` file's JSX can't be
 * parsed by `--experimental-strip-types`, only plain TypeScript — the same
 * split used for chartTheme.ts). ERDiagramPanel.tsx imports and re-exports
 * everything here, so its public API is unchanged.
 *
 * Covers the three pieces of real, pure logic behind the ER diagram's
 * zoom/drag/reset interactions:
 *   1. clampZoom() / zoomAnchored() — the anchor-preserving zoom math (fixes
 *      zoom pivoting toward the top-left instead of the cursor/viewport center).
 *   2. isDragMove() — the click-vs-drag movement threshold.
 *   3. hasLayoutOverrides() — the "Reset layout" button's enabled predicate.
 */

/** Clamp a zoom factor to the diagram's supported range (0.15x-3x). */
export function clampZoom(z: number): number {
  return Math.min(3, Math.max(0.15, z))
}

/**
 * Zoom by `factor`, anchored at (anchorX, anchorY) in container-relative
 * screen pixels, so whatever content sits under that point stays under it —
 * rather than pivoting at the SVG transform's local (0,0) origin (the
 * content's top-left corner), which is what caused zoom to visibly drift
 * toward the top-left before this fix. `zOld`/`panOld` are the CURRENT zoom
 * and pan; the returned zoom is clamped via clampZoom.
 */
export function zoomAnchored(
  zOld: number,
  panOld: { x: number; y: number },
  factor: number,
  anchorX: number,
  anchorY: number,
): { zoom: number; pan: { x: number; y: number } } {
  const zNew = clampZoom(zOld * factor)
  const ratio = zNew / zOld
  return {
    zoom: zNew,
    pan: {
      x: anchorX - ratio * (anchorX - panOld.x),
      y: anchorY - ratio * (anchorY - panOld.y),
    },
  }
}

/**
 * Movement-threshold classifier distinguishing a click from a drag: a pointer
 * that has moved more than `threshold` screen pixels on either axis from its
 * pointerdown position counts as a drag (suppressing the click-to-select).
 */
export function isDragMove(dxScreen: number, dyScreen: number, threshold = 3): boolean {
  return Math.abs(dxScreen) > threshold || Math.abs(dyScreen) > threshold
}

/**
 * Whether the "Reset layout" control should be enabled — true once at least
 * one card has a session-only manual drag override recorded.
 */
export function hasLayoutOverrides(overrides: Record<string, { x: number; y: number }>): boolean {
  return Object.keys(overrides).length > 0
}
