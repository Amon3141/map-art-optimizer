# 本番アプリ実装ガイド

本番 UI（`/`）とデバッグ UI（`/debug`）は同一デプロイで共存する。このファイルは本番向けの UX 決定・実装方針を記録する。

---

## 本番環境の UI ゲート（`VITE_APP_ENV`）

フロントは `VITE_APP_ENV`（`development` | `production`）で公開範囲を切り替える。判定は [`frontend/src/lib/appEnv.ts`](../frontend/src/lib/appEnv.ts) に集約し、各コンポーネントは `isProduction` / `isDevelopment` を import する。

### 環境変数の解決

| `VITE_APP_ENV` | 結果 |
|----------------|------|
| `production` | production |
| `development` | development |
| 未設定 or 不正 | `vite dev` → development、`vite build` → production |

公開デプロイでは `vite build` のみで production になる（明示は任意）。ローカルで本番 UI を試すときは `VITE_APP_ENV=production npm run dev`。

### production で非表示・到達不可にするもの

| 対象 | 挙動 | 実装 |
|------|------|------|
| スケッチのテキストツール | 入力モード切替から「テキスト」を除外。手書き・ペン（タッチ端末ではペンも非表示）のみ | [`SketchModal.tsx`](../frontend/src/components/SketchModal.tsx) の `inputModeOptions` |
| 距離の目安（km） | サイドバーの数値入力 UI を非表示 | [`Sidebar.tsx`](../frontend/src/components/Sidebar.tsx) |
| デバッグページへのリンク | ホームサイドバー下部の「デバッグページへ →」を非表示 | [`Sidebar.tsx`](../frontend/src/components/Sidebar.tsx) |
| `/debug` ルート | URL 直打ち・ブックマークでも `/` へ `replace` リダイレクト。`DebugPage` はマウントしない | [`App.tsx`](../frontend/src/App.tsx) |

**補足（距離の目安）:** UI は隠すが、`HomePage` の `targetKm` state は残る（API 未連携のため本番挙動への影響なし）。将来 API に載せる場合は development 側 UI から送る想定。

**補足（テキスト）:** production では `inputMode` の初期値 `freehand` のみ。テキスト用の opentype 生成・デバウンス処理はバンドルに含まれるが、ユーザーからは選択不可。

### production でも利用できるもの（本番 UI）

- ホーム `/`（スケッチ入力・速度プリセット・向き固定トグル・最適化実行）
- 手書き・ペン（デスクトップ等）によるスケッチ
- 確定形プレビュー（もとの形 / 巡回順）
- 地図・ルートオーバーレイ・`RouteInfoPanel`（距離・候補・トレース再生）
- `POST /api/optimize`（道路取得〜最適化の一括）

### バックエンド（本番ゲートの対象外）

`/api/debug/*` は環境変数で無効化しない（同一デプロイ・下記「実装原則」のとおり）。フロントの `/debug` 遮断のみでデバッグ UI への導線を切る。API を直接叩くことは可能。

### development との差（要約）

| 項目 | development | production |
|------|-------------|------------|
| テキストツール | あり | なし |
| 距離の目安 UI | あり | なし |
| `/debug` リンク・ルート | あり | なし（`/` へリダイレクト） |

---

## UX 設計決定

### 角度制約 (ignore_source_rotation)
**本番デフォルト: 回転自由（ignore_source_rotation = true）**

GPS アートでは形の良さが最優先。向きに縛ると探索空間が狭まる。  
ユーザー向けには「向きを固定する」トグル（デフォルト OFF）として公開。デバッグのデフォルト（回転ペナルティあり）とは逆。

### 探索速度プリセット
生の秒数は公開せず、3段階に抽象化する。

| プリセット | ラベル | budget_s | restarts | max_iter |
|-----------|--------|----------|----------|----------|
| fast      | 速め   | 10s      | 2        | 150      |
| normal    | ふつう | 20s      | 5        | 300      |
| thorough  | じっくり | 30s   | 10       | 500      |

各プリセットは `backend/app/optimization/app_defaults.py` に定義。  
フロント側の UI メタ（ラベル・説明）は `frontend/src/lib/productionDefaults.ts` に定義。

**UI / API 省略時のデフォルト: fast（速め）**

### 走行順の可視化
結果表示時、サイドパネルのプレビュー領域を「巡回順 SVG」に切り替えるトグルを設ける。  
「もとの形」と「巡回順」をボタンで切り替え。地図上には表示しない。  
`RouteOrderPreview` コンポーネント（`frontend/src/components/RouteOrderPreview.tsx`）を使用。

### ルート情報パネル（マップ内オーバーレイ）
最適化完了後、マップ左下に `RouteInfoPanel`（`frontend/src/components/RouteInfoPanel.tsx`）を表示。  
ルートに依存する全情報をここに集約する。サイドバーには置かない。

