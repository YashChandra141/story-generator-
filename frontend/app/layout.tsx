import type { Metadata } from "next";
import { Plus_Jakarta_Sans, Literata } from "next/font/google";
import "./globals.css";

const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-ui",
});

const literata = Literata({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-literata",
});

export const metadata: Metadata = {
  title: "Word by Word",
  description:
    "Stories made only of words your child can already read, for young readers aged 5-10.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${jakarta.variable} ${literata.variable} h-full antialiased`}>
      <body className="min-h-full bg-[#f3f4fb] text-[#22263a]">{children}</body>
    </html>
  );
}