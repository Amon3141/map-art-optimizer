# フロントエンド UI 規約

## 全画面モーダル（`ModalShell`）

ブロッキングするポップアップ（確認ダイアログ・スケッチ編集など）は [`ModalShell`](../frontend/src/components/ModalShell.tsx) で実装する。

- **`createPortal`** で `document.body` 直下に描画する（親の `overflow` / `transform` や MapLibre の stacking context の影響を避ける）
- 外枠・半透明背景・z-index・Esc / 背景クリックはシェルが担当する
- 各コンポーネントは **パネル内のコンテンツだけ** を書く

### いつ使うか

- 画面全体を覆うダイアログ・シート・フルスクリーンに近い編集 UI

### いつ使わないか

- マップコンテナ内の `absolute` オーバーレイ（例: [`OptimizeStatusOverlay`](../frontend/src/components/OptimizeStatusOverlay.tsx)、[`RouteInfoPanel`](../frontend/src/components/RouteInfoPanel.tsx)）
- ツールチップ・インラインの軽い UI

これらは従来どおりマップ親要素内に配置する。

### z-index

定数は [`frontend/src/lib/modalLayers.ts`](../frontend/src/lib/modalLayers.ts) に集約する。

| 層 | 値 | 例 |
|----|-----|-----|
| マップ内オーバーレイ | `z-20` | 探索進捗、ルート情報 |
| モーダル | `MODAL_Z_INDEX` (50) | スケッチモーダル |
| 前面モーダル | `MODAL_Z_INDEX_STACKED` (60) | 確認ダイアログ |
| 最小幅ガード | `VIEWPORT_GUARD_Z_INDEX` (70) | 320px 未満（[`MinViewportGuard`](../frontend/src/components/MinViewportGuard.tsx)） |

### `ModalShell` の主な props

| prop | 説明 |
|------|------|
| `open` | `false` のとき portal しない |
| `layout` | `'center'`（中央） / `'sheet'`（モバイル下寄せ・sm 以上で中央） |
| `backdrop` | `'default'`（濃いめ） / `'light'`（スケッチ用） |
| `stacked` | `true` で z-index 60 |
| `onClose` | 背景クリック・Esc 時（無効化は `closeOnBackdropClick` / `closeOnEscape`） |
| `backdropClassName` | 背景レイヤーへの追加クラス（退場アニメなど） |

### 新しいモーダルを追加する手順

1. `frontend/src/components/` に中身用コンポーネントを追加
2. ルートを `<ModalShell open layout="center" ...>` でラップ（親ページで `open` を state 管理）
3. 他モーダルより前面に出す必要があれば `stacked`
4. 文言だけ違う場合は [`ConfirmDialog`](../frontend/src/components/ConfirmDialog.tsx) と同様に `Record<Variant, Copy>` で切り替え

### 参考実装

- 中央・確認: [`ConfirmDialog.tsx`](../frontend/src/components/ConfirmDialog.tsx)
- シート: [`SketchModal.tsx`](../frontend/src/components/SketchModal.tsx)
