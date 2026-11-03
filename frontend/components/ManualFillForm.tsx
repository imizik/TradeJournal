"use client";

import { startTransition, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Account, api, Fill, FillWriteInput } from "@/lib/api";

type Status = "idle" | "loading" | "done" | "error";
type Mode = "create" | "edit";

const STOCK_SIDE_OPTIONS = [
  { value: "buy", label: "Buy" },
  { value: "sell", label: "Sell" },
];

const OPTION_SIDE_OPTIONS = [
  { value: "buy_to_open", label: "Buy to Open" },
  { value: "sell_to_open", label: "Sell to Open" },
  { value: "buy_to_close", label: "Buy to Close" },
  { value: "sell_to_close", label: "Sell to Close" },
];

type ManualFillFormProps = {
  accounts: Account[];
  mode?: Mode;
  initialFill?: Fill;
  successHref?: string;
  cancelHref?: string;
  onSaved?: (message: string) => void;
  onCancel?: () => void;
};

type FillFormState = {
  accountId: string;
  instrumentType: "stock" | "option";
  ticker: string;
  side: string;
  contracts: string;
  price: string;
  tradeDate: string;
  tradeTime: string;
  optionType: "call" | "put";
  strike: string;
  expiration: string;
};

function todayDateString() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function defaultFormState(accounts: Account[]): FillFormState {
  return {
    accountId: accounts[0]?.id ?? "",
    instrumentType: "stock",
    ticker: "",
    side: "buy",
    contracts: "",
    price: "",
    tradeDate: todayDateString(),
    tradeTime: "12:00",
    optionType: "call",
    strike: "",
    expiration: "",
  };
}

function stringNumber(value: number | null | undefined) {
  if (value == null) return "";
  return String(Number(value));
}

function formStateFromFill(fill: Fill): FillFormState {
  const executedAt = fill.executed_at;
  return {
    accountId: fill.account_id,
    instrumentType: fill.instrument_type as "stock" | "option",
    ticker: fill.ticker,
    side: fill.side,
    contracts: stringNumber(fill.contracts),
    price: stringNumber(fill.price),
    tradeDate: executedAt.slice(0, 10),
    tradeTime: executedAt.slice(11, 16) || "12:00",
    optionType: (fill.option_type as "call" | "put" | null) ?? "call",
    strike: stringNumber(fill.strike),
    expiration: fill.expiration ?? "",
  };
}

