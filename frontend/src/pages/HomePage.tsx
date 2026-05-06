import { useState } from 'react'
import { HomeSidebar } from '../components/HomeSidebar'
import { MapPanel } from '../components/MapPanel'
import { SketchModal } from '../components/SketchModal'
import type { Point } from '../lib/simplify'

export function HomePage() {
  const [targetKm, setTargetKm] = useState(10)
  const [sketchOpen, setSketchOpen] = useState(false)
  const [strokePoints, setStrokePoints] = useState<Point[] | null>(null)

  return (
    <div className="flex h-full min-h-0 flex-col gap-0 bg-[#faf8f4] lg:flex-row lg:gap-5">
      <HomeSidebar
        targetKm={targetKm}
        onTargetKmChange={setTargetKm}
        strokePoints={strokePoints}
        onOpenSketch={() => setSketchOpen(true)}
      />

      <main className="min-h-0 min-w-0 flex-1 px-3 pb-3 pt-1.5 lg:min-h-0 lg:flex-1 lg:px-5 lg:pb-5 lg:pl-0 lg:pt-5">
        <div className="h-full min-h-[280px] overflow-hidden rounded-2xl border border-stone-200/80 bg-[#faf8f4] shadow-[inset_0_1px_0_rgba(255,255,255,0.35)] lg:min-h-0">
          <MapPanel className="h-full w-full" />
        </div>
        <p className="mt-2 text-center text-[11px] text-stone-500">
          © OpenStreetMap contributors
        </p>
      </main>

      {sketchOpen ? (
        <SketchModal
          onClose={() => setSketchOpen(false)}
          onConfirm={(pts) => setStrokePoints(pts)}
        />
      ) : null}
    </div>
  )
}
