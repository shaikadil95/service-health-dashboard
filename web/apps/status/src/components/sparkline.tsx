import { Area, AreaChart, ReferenceLine, YAxis } from "recharts"

import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@workspace/ui/components/chart"

import type { Point } from "@/lib/api"

type SparklineProps = {
  label: string
  points: Point[]
  format: (value: number | null) => string
  threshold?: number
  color?: string
}

export function Sparkline({
  label,
  points,
  format,
  threshold,
  color = "var(--chart-2)",
}: SparklineProps) {
  const config = { v: { label, color } } satisfies ChartConfig
  const data = points.map((p) => ({ t: p.t * 1000, v: p.v }))
  return (
    <ChartContainer
      config={config}
      className="aspect-auto h-10 w-full"
      role="img"
      aria-label={`${label}, last 30 minutes`}
    >
      <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
        <YAxis
          hide
          domain={[0, (max: number) => Math.max(max, threshold ?? 0)]}
        />
        {threshold !== undefined && (
          <ReferenceLine
            y={threshold}
            stroke="var(--destructive)"
            strokeDasharray="3 3"
            ifOverflow="extendDomain"
          />
        )}
        <ChartTooltip
          cursor={false}
          content={
            <ChartTooltipContent
              indicator="line"
              labelFormatter={(_, payload) => {
                const t = payload?.[0]?.payload?.t as number | undefined
                return t ? new Date(t).toLocaleTimeString("en-GB") : ""
              }}
              formatter={(value) => format(value as number | null)}
            />
          }
        />
        <Area
          dataKey="v"
          type="monotone"
          stroke="var(--color-v)"
          fill="var(--color-v)"
          fillOpacity={0.2}
          strokeWidth={1.5}
          isAnimationActive={false}
          connectNulls
        />
      </AreaChart>
    </ChartContainer>
  )
}
