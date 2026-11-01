import { describe, expect, it } from "vitest"

import { formatMs, formatPercent, formatRps, formatSince } from "@/lib/format"

describe("format", () => {
  it("formats metrics and missing values", () => {
    expect(formatRps(2.5749)).toBe("2.6 req/s")
    expect(formatPercent(0.032)).toBe("3.2%")
    expect(formatMs(812.4)).toBe("812 ms")
    expect(formatRps(null)).toBe("–")
  })

  it("formats durations", () => {
    const now = new Date("2026-10-31T22:00:00Z")
    expect(formatSince("2026-10-31T21:59:30Z", now)).toBe("30s")
    expect(formatSince("2026-10-31T21:55:00Z", now)).toBe("5m")
    expect(formatSince("2026-10-31T20:30:00Z", now)).toBe("1h 30m")
  })
})
