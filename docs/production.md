# 本番アプリ実装ガイド

本番 UI（`/`）とデバッグ UI（`/debug`）は同一デプロイで共存する。このファイルは本番向けの UX 決定・実装方針を記録する。

---

## UX 設計決定

### 角度制約 (ignore_source_rotation)
**本番デフォルト: 回転自由（ignore_source_rotation = true）**

GPS アートでは形の良さが最優先。向きに縛ると探索空間が狭まる。  
ユーザー向けには「向きを固定する」トグル（デフォルト OFF）として公開。デバッグのデフォルト（回転ペナルティあり）とは逆。

### 探索速度プリセット
生の秒数は公開せず、3段階に抽象化する。

| プリセット | ラベル | budget_s | restarts | max_iter | fetch_radius_m |
|-----------|--------|----------|----------|----------|----------------|
| fast      | 速め   | 10s      | 2        | 150      | 3500m          |
| normal    | ふつう | 20s      | 5        | 300      | 5000m          |
| thorough  | じっくり | 30s   | 10       | 500      | 7000m          |

各プリセットは `backend/app/optimization/production_defaults.py` に定義。  
フロント側の UI メタ（ラベル・説明）は `frontend/src/lib/productionDefaults.ts` に定義。

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

### 道路データ取得
ユーザーには公開しない。`POST /api/optimize` 内部で自動実施:
1. 地図中心座標 + プリセットの `fetch_radius_m` → bbox 計算
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
| 道路データ取得 | ユーザーが手動でフェッチ・bbox指定 | 内部自動（地図中心 + radius） |
| グラフ可視化 | ノード・エッジをオーバーレイ表示 | なし |
| グラフ前処理オプション | UI から全パラメータ変更可 | デフォルト固定 |
| 角度制約デフォルト | ON（回転ペナルティあり） | OFF（回転自由） |
| パラメータ設定 | 30+ パラメータを細かく調整可 | 速度プリセット + 角度トグルのみ |
| トレース表示 | 全 trace step を完全表示 | 結果後に軽量スライダー |
| 環境分離 | `VITE_DEBUG=true` で表示 | 常時表示 |

---

## 実装原則

### バックエンド
- 本番用パラメータは `backend/app/optimization/production_defaults.py` に集約する
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
