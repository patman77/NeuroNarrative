/**
 * Who built this copy, and when.
 *
 * The values are substituted by Vite at build time (see `define` in `vite.config.ts`), so they
 * cost nothing at runtime and cannot drift from the bundle they were compiled into. The
 * declarations exist because `define` replaces bare identifiers that TypeScript would otherwise
 * refuse to compile.
 */

declare const __APP_VERSION__: string;
declare const __BUILD_YEAR__: string;
declare const __BUILD_DATE__: string;

/** e.g. "0.2.0" from a tagged release, or "0.1.0-dev" from a working copy. */
export const APP_VERSION: string = __APP_VERSION__;

/** The year the bundle was built — the copyright year, so nobody has to bump it in January. */
export const BUILD_YEAR: string = __BUILD_YEAR__;

/** ISO date of the build, for telling two builds of the same version apart. */
export const BUILD_DATE: string = __BUILD_DATE__;

export const AUTHOR = "Patrick Klie";

/** True for a build that did not come from a release tag. */
export const IS_DEV_BUILD = APP_VERSION.endsWith("-dev");
