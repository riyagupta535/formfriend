import "./globals.css";
import type { Metadata } from "next";
import { Lexend } from "next/font/google";
// Lexend was designed to reduce visual stress and improve reading fluency; clean and easy to read.
const body = Lexend({ subsets: ["latin"], variable: "--font-body", display: "swap" });
export const metadata: Metadata = { title: "forma", description: "Forms, one friendly question at a time." };
export default function Layout({ children }: { children: React.ReactNode }) {
 return <html lang="en" className={body.variable}><body>{children}</body></html>;
}
