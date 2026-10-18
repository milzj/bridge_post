#!/usr/bin/env python3
"""Create host-viewable figures and an entirely offline 3-D results report.

The geometry comes from Firedrake's VTK output.  The displayed full bridge is
the computed quarter reflected across its two displacement-symmetry planes,
x=0 and y=1.  The thresholded cells visualize the optimized density field,
not a second optimization or a reconstructed CAD/finite-element model.
"""

from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "bridge-matplotlib"))
if sys.platform.startswith("linux"):
    os.environ.setdefault("VTK_DEFAULT_OPENGL_WINDOW", "vtkEGLRenderWindow")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
import pyvista as pv
from PIL import Image, ImageDraw, ImageFont


NAVY = "#142838"
TEAL = "#168b88"
GOLD = "#d2a15a"
RED = "#d86a58"
BLUE = "#3f7198"
GRAY = "#8799a5"
BG = "#f4f6f8"


def read_grid(path: Path, first: bool = False) -> pv.UnstructuredGrid:
    """Read serial or parallel VTU/PVD output, including multiblock readers."""
    reader = pv.get_reader(str(path))
    if hasattr(reader, "time_values") and reader.time_values:
        reader.set_active_time_value(reader.time_values[0 if first else -1])
    mesh = reader.read()
    while isinstance(mesh, pv.MultiBlock):
        blocks = [block for block in mesh if block is not None]
        if len(blocks) == 1:
            mesh = blocks[0]
        else:
            mesh = mesh.combine(merge_points=True)
    if not isinstance(mesh, pv.UnstructuredGrid):
        mesh = mesh.cast_to_unstructured_grid()
    if not mesh.n_cells:
        raise ValueError(f"No volume cells in {path}")
    return mesh


def density_name(mesh: pv.DataSet, requested: str | None) -> str:
    names = list(mesh.array_names)
    if requested:
        if requested not in names:
            raise ValueError(f"Density field {requested!r} not found; fields: {names}")
        return requested
    for key in (
        "material-density", "material_density", "material density", "rho_material",
        "density-filtered", "density_filtered", "filtered_density", "rho_filtered", "rhof", "rho", "density",
    ):
        if key in names:
            return key
    raise ValueError(f"No recognized density field; fields: {names}. Use --density-field.")


def full_bridge(quarter: pv.PolyData) -> pv.PolyData:
    pieces = []
    for reflect_x, reflect_y in ((False, False), (True, False), (False, True), (True, True)):
        piece = quarter.copy(deep=True)
        xyz = piece.points.copy()
        if reflect_x:
            xyz[:, 0] *= -1
        if reflect_y:
            xyz[:, 1] = 2 - xyz[:, 1]
        piece.points = xyz
        # A single reflection reverses orientation.  Reorient closed components
        # after combining, which also handles the two-reflection case.
        pieces.append(piece)
    merged = pieces[0].merge(pieces[1:], merge_points=True).clean().triangulate()
    # Reflection makes coincident triangles on the symmetry planes. Remove
    # those interior faces instead of displaying fictitious plates in holes.
    triangles = merged.faces.reshape((-1, 4))[:, 1:]
    _, inverse, counts = np.unique(np.sort(triangles, axis=1), axis=0,
                                    return_inverse=True, return_counts=True)
    exterior = triangles[counts[inverse] == 1]
    faces = np.column_stack((np.full(len(exterior), 3), exterior)).ravel()
    return pv.PolyData(merged.points, faces).clean()


def topology_surface(mesh: pv.UnstructuredGrid, name: str, level: float) -> pv.PolyData:
    """Exterior of retained density cells, with domain boundaries closed."""
    # Thresholding then extracting the surface keeps all cut domain boundaries
    # closed and is robust to coarse meshes and spatially constant densities.
    # The physical optimization fields are saved unchanged in their VTK files.
    data = mesh.copy()
    if name in data.point_data:
        data = data.point_data_to_cell_data(pass_point_data=True)
    keep = np.asarray(data.cell_data[name]).reshape(data.n_cells, -1)[:, 0] >= level
    # The deck is drawn as its exact slab below. Excluding its cells here avoids
    # overlapping coplanar gold and blue triangles (depth-buffer flickering).
    keep &= data.cell_centers().points[:, 2] < 0.98 - 1e-8
    if not np.any(keep):
        print(f"No design cells exceed density threshold {level}; displaying the solid deck only.", flush=True)
        return pv.PolyData()
    surface = data.extract_cells(keep).extract_surface(algorithm="dataset_surface").triangulate().clean()
    return full_bridge(surface).compute_normals(
        consistent_normals=True, auto_orient_normals=True, split_vertices=False,
    )


