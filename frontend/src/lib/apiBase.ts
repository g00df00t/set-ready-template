/* Where the API lives, for code that runs on the server.
 *
 * lib/api.ts has always carried this fallback for the browser. The two server
 * components — /confirm/[token] and /wrap/[token] — used to read
 * process.env.NEXT_PUBLIC_API_URL directly, so an unset variable would build
 * the string "undefined/api/…" and throw during render.
 *
 * That turned out not to be what broke them on Vercel Preview (the variable is
 * set there): the 500s were the Railway backend restarting after a push. Those
 * two pages fetch during render, so a down API failed the page itself rather
 * than just its data. Both pages now catch that; this fallback just keeps them
 * from reading the env var raw.
 */
export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
