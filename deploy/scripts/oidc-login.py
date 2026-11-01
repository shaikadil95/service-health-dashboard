#!/usr/bin/env python3
"""Scripted browser login through Envoy Gateway's OIDC filter and Keycloak (`make verify`, Phase 6).

Requests the first URL like a browser without a session, follows the redirect to Keycloak's login
page, submits the login form, follows the callback back to the gateway (which sets its session
cookies) and then requests every URL with that session. Prints one line per URL:

    <status> <url> <first 200 characters of the body>

Usage:
    OIDC_USERNAME=sre OIDC_PASSWORD=... oidc-login.py --cacert ca.pem URL [URL ...] \
        [--post URL JSON ...]

--post sends JSON like the web apps' fetch() calls (Content-Type: application/json,
X-Requested-With: fetch) after the GETs, with the same session. --cookie-jar saves the session
cookies in Netscape format for `curl -b FILE -c FILE`.

*.localtest.me is resolved to --address (default 127.0.0.1), independent of the host's DNS
resolver, so the check also works where DNS rebinding protection filters localtest.me.
Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import html
import http.cookiejar
import os
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

FORM = re.compile(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', re.S)


def pin_localtest(address: str) -> None:
    original = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        if isinstance(host, str) and (host == "localtest.me" or host.endswith(".localtest.me")):
            host = address
        return original(host, *args, **kwargs)

    socket.getaddrinfo = getaddrinfo


def fetch(
    opener, url: str, data: bytes | None = None, headers: dict | None = None
) -> tuple[int, str, str]:
    """(status, final URL, body) following redirects; HTTP errors are results, not exceptions."""
    if not url.startswith("https://"):
        raise ValueError(f"only https:// URLs: {url}")
    request = urllib.request.Request(  # noqa: S310 (scheme checked above)
        url, data=data, headers={"User-Agent": "oidc-login/1", **(headers or {})}
    )
    try:
        with opener.open(request, timeout=20) as response:
            return response.status, response.geturl(), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.geturl(), err.read().decode("utf-8", "replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--cacert", required=True)
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--post", nargs=2, action="append", default=[], metavar=("URL", "JSON"))
    parser.add_argument("--cookie-jar", help="save the session cookies here (Netscape format)")
    args = parser.parse_args()
    username = os.environ["OIDC_USERNAME"]
    password = os.environ["OIDC_PASSWORD"]

    pin_localtest(args.address)
    context = ssl.create_default_context(cafile=args.cacert)
    jar = http.cookiejar.MozillaCookieJar(args.cookie_jar) if args.cookie_jar else None
    jar = jar if jar is not None else http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPCookieProcessor(jar),
    )

    status, url, body = fetch(opener, args.urls[0])
    match = FORM.search(body)
    if not match or ("/protocol/openid-connect/" not in url and "/login-actions/" not in url):
        print(f"no login page: {status} {url}", file=sys.stderr)
        return 2
    action = html.unescape(match.group(1))
    form = urllib.parse.urlencode({"username": username, "password": password, "credentialId": ""})
    status, url, body = fetch(opener, action, form.encode())
    if FORM.search(body):
        error = re.search(r'id="input-error[^"]*"[^>]*>\s*([^<]+)', body)
        print(f"login failed: {error.group(1).strip() if error else status}", file=sys.stderr)
        return 3

    for i, target in enumerate(args.urls):
        if i > 0:
            status, url, body = fetch(opener, target)
        snippet = " ".join(body.split())[:200]
        print(f"{status} {target} {snippet}")
    for target, payload in args.post:
        headers = {"Content-Type": "application/json", "X-Requested-With": "fetch"}
        status, url, body = fetch(opener, target, payload.encode(), headers)
        snippet = " ".join(body.split())[:200]
        print(f"{status} POST {target} {snippet}")
    if args.cookie_jar:
        jar.save(ignore_discard=True, ignore_expires=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
