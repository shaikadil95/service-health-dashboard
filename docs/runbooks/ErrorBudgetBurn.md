# ErrorBudgetBurn

**Severity:** critical (pages on-call) · **Fires when:** order's 5xx ratio is above 7.2 % over both the last hour and the
last 5 minutes, for 2 minutes. 7.2 % is 14.4 times the error budget of the SLO "99.5 % of order requests succeed over
30 days" (budget 0.5 %): at this speed 2 % of the monthly budget is used per hour, and the whole budget in about two days
([SRE Workbook, multi-window multi-burn-rate alerts](https://sre.google/workbook/alerting-on-slos/)).

## Impact

Same as [HighErrorRate](HighErrorRate.md) on order, but measured against the SLO: it fires on a sustained, significant
problem and ignores short spikes (the 1-hour window) while still resetting quickly when it is fixed (the 5-minute window).

## Triage and remediation

Follow [HighErrorRate](HighErrorRate.md) for order. Then decide with the team whether the remaining budget allows further
risky changes this month:

```promql
service:http_server_errors:ratio_rate1h{service="order"} / 0.005    # current burn rate
```