export default function ManualFillForm({
  accounts,
  mode = "create",
  initialFill,
  successHref,
  cancelHref,
  onSaved,
  onCancel,
}: ManualFillFormProps) {
  const router = useRouter();
  const [form, setForm] = useState<FillFormState>(
    initialFill ? formStateFromFill(initialFill) : defaultFormState(accounts),
  );
  const [status, setStatus] = useState<Status>("idle");
  const [msg, setMsg] = useState<string | null>(null);

  const busy = status === "loading";
  const sideOptions = form.instrumentType === "stock" ? STOCK_SIDE_OPTIONS : OPTION_SIDE_OPTIONS;
  const quantityLabel = form.instrumentType === "stock" ? "Quantity" : "Contracts";
  const priceLabel = form.instrumentType === "stock" ? "Price Per Share" : "Premium Per Contract";
  const title = mode === "edit" ? "Edit Fill" : "Add Manual Fill";
  const description =
    mode === "edit"
      ? "Update the stored fill and rebuild trades from the full fill history so the position reflects the corrected values."
      : "Use this for transferred positions, missing historical cost basis, or older fills that never came through email. Saving a manual fill rebuilds trades from the full fill history.";

  function update<K extends keyof FillFormState>(key: K, value: FillFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleInstrumentTypeChange(next: "stock" | "option") {
    setForm((current) => ({
      ...current,
      instrumentType: next,
      side: next === "stock" ? "buy" : "buy_to_open",
      optionType: next === "stock" ? "call" : current.optionType,
      strike: next === "stock" ? "" : current.strike,
      expiration: next === "stock" ? "" : current.expiration,
    }));
  }

  function resetForm() {
    setForm(defaultFormState(accounts));
  }

  function buildPayload(): FillWriteInput {
    const base: FillWriteInput = {
      account_id: form.accountId,
      ticker: form.ticker.trim().toUpperCase(),
      instrument_type: form.instrumentType,
      side: form.side,
      contracts: Number(form.contracts),
      price: Number(form.price),
      executed_at: `${form.tradeDate}T${form.tradeTime || "12:00"}`,
    };

    if (form.instrumentType === "option") {
      base.option_type = form.optionType;
      base.strike = Number(form.strike);
      base.expiration = form.expiration;
    }

    return base;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("loading");
    setMsg(null);

    try {
      const payload = buildPayload();
      const result =
        mode === "edit" && initialFill
          ? await api.updateFill(initialFill.id, payload)
          : await api.createFill(payload);

      const actionLabel = mode === "edit" ? "Fill updated" : "Manual fill saved";
      const anomalySuffix = result.anomalies.length
        ? ` ${result.anomalies.length} anomaly/anomalies logged.`
        : "";

      const message = `${actionLabel}. Rebuilt ${result.trades_rebuilt} trade${result.trades_rebuilt === 1 ? "" : "s"}.${anomalySuffix}`;
      setMsg(message);
      setStatus("done");
      onSaved?.(message);

      if (mode === "create") {
        resetForm();
      }

      startTransition(() => {
        if (successHref) {
          router.push(successHref);
        } else {
          router.refresh();
        }
      });
    } catch (error) {
      setMsg(`${mode === "edit" ? "Fill update" : "Manual fill"} failed: ${(error as Error).message}`);
      setStatus("error");
    } finally {
      window.setTimeout(() => setStatus("idle"), 3000);
    }
  }

  return (
    <section className="rounded-lg border bg-card">
      <h2 className="border-b px-3.5 py-2.5 text-[13.5px] font-semibold tracking-tight">
        {title}
      </h2>
      <div className="px-4 pt-4">
        <p className="text-sm text-muted-foreground">{description}</p>
        {mode === "edit" && initialFill && (
          <p className="mt-2 text-xs text-muted-foreground">
            Source ID stays fixed as <span className="font-mono text-foreground/80">{initialFill.raw_email_id}</span>.
          </p>
        )}
      </div>

      <form onSubmit={handleSubmit} className="space-y-4 p-4">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Field>
            <Label htmlFor="account">Account</Label>
            <select
              id="account"
              value={form.accountId}
              onChange={(event) => update("accountId", event.target.value)}
              className="h-10 rounded-md border bg-background px-3 text-base sm:text-sm"
              disabled={busy}
              required
            >
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </select>
          </Field>

          <Field>
            <Label htmlFor="instrument_type">Instrument</Label>
            <select
              id="instrument_type"
              value={form.instrumentType}
              onChange={(event) => handleInstrumentTypeChange(event.target.value as "stock" | "option")}
              className="h-10 rounded-md border bg-background px-3 text-base sm:text-sm"
              disabled={busy}
            >
              <option value="stock">Stock</option>
              <option value="option">Option</option>
            </select>
          </Field>

          <Field>
            <Label htmlFor="ticker">Ticker</Label>
            <input
              id="ticker"
              value={form.ticker}
              onChange={(event) => update("ticker", event.target.value.toUpperCase())}
              className="h-10 rounded-md border bg-background px-3 text-base sm:text-sm"
              placeholder="ASTS"
              disabled={busy}
              required
            />
          </Field>

          <Field>
            <Label htmlFor="side">Side</Label>
            <select
              id="side"
              value={form.side}
              onChange={(event) => update("side", event.target.value)}
              className="h-10 rounded-md border bg-background px-3 text-base sm:text-sm"
              disabled={busy}
            >
              {sideOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>

          <Field>
            <Label htmlFor="contracts">{quantityLabel}</Label>
            <input
              id="contracts"
              type="number"
              min="0.000001"
              step="0.000001"
              value={form.contracts}
              onChange={(event) => update("contracts", event.target.value)}
              className="h-10 rounded-md border bg-background px-3 text-base sm:text-sm"
              placeholder={form.instrumentType === "stock" ? "10" : "2"}
              disabled={busy}
              required
            />
          </Field>

          <Field>
            <Label htmlFor="price">{priceLabel}</Label>
            <input
              id="price"
              type="number"
              min="0.000001"
              step="0.000001"
              value={form.price}
              onChange={(event) => update("price", event.target.value)}
              className="h-10 rounded-md border bg-background px-3 text-base sm:text-sm"
              placeholder={form.instrumentType === "stock" ? "22.50" : "1.35"}
              disabled={busy}
              required
            />
          </Field>

          <Field>
            <Label htmlFor="trade_date">Trade Date</Label>
            <input
              id="trade_date"
              type="date"
              value={form.tradeDate}
              onChange={(event) => update("tradeDate", event.target.value)}
              className="h-10 rounded-md border bg-background px-3 text-base sm:text-sm"
              disabled={busy}
              required
            />
          </Field>

          <Field>
            <Label htmlFor="trade_time">Approx Time</Label>
            <input
              id="trade_time"
              type="time"
              value={form.tradeTime}
              onChange={(event) => update("tradeTime", event.target.value)}
              className="h-10 rounded-md border bg-background px-3 text-base sm:text-sm"
              disabled={busy}
            />
          </Field>
        </div>

        {form.instrumentType === "option" && (
          <div className="grid gap-4 md:grid-cols-3">
            <Field>
              <Label htmlFor="option_type">Option Type</Label>
              <select
                id="option_type"
                value={form.optionType}
                onChange={(event) => update("optionType", event.target.value as "call" | "put")}
                className="h-10 rounded-md border bg-background px-3 text-base sm:text-sm"
                disabled={busy}
              >
                <option value="call">Call</option>
                <option value="put">Put</option>
              </select>
            </Field>

            <Field>
              <Label htmlFor="strike">Strike</Label>
              <input
                id="strike"
                type="number"
                min="0.01"
                step="0.01"
                value={form.strike}
                onChange={(event) => update("strike", event.target.value)}
                className="h-10 rounded-md border bg-background px-3 text-base sm:text-sm"
                placeholder="250"
                disabled={busy}
                required={form.instrumentType === "option"}
              />
            </Field>

            <Field>
              <Label htmlFor="expiration">Expiration</Label>
              <input
                id="expiration"
                type="date"
                value={form.expiration}
                onChange={(event) => update("expiration", event.target.value)}
                className="h-10 rounded-md border bg-background px-3 text-base sm:text-sm"
                disabled={busy}
                required={form.instrumentType === "option"}
              />
            </Field>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <p className="text-xs text-muted-foreground">
            Use approximate time if you only know the date. Earlier fills should use earlier timestamps so the rebuild
            can reconstruct position history in the right order.
          </p>
          <div className="flex items-center gap-2">
            {cancelHref && (
              <a
                href={cancelHref}
                className="inline-flex min-h-11 items-center rounded-md border px-3 text-sm font-medium hover:bg-secondary sm:min-h-9"
              >
                Cancel
              </a>
            )}
            {onCancel && (
              <button
                type="button"
                onClick={onCancel}
                className="inline-flex min-h-11 items-center rounded-md border px-3 text-sm font-medium hover:bg-secondary sm:min-h-9"
              >
                Cancel
              </button>
            )}
            <button
              type="submit"
              disabled={busy || accounts.length === 0}
              className={`inline-flex min-h-11 items-center rounded-md px-3 text-sm font-medium transition-colors disabled:opacity-50 sm:min-h-9 ${mode === "edit" ? "bg-primary text-primary-foreground hover:bg-primary/90" : "border hover:bg-secondary"}`}
            >
              {status === "loading"
                ? mode === "edit"
                  ? "Saving..."
                  : "Saving..."
                : mode === "edit"
                  ? "Save Changes"
                  : "Save Manual Fill"}
            </button>
          </div>
        </div>

        {msg && (
          <p
            className={`text-sm ${
              status === "error"
                ? "text-red-400"
                : status === "done"
                  ? "text-foreground"
                  : "text-muted-foreground"
            }`}
          >
            {msg}
          </p>
        )}
      </form>
    </section>
  );
}

/** The Fills page header with a folded "Add manual fill": adding a fill is rare, so the history leads and the form opens on demand. */
export function AddManualFill({ accounts, children }: { accounts: Account[]; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current && !open) button.current?.focus(); // closing the form hands focus back to its button
    wasOpen.current = open;
  }, [open]);
  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>{children}</div>
        {!open && (
          <button
            ref={button}
            type="button"
            onClick={() => { setSaved(null); setOpen(true); }}
            className="inline-flex min-h-11 shrink-0 items-center rounded-md border px-3 text-sm font-medium hover:bg-secondary sm:min-h-9"
          >
            Add manual fill
          </button>
        )}
      </div>
      <p role="status" className="text-sm text-foreground empty:hidden">{!open && saved}</p>
      {open && <ManualFillForm accounts={accounts} onSaved={(message) => { setSaved(message); setOpen(false); }} onCancel={() => setOpen(false)} />}
    </>
  );
}

function Field({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-col gap-1.5">{children}</div>;
}

function Label({ children, htmlFor }: { children: React.ReactNode; htmlFor: string }) {
  return (
    <label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
      {children}
    </label>
  );
}
