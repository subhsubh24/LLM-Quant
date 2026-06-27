import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, verifySessionToken } from "@/lib/auth";

/**
 * Password gate. Every route requires a valid signed session cookie except the
 * login page and the auth API. If AUTH_SECRET / APP_PASSWORD are unset, the app
 * still redirects to /login (which will show a "not configured" message) so the
 * panel is never accidentally left open.
 */

const PUBLIC_PREFIXES = ["/login", "/api/auth/"];

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // Allow the login page + auth endpoints through.
  if (PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (await verifySessionToken(token)) {
    return NextResponse.next();
  }

  // Not authenticated -> redirect to login, preserving where they were going.
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  if (pathname && pathname !== "/") url.searchParams.set("next", pathname);
  return NextResponse.redirect(url);
}

export const config = {
  // Run on everything except Next internals and static asset files.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|gif|svg|ico|webp|woff2?)$).*)",
  ],
};
