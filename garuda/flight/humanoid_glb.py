"""
Generate a human-shaped glTF 2.0 (GLB) mesh from scratch, with no dependencies.

Why this exists
---------------
Person-following cannot be demonstrated on the Project AirSim environment: its
stock scene has no people, and ``World.spawn_object`` only serves assets the
environment was packaged with (``/Engine/BasicShapes/Cube`` returns ``None``).
``World.spawn_object_from_file`` is the escape hatch -- it takes raw *bytes*,
so the asset does not need to exist on the server.

``spawn_object_from_file`` accepts only ``file_format="gltf"``. This machine has
an ``AnimatedCharacter.fbx`` and a ``Mikkt_SkeletalMesh.fbx`` in the UE 5.7.4
engine content, but there is no FBX->glTF converter installed (no ``trimesh``,
no Blender, no assimp), so those are unusable. Rather than add a toolchain, this
builds the glTF directly: a humanoid assembled from boxes in correct human
proportions, which is what a ``person`` detector actually keys on.

It is not skinned and it is not rigged. It does not need to be -- ``import_ned_trajectory``
moves the actor, so the walker still moves while the follow loop tracks it.

glTF conventions honoured here: Y up, right-handed, metres, -Z forward,
single buffer, 4-byte aligned accessors, POSITION min/max required.

Verify before use:
    python -m garuda.flight.humanoid_glb > /dev/null   # see self-test output
"""

from __future__ import annotations

import json
import struct
from typing import Sequence

# ── geometry helpers ────────────────────────────────────────────────────

#: Half-extent unit cube corners, and the 6 faces as (normal, corner indices).
_UNIT_HALF = 0.5
_FACES = (
    ((0.0, 0.0, 1.0), (0, 1, 2, 3)),    # +Z
    ((0.0, 0.0, -1.0), (4, 7, 6, 5)),   # -Z
    ((1.0, 0.0, 0.0), (1, 0, 4, 5)),    # +X
    ((-1.0, 0.0, 0.0), (0, 3, 7, 4)),   # -X
    ((0.0, 1.0, 0.0), (3, 2, 6, 7)),    # +Y
    ((0.0, -1.0, 0.0), (0, 1, 5, 4)),   # -Y
)
_CORNERS = (
    (-1.0, -1.0, 1.0), (1.0, -1.0, 1.0), (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0),
    (-1.0, -1.0, -1.0), (1.0, -1.0, -1.0), (1.0, 1.0, -1.0), (-1.0, 1.0, -1.0),
)


def _box(
    centre: Sequence[float], size: Sequence[float]
) -> tuple[list, list, list]:
    """Return (positions, normals, indices) for one axis-aligned box."""
    cx, cy, cz = centre
    sx, sy, sz = (s * _UNIT_HALF for s in size)
    positions: list[list[float]] = []
    normals: list[list[float]] = []
    indices: list[int] = []
    for normal, corners in _FACES:
        base = len(positions)
        for ci in corners:
            vx, vy, vz = _CORNERS[ci]
            positions.append([cx + vx * sx, cy + vy * sy, cz + vz * sz])
            normals.append(list(normal))
        indices.extend([base, base + 1, base + 2, base, base + 2, base + 3])
    return positions, normals, indices


# ── the humanoid ────────────────────────────────────────────────────────

#: (material, centre, size). Human proportions at 1.90 m overall height.
#: Standing symmetric and neutral: a ``person`` classifier keys on the
#: silhouette, and an asymmetric pose reads as noise at low resolution.
BODY: tuple[tuple[str, tuple[float, float, float], tuple[float, float, float]], ...] = (
    # feet (distinct left/right spacing)
    ("shoe", (0.150, 0.040, 0.045), (0.130, 0.080, 0.280)),
    ("shoe", (-0.150, 0.040, 0.045), (0.130, 0.080, 0.280)),
    # lower legs (clear gap between legs)
    ("pants", (0.150, 0.280, 0.000), (0.120, 0.400, 0.150)),
    ("pants", (-0.150, 0.280, 0.000), (0.120, 0.400, 0.150)),
    # upper legs
    ("pants", (0.140, 0.690, 0.000), (0.140, 0.420, 0.180)),
    ("pants", (-0.140, 0.690, 0.000), (0.140, 0.420, 0.180)),
    # pelvis
    ("pants", (0.000, 1.000, 0.000), (0.360, 0.200, 0.220)),
    # torso
    ("shirt", (0.000, 1.330, 0.000), (0.440, 0.500, 0.260)),
    # neck
    ("skin", (0.000, 1.610, 0.000), (0.130, 0.080, 0.130)),
    # head (face/skin)
    ("skin", (0.000, 1.770, 0.010), (0.220, 0.240, 0.220)),
    # hair (top/back crown of head for natural human head contrast)
    ("hair", (0.000, 1.840, -0.010), (0.230, 0.100, 0.230)),
    # upper arms (spaced clearly off torso)
    ("shirt", (0.300, 1.450, 0.000), (0.120, 0.320, 0.150)),
    ("shirt", (-0.300, 1.450, 0.000), (0.120, 0.320, 0.150)),
    # forearms
    ("skin", (0.320, 1.150, 0.020), (0.110, 0.300, 0.130)),
    ("skin", (-0.320, 1.150, 0.020), (0.110, 0.300, 0.130)),
)

#: Base colour (linear-ish RGB 0-1), metallic, roughness per material.
MATERIALS: dict[str, tuple[list[float], float, float]] = {
    "skin": ([0.85, 0.65, 0.55], 0.0, 0.75),
    "hair": ([0.12, 0.08, 0.06], 0.0, 0.90),
    "shirt": ([0.20, 0.35, 0.70], 0.0, 0.85),
    "pants": ([0.18, 0.18, 0.22], 0.0, 0.90),
    "shoe": ([0.10, 0.10, 0.10], 0.0, 0.70),
}