def read_history(path: Path | None) -> dict[str, np.ndarray]:
    if path is None or not path.exists():
        return {}
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return {}
    result = {}
    for key in rows[0]:
        try:
            result[key] = np.array([float(row[key]) if row[key] else np.nan for row in rows])
        except (ValueError, TypeError):
            pass
    return result


def find_column(history: dict, names: tuple[str, ...]):
    for name in names:
        if name in history:
            return history[name]
    return None


def read_summary(path: Path | None) -> dict:
    if path and path.exists():
        return json.loads(path.read_text())
    return {}


def pick_value(summary: dict, *keys, default=None):
    for key in keys:
        value = summary.get(key)
        if isinstance(value, (float, int, str)):
            return value
    return default


def support_boxes() -> list[pv.PolyData]:
    return [pv.Box(bounds=(-0.2, 0.2, y0, y1, -0.045, -0.005)).triangulate()
            for y0, y1 in ((0, 0.3), (1.7, 2))]


def load_arrows() -> list[pv.PolyData]:
    return [pv.Arrow(start=(x, y, 1.32), direction=(0, 0, -1), scale=0.25,
                     tip_length=0.3, tip_radius=0.10, shaft_radius=0.025).triangulate()
            for x in (-0.32, 0.32) for y in (0.28, 1, 1.72)]


def setup_surface() -> pv.PolyData:
    return pv.Box(bounds=(-0.5, 0.5, 0, 2, 0, 0.98)).triangulate()


def add_scene(plotter: pv.Plotter, surface: pv.PolyData | None, setup: bool = False):
    plotter.set_background(BG)
    if setup:
        plotter.add_mesh(setup_surface(), color="#b9cbd4", opacity=0.15,
                         show_edges=False, smooth_shading=False)
        plotter.add_mesh(pv.Box(bounds=(-0.5, 0.5, 0, 2, 0, 0.98)).outline(),
                         color="#8aa1b0", line_width=1)
        quarter_box = pv.Box(bounds=(0, 0.5, 0, 1, 0, 0.98))
        plotter.add_mesh(quarter_box, color=TEAL, opacity=0.22)
        plotter.add_mesh(quarter_box.outline(), color=TEAL, line_width=2)
    elif surface is not None and surface.n_cells:
        plotter.add_mesh(surface, color=GOLD, smooth_shading=True,
                         split_sharp_edges=True, specular=0.3, specular_power=35,
                         ambient=0.24, diffuse=0.75)
    deck = pv.Box(bounds=(-0.5, 0.5, 0, 2, 0.98, 1.0))
    plotter.add_mesh(deck, color="#516a7b", smooth_shading=False,
                     specular=0.25, ambient=0.35)
    for support in support_boxes():
        plotter.add_mesh(support, color=BLUE, ambient=0.35)
    for arrow in load_arrows():
        plotter.add_mesh(arrow, color=RED, smooth_shading=True, ambient=0.35)
    plotter.camera_position = [(3.0, -3.9, 2.7), (0, 1, 0.58), (0, 0, 1)]
    plotter.camera.parallel_projection = True
    plotter.camera.parallel_scale = 1.08
    plotter.enable_anti_aliasing("ssaa")


