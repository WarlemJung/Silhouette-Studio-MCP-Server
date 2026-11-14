import sys
from pathlib import Path

# Adiciona o diretorio src ao path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from silhouette_mcp import server

def main():
    name = "tags_presente_luxo"
    print(f"--- Criando design '{name}' (preset A4: 210 x 297 mm) ---")
    server.silhouette_new_design(name, preset="a4", overwrite=True)

    # 4 Tags de Presente / Lembrancinha
    tags_pos = [
        (30, 30, "star"),
        (110, 30, "hexagon"),
        (30, 140, "circle"),
        (110, 140, "star8"),
    ]

    for i, (bx, by, emblem) in enumerate(tags_pos, 1):
        # 1. Contorno externo cortado com chanfros superiores (50 x 90 mm)
        tag_contour = [
            [bx, by + 15],
            [bx + 15, by],
            [bx + 35, by],
            [bx + 50, by + 15],
            [bx + 50, by + 90],
            [bx, by + 90],
        ]
        server.silhouette_add_polyline(
            name, tag_contour, closed=True, layer="CUT", label=f"tag_corpo_{i}"
        )

        # 2. Furo para fita/cordao (diametro 5 mm)
        server.silhouette_add_circle(
            name, cx_mm=bx + 25, cy_mm=by + 10, radius_mm=2.5, layer="CUT", label=f"furo_{i}"
        )

        # 3. Linha de vinco/dobra pontilhada (camada SCORE / azul)
        server.silhouette_add_line(
            name,
            x1_mm=bx + 5,
            y1_mm=by + 24,
            x2_mm=bx + 45,
            y2_mm=by + 24,
            dashed=True,
            dash_len_mm=3.0,
            gap_len_mm=2.0,
            layer="SCORE",
            label=f"vinco_{i}",
        )

        # 4. Recorte vazado decorativo no centro
        cx, cy = bx + 25, by + 57
        if emblem == "star":
            server.silhouette_add_star(
                name, cx_mm=cx, cy_mm=cy, outer_radius_mm=13, inner_radius_mm=5.5, points=5,
                layer="CUT", label=f"estrela_{i}"
            )
        elif emblem == "hexagon":
            server.silhouette_add_polygon(
                name, cx_mm=cx, cy_mm=cy, radius_mm=12, sides=6, rotation_deg=30,
                layer="CUT", label=f"hex_{i}"
            )
        elif emblem == "circle":
            server.silhouette_add_circle(
                name, cx_mm=cx, cy_mm=cy, radius_mm=12, layer="CUT", label=f"anel_ext_{i}"
            )
            server.silhouette_add_circle(
                name, cx_mm=cx, cy_mm=cy, radius_mm=6, layer="CUT", label=f"anel_int_{i}"
            )
        elif emblem == "star8":
            server.silhouette_add_star(
                name, cx_mm=cx, cy_mm=cy, outer_radius_mm=13, inner_radius_mm=7, points=8,
                layer="CUT", label=f"estrela8_{i}"
            )

    desc = server.silhouette_describe_design(name)
    print("Design estruturado com sucesso:")
    print(f" - Quantidade de formas: {desc['shape_count']}")
    print(f" - Dimensoes do tapete/pagina: {desc['width_mm']} x {desc['height_mm']} mm")
    print(f" - Bounding Box geral das pecas: {desc['overall_bbox_mm']}")
    print(f" - Avisos: {desc['warnings']}")

    print("\n--- Exportando DXF e SVG ---")
    exp = server.silhouette_export(name, formats="dxf,svg")
    for fmt, p in exp["files"].items():
        print(f" - {fmt.upper()}: {p}")

    print("\n--- Abrindo diretamente no Silhouette Studio ---")
    open_res = server.silhouette_open_in_studio(name)
    print("Resultado da abertura:", open_res)

if __name__ == "__main__":
    main()

