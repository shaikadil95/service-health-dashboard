import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CircleCheck, CircleX, LogOut, Store } from "lucide-react"

import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import { Skeleton } from "@workspace/ui/components/skeleton"

import { OrderForm } from "@/components/order-form"
import { OrdersTable } from "@/components/orders-table"
import { ThemeToggle } from "@/components/theme-toggle"
import {
  fetchOrders,
  fetchProfile,
  placeOrder,
  SessionExpiredError,
  type Order,
} from "@/lib/api"
import { formatMoney } from "@/lib/catalog"

// Envoy Gateway's OIDC logout path: clears the session cookies and ends the Keycloak session.
export const LOGOUT_PATH = "/oauth2/logout"

export function App() {
  const queryClient = useQueryClient()
  // The profile first: the user service creates it on first sign-in, before the first order.
  const profile = useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => fetchProfile(signal),
  })
  const orders = useQuery({
    queryKey: ["orders"],
    queryFn: ({ signal }) => fetchOrders(signal),
    enabled: profile.isSuccess,
  })
  const order = useMutation({
    mutationFn: placeOrder,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["orders"] }),
  })

  const expired = [profile.error, orders.error, order.error].some(
    (e) => e instanceof SessionExpiredError
  )

  return (
    <div className="mx-auto flex min-h-svh max-w-4xl flex-col gap-6 p-4 sm:p-6">
      <header className="flex flex-wrap items-center gap-3">
        <Store aria-hidden="true" className="size-6" />
        <div className="mr-auto">
          <h1 className="text-xl font-semibold">Service Health Shop</h1>
          <p className="text-sm text-muted-foreground">
            {profile.data
              ? `Signed in as ${profile.data.name}`
              : "Demo customer page"}
          </p>
        </div>
        <ThemeToggle />
        <Button variant="outline" asChild>
          <a href={LOGOUT_PATH}>
            <LogOut aria-hidden="true" />
            Sign out
          </a>
        </Button>
      </header>

      {expired && (
        <Alert variant="destructive" role="alert">
          <AlertTitle>Your session has expired</AlertTitle>
          <AlertDescription>
            <Button className="mt-2" onClick={() => window.location.reload()}>
              Sign in again
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {profile.isError && !expired && (
        <Alert variant="destructive" role="alert">
          <AlertTitle>Your profile could not be loaded</AlertTitle>
          <AlertDescription>{profile.error.message}</AlertDescription>
        </Alert>
      )}

      {order.data && <OrderResult order={order.data} />}
      {order.isError && !expired && (
        <Alert variant="destructive" role="alert">
          <CircleX aria-hidden="true" />
          <AlertTitle>The order failed</AlertTitle>
          <AlertDescription>{order.error.message}</AlertDescription>
        </Alert>
      )}

      <OrderForm
        onSubmit={(items) => order.mutate(items)}
        pending={order.isPending || !profile.isSuccess}
      />

      <Card>
        <CardHeader>
          <CardTitle>Your orders</CardTitle>
        </CardHeader>
        <CardContent>
          {orders.isPending ? (
            <Skeleton className="h-24 w-full" />
          ) : (
            <OrdersTable orders={orders.data ?? []} />
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function OrderResult({ order }: { order: Order }) {
  const ok = order.status === "confirmed"
  return (
    <Alert variant={ok ? "default" : "destructive"} role="status">
      {ok ? <CircleCheck aria-hidden="true" /> : <CircleX aria-hidden="true" />}
      <AlertTitle>
        {ok ? "Thank you for your order" : "Payment was declined"}
      </AlertTitle>
      <AlertDescription>
        Order {order.id} · {formatMoney(order.total, order.currency)}
      </AlertDescription>
    </Alert>
  )
}
