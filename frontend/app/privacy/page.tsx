import type { Metadata } from "next";

export const metadata: Metadata = { title: "Privacy · Trade Journal" };

// Linked from the Google OAuth consent screen (Branding → privacy policy).
// Keep it true to what the Gmail integration actually does.
export default function PrivacyPage() {
  return (
    <div className="max-w-2xl space-y-4 text-sm text-muted-foreground">
      <h1 className="text-2xl font-semibold text-foreground">Privacy</h1>
      <p>
        Trade Journal is a private, single-user application. It runs on its owner&apos;s own server and is reachable only
        from the owner&apos;s private Tailscale network.
      </p>
      <h2 className="pt-2 text-base font-semibold text-foreground">Google data</h2>
      <p>
        With the owner&apos;s permission, the app has read-only access to the owner&apos;s Gmail. It downloads only
        Robinhood order-execution emails and records the trade details in them: ticker, side, quantity, price, time and
        the last four digits of the account. For other messages that reach it, it reads only the sender and subject
        needed to tell them apart. It never sends, changes or deletes email.
      </p>
      <h2 className="pt-2 text-base font-semibold text-foreground">Storage and sharing</h2>
      <p>
        Trade records live in the owner&apos;s own database, and the Gmail access token stays on the owner&apos;s
        server. Nothing is sold or used for advertising. Email content is not sent to any third party; market-data
        providers the owner configures receive tickers and dates, not email.
      </p>
      <h2 className="pt-2 text-base font-semibold text-foreground">Removing access</h2>
      <p>
        Access can be revoked at any time from the Google Account security settings (third-party access → Trade
        Journal).
      </p>
    </div>
  );
}
