import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Nav } from "@/components/Nav";
import GmailStatusBanner from "@/components/GmailStatusBanner";

const inter = Inter({ subsets: ["latin"] });

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
  themeColor: "#12151c",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={inter.className} suppressHydrationWarning>
        <div className="flex min-h-screen flex-col pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] md:flex-row">
          <Nav />
          <main className="min-w-0 flex-1 p-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] md:p-6 md:pb-6">
            <GmailStatusBanner />
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