- **ルート距離**: 選択候補の `route_length_km` を表示
- **候補切り替え**: `ranked_candidates` が 2 件以上のとき ‹ 候補 N/M › ＋「ベスト」バッジを表示
- **探索トレース**: 「探索の様子を見る」で `AnnealingTraceSlider` を展開。trace step を操作 → 地図のルートが変化する

本番エンドポイントは `record_trace: true` 相当で動作し、レスポンスに `restarts` と `edges_geojson` を含む。

### 探索範囲（道路データ）
サイドバーのスライダーでユーザーが半径を指定する（1,000〜5,000 m、500 m 刻み、デフォルト 3,000 m）。地図左上のトグル（`範囲円なし` / `範囲円あり`、デバッグのノード表示切替と同型）で円プレビューの表示を切り替える。デフォルトは ON。

- 通常時: 円は地図中心に追従する
- 最適化実行中: リクエスト送信時の中心・半径で円を固定（マップをパンしても円は動かない）
- 最適化成功後: トグルは自動で OFF
- スケッチ確定・探索設定（速度プリセット・探索範囲・向き固定）の変更時: トグルは自動で ON

定数は `app_defaults.py` / `productionDefaults.ts` の `FETCH_RADIUS_*` に定義。

探索範囲が大きすぎる、または道路が密すぎて Overpass が失敗した場合、API は `detail: { code: "fetch_area_too_large", message: "..." }`（HTTP 413 または 502）を返す。フロントは `FetchRadiusErrorDialog`（`ModalShell`）で半径縮小を案内する。

### 道路データ取得
ユーザーには Overpass の詳細を公開しない。`POST /api/optimize` 内部で自動実施:
1. 地図中心座標 + リクエストの `fetch_radius_m` → bbox 計算
2. Overpass API で `way["highway"]` を取得
3. グラフ構築（本番用デフォルトオプション）
4. 最適化実行

地図中心は `MapPanel` の `onCenterChange` コールバックで `HomePage` が保持し、最適化呼び出し時に渡す。

### ステータス表示
最適化中は地図上にオーバーレイポップアップを表示（`OptimizeStatusOverlay` コンポーネント）。  
表示ステップは経過時間ベースの推定:
- 0–3s:「道路データを取得中…」
- 3–6s:「道路グラフを構築中…」
- 6s–:「ルートを探索中…」

---

## デバッグとの差異

| 項目 | デバッグ | 本番 |
|------|---------|------|
| 道路データ取得 | ユーザーが手動でフェッチ・bbox指定 | 内部自動（地図中心 + ユーザー指定半径） |
| グラフ可視化 | ノード・エッジをオーバーレイ表示 | なし |
| グラフ前処理オプション | UI から全パラメータ変更可 | デフォルト固定 |
| 角度制約デフォルト | ON（回転ペナルティあり） | OFF（回転自由） |
| パラメータ設定 | 30+ パラメータを細かく調整可 | 速度プリセット + 角度トグルのみ |
| トレース表示 | 全 trace step を完全表示 | 結果後に軽量スライダー |
| 環境分離（UI ゲート） | 上記「本番環境の UI ゲート」参照 | テキスト・距離目安・`/debug` を非表示 |

---

## 実装原則

### バックエンド
- 本番用パラメータは `backend/app/optimization/app_defaults.py` に集約する
- 本番エンドポイントは `backend/app/routes.py`（デバッグとは別ファイル）
- デバッグ専用ロジックを変更しないこと。本番エンドポイントから `run_simulated_annealing` / `run_joint_simulated_annealing` を直接インポートして使う
- 環境変数での本番/デバッグ分岐はしない（同一デプロイを想定）

### フロントエンド
- 本番でも使う共有コンポーネントは `frontend/src/components/` に配置
- 本番でも使う共有ユーティリティは `frontend/src/lib/` に配置
- デバッグページの既存コンポーネントが共有コードをインポートする形に変更
- デバッグページの UI は変更しない
- スタイルは既存の「スケッチブック感・温かみ」（stone カラー、rounded-xl/2xl、shadow）を踏襲

### 共有コンポーネント・ライブラリ
`frontend/src/components/` と `frontend/src/lib/` が共有レイヤー。デバッグコードはここから import する（逆依存禁止）。

| ファイル | 内容 |
|--------|------|
| `components/RouteOrderPreview.tsx` | 巡回順 SVG（矢印・始終点・交点番号） |
| `components/AnnealingTraceSlider.tsx` | トレーススライダー UI |
| `components/RouteInfoPanel.tsx` | マップ左下ルート情報パネル |
| `components/OptimizeStatusOverlay.tsx` | 実行中プログレスオーバーレイ |
| `lib/routeOverlay.ts` | `overlayForCandidate`・`rebuildRouteForTraceStep` 等 |
| `lib/optimizeTypes.ts` | 最適化 API レスポンス型 |
