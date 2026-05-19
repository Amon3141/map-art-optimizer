# 入力形状の処理（フロントエンド）

ユーザーがキャンバスに描いた形を、バックエンドへ送る前にどう処理するかをまとめる。

---

## 1. 型定義（`frontend/src/lib/strokeTypes.ts`）

```typescript
type InputMode = 'freehand' | 'pen' | 'text'

type StrokeData = {
  inputMode: InputMode
  strokes:    Point[][]   // 描画順のストローク列
}

const MAX_STROKE_POINTS = 150  // 全ストローク合計点数の上限（全モード共通）
```

### 入力モード

| `inputMode` | 概要 |
|---|---|
| `freehand` | マウス/タッチで自由に描く |
| `pen` | 折れ線ツールでクリックごとに頂点追加 |
| `text` | opentype.js でグリフアウトラインを `Point[][]` に変換（`frontend/src/lib/textToStrokes.ts`） |

複数の独立したストローク（接触・交差していないもの）はそのまま許容する。後処理で connected component ごとに分割される。

---

## 2. 前処理フロー

`strokesToProcessedComponents`（[`frontend/src/lib/singlePathPostprocess.ts`](../frontend/src/lib/singlePathPostprocess.ts)）が最適化送信直前に実行される（`DebugOptimizePanel` では `strokeData` から `useMemo` で導出）。

```
strokes: Point[][]
    ↓
findConnectedComponents(strokes)
    → ConnectedComponent[]（各コンポーネント = ストロークの部分集合）
    ↓ 各コンポーネントに対して
buildSinglePath(componentStrokes)
    → Point[]（一筆書き化済みの点列）
    ↓
processedComponents: Point[][]
    ↓ バックエンドへ
POST /api/debug/optimize
  stroke_components: processedComponents
```

- `processedComponents` の長さ = connected component 数（1 ならシングル SA、2 以上ならジョイント SA）

---

## 3. Connected Component 検出（`frontend/src/lib/strokeConnectivity.ts`）

ストローク間の「接続」はエッジの交差判定で決める。

- **`segmentIntersectionParam`**: 2線分の交差判定（パラメトリック）。精度閾値 `GEOMETRY_EPS` 以内で交差とみなす。
- **`findConnectedComponents`**: 各ストロークをノード、交差を辺としてグラフを構築し、Union-Find で connected component を列挙する。

---

## 4. `buildSinglePath`（`frontend/src/lib/singlePathPostprocess.ts`）

**Chinese Postman アルゴリズム**により、1つの connected component 内の複数ストロークを一筆書き順の `Point[]` に変換する。

### 入力・出力

- **入力**: 1つの connected component に属するストロークの集合 `Point[][]`。
- **出力**: `Point[]`（一筆書き順の点列）。

### 処理ステップ

1. **交点検出 + グラフ構築**  
   全セグメントペアの交点を検出し、セグメントを分割。頂点 V・辺 E からなるグラフ G を構築する（入力にないエッジは追加しない）。

2. **奇数次頂点の検出**  
   次数が奇数の頂点 k 個を列挙する。オイラー路が存在するなら k=0（回路）か k=2（路）。k>2 なら重複通過が必要。

3. **奇数次頂点間の最短経路（Dijkstra 全対計算）**  
   k 個の奇数次頂点すべての組合せについて Dijkstra で最短距離を求める。

4. **最小重みマッチング（重複辺の決定）**  
   - k ≤ 20: bitmask DP（最適解）
   - k > 20: greedy（近似）  
   マッチングされた経路を重複辺として G に追加し、全頂点の次数を偶数にする。

5. **オイラー路抽出（Hierholzer）**  
   拡張グラフ上でオイラー路を抽出する。PATH（始点≠終点）と CIRCUIT（始点=終点）をコスト比較し、**出力長が短い方**を採用する。

### 制約・注意点

- 入力にないエッジは絶対に追加しない（往復は既存エッジの重複通過で表現する）
- 出力長最小化を目標とするが、最短保証ではなく「良い近似」
- 点数上限 `MAX_STROKE_POINTS = 150` は呼び出し前にフロントが保証する

---

## 5. バックエンドへの送信フォーマット（`POST /api/debug/optimize`）

```json
{
  "stroke_components": [
    [{"x": 0.1, "y": 0.3}, ...],
    [{"x": 0.8, "y": 0.2}, ...]
  ]
}
```

- `x`, `y` はキャンバス正規化座標（[0, 1] 付近）
- 各 component はすでに `buildSinglePath` による **一筆書き済みの `Point[]`** なので、バックエンドでの順序再構成は不要
- `stroke_components` は 1 件以上必須

詳細な API スキーマとルーティングは [`debug.md`](./debug.md)、バックエンド側の最適化ロジックは [`optimization.md`](./optimization.md) を参照。
