export type Product = {
  sku: string
  name: string
  description: string
  unitPrice: string
}

// The demo catalog (the services have no product database).
export const CATALOG: Product[] = [
  {
    sku: "book",
    name: "Site Reliability Engineering",
    description: "Paperback, the classic",
    unitPrice: "12.50",
  },
  {
    sku: "pen",
    name: "On-call pen",
    description: "Writes upside down at 3 a.m.",
    unitPrice: "1.99",
  },
  {
    sku: "laptop-sleeve",
    name: "Laptop sleeve",
    description: "Fits 14 inch",
    unitPrice: "24.00",
  },
]

export const formatMoney = (amount: string | number, currency = "EUR") =>
  new Intl.NumberFormat("en-IE", { style: "currency", currency }).format(
    Number(amount)
  )
