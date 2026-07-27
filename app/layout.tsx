import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Public Health Repo Auditor",
  description:
    "Automated reproducibility and repository-quality checks for public-health research.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
