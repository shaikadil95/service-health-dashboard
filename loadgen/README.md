# Load generator (k6)

Steady, low background traffic so that dashboards and alerts always have data. [`scripts/orders.js`](scripts/orders.js)
creates orders for the active users u-1001…u-1003 through the edge (`http://api.localtest.me`), reads them back and
sometimes reads the user: about 4.6 requests per second at the gateway with the default `RATE=2` iterations per second.
It uses k6's `constant-arrival-rate` executor (open model), so a slow or failing service shows up as latency and errors
instead of less traffic. `402` (payment declined) counts as a valid outcome.

In the cluster it runs as the `loadgen` Helm release (this directory is the chart; namespace `loadgen`, Pod Security
`restricted`), started by `make up`:

```bash
make load-stop     # scale to 0
make load-start    # scale to 1
```

From the host (k6 2.x):

```bash
k6 run loadgen/scripts/orders.js
BASE_URL=http://api.localtest.me:8080 RATE=5 DURATION=5m k6 run loadgen/scripts/orders.js
```
