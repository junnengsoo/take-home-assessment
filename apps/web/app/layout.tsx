import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "Lead Intake",
  description: "Attorney lead intake workspace"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
