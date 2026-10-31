import { Badge } from "@workspace/ui/components/badge"
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"

import type { Alert } from "@/lib/api"
import { formatSince } from "@/lib/format"

export function AlertsTable({ alerts }: { alerts: Alert[] }) {
  return (
    <Table>
      <TableCaption className="sr-only">Active alerts</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Severity</TableHead>
          <TableHead>Alert</TableHead>
          <TableHead>Service</TableHead>
          <TableHead>Summary</TableHead>
          <TableHead className="text-right">Firing for</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {alerts.length === 0 ? (
          <TableRow>
            <TableCell
              colSpan={5}
              className="text-center text-muted-foreground"
            >
              No active alerts
            </TableCell>
          </TableRow>
        ) : (
          alerts.map((alert) => (
            <TableRow key={`${alert.name}-${alert.service}-${alert.starts_at}`}>
              <TableCell>
                <Badge
                  variant={
                    alert.severity === "critical" ? "destructive" : "secondary"
                  }
                >
                  {alert.severity}
                </Badge>
              </TableCell>
              <TableCell className="font-medium">
                {alert.runbook_url ? (
                  <a
                    className="underline-offset-4 hover:underline"
                    href={alert.runbook_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {alert.name}
                  </a>
                ) : (
                  alert.name
                )}
              </TableCell>
              <TableCell className="capitalize">
                {alert.service ?? "–"}
              </TableCell>
              <TableCell className="max-w-md truncate whitespace-normal">
                {alert.summary ?? "–"}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatSince(alert.starts_at)}
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  )
}
