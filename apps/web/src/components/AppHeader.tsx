import Link from "next/link";

export function AppHeader() {
  return (
    <header className="site-header">
      <Link href="/" className="brand">
        <span className="brand-mark" aria-hidden="true">
          B
        </span>
        <span>
          <strong>展示インサイト</strong>
          <small>BOAT RACE EXHIBITION ANALYSIS</small>
        </span>
      </Link>
      <nav aria-label="メインナビゲーション">
        <Link href="/">レース分析</Link>
        <Link href="/live">LIVE</Link>
        <Link href="/lab">買い方LAB</Link>
        <Link href="/evaluation">評価</Link>
        <Link href="/data-quality">データ品質</Link>
      </nav>
    </header>
  );
}
