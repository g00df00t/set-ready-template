import { NextResponse, type NextRequest } from "next/server";

/* Next 16's rename of middleware.ts.
 *
 * One job: send someone who already has an account to their own shoot instead of
 * the sales page. A producer typing set-ready-set.com was being pitched a product
 * they already use, down to a "Request an invite" button.
 *
 * Done as a REWRITE at the edge rather than a check inside the page, because the
 * alternative flashes. A client-side session check has to render something first,
 * and rendering the marketing page for 200ms before replacing it feels worse than
 * the problem being fixed. Rewriting means "/" serves the welcome page directly:
 * no flash, no redirect, and the URL the producer typed is the URL they keep.
 *
 * Signed-out visitors are untouched, so "/" stays the statically prerendered
 * marketing page for every visitor search engines care about.
 *
 * ⚠️ A cookie is not a session — it can be expired or revoked, and this
 * deliberately does not verify it (that would mean a network round trip on every
 * request to the front page). /welcome revalidates properly and sends anyone
 * holding a stale cookie to the login page.
 */

/** Supabase SSR writes `sb-<project-ref>-auth-token`, and chunks large ones into
 *  `…auth-token.0`, `…auth-token.1`. Match the stem so chunked sessions count. */
const AUTH_COOKIE = /^sb-.+-auth-token(\.\d+)?$/;

export function proxy(request: NextRequest) {
  if (request.nextUrl.pathname === "/") {
    const signedIn = request.cookies.getAll().some((c) => AUTH_COOKIE.test(c.name));
    if (signedIn) {
      return NextResponse.rewrite(new URL("/welcome", request.url));
    }
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.svg).*)"],
};
