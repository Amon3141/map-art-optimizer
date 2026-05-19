import { useState } from 'react'
import { Sidebar } from '../components/Sidebar'
import { MapPanel } from '../components/MapPanel'
import { SketchModal } from '../components/SketchModal'
import type { StrokeData } from '../lib/strokeTypes'

export function HomePage() {
  const [targetKm, setTargetKm] = useState(10)
  const [sketchOpen, setSketchOpen] = useState(false)
  const [strokeData, setStrokeData] = useState<StrokeData | null>(null)

  return (
    <div className="flex h-full min-h-0 flex-col gap-0 bg-[#faf8f4] lg:flex-row lg:gap-5">
      <Sidebar
        targetKm={targetKm}
        onTargetKmChange={setTargetKm}
        strokeData={strokeData}
        onOpenSketch={() => setSketchOpen(true)}
      />

      <main className="flex min-h-0 min-w-0 flex-1 flex-col px-3 pb-3 pt-1.5 lg:min-h-0 lg:flex-1 lg:px-5 lg:pb-5 lg:pl-0 lg:pt-5">
        <div className="flex min-h-[280px] flex-1 flex-col overflow-hidden rounded-2xl border border-stone-200/80 bg-[#faf8f4] shadow-[inset_0_1px_0_rgba(255,255,255,0.35)] lg:min-h-0">
          <MapPanel className="min-h-0 w-full flex-1" />
        </div>
      </main>

      {sketchOpen ? (
        <SketchModal
          onClose={() => setSketchOpen(false)}
          onConfirm={(data) => {
            setStrokeData(data)
            setSketchOpen(false)
          }}
        />
      ) : null}
    </div>
  )
}
