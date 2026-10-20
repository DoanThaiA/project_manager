import type { Metadata } from "next";
import { Be_Vietnam_Pro } from "next/font/google";
import { Suspense } from "react";

import { Providers } from "@/components/providers";
import { Spinner } from "@/components/ui/misc";

import "./globals.css";

const font = Be_Vietnam_Pro({
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-be-vietnam",
});

export const metadata: Metadata = {
  title: { default: "Project Manager", template: "%s · Project Manager" },
  description: "Quản lý dự án phần mềm theo Scrum/Agile",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="vi" className={font.variable}>
      <body className="min-h-dvh font-sans text-sm">
        {/* Ứng dụng chạy phía client (JWT trong localStorage); Suspense cho các hook đọc URL */}
        <Suspense fallback={<Spinner className="min-h-dvh" />}>
          <Providers>{children}</Providers>
        </Suspense>
      </body>
    </html>
  );
}
