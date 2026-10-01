# 展示インサイト

既存のボートレース展示データをPostgreSQLへ安全に取り込み、6艇比較、説明可能な参考順位、過去結果による時系列評価を提供する個人向けローカルWebアプリです。

> 本アプリの表示は統計的な参考情報です。レース結果や利益を保証するものではありません。20歳未満の方は舟券を購入できません。

## 構成

- Web: Next.js / TypeScript
- API・分析: FastAPI / SQLAlchemy / Python
- 保存先: PostgreSQL
- マイグレーション: Alembic
- ローカル実行: Docker Compose

既存DBは読み取り専用の `SOURCE_DATABASE_URL`、アプリDBは `DATABASE_URL` として完全に分離します。

## セットアップ

1. `.env.example` を `.env` へコピーします。
2. `SOURCE_DATABASE_URL` に、既存PostgreSQLの読み取り専用ロールを設定します。
3. `docker compose up --build` を実行します。
4. Web UIを `http://localhost:3000`、API仕様を `http://localhost:8000/docs` で開きます。

アプリDBだけを起動し、APIとWebをホスト側で開発することもできます。

```powershell
docker compose up -d db
cd apps\api
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\uvicorn boat_analysis.main:app --reload
```

別のターミナルで:

```powershell
cd apps\web
npm install
npm run dev
```

## 既存PostgreSQLの調査と移行

既存DBには、書き込み権限を持たない専用ロールを使用してください。

```sql
CREATE ROLE boat_source_reader LOGIN PASSWORD 'replace-this';
GRANT CONNECT ON DATABASE source_database TO boat_source_reader;
GRANT USAGE ON SCHEMA public TO boat_source_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO boat_source_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO boat_source_reader;
```

スキーマ調査:

```powershell
cd apps\api
.\.venv\Scripts\boat-analysis inspect-source > ..\..\source-schema-report.json
```

この環境の実データには `config\source-mapping.json` の `boatrace_brd_v1`
アダプターを使用します。`brd_b2`、`brd_b3`、`brd_c2`、`brd_c3`、
`brd_c4`、`brd_k3` の複合キーと固定小数点表現を正規化し、`brd_c3`
の部品列は部品交換行へ展開します。`brd_c4` は場別仕様に応じて半周または
一周、回り足、直線タイムをNULL許容で保存します。別形式のDBでは
`config\source-mapping.example.json` を基にマッピングを作成してください。

展示・気象テーブルに実取得時刻がないため、`boatrace_brd_v1` は発走予定時刻を
保守的なデータ締切として保存し、来歴へ
`observed_at_strategy=scheduled_at` を記録します。

```powershell
.\.venv\Scripts\boat-analysis import-source
```

取込は業務キーによるUPSERTで冪等に実行されます。元DBには読み取り専用トランザクション、30秒のstatement timeout、5秒のlock timeoutを設定します。

## 主なAPI

| API | 用途 |
|---|---|
| `GET /health` | DB接続確認 |
| `GET /api/imports/source-schema` | 元DBのテーブル・列・推定件数・統計を確認 |
| `GET /api/races` | 開催日・場でレースを検索 |
| `GET /api/races/{id}` | 展示データを含む6艇比較 |
| `GET /api/analysis/races/{id}` | 説明可能な相対スコアと寄与内訳 |
| `GET /api/analysis/races/{id}/two-boat-flow` | 2艇判定フロー、AP、買い目候補、合成オッズ |
| `GET /api/evaluations/summary` | 日付順の過去評価 |
| `GET /api/evaluations/two-boat-flow` | 2艇判定フローの最大90日バックテスト |
| `GET /api/reports/daily.xlsx?race_date=YYYY-MM-DD` | 1レース1行の日次Excelを生成・ダウンロード |
| `POST /api/imports/live-refresh` | 当日データを取込み、締切5分前の公式展示・Boatcast周回、3分前の公式単勝、15分後の公式結果を確認 |

## スコアの扱い