def font(size: int, bold: bool = False):
    candidates = [
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/liberation2/LiberationSans{'-Bold' if bold else '-Regular'}.ttf",
        f"/System/Library/Fonts/Supplemental/Arial{' Bold' if bold else ''}.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def static_illustration(surface: pv.PolyData, output: Path, summary: dict, level: float):
    scenes = []
    for is_setup in (True, False):
        plotter = pv.Plotter(off_screen=True, window_size=(1200, 900), lighting="three lights")
        try:
            add_scene(plotter, surface, setup=is_setup)
            scenes.append(Image.fromarray(plotter.screenshot(return_img=True)))
        finally:
            plotter.close()
    page = Image.new("RGB", (2400, 1490), BG)
    draw = ImageDraw.Draw(page)
    draw.text((90, 54), "BRIDGE / COMPUTATIONAL DESIGN", font=font(24, True), fill=TEAL)
    draw.text((85, 101), "A bridge shaped by forces", font=font(67, True), fill=NAVY)
    draw.text((90, 195), "Linear elasticity  /  Helmholtz density filter  /  volume-constrained optimization",
              font=font(27), fill="#59707f")
    for i, scene in enumerate(scenes):
        page.paste(scene, (i * 1200, 340))
    draw = ImageDraw.Draw(page)
    draw.text((90, 279), "01  THE DESIGN PROBLEM", font=font(26, True), fill=NAVY)
    draw.text((1290, 279), "02  THE COMPUTED STRUCTURE", font=font(26, True), fill=NAVY)
    draw.line((1200, 290, 1200, 1285), fill="#dce3e7", width=2)
    # Scene thumbnails have a large image viewport; captions are laid over their
    # empty lower margin so the poster remains useful at ordinary screen sizes.
    draw.text((90, 1277), "Shaded quarter: finite-element model", font=font(25, True), fill=NAVY)
    draw.text((90, 1320), "The full bridge follows by two symmetry reflections.", font=font(23), fill="#59707f")
    draw.text((1290, 1277), f"Solid display: material density ≥ {level:g}", font=font(25, True), fill=NAVY)
    draw.text((1290, 1320), "Actual simulation output; the deck is kept solid.", font=font(23), fill="#59707f")
    draw.line((90, 1385, 2310, 1385), fill="#dce3e7", width=2)
    draw.ellipse((94, 1422, 112, 1440), fill=RED)
    draw.text((128, 1411), "Distributed vertical load", font=font(23), fill="#59707f")
    draw.rectangle((647, 1422, 665, 1440), fill=BLUE)
    draw.text((683, 1411), "Fixed support patches", font=font(23), fill="#59707f")
    draw.rectangle((1197, 1422, 1215, 1440), fill=GOLD)
    draw.text((1233, 1411), "Density-threshold visualization", font=font(23), fill="#59707f")
    draw.text((2040, 1411), "FIREDRAKE", font=font(23, True), fill=NAVY)
    page.save(output / "bridge.png", optimize=True)


def convergence_figure(history: dict, summary: dict, output: Path):
    compliance = find_column(history, ("compliance", "objective", "J", "cost"))
    volume = find_column(history, ("volume_fraction", "volume", "filtered_volume_fraction"))
    if compliance is None:
        return False
    it = find_column(history, ("iteration", "iter", "iterations", "step"))
    if it is None:
        it = np.arange(len(compliance))
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 12, "axes.spines.top": False,
        "axes.spines.right": False, "axes.labelcolor": NAVY, "text.color": NAVY,
        "xtick.color": "#59707f", "ytick.color": "#59707f", "axes.edgecolor": "#cfdae1",
        "figure.facecolor": BG, "axes.facecolor": BG,
    })
    fig, axes = plt.subplots(1, 2, figsize=(13.6, 4.8), layout="constrained")
    scale = compliance[0] if compliance[0] != 0 else 1
    axes[0].plot(it, compliance / scale, color=TEAL, lw=2.5)
    axes[0].set(ylabel="Compliance / initial compliance", xlabel="Optimization iteration",
                title="Stiffness improves as material moves")
    if volume is not None:
        axes[1].plot(it, 100 * volume, color=GOLD, lw=2.5, label="Filtered design volume")
        limit = float(pick_value(summary, "volume_limit", "volume_fraction_limit", "target_volume_fraction", default=0.15))
        axes[1].axhline(100 * limit, color=RED, lw=1.6, ls="--", label=f"Limit: {100 * limit:g}%")
        axes[1].legend(frameon=False, fontsize=10)
    axes[1].set(ylabel="Design-region material (%)", xlabel="Optimization iteration",
                title="The material budget is enforced")
    for ax in axes:
        ax.grid(axis="y", color="#dfe6ea", lw=0.7)
        ax.set_axisbelow(True)
    fig.suptitle("Optimization history", fontsize=22, fontweight="bold", x=0.015, ha="left")
    fig.savefig(output / "convergence.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    return True


def mesh_trace(surface: pv.PolyData, *, name: str, color: str, opacity: float = 1):
    surface = surface.triangulate()
    faces = surface.faces.reshape((-1, 4))[:, 1:]
    points = surface.points
    return go.Mesh3d(x=points[:, 0], y=points[:, 1], z=points[:, 2],
                     i=faces[:, 0], j=faces[:, 1], k=faces[:, 2],
                     name=name, color=color, opacity=opacity,
                     flatshading=False, hoverinfo="skip", showlegend=True,
                     lighting=dict(ambient=0.45, diffuse=0.8, specular=0.25,
                                   roughness=0.35, fresnel=0.1),
                     lightposition=dict(x=3, y=-4, z=5))


def interactive_figure(surface: pv.PolyData, level: float):
    fig = go.Figure()
    fig.add_trace(mesh_trace(surface, name=f"Optimized material (ρ ≥ {level:g})", color=GOLD))
    fig.add_trace(mesh_trace(pv.Box(bounds=(-0.5, 0.5, 0, 2, 0.98, 1)).triangulate(),
                             name="Solid deck", color="#516a7b"))
    support = support_boxes()
    fig.add_trace(mesh_trace(support[0].merge(support[1]), name="Fixed support patches", color=BLUE))
    arrows = load_arrows()
    fig.add_trace(mesh_trace(arrows[0].merge(arrows[1:]), name="Downward load", color=RED))
    fig.add_trace(mesh_trace(setup_surface(), name="Design envelope", color="#b9cbd4", opacity=0.1))
    fig.update_layout(
        height=670, margin=dict(l=0, r=0, b=0, t=5), paper_bgcolor=BG,
        font=dict(family="Arial, sans-serif", color=NAVY),
        legend=dict(x=0.02, y=0.98, bgcolor="rgba(244,246,248,0.85)", font=dict(size=12)),
        scene=dict(
            xaxis=dict(title="Width, x", showbackground=False, showgrid=False, zeroline=False,
                       range=[-0.65, 0.65]),
            yaxis=dict(title="Span, y", showbackground=False, showgrid=False, zeroline=False,
                       range=[-0.12, 2.12]),
            zaxis=dict(title="Height, z", showbackground=False, showgrid=False, zeroline=False,
                       range=[-0.08, 1.36]),
            aspectmode="data", bgcolor=BG,
            camera=dict(eye=dict(x=1.55, y=-2.25, z=1.5),
                        center=dict(x=0, y=0, z=0), projection=dict(type="orthographic")),
        ),
        updatemenus=[dict(type="buttons", direction="left", x=0.02, y=0.06,
                          buttons=[dict(label="Show envelope", method="restyle",
                                        args=[{"visible": True}, [4]]),
                                   dict(label="Hide envelope", method="restyle",
                                        args=[{"visible": False}, [4]])],
                          bgcolor="#ffffff", bordercolor="#d8e1e6")],
    )
    return fig


def image_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def write_report(surface: pv.PolyData, output: Path, summary: dict, history: dict,
                 level: float, source: Path, has_history: bool):
    figure = interactive_figure(surface, level)
    chart = figure.to_html(full_html=False, include_plotlyjs=False,
                           config={"displaylogo": False, "responsive": True,
                                   "toImageButtonOptions": {"filename": "bridge-3d", "scale": 2}})
    compliance = find_column(history, ("compliance", "objective", "J", "cost"))
    volume = find_column(history, ("volume_fraction", "volume", "filtered_volume_fraction"))
    iteration = pick_value(summary, "iterations", "iteration", "iteration_count",
                           default=max(0, len(compliance) - 1) if compliance is not None else "—")
    vf = pick_value(summary, "volume_fraction", "final_volume_fraction", "filtered_volume_fraction",
                    default=float(volume[-1]) if volume is not None else None)
    comp = pick_value(summary, "compliance", "final_compliance", "objective",
                      default=float(compliance[-1]) if compliance is not None else None)
    cards = [
        ("Optimization iterations", str(iteration)),
        ("Design-region volume", f"{100 * float(vf):.2f}%" if vf is not None else "See summary.json"),
        ("Final compliance", f"{float(comp):.5g}" if comp is not None else "See summary.json"),
        ("Display threshold", f"ρ ≥ {level:g}"),
    ]
    metrics_html = "".join(f'<div class="metric"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>'
                           for label, value in cards)
    run_status = ""
    if "converged" in summary:
        status = "Convergence tolerance reached" if summary["converged"] else "Convergence tolerance not yet reached"
        reason = str(summary.get("stopping_reason", "")).replace("_", " ")
        run_status = f'<p class="hint"><strong>Run status:</strong> {status}. Stopping reason: {html.escape(reason)}.</p>'
    convergence_html = (f'<section class="card"><h2>Optimization history</h2><img alt="Compliance and volume histories" '
                        f'src="{image_uri(output / "convergence.png")}"></section>') if has_history else ""
    summary_html = html.escape(json.dumps(summary, indent=2))
    report = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Firedrake bridge · computed topology</title>
<style>
:root{{--ink:{NAVY};--muted:#59707f;--teal:{TEAL};--bg:{BG};--line:#dce4e9}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}}
main{{max-width:1280px;margin:auto;padding:40px 28px 70px}}.eyebrow{{font-size:12px;font-weight:750;letter-spacing:.16em;color:var(--teal)}}
h1{{font-size:clamp(36px,6vw,64px);letter-spacing:-.045em;line-height:1.06;margin:16px 0}}.intro{{font-size:18px;max-width:850px;color:var(--muted)}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:32px 0}}.metric{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:20px}}
.metric span{{display:block;font-size:12px;color:var(--muted)}}.metric strong{{font-size:27px;letter-spacing:-.025em;display:block;margin-top:4px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:18px;margin:24px 0;overflow:hidden}}.card h2{{font-size:21px;margin:24px 26px 5px;letter-spacing:-.02em}}
.card p{{margin:8px 26px 20px;color:var(--muted)}}.card img{{display:block;width:100%;height:auto}}.hint{{font-size:13px}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:28px}}h3{{font-size:16px;margin:18px 0 6px}}p{{margin-top:6px}}code{{font-size:13px;background:#edf1f4;padding:2px 5px;border-radius:4px}}
details{{border-top:1px solid var(--line);margin-top:24px;padding-top:18px}}summary{{cursor:pointer;font-weight:600}}pre{{overflow:auto;font-size:12px;padding:20px;background:#eaf0f3;border-radius:10px}}
footer{{font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:22px;margin-top:28px}}@media(max-width:760px){{main{{padding:25px 14px}}.metrics{{grid-template-columns:1fr 1fr}}.two{{grid-template-columns:1fr}}}}
</style><script>{get_plotlyjs()}</script></head><body><main>
<div class="eyebrow">FIREDRAKE / COMPUTATIONAL STRUCTURAL DESIGN</div>
<h1>A bridge shaped by forces.</h1>
<p class="intro">An elastic bridge carries a downward deck load using a limited material budget.
A Helmholtz filter regularizes the density field. The surface below comes directly from the computed finite-element solution.</p>
<div class="metrics">{metrics_html}</div>
{run_status}
<section class="card"><h2>Explore the computed structure</h2><p class="hint">Drag to rotate · scroll to zoom · click a legend item to hide it · use the camera button to save a view. Works offline.</p>
{chart}<p class="hint">The full bridge is the computed quarter reflected across x = 0 and y = 1.
The material display uses cell density ≥ {level:g}; it is a visualization, not a separate mechanical validation of a thresholded structure.</p></section>
<section class="card"><img alt="Bridge design domain, loading, supports, and optimized topology" src="{image_uri(output / 'bridge.png')}"></section>
{convergence_html}
<div class="two"><div><h3>What is being optimized?</h3><p>Material density in the region below the deck. Compliance measures load-weighted displacement;
smaller compliance means a stiffer structure for this load. The deck remains solid and is excluded from the design-region volume percentage.</p></div>
<div><h3>What the illustration shows</h3><p>Gold is retained design material, blue marks fixed support patches, and red arrows represent the distributed downward load.
The left illustration highlights the quarter modeled with symmetry; no additional full-bridge solve is implied.</p></div></div>
<details><summary>Run metadata</summary><pre>{summary_html}</pre></details>
<footer>Source: <code>{html.escape(source.name)}</code>. Original bridge geometry and formulation by Miguel Salazar de Troya.
This self-contained file embeds its 3-D viewer, figures, and run metadata. No server or internet connection is required.</footer>
</main></body></html>'''
    (output / "report.html").write_text(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Firedrake .pvd/.vtu/.pvtu output (latest time is selected)")
    parser.add_argument("--history", type=Path, help="CSV optimization history")
    parser.add_argument("--summary", type=Path, help="JSON run metadata")
    parser.add_argument("--output-dir", "--output_dir", type=Path, default=Path("results"))
    parser.add_argument("--density-field", help="Override automatic density-field selection")
    parser.add_argument("--threshold", type=float, default=0.45, help="Density threshold used only for visual display")
    args = parser.parse_args()
    if not 0 < args.threshold < 1:
        parser.error("--threshold must be between 0 and 1")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    mesh = read_grid(args.input)
    field = density_name(mesh, args.density_field)
    print(f"Rendering {mesh.n_cells:,} quarter-domain cells; field={field}; threshold={args.threshold}", flush=True)
    surface = topology_surface(mesh, field, args.threshold)
    print(f"Full-bridge display surface: {surface.n_cells:,} triangles", flush=True)
    history = read_history(args.history)
    summary = read_summary(args.summary)
    static_illustration(surface, args.output_dir, summary, args.threshold)
    has_history = convergence_figure(history, summary, args.output_dir)
    write_report(surface, args.output_dir, summary, history, args.threshold, args.input, has_history)
    print(f"Figures: {args.output_dir / 'bridge.png'}", flush=True)
    if has_history:
        print(f"History: {args.output_dir / 'convergence.png'}", flush=True)
    print(f"Offline interactive report: {args.output_dir / 'report.html'}", flush=True)


if __name__ == "__main__":
    main()