HEIGHT_M = 1.90


def _pad(n: int) -> int:
    """Bytes to append so the next write starts on a 4-byte boundary."""
    return (4 - (n % 4)) % 4


def build_glb(body: Sequence = BODY) -> bytes:
    """Assemble the humanoid into a self-contained GLB byte string."""
    by_material: dict[str, tuple[list, list, list]] = {
        name: ([], [], []) for name in MATERIALS
    }
    for material, centre, size in body:
        pos, nrm, idx = _box(centre, size)
        p_acc, n_acc, i_acc = by_material[material]
        offset = len(p_acc)
        p_acc.extend(pos)
        n_acc.extend(nrm)
        i_acc.extend(i + offset for i in idx)

    blob = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []
    gltf_materials: list[dict] = []
    mat_index = {name: i for i, name in enumerate(MATERIALS)}
    for name, (rgba, metallic, roughness) in MATERIALS.items():
        gltf_materials.append(
            {
                "name": name,
                "pbrMetallicRoughness": {
                    "baseColorFactor": rgba + [1.0],
                    "metallicFactor": metallic,
                    "roughnessFactor": roughness,
                },
                "doubleSided": False,
            }
        )

    primitives: list[dict] = []
    for name in MATERIALS:
        positions, normals, indices = by_material[name]
        if not positions:
            continue
        count = len(positions)

        def _view(data: bytes, target: int = 34962) -> int:
            while len(blob) % 4:
                blob.append(0)
            views.append(
                {
                    "buffer": 0,
                    "byteOffset": len(blob),
                    "byteLength": len(data),
                    "target": target,
                }
            )
            blob.extend(data)
            return len(views) - 1

        flat = [c for p in positions for c in p]
        pos_bytes = struct.pack(f"<{len(flat)}f", *flat)
        pos_view = _view(pos_bytes)
        accessors.append(
            {
                "bufferView": pos_view,
                "componentType": 5126,
                "count": count,
                "type": "VEC3",
                "min": [min(p[i] for p in positions) for i in range(3)],
                "max": [max(p[i] for p in positions) for i in range(3)],
            }
        )
        pos_acc = len(accessors) - 1

        flat_n = [c for p in normals for c in p]
        nrm_view = _view(struct.pack(f"<{len(flat_n)}f", *flat_n))
        accessors.append(
            {
                "bufferView": nrm_view,
                "componentType": 5126,
                "count": count,
                "type": "VEC3",
            }
        )
        nrm_acc = len(accessors) - 1

        idx_bytes = struct.pack(f"<{len(indices)}H", *indices)
        idx_view = _view(idx_bytes, target=34963)
        accessors.append(
            {
                "bufferView": idx_view,
                "componentType": 5123,
                "count": len(indices),
                "type": "SCALAR",
            }
        )
        primitives.append(
            {
                "attributes": {"POSITION": pos_acc, "NORMAL": nrm_acc},
                "indices": len(accessors) - 1,
                "material": mat_index[name],
                "mode": 4,
            }
        )

    gltf = {
        "asset": {"version": "2.0", "generator": "garuda humanoid_glb"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "Humanoid"}],
        "meshes": [{"name": "Humanoid", "primitives": primitives}],
        "materials": gltf_materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * _pad(len(json_bytes))
    bin_bytes = bytes(blob) + b"\0" * _pad(len(blob))

    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)          # 'glTF', v2
    out += struct.pack("<II", len(json_bytes), 0x4E4F534A)   # JSON chunk
    out += json_bytes
    out += struct.pack("<II", len(bin_bytes), 0x004E4942)     # BIN chunk
    out += bin_bytes
    return bytes(out)


def humanoid_bytes() -> bytes:
    """Convenience wrapper used by the follow scripts."""
    return build_glb()


if __name__ == "__main__":  # pragma: no cover - self-test
    data = build_glb()
    magic, version, total = struct.unpack("<III", data[:12])
    print(f"GLB {len(data)} bytes  magic={magic:#x}  version={version}  declared={total}")
    assert magic == 0x46546C67, "bad magic"
    assert version == 2, "not glTF 2.0"
    assert total == len(data), f"declared {total} != actual {len(data)}"
    gltf = json.loads(data[20 : 20 + struct.unpack("<I", data[12:16])[0]].decode())
    acc = gltf["accessors"]
    # NORMAL accessors are also VEC3 but carry no min/max, so select the
    # POSITION accessors the primitives actually reference.
    pos = [
        acc[p["attributes"]["POSITION"]]
        for p in gltf["meshes"][0]["primitives"]
    ]
    # One primitive per material, so overall height is the union across parts.
    lo = min(a["min"][1] for a in pos)
    hi = max(a["max"][1] for a in pos)
    span_x = max(a["max"][0] for a in pos) - min(a["min"][0] for a in pos)
    print(
        f"primitives={len(gltf['meshes'][0]['primitives'])} "
        f"materials={len(gltf['materials'])} accessors={len(acc)}"
    )
    assert abs(lo) < 0.01, f"feet should sit at y=0, got {lo}"
    assert abs((hi - lo) - HEIGHT_M) < 0.01, f"height {hi - lo}"
    # Shoulder span matters for silhouette: too narrow and a detector reads
    # the figure as an obstacle rather than a person.
    assert 0.5 < span_x < 0.9, f"arm span {span_x:.3f} m looks wrong"
    print(f"height {hi - lo:.3f} m, arm span {span_x:.3f} m  -> OK")