`exhibition-v2` は、展示タイム、展示ST、進入安定性に、場ごとの周回展示
（半周または一周、回り足、直線）を加えた同一レース内相対スコアです。
提供されない項目は場単位で配点対象から外し、利用可能な指標を100点へ正規化
します。周回展示が個別艇だけ欠ける場合は観測済み艇の平均点を用いて信頼度を
下げ、比較可能な値が2種類未満の指標は配点対象外とします。主要展示の欠損と
負の展示STは警告・減点対象です。表示値は勝率ではありません。

展示タイム・周回展示（半周/一周、回り足、直線）の艇間比較は、場ごとの
「スタンダード版補正値」（`services/standard_correction.py`）を加算した
補正後タイムで行います。1号艇は常に補正0.00、2〜6号艇には主にマイナス
補正（タイムを速くする方向の下駄）が場・艇番ごとに設定されており、生タイム
では1号艇や内枠寄りの艇が速く見えても、補正後は外枠艇が逆転することが
あります（「隠れ一番時計」）。表示上の`raw_value`は生の観測値のまま変えず、
補正が適用された艇には`explanation`に補正秒数を注記します。江戸川(03)は
周回展示が存在しないため対象外、住之江(12)・尼崎(13)・徳山(18)は直線タイム
自体が存在しないため補正は常に0.00です。

評価では発走予定時刻以前に観測された展示だけを使い、1着艇の参考順位、Top-1/2/3、平均順位を算出します。1号艇固定を単純基準として併記し、対象件数が100未満の場合は小標本警告を表示します。

2艇判定フローでは、隣接する外側艇が展示タイムで0.10秒以上速い組を
最大差で1組選びます。APは展示タイムまたは一周タイムの1・2番時計です。
展示タイム・一周タイムの艇間比較（0.10秒差の判定、AP、外の外艇との比較、
イン評価、買い目の相手選び）はすべてスタンダード版補正後のタイムで行います。
生タイムでは0.10秒に満たない差でも、補正後に条件を満たす（またはその逆）
ことがあります。APIの`exhibition_time`・`lap_time`は生値のままで、補正後の値は
`exhibition_time_corrected`・`lap_time_corrected`で返します。
コース平均ST順位・平均STはレース日以前に値が収録された最新履歴だけを使い、
必要な順位が欠けるレースは「データ不足」として判定対象から除外します。
履歴の収録開始は2026-07-07で、それ以前は検証できません。2026-07-07〜07-08は
初期スナップショットの作成時点を確認できないため、独立した検証期間として
扱いません。また、履歴値の大半は期間中固定であるため、スナップショット日付と
レース日との差が0日でも、値が当日に更新されたことを意味しません。
コース3連率は進入数10以上の場合だけ追加根拠に使用します。バックテストでは
ST履歴充足数、買い目生成数、イン判定数、オッズ収録数を各指標の標本数として
表示し、評価不能な指標を0%とは表示しません。合成オッズは均等払戻換算、
回収率は各候補100円の均等買いです。オッズ更新時刻が空欄の行は締切オッズ
として最優先し、空欄がない場合は最新更新時刻の行を使います。
いずれも比較材料として表示しますが、
収益優位が確認できない限り自動的な「Go」判定は行いません。

## LIVE結果取得

- 展示・気象・出走情報は読み取り専用の元PostgreSQLから取得します。
- 展示タイム、チルト、展示進入、展示STはBOAT RACE公式サイトの
  `beforeinfo` ページを締切予定時刻の5分前から確認し、公式値を優先します。
- LIVEの周回展示は `race.boatcast.jp` の `bc_oriten` テキストを展示と同じ
  締切予定時刻の5分前から確認します。桐生の半周ラップ、場ごとの直線タイム
  有無をヘッダーから判定し、江戸川は提供対象外として取得しません。
- 当日レースでは元PostgreSQLの `brd_c4` を取り込まず、画面・分析とも
  Boatcast出典の周回値だけを使用します。過去レースは既存評価との連続性のため
  保存済み `brd_c4` を参照します。
- 公式展示が未掲載の場合は1分以上空けて再確認します。1回12レースまで、
  各リクエストを1秒以上空けます。通信タイムアウト時はその周期の取得を中断し、
  次周期へ延期します。
- Boatcast周回が未掲載（HTTP 403/404を含む）の場合も1分以上空けて再確認し、
  1回12レースまで、各リクエストを1秒以上空けます。
