# 入力前処理

ストロークの前処理はすべて API 呼び出し前にブラウザで実行される。

## データモデル

`frontend/src/lib/strokeTypes.ts` で定義:

```typescript
type InputMode = 'freehand' | 'pen' | 'text'

type StrokeData = {
  inputMode: InputMode
  strokes: Point[][]   // 描画順の複数ストローク
}

const MAX_STROKE_POINTS = 150  // 全ストローク合計点数上限
```

| モード | 実装 |
|--------|------|
| `freehand` | 自由描画。ポインター離脱時に Ramer–Douglas–Peucker 簡略化（`frontend/src/lib/simplify.ts`、`SIMPLIFY_TOLERANCE_PX`） |
| `pen` | クリックで頂点追加。ノードスナップあり（`frontend/src/lib/penNodeSnap.ts`） |
| `text` | opentype.js でグリフアウトライン生成（`frontend/src/lib/textToStrokes.ts`）。development UI のみ |

## 処理パイプライン

`frontend/src/lib/singlePathPostprocess.ts` の `strokesToProcessedComponents` がスケッチ確定時に実行される:

```
strokes: Point[][]
  → findConnectedComponents(strokes)
  → 各 component: buildSinglePath(componentStrokes)
  → processedComponents: Point[][]
  → POST /api/optimize { stroke_components: processedComponents }
```

- 1 コンポーネント → シングルコンポーネント焼きなまし
- 2 コンポーネント以上 → ジョイント焼きなまし

## Connected component 検出

`frontend/src/lib/strokeConnectivity.ts`:

- `segmentIntersectionParam` — 線分交差判定（許容 `GEOMETRY_EPS`）
- `findConnectedComponents` — エッジ交差で接続されたストロークを Union-Find で分割

接触しないストロークは別コンポーネントになる（例: 左右の目と口）。

## 一筆書き変換（Chinese Postman）

`buildSinglePath` は、ユーザーが描いていないエッジを追加せずに、1 つの connected component を連続した頂点列に変換する。

手順:

1. 交点検出 → セグメント分割 → グラフ G = (V, E) を構築
2. 奇数次頂点を列挙
3. 奇数次頂点間の全対最短経路（Dijkstra）
4. 奇数次頂点の最小重みマッチング（k ≤ 20 は bitmask DP、それ以上は greedy）
5. 既存エッジの重複通過を追加 → Hierholzer でオイラー路を抽出
6. PATH（始点 ≠ 終点）と CIRCUIT（始点 = 終点）を比較し、短い方を採用

**制約:** スケッチの離れた部分をつなぐショートカットエッジは挿入しない。往復は既存エッジの重複通過のみ。

## API ペイロード

```json
{
  "stroke_components": [
    [{"x": 0.1, "y": 0.3}, ...],
    [{"x": 0.8, "y": 0.2}, ...]
  ]
}
```

- `x`, `y` — キャンバス正規化座標
- 各配列はすでに一筆書き済み。バックエンドは頂点順序を再構成しない

## 関連ドキュメント

- [概要](overview.md)
- [最適化](optimization.md)
