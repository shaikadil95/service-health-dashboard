import { Badge } from "@workspace/ui/components/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"

import type { Order, OrderStatus } from "@/lib/api"
import { formatMoney } from "@/lib/catalog"

const LABEL: Record<OrderStatus, string> = {
  confirmed: "Confirmed",
  payment_declined: "Payment declined",
  payment_failed: "Payment failed",
  payment_unknown: "Payment pending",
}

export function OrdersTable({ orders }: { orders: Order[] }) {
  if (orders.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">You have no orders yet.</p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Order</TableHead>
          <TableHead>Placed</TableHead>
          <TableHead>Items</TableHead>
          <TableHead className="text-right">Total</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {orders.map((order) => (
          <TableRow key={order.id}>
            <TableCell className="font-mono text-xs">{order.id}</TableCell>
            <TableCell>{new Date(order.created_at).toLocaleString()}</TableCell>
            <TableCell>
              {order.items.map((i) => `${i.quantity}× ${i.sku}`).join(", ")}
            </TableCell>
            <TableCell className="text-right">
              {formatMoney(order.total, order.currency)}
            </TableCell>
            <TableCell>
              <Badge
                variant={
                  order.status === "confirmed" ? "secondary" : "destructive"
                }
              >
                {LABEL[order.status]}
              </Badge>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
