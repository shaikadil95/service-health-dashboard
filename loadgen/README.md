# Load generator (k6)

Steady, low background traffic so that dashboards and alerts always have data. [`scripts/orders.js`](scripts/orders.js)
creates orders for the active users u-1001…u-1003 through the edge (`https://api.localtest.me`), reads them back and
sometimes reads the user: about 4.6 requests per second at the gateway with the default `RATE=2` iterations per second.
It uses k6's `constant-arrival-rate` executor (open model), so a slow or failing service shows up as latency and errors
instead of less traffic. `402` (payment declined) counts as a valid outcome.

**Authentication (Phase 6).** The API needs an OAuth 2.0 access token. k6 is a machine client, so it uses the **client
credentials** grant with its own test client `loadgen` in Keycloak's `customers` realm (realm roles `orders:read` and
`orders:write`, client role `users:read` of `user-service`, audience `shop-api`). Each VU caches its token and renews it
30 seconds before it expires. The password grant stays disabled for every client. The client secret comes from the
Secret `loadgen/loadgen-client` (`deploy/scripts/identity-secrets.sh`); TLS is verified with the mkcert CA
(`SSL_CERT_FILE`).

In the cluster it runs as the `loadgen` Helm release (this directory is the chart; namespace `loadgen`, Pod Security
`restricted`), started by `make up`:

```bash
make load-stop     # scale to 0
make load-start    # scale to 1
```

From the host (k6 2.x; the mkcert CA must be trusted, `mkcert -install`, or set `SSL_CERT_FILE="$(mkcert -CAROOT)/rootCA.pem"`):

```bash
CLIENT_SECRET=$(kubectl --context kind-shd -n loadgen get secret loadgen-client -o jsonpath='{.data.client-secret}' | base64 -d) \
  k6 run loadgen/scripts/orders.js
```
