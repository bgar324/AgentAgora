import type { Metadata } from "next"
import { Inter } from "next/font/google"
import type { ReactNode } from "react"

import "@/styles/globals.css"

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
})

export const metadata: Metadata = {
  title: "Agent Agora Study",
  description: "Perspective-centered multi-agent hypothesis generation",
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`h-full antialiased font-sans ${inter.variable}`}>
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  )
}
