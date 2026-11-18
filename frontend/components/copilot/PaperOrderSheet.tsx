"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import ModeMark from "./ModeMark";

/**
 * Robinhood-style "Review order" sheet for a paper order: the Paper home opens it from a position card (``CloseRow``'s
 * sheet). Presentational: the order's controls and swipe come in as children. A row with nothing to say (no buying power
 * after for a close) is left out.
 */

export type PaperOrderReview = {
  title: string;
  side: "buy" | "sell";
  orderType: "market" | "limit";
  quantity: number;
  unit: "contracts" | "shares";
  price: number | null;
  quotedAt: number | null;
  estimated: number | null;
  buyingPowerAfter: number | null;
  warnings?: string[];
};

const formatUsd = (value: number): string => {
  const abs = Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${value < 0 ? "−" : ""}$${abs}`;
};

const formatPrice = (value: number): string => {
  const subDollar = Math.abs(value) < 1 && value !== 0;
  return `$${value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: subDollar ? 4 : 2,
  })}`;
};

const formatTimeET = (epochSeconds: number): string =>
  `${new Date(epochSeconds * 1000).toLocaleTimeString("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    minute: "2-digit",
  })} ET`;

const formatQuantity = (quantity: number, unit: PaperOrderReview["unit"]): string => {
  if (!Number.isFinite(quantity)) return "—";
  const label = quantity === 1 ? unit.replace(/s$/, "") : unit;
  return `${quantity.toLocaleString("en-US")} ${label}`;
};

const formatPriceRow = (review: PaperOrderReview): string | null => {
  if (review.price == null || !Number.isFinite(review.price)) return null;
  const formatted = formatPrice(review.price);
  if (review.orderType === "limit") return `Limit ${formatted}`;
  const quoteSide = review.side === "buy" ? "ask" : "bid";
  const time =
    review.quotedAt != null && Number.isFinite(review.quotedAt)
      ? ` at ${formatTimeET(review.quotedAt)}`
      : "";
  return `Market · ${quoteSide} ${formatted}${time}`;
};

export default function PaperOrderSheet({
  review,
  children,
  onCancel,
  className,
}: {
  review: PaperOrderReview;
  children?: ReactNode;
  onCancel(): void;
  className?: string;
}) {
  const priceText = formatPriceRow(review);
  const estimated =
    review.estimated != null && Number.isFinite(review.estimated)
      ? review.estimated
      : null;
  const buyingPowerAfter =
    review.buyingPowerAfter != null && Number.isFinite(review.buyingPowerAfter)
      ? review.buyingPowerAfter
      : null;
  const shortBuyingPower = buyingPowerAfter != null && buyingPowerAfter < 0;
  const warnings = (review.warnings ?? []).filter((w) => w.trim().length > 0);

  return (
    <section
      aria-label="Review order"
      data-testid="paper-order-sheet"
      className={cn(
        "w-full rounded-t-xl border-x border-t border-dashed border-violet-400/40 bg-card px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 shadow-2xl sm:rounded-xl sm:border-b",
        className,
      )}
    >
      <div
        aria-hidden
        className="mx-auto mb-3 h-1 w-10 rounded-full bg-muted-foreground/40 sm:hidden"
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">Review order</h2>
        <ModeMark mode="paper" />
      </div>

      <p
        data-testid="paper-order-sheet-title"
        className="mt-2 text-sm font-medium text-foreground"
      >
        {review.title}
      </p>

      <dl className="mt-3 divide-y divide-border/60 border-y border-border/60 text-xs tabular-nums">
        <div className="flex items-baseline justify-between gap-4 py-2">
          <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Order type
          </dt>
          <dd className="text-right text-foreground">
            {review.orderType === "market" ? "Market" : "Limit"}
          </dd>
        </div>

        <div className="flex items-baseline justify-between gap-4 py-2">
          <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Quantity
          </dt>
          <dd className="text-right text-foreground">
            {formatQuantity(review.quantity, review.unit)}
          </dd>
        </div>

        <div className="flex items-baseline justify-between gap-4 py-2">
          <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Price
          </dt>
          <dd
            className={cn(
              "text-right",
              priceText ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {priceText ?? "—"}
          </dd>
        </div>

        <div className="flex items-baseline justify-between gap-4 py-2">
          <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {review.side === "sell" ? "Estimated credit" : "Estimated cost"}
          </dt>
          <dd
            className={cn(
              "text-right",
              estimated != null ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {estimated != null ? formatUsd(estimated) : "—"}
          </dd>
        </div>

        {review.buyingPowerAfter != null && <div className="flex items-baseline justify-between gap-4 py-2">
          <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Buying power after
          </dt>
          <dd
            className={cn(
              "text-right",
              buyingPowerAfter == null
                ? "text-muted-foreground"
                : shortBuyingPower
                  ? "text-rose-300"
                  : "text-foreground",
            )}
          >
            {buyingPowerAfter != null
              ? `${formatUsd(buyingPowerAfter)}${shortBuyingPower ? " (not enough)" : ""}`
              : "—"}
          </dd>
        </div>}
      </dl>

      {warnings.length > 0 && (
        <ul
          aria-label="Order warnings"
          data-testid="paper-order-sheet-warnings"
          className="mt-3 space-y-1 text-xs text-amber-300"
        >
          {warnings.map((warning, index) => (
            <li key={`${index}-${warning}`}>{warning}</li>
          ))}
        </ul>
      )}

      {children != null && <div className="mt-4">{children}</div>}

      <button
        type="button"
        onClick={onCancel}
        className="mt-2 inline-flex min-h-11 w-full items-center justify-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8"
      >
        Cancel
      </button>
    </section>
  );
}
