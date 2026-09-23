import type { Metadata } from "next";

import { AppHeader } from "@/components/AppHeader";
import "./globals.css";

export const metadata: Metadata = {
  title: "展示インサイト",
  description: "ボートレース展示データの統計分析・比較ツール",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ja">
      <body>
        <AppHeader />
        <main>{children}</main>
        <footer>
          <p>
            本サービスの分析は統計的な参考情報です。レース結果や利益を保証するものではありません。
          </p>
          <p>20歳未満の方は舟券を購入できません。無理のない範囲でお楽しみください。</p>
        </footer>
      </body>
    </html>
  );
}
