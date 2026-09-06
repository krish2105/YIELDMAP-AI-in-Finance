"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { useReducedMotion } from "motion/react";

import { compactAed } from "@/lib/format";

/**
 * Dubai, extruded by whichever metric is selected.
 *
 * Each community is a hexagonal column at its centroid, its height the metric and its colour the
 * same. Hexagons rather than true boundaries because no open GeoJSON of Dubai's community
 * polygons is reachable — the shapes are honest about being approximate, and an area with no
 * centroid at all is listed beside the map rather than placed at the origin.
 *
 * Every column is one instance of a single mesh, so eighty-odd communities cost one draw call.
 * The frame loop is demand-driven: with nothing moving, nothing renders, which is what lets this
 * sit on a phone without draining the battery.
 */

export interface CityDatum {
  area_key: string;
  name: string;
  lat: number;
  lon: number;
  value: number | null;
  n: number;
}

// Dubai's bounding box, used to map degrees onto a scene that fits the camera.
const BOUNDS = { minLat: 24.78, maxLat: 25.36, minLon: 54.95, maxLon: 55.58 };
const SPAN = 34;

function project(lat: number, lon: number): [number, number] {
  const x = ((lon - BOUNDS.minLon) / (BOUNDS.maxLon - BOUNDS.minLon) - 0.5) * SPAN;
  const z = -((lat - BOUNDS.minLat) / (BOUNDS.maxLat - BOUNDS.minLat) - 0.5) * SPAN;
  return [x, z];
}

function Columns({
  data,
  onHover,
  selected,
}: {
  data: CityDatum[];
  onHover: (datum: CityDatum | null) => void;
  selected: string | null;
}) {
  const mesh = useRef<THREE.InstancedMesh>(null);
  const reduce = useReducedMotion();
  const grown = useRef(0);

  const { positions, heights, colors } = useMemo(() => {
    const values = data.map((d) => d.value ?? 0).filter((v) => v > 0);
    const max = values.length ? Math.max(...values) : 1;
    const positions = data.map((d) => project(d.lat, d.lon));
    const heights = data.map((d) => (d.value === null ? 0.12 : 0.35 + (d.value / max) * 7));
    // Teal to sand along the metric. A single hue ramp, light to dark, because this encodes
    // magnitude rather than identity.
    const low = new THREE.Color("#0e5f45");
    const high = new THREE.Color("#e0a53a");
    const colors = data.map((d) =>
      d.value === null
        ? new THREE.Color("#4a4a4a")
        : low.clone().lerp(high, Math.min((d.value / max) ** 0.7, 1)),
    );
    return { positions, heights, colors };
  }, [data]);

  useFrame((_, delta) => {
    if (!mesh.current) return;
    // One short grow-in on load, then the loop goes quiet. Reduced motion skips straight to full.
    const target = 1;
    if (grown.current < target) {
      grown.current = reduce ? target : Math.min(target, grown.current + delta * 1.6);
    }
    const eased = 1 - (1 - grown.current) ** 3;
    const dummy = new THREE.Object3D();
    for (let i = 0; i < data.length; i++) {
      const [x, z] = positions[i]!;
      const height = Math.max(heights[i]! * eased, 0.02);
      dummy.position.set(x, height / 2, z);
      dummy.scale.set(1, height, 1);
      dummy.updateMatrix();
      mesh.current.setMatrixAt(i, dummy.matrix);
      const colour = colors[i]!;
      const isSelected = selected === data[i]!.area_key;
      mesh.current.setColorAt(
        i,
        isSelected ? colour.clone().offsetHSL(0, 0.1, 0.22) : colour,
      );
    }
    mesh.current.instanceMatrix.needsUpdate = true;
    if (mesh.current.instanceColor) mesh.current.instanceColor.needsUpdate = true;
  });

  return (
    <instancedMesh
      ref={mesh}
      args={[undefined, undefined, data.length]}
      onPointerMove={(event) => {
        event.stopPropagation();
        const index = event.instanceId;
        onHover(index === undefined ? null : (data[index] ?? null));
      }}
      onPointerOut={() => onHover(null)}
      castShadow
    >
      {/* Six sides: a hex reads as a cell of a map rather than as a building. */}
      <cylinderGeometry args={[0.42, 0.42, 1, 6]} />
      <meshStandardMaterial roughness={0.55} metalness={0.05} />
    </instancedMesh>
  );
}

