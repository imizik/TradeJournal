import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Instrument_Sans } from "next/font/google";
import "./globals.css";
import { Nav } from "@/components/Nav";
import GmailStatusBanner from "@/components/GmailStatusBanner";
import AssistantSession from "@/components/AssistantSession";
import AccessProvider from "@/components/AccessProvider";
import { currentAccess, lockSignInNeeded } from "@/lib/accessServer";
import { PRIVATE_ACCESS } from "@/lib/accessTypes";
import { ChartSessionProvider } from "@/lib/chartSession";
import AppMain from "@/components/AppMain";
import LockSignInNotice from "@/components/LockSignInNotice";

// Session identity and permissions are evaluated per request in both profiles.
export const dynamic = "force-dynamic";

// The app's type is the Copilot desk's: Instrument Sans for text, IBM Plex Mono for numbers (globals.css).
const sans = Instrument_Sans({ subsets: ["latin"], variable: "--font-sans" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Trade Journal",
  description: "Trade and fill tracking",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon-192.png", apple: "/apple-touch-icon.png" },
  // Added to the home screen, it opens without browser chrome.
  appleWebApp: { capable: true, title: "Trade Journal", statusBarStyle: "black-translucent" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // cover + the safe-area padding below keeps content clear of the notch and
  // the home indicator when it runs full screen.
  viewportFit: "cover",
  themeColor: "#0e0e10",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const access = await currentAccess();
  const owner = access?.owner ?? false;
  const signInNeeded = await lockSignInNeeded();
  return (
    <html lang="en" className="dark">
      <body className={`${sans.variable} ${mono.variable} font-sans antialiased`} suppressHydrationWarning>
        <AccessProvider access={access ?? { ...PRIVATE_ACCESS, owner: false, enabled: true }}><div className="flex min-h-screen flex-col pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] md:flex-row">
          {access && <Nav owner={owner} journal={owner || !!access.grants.journal_read} />}
          <ChartSessionProvider><AppMain banner={owner ? <>{signInNeeded && <LockSignInNotice />}<GmailStatusBanner /></> : access ? <AssistantSession /> : null}>{children}</AppMain></ChartSessionProvider>
        </div></AccessProvider>
      </body>
    </html>
  );
}
