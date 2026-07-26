/**
 * X/Twitter reads its own `twitter:image` and does not fall back to the Open
 * Graph one when a `twitter:card` is declared, so the same drawing is exported
 * under the name that convention expects. One source, two routes.
 */
export { alt, size, contentType, default } from './opengraph-image'
