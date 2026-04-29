"use client"

import { useState } from "react"
import { EditorialDirection } from "@/components/directions/editorial"
import { ConsoleDirection } from "@/components/directions/console"
import { TactileDirection } from "@/components/directions/tactile"

type Direction = "editorial" | "console" | "tactile"

const DIRECTIONS = [
  {
    id: "editorial" as Direction,
    number: "01",
    title: "Editorial Research Workspace",
    tagline: "Print-informed hierarchy. Reading-first layout.",
    description:
      "Inspired by editorial print design and research notebooks. A warm off-white canvas with serif type, tight editorial spacing, and document-forward layout. Citations feel like footnotes — natural and integrated, never bolted on. The document rail and chat share the same visual language, reading as one surface rather than two panels.",
    palette: ["#faf9f7", "#1a1916", "#7a746a", "#e8e4dc"],
    paletteLabels: ["Canvas", "Ink", "Muted", "Rule"],
    typeface: "Georgia / Geist",
    mood: "Scholarly · Quiet · Legible",
  },
  {
    id: "console" as Direction,
    number: "02",
    title: "Calm Operational Console",
    tagline: "Dark. Precise. Status-driven.",
    description:
      "Built for operators who scan status constantly and need fast orientation. A disciplined dark UI — near-black with blue structural accents — where every element earns its place. Document state is the primary signal. Citations surface as compact chips with expandable excerpts. The palette stays intentionally narrow: one structural color, two neutrals.",
    palette: ["#0f1117", "#161b25", "#3b82f6", "#e2e4ea"],
    paletteLabels: ["Base", "Surface", "Signal", "Text"],
    typeface: "Geist / Geist Mono",
    mood: "Precise · Dense · Trustworthy",
  },
  {
    id: "tactile" as Direction,
    number: "03",
    title: "Warm Tactile Intelligence",
    tagline: "Cards. Texture. Rounded, human-feeling surfaces.",
    description:
      "A warmer take that feels closer to a paper-based productivity tool than a terminal or CMS. Document cards have depth, rounded forms, and status communicated through background tinting rather than color alone. Chat uses a bubble pattern that creates a clear directional conversation flow. Citations have visual connectors — a numbered column with a lead line — making provenance feel natural.",
    palette: ["#f7f5f0", "#2d5e3f", "#1e1c18", "#e0dbd2"],
    paletteLabels: ["Paper", "Green", "Ink", "Border"],
    typeface: "Geist / System",
    mood: "Warm · Approachable · Grounded",
  },
]

export default function ExplorationPage() {
  const [active, setActive] = useState<Direction>("tactile")

  const activeDir = DIRECTIONS.find((d) => d.id === active)!

  return (
    <div className="exploration-root min-h-screen flex flex-col" style={{ fontFamily: "'Geist', system-ui, sans-serif" }}>
      {/* Exploration header */}
      <div className="exploration-meta border-b" style={{ background: "#f9f9f8", borderColor: "#e5e3df" }}>
        <div className="max-w-screen-xl mx-auto px-8 py-5 flex items-start justify-between gap-8">
          <div>
            <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.1em", color: "#9a948c", fontWeight: 600, marginBottom: 4 }}>
              Design Exploration
            </div>
            <div style={{ fontSize: 20, fontWeight: 700, color: "#1a1916", letterSpacing: "-0.02em" }}>
              RAG Workspace · 3 Directions
            </div>
            <div style={{ fontSize: 13, color: "#7a746a", marginTop: 4, maxWidth: 420, lineHeight: 1.5 }}>
              Frontend redesign exploration. Each direction uses realistic mock data — no backend, auth, or billing logic.
            </div>
          </div>

          {/* Direction switcher */}
          <div className="flex items-center gap-2">
            {DIRECTIONS.map((dir) => (
              <button
                key={dir.id}
                onClick={() => setActive(dir.id)}
                className="dir-tab"
                data-active={active === dir.id}
                style={{
                  padding: "8px 16px",
                  borderRadius: 8,
                  border: "1.5px solid",
                  borderColor: active === dir.id ? "#1a1916" : "#e0ddd8",
                  background: active === dir.id ? "#1a1916" : "transparent",
                  color: active === dir.id ? "#faf9f7" : "#7a746a",
                  cursor: "pointer",
                  fontSize: 13,
                  fontWeight: 600,
                  transition: "all 0.15s",
                  fontFamily: "inherit",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "flex-start",
                  gap: 2,
                  minWidth: 120,
                }}
              >
                <span style={{ fontSize: 10, opacity: 0.6, fontWeight: 500, letterSpacing: "0.05em" }}>
                  {dir.number}
                </span>
                <span style={{ fontSize: 12, lineHeight: 1.3 }}>{dir.title}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Direction metadata strip */}
        <div style={{ background: "#f2f0ec", borderTop: "1px solid #e5e3df" }}>
          <div className="max-w-screen-xl mx-auto px-8 py-3 flex items-center gap-8">
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {activeDir.palette.map((color, i) => (
                <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
                  <div
                    style={{
                      width: 20, height: 20, borderRadius: 5,
                      background: color,
                      border: "1px solid rgba(0,0,0,0.08)",
                    }}
                  />
                  <span style={{ fontSize: 9, color: "#9a948c", letterSpacing: "0.04em" }}>{activeDir.paletteLabels[i]}</span>
                </div>
              ))}
            </div>
            <div style={{ width: 1, height: 28, background: "#e0ddd8" }} />
            <div>
              <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.1em", color: "#9a948c", fontWeight: 600 }}>Typeface</div>
              <div style={{ fontSize: 12, color: "#3a3830", fontWeight: 500, marginTop: 1 }}>{activeDir.typeface}</div>
            </div>
            <div style={{ width: 1, height: 28, background: "#e0ddd8" }} />
            <div>
              <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.1em", color: "#9a948c", fontWeight: 600 }}>Mood</div>
              <div style={{ fontSize: 12, color: "#3a3830", fontWeight: 500, marginTop: 1 }}>{activeDir.mood}</div>
            </div>
            <div style={{ width: 1, height: 28, background: "#e0ddd8" }} />
            <p style={{ fontSize: 12, color: "#7a746a", lineHeight: 1.5, flex: 1, maxWidth: 540 }}>
              {activeDir.description}
            </p>
          </div>
        </div>
      </div>

      {/* Preview frame */}
      <div className="flex-1 overflow-hidden" style={{ minHeight: 0, height: "calc(100vh - 160px)" }}>
        {active === "editorial" && <EditorialDirection />}
        {active === "console" && <ConsoleDirection />}
        {active === "tactile" && <TactileDirection />}
      </div>
    </div>
  )
}
