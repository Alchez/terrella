/** Outbound links the SITE ITSELF owns, as opposed to the third-party links each page inlines.
 *
 *  The distinction is why this file exists for what is currently one string: a link to maplibre.org
 *  can be written wherever it is needed, because nothing we do can invalidate it. A link to our own
 *  repository is different — rename the project or move the org and every copy is wrong at once,
 *  silently, because a 404 on an external link is invisible from inside a build. One export, one
 *  place to change, and a test that fails if a page inlines the URL instead.
 */

/** The public source repository, linked from the gallery masthead and the globe's chrome. */
export const REPO_URL = "https://github.com/Alchez/terrella";