function Scene({
  data,
  onHover,
  selected,
}: {
  data: CityDatum[];
  onHover: (datum: CityDatum | null) => void;
  selected: string | null;
}) {
  return (
    <>
      <ambientLight intensity={0.75} />
      <directionalLight position={[10, 18, 8]} intensity={1.5} />
      <directionalLight position={[-12, 8, -10]} intensity={0.35} color="#7fd6b5" />
      <Columns data={data} onHover={onHover} selected={selected} />
      <gridHelper args={[SPAN * 1.25, 26, "#3a3a40", "#26262b"]} position={[0, -0.01, 0]} />
      <OrbitControls
        enablePan={false}
        minDistance={12}
        maxDistance={44}
        maxPolarAngle={Math.PI / 2.15}
        enableDamping
        dampingFactor={0.08}
      />
    </>
  );
}

/** The fallback when WebGL is missing: the same data, ranked, as a plain list. */
function FlatFallback({ data, unit }: { data: CityDatum[]; unit: string }) {
  const ranked = [...data]
    .filter((d) => d.value !== null)
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
    .slice(0, 20);
  const max = ranked[0]?.value ?? 1;

  return (
    <div className="p-4" data-testid="city-fallback">
      <p className="mb-3 text-xs text-ink-muted">
        3D is unavailable in this browser, so the same figures are shown as a ranked list.
      </p>
      <ul className="space-y-1">
        {ranked.map((datum) => (
          <li key={datum.area_key} className="flex items-center gap-2 text-xs">
            <span className="w-40 shrink-0 truncate text-ink-secondary">{datum.name}</span>
            <span className="h-2 flex-1 overflow-hidden rounded-full bg-sunken">
              <span
                className="block h-full rounded-full"
                style={{
                  width: `${Math.max(((datum.value ?? 0) / max) * 100, 2)}%`,
                  background: "var(--teal)",
                }}
              />
            </span>
            <span className="w-24 shrink-0 text-right font-medium text-ink">
              {compactAed(datum.value ?? 0)} {unit}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function City3D({
  data,
  unit,
  selected = null,
  onSelect,
  height = 440,
}: {
  data: CityDatum[];
  unit: string;
  selected?: string | null;
  onSelect?: (areaKey: string) => void;
  height?: number;
}) {
  const [hovered, setHovered] = useState<CityDatum | null>(null);
  const [failed, setFailed] = useState(false);

  const supported = useMemo(() => {
    if (typeof window === "undefined") return true;
    try {
      const canvas = document.createElement("canvas");
      return Boolean(
        canvas.getContext("webgl2") ?? canvas.getContext("webgl"),
      );
    } catch {
      return false;
    }
  }, []);

  if (!supported || failed || data.length === 0) {
    return (
      <div
        className="overflow-hidden rounded-xl border border-line bg-raised"
        style={{ minHeight: height }}
      >
        <FlatFallback data={data} unit={unit} />
      </div>
    );
  }

  return (
    <div
      className="relative overflow-hidden rounded-xl border border-line bg-sunken"
      style={{ height }}
      data-testid="city-3d"
    >
      <Canvas
        // Nothing renders unless something changed. This is what keeps it viable on a phone.
        frameloop="demand"
        shadows={false}
        dpr={[1, 1.75]}
        camera={{ position: [0, 19, 24], fov: 42 }}
        onCreated={({ gl }) => gl.setClearColor("#0d0d0f", 1)}
        onError={() => setFailed(true)}
      >
        <Scene data={data} onHover={setHovered} selected={selected} />
      </Canvas>

      {hovered ? (
        <div
          className="pointer-events-none absolute left-3 top-3 rounded-lg border border-line bg-raised/95 px-3 py-2 text-xs shadow-card backdrop-blur"
          data-testid="city-tooltip"
        >
          <p className="font-medium text-ink">{hovered.name}</p>
          <p className="text-ink-secondary">
            {hovered.value === null ? "insufficient data" : `${compactAed(hovered.value)} ${unit}`}
          </p>
          <p className="text-ink-muted">n = {hovered.n.toLocaleString()}</p>
        </div>
      ) : null}

      {onSelect && hovered ? (
        <button
          type="button"
          onClick={() => onSelect(hovered.area_key)}
          className="absolute bottom-3 left-3 rounded-lg border border-line bg-raised/95 px-3 py-1.5 text-xs text-ink hover:border-teal"
        >
          Open {hovered.name}
        </button>
      ) : null}

      <p className="pointer-events-none absolute bottom-3 right-3 max-w-[16rem] text-right text-[10px] leading-tight text-ink-muted">
        Hex cells at approximate community centroids, not true boundaries.
      </p>
    </div>
  );
}
