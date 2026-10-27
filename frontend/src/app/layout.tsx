import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import TermsGate from "@/components/TermsGate";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  // metadataBase makes the generated social-card URLs absolute. Without it,
  // og:image is emitted as a relative path and every scraper — iMessage, Slack,
  // WhatsApp — silently drops it and falls back to whatever image it can find
  // on the page.
  metadataBase: new URL("https://set-ready-set.com"),
  title: "SET>READY",
  description:
    "Build the shoot day once. Every crew member gets their own call time, and you can see who has confirmed before the morning of.",
  openGraph: {
    // The card image already carries the brand and the promise ("Plan the day.
    // Tell the crew. Know they got it."), so this line does the other half of
    // the job: the specifics. Repeating the tagline here wasted it.
    //
    // No "SET>READY —" prefix. iMessage strips anything matching og:site_name
    // from the front of this, and every client shows the domain underneath, so
    // the brand is already covered twice over.
    title: "Crew, schedule, location — and a call sheet everyone confirms",
    description:
      "Build the shoot day once. Every crew member gets their own call time, and you can see who has confirmed before the morning of.",
    url: "https://set-ready-set.com",
    siteName: "SET>READY",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Crew, schedule, location — and a call sheet everyone confirms",
    description:
      "Build the shoot day once. Every crew member gets their own call time, and you can see who has confirmed before the morning of.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: `(function(){var t=localStorage.getItem('theme')||'dark';document.documentElement.setAttribute('data-theme',t);})();` }} />
      </head>
      <body className="min-h-full flex flex-col" suppressHydrationWarning>
        <a href="#main-content" className="skip-link">Skip to main content</a>
        <main id="main-content" className="flex flex-col flex-1">{children}</main>
        <TermsGate />
      </body>
    </html>
  );
}
