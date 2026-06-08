# 概要

手描きGPSアートは、キャンバスに描いた形を実際の道路上のランニングルートに変換するアプリです。地図上に直接形を描いてスナップする既存ツールと異なり、自由なキャンバス上で描いた形を、地図上の探索範囲内で「どこに・どの角度で・どの大きさで置くか」を探索します。

## パイプライン

```
ユーザーのスケッチ（ストローク）
  → connected component 分割 + 一筆書き化（フロントエンド）
  → OSM 取得 + 道路グラフ前処理（バックエンド）
  → 変換後形状の道路スナップ + スコア計算（バックエンド）
  → (tx, ty, θ, scale) のマルチスタート焼きなまし（バックエンド）
  → ランク付きルート候補 + トレース（API → 地図オーバーレイ）
```

図解は [article_visuals.html](article_visuals.html) を参照。

## 中核の設計判断

探索対象は **ルートそのものではなく**、入力折れ線に与える変換です。

```
state = { tx_m, ty_m, theta_rad, scale }
```

各候補変換に対してバックエンドが道路グラフへスナップし、スコアを計算します。道路グラフが数万ノード規模でも、探索空間は低次元（コンポーネント群あたり 4 次元）に保てます。

複数パーツ（目・口など）がある場合は **ジョイント焼きなまし** を使います。全体で 1 つの global 変換に加え、コンポーネントごとに小さな local offset `(dx_m, dy_m)` を許容します。

## 本番フロー

1. ユーザーがキャンバスに描き、地図中心・探索半径・速度プリセットを選ぶ。
2. `POST /api/optimize` が OSM way を取得し、グラフを構築して最適化を実行し、GeoJSON ルートを返す。
3. 地図上にランク付き候補を表示し、焼きなましのトレースを再生できる。

## 主要なソース

| 領域 | パス |
|------|------|
| スケッチ入力 UI | `frontend/src/components/SketchModal.tsx` |
| ストローク → コンポーネント | `frontend/src/lib/singlePathPostprocess.ts` |
| 本番ページ | `frontend/src/pages/HomePage.tsx` |
| 本番 API | `backend/app/routes.py` |
| 最適化コア | `backend/app/optimization/` |
| グラフ前処理 | `backend/app/preprocess/` |
| OSM 取得・取り込み | `backend/app/osm/` |

## 関連ドキュメント

- [アーキテクチャ](architecture.md)
- [入力前処理](input-preprocessing.md)
- [道路グラフ](road-graph.md)
- [最適化](optimization.md)
