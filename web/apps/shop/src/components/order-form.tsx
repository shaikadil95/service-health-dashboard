import { useState } from "react"
import { Minus, Plus, ShoppingCart } from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"

import type { OrderItem } from "@/lib/api"
import { CATALOG, formatMoney } from "@/lib/catalog"

const MAX_QUANTITY = 100

export function OrderForm({
  onSubmit,
  pending,
}: {
  onSubmit: (items: OrderItem[]) => void
  pending: boolean
}) {
  const [quantities, setQuantities] = useState<Record<string, number>>({})
  const items: OrderItem[] = CATALOG.filter(
    (p) => (quantities[p.sku] ?? 0) > 0
  ).map((p) => ({
    sku: p.sku,
    quantity: quantities[p.sku],
    unit_price: p.unitPrice,
  }))
  const total = items.reduce(
    (sum, i) => sum + Number(i.unit_price) * i.quantity,
    0
  )
  const set = (sku: string, value: number) =>
    setQuantities((q) => ({
      ...q,
      [sku]: Math.max(
        0,
        Math.min(MAX_QUANTITY, Number.isNaN(value) ? 0 : value)
      ),
    }))

  return (
    <Card>
      <CardHeader>
        <CardTitle>Products</CardTitle>
        <CardDescription>
          Choose quantities and place your order.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {CATALOG.map((product) => {
          const id = `qty-${product.sku}`
          const quantity = quantities[product.sku] ?? 0
          return (
            <div key={product.sku} className="flex items-center gap-3">
              <div className="mr-auto">
                <Label htmlFor={id}>{product.name}</Label>
                <p className="text-sm text-muted-foreground">
                  {product.description} · {formatMoney(product.unitPrice)}
                </p>
              </div>
              <Button
                variant="outline"
                size="icon"
                aria-label={`One less ${product.name}`}
                onClick={() => set(product.sku, quantity - 1)}
                disabled={quantity === 0}
              >
                <Minus aria-hidden="true" />
              </Button>
              <Input
                id={id}
                type="number"
                inputMode="numeric"
                min={0}
                max={MAX_QUANTITY}
                className="w-16 text-center"
                value={quantity}
                onChange={(e) => set(product.sku, e.target.valueAsNumber)}
              />
              <Button
                variant="outline"
                size="icon"
                aria-label={`One more ${product.name}`}
                onClick={() => set(product.sku, quantity + 1)}
              >
                <Plus aria-hidden="true" />
              </Button>
            </div>
          )
        })}
      </CardContent>
      <CardFooter className="flex items-center justify-between gap-3">
        <span className="font-medium" aria-live="polite">
          Total {formatMoney(total)}
        </span>
        <Button
          disabled={items.length === 0 || pending}
          onClick={() => {
            onSubmit(items)
            setQuantities({})
          }}
        >
          <ShoppingCart aria-hidden="true" />
          {pending ? "Placing order…" : "Place order"}
        </Button>
      </CardFooter>
    </Card>
  )
}
