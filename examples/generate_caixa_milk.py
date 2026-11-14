import sys
from pathlib import Path

# Adiciona o diretorio src do MCP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from silhouette_mcp import server

def create_caixa_milk_luxo():
    design_name = "caixa_milk_luxo"
    print(f"=== Criando '{design_name}' para Silhouette Studio ===")

    # 1. Cria a base A4 em formato paisagem (297 x 210 mm)
    server.silhouette_new_design(
        name=design_name,
        width_mm=297.0,
        height_mm=210.0,
        cut_margin_mm=5.0,
        overwrite=True,
    )

    # Parametros geometricos em mm
    W = 60.0       # Largura de cada face (4 faces = 240 mm)
    G = 12.0       # Aba de colagem lateral
    H_top = 20.0   # Aba superior do laco
    H_pyr = 30.0   # Seção piramidal do vinco leiteiro
    H_body = 85.0  # Corpo principal
    H_bot = 35.0   # Abas do fundo

    # Coordenadas X
    X0 = 22.5      # Borda esquerda da aba de colagem
    X1 = X0 + G    # 34.5 (Inicio Face 1 - Frente)
    X2 = X1 + W    # 94.5 (Inicio Face 2 - Lateral Esquerda)
    X3 = X2 + W    # 154.5 (Inicio Face 3 - Traseira)
    X4 = X3 + W    # 214.5 (Inicio Face 4 - Lateral Direita)
    X5 = X4 + W    # 274.5 (Borda direita da Face 4)

    # Coordenadas Y
    Y0 = 20.0              # Topo da caixa
    Y1 = Y0 + H_top        # 40.0 (Vinco gola superior)
    Y2 = Y1 + H_pyr        # 70.0 (Vinco base da piramide)
    Y3 = Y2 + H_body       # 155.0 (Vinco das abas do fundo)
    Y4 = Y3 + H_bot        # 190.0 (Extremo inferior das abas)

    # -------------------------------------------------------------
    # 1. CONTORNO EXTERNO DE CORTE (CUT) - Poligono unico e fechado
    # -------------------------------------------------------------
    perimeter = [
        # Topo
        [X1, Y0],
        [X5, Y0],
        # Lateral direita
        [X5, Y3],
        # Aba Fundo 4 (lateral direita - aba de poeira chanfrada)
        [X5 - 3.0, Y3 + 26.0],
        [X4 + 3.0, Y3 + 26.0],
        [X4, Y3],
        # Aba Fundo 3 (fundo principal)
        [X4 - 1.5, Y4],
        [X3 + 1.5, Y4],
        [X3, Y3],
        # Aba Fundo 2 (lateral esquerda - aba de poeira chanfrada)
        [X3 - 3.0, Y3 + 26.0],
        [X2 + 3.0, Y3 + 26.0],
        [X2, Y3],
        # Aba Fundo 1 (fundo principal)
        [X2 - 1.5, Y4],
        [X1 + 1.5, Y4],
        [X1, Y3],
        # Aba de colagem (inferior chanfrado)
        [X0, Y3 - 5.0],
        # Borda esquerda da aba de colagem
        [X0, Y1 + 5.0],
        # Aba de colagem (superior chanfrado)
        [X1, Y1],
        # Subida ate o topo
        [X1, Y0],
    ]

    server.silhouette_add_polyline(
        design=design_name,
        points=perimeter,
        closed=True,
        layer="CUT",
        label="contorno_caixa_milk",
    )

    # -------------------------------------------------------------
    # 2. VINCOS HORIZONTAIS (SCORE) - Linhas pontilhadas para dobra
    # -------------------------------------------------------------
    # Vinco entre gola e piramide (Y1)
    server.silhouette_add_line(
        design_name, X1, Y1, X5, Y1, dashed=True, dash_len_mm=3.5, gap_len_mm=2.0, layer="SCORE", label="vinco_gola"
    )
    # Vinco entre piramide e corpo (Y2)
    server.silhouette_add_line(
        design_name, X1, Y2, X5, Y2, dashed=True, dash_len_mm=3.5, gap_len_mm=2.0, layer="SCORE", label="vinco_corpo"
    )
    # Vinco entre corpo e fundo (Y3)
    server.silhouette_add_line(
        design_name, X1, Y3, X5, Y3, dashed=True, dash_len_mm=3.5, gap_len_mm=2.0, layer="SCORE", label="vinco_fundo"
    )

    # -------------------------------------------------------------
    # 3. VINCOS VERTICAIS (SCORE)
    # -------------------------------------------------------------
    # Vinco da aba de colagem (X1, de Y1 a Y3)
    server.silhouette_add_line(
        design_name, X1, Y1, X1, Y3, dashed=True, dash_len_mm=3.5, gap_len_mm=2.0, layer="SCORE", label="vinco_aba_colagem"
    )
    # Vincos entre as faces (X2, X3, X4, de Y0 a Y3)
    server.silhouette_add_line(
        design_name, X2, Y0, X2, Y3, dashed=True, dash_len_mm=3.5, gap_len_mm=2.0, layer="SCORE", label="vinco_face_1_2"
    )
    server.silhouette_add_line(
        design_name, X3, Y0, X3, Y3, dashed=True, dash_len_mm=3.5, gap_len_mm=2.0, layer="SCORE", label="vinco_face_2_3"
    )
    server.silhouette_add_line(
        design_name, X4, Y0, X4, Y3, dashed=True, dash_len_mm=3.5, gap_len_mm=2.0, layer="SCORE", label="vinco_face_3_4"
    )

    # -------------------------------------------------------------
    # 4. VINCOS PIRAMIDAIS TRIANGULARES (Inward Pinch Fold)
    # -------------------------------------------------------------
    # Face 2 (Lateral esquerda): centro em (X2 + 30, Y1)
    cx2 = X2 + W / 2.0
    server.silhouette_add_line(
        design_name, X2, Y2, cx2, Y1, dashed=True, dash_len_mm=3.0, gap_len_mm=2.0, layer="SCORE", label="piramide_f2_esq"
    )
    server.silhouette_add_line(
        design_name, X3, Y2, cx2, Y1, dashed=True, dash_len_mm=3.0, gap_len_mm=2.0, layer="SCORE", label="piramide_f2_dir"
    )
    server.silhouette_add_line(
        design_name, cx2, Y1, cx2, Y0, dashed=True, dash_len_mm=3.0, gap_len_mm=2.0, layer="SCORE", label="piramide_f2_vert"
    )

    # Face 4 (Lateral direita): centro em (X4 + 30, Y1)
    cx4 = X4 + W / 2.0
    server.silhouette_add_line(
        design_name, X4, Y2, cx4, Y1, dashed=True, dash_len_mm=3.0, gap_len_mm=2.0, layer="SCORE", label="piramide_f4_esq"
    )
    server.silhouette_add_line(
        design_name, X5, Y2, cx4, Y1, dashed=True, dash_len_mm=3.0, gap_len_mm=2.0, layer="SCORE", label="piramide_f4_dir"
    )
    server.silhouette_add_line(
        design_name, cx4, Y1, cx4, Y0, dashed=True, dash_len_mm=3.0, gap_len_mm=2.0, layer="SCORE", label="piramide_f4_vert"
    )

    # -------------------------------------------------------------
    # 5. FUROS SUPERIORES PARA LAÇO DE FITA DE CETIM (CUT)
    # -------------------------------------------------------------
    # Furo Face 1 (Frente)
    server.silhouette_add_circle(
        design_name, cx_mm=X1 + W / 2.0, cy_mm=Y0 + 10.0, radius_mm=2.25, layer="CUT", label="furo_laco_frente"
    )
    # Furo Face 3 (Trás)
    server.silhouette_add_circle(
        design_name, cx_mm=X3 + W / 2.0, cy_mm=Y0 + 10.0, radius_mm=2.25, layer="CUT", label="furo_laco_tras"
    )

    # -------------------------------------------------------------
    # 6. VISOR SHAKER VAZADO LUXO NA FRENTE (CUT)
    # -------------------------------------------------------------
    # Moldura arredondada elegante no centro da Face 1
    visor_w = 36.0
    visor_h = 50.0
    vx = (X1 + W / 2.0) - (visor_w / 2.0)
    vy = Y2 + (H_body - visor_h) / 2.0
    server.silhouette_add_rectangle(
        design_name,
        x_mm=vx,
        y_mm=vy,
        width_mm=visor_w,
        height_mm=visor_h,
        corner_radius_mm=8.0,
        layer="CUT",
        label="visor_shaker_frente",
    )

    # Detalhe ornamental vazado: pequena estrela luxo acima do visor
    server.silhouette_add_star(
        design_name,
        cx_mm=X1 + W / 2.0,
        cy_mm=vy - 6.0,
        outer_radius_mm=4.0,
        inner_radius_mm=1.8,
        points=5,
        layer="CUT",
        label="detalhe_estrela_topo",
    )

    # -------------------------------------------------------------
    # 7. EXPORTAÇÃO E ABERTURA NO SILHOUETTE STUDIO
    # -------------------------------------------------------------
    desc = server.silhouette_describe_design(design_name)
    print("\n--- Relatório da Caixa Milk Luxo ---")
    print(f"Formas cadastradas: {desc['shape_count']}")
    print(f"Área útil A4: {desc['width_mm']} x {desc['height_mm']} mm")
    print(f"Limites da peça (Bounding Box): {desc['overall_bbox_mm']}")
    print(f"Avisos de corte: {desc['warnings']}")

    print("\n--- Exportando arquivos DXF e SVG ---")
    exp = server.silhouette_export(design_name, formats="dxf,svg")
    for fmt, p in exp["files"].items():
        print(f"  {fmt.upper()}: {p}")

    print("\n--- Abrindo diretamente no Silhouette Studio ---")
    res_open = server.silhouette_open_in_studio(design_name)
    print("Status:", res_open)

if __name__ == "__main__":
    create_caixa_milk_luxo()

