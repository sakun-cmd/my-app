export function LoadingState({ label = "読み込み中" }: { label?: string }) {
  return (
    <div className="status-card" role="status">
      <span className="spinner" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="status-card error" role="alert">
      <strong>データを取得できませんでした</strong>
      <p>{message}</p>
      <small>APIとPostgreSQLの起動状態、接続設定を確認してください。</small>
    </div>
  );
}

export function EmptyState() {
  return (
    <div className="status-card">
      <strong>対象レースがありません</strong>
      <p>既存PostgreSQLのスキーマ調査とインポートを実行してください。</p>
      <code>boat-analysis inspect-source</code>
    </div>
  );
}