- LIVEの単勝オッズはBOAT RACE公式サイトの `oddstf` ページを締切予定時刻の
  3分前から確認し、6艇分を一度だけ保存します。人気順位は単勝オッズの低い順で、
  同一オッズは艇番順です。当日レースでは元DBへフォールバックせず、公式取得前
  または未取得の場合は未取得として表示します。
- 公式単勝オッズが未掲載の場合は1分以上空けて再確認します。1回12レースまで、
  各リクエストを1秒以上空け、通信タイムアウト時はその周期の取得を中断します。
- 当日の確定着順はSQLを使用せず、BOAT RACE公式サイトのレース結果ページを
  締切予定時刻の15分後から確認します。
- APIは60秒周期で対象時刻を確認します。公式結果が未掲載の場合は5分以上空けて
  再確認し、1回12レースまで、各リクエストを0.5秒以上空けます。
- 公式確定後は再取得せず、業務キーによるUPSERTで冪等に保存します。取得元DBへは
  一切書き込みません。
- 取得件数、未掲載件数、エラー件数は `POST /api/imports/live-refresh` の
  `official_exhibitions`、`boatcast_laps`、`official_win_odds`、
  `official_results` で確認できます。

## 日次Excel

- 毎日0:30（JST）以降、前日分の全レースで公式結果と3連単払戻が揃い次第、
  `exports/boat-race-daily-YYYYMMDD.xlsx` を自動生成します。アプリ停止中に時刻を
  過ぎた場合も、次回起動時に未生成の前日分を作成します。
- LIVE画面の「前日Excel」からダウンロードできます。任意の日は
  `http://localhost:8000/api/reports/daily.xlsx?race_date=YYYY-MM-DD` を開きます。
- 「レース結果」シートは1レース1行です。開催情報、気象、6艇すべての選手・機材・
  展示・周回・単勝人気・能力指標・部品交換・着順・本番進入/ST、2艇判定の買い目、
  公式3連単結果・払戻・人気、的中買い目、各100円時の投資額・払戻額・収支を含みます。
- 買い目は保存済みの公式展示・Boatcast周回・締切単勝オッズを優先して日次再計算します。
  公式値がない過去レースだけ元DB値を使用します。買い目1点を各100円とし、
  公式3連単結果と一致した場合だけ「的中」とします。投票や購入実績を表すものでは
  なく、的中・利益を保証しません。
- 「バックテスト比較」シートは、同じレースをバックテストと同じ元DB値（`brd_c3`展示、
  `brd_c4`一周、`brd_k3`着順、`odds_view`オッズ）だけで判定した結果（BT列）と、
  公式値優先の判定（実列）を1レース1行で並べます。展示・周回の艇別差（実-BT）、
  判定・買い目・着順・的中・収支の一致、相違要因（展示タイム差、周回タイム差、
  着順データ差、オッズ・払戻差）を示し、相違があるレースは黄色で表示します。
  「比較集計」シートに一致率、回収率、相違要因別の件数をまとめます。

## データ利用上の注意

- 既存データの取得元、取得方法、利用許諾、再配布可否を確認してください。確認できないデータは利用・公開しないでください。
- BOAT RACE公式サイト上のコンテンツは著作権等で保護されています。結果取得は
  ローカルでの統計照合に限定し、再配布しません。サイトポリシーとrobots.txtを
  定期的に再確認し、仕様変更、取得拒否、許諾上の問題があれば停止してください。
- 大量アクセスは禁止されています。上記の遅延・再試行間隔・件数上限を緩和しないでください。
- ローカル利用を前提とし、元データを第三者へ再配布しないでください。

参考: [BOAT RACEオフィシャルウェブサイト サイトポリシー](https://www.boatrace.jp/owpc/pc/extra/policy.html)

## テスト

```powershell
cd apps\api
.\.venv\Scripts\pytest
.\.venv\Scripts\ruff check .

cd ..\web
npm test
npm run lint
npm run build
```

DB統合テストと実データ契約テストは、PostgreSQLおよび `SOURCE_DATABASE_URL` を設定した環境で実行します。SQLite代替は使用しません。
