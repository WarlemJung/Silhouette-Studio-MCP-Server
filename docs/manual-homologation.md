# Protocolo de Homologação Manual (Visual e Corte Físico)

> **Status geral da homologação física e visual:** **`Não executado`**
>
> Este ambiente validou instalação editável, registro das 28 ferramentas MCP, comunicação STDIO, testes unitários/integração/regressão/performance, cobertura de código e exportação/importação de arquivos em disco. **Nenhuma etapa visual no GUI do Silhouette Studio nem corte físico em plotter foi executada automaticamente.**

---

## 1. Pré-requisitos do Ambiente de Homologação

- Windows com **Silhouette Studio** instalado e acessível.
- Equipamento Silhouette conectado via USB/Bluetooth e calibrado com base de corte e lâmina compatíveis com o papel/vinil de ensaio.
- Paquímetro ou régua milimetrada calibrada para conferência dimensional.
- Repositório instalado (`pip install -e .`) e `SILHOUETTE_OUTPUT_DIR` apontando para uma pasta dedicada de ensaio.

---

## 2. Etapa A — Inspeção Visual no Silhouette Studio

**Status:** `Não executado`

1. Gerar um projeto combinando corte, vinco tracejado e marcas de registro (`CUT`, `SCORE`, `REGMARK`) e exportar via `silhouette_export_dxf` e `silhouette_export_svg`.
2. Abrir os arquivos gerados diretamente no Silhouette Studio (também testando `silhouette_open_in_studio`).
3. Conferir:
   - Escala exata 1:1 em milímetros (ausência de fator 25.4 / 96 DPI distorcido).
   - Separação clara das geometrias de corte (`CUT`) e vinco (`SCORE`).
   - Posicionamento íntegro das marcas de registro (`REGMARK`) dentro dos limites imprimíveis da página.
   - Ausência de segmentos fantasma, linhas abertas inesperadas no contorno externo ou artefatos de fechamento.

---

## 3. Etapa B — Ensaio Dimensional Controlado (`100 × 100 mm`)

**Status:** `Não executado`

| Caso de Teste | Dimensão Nominal | Tolerância Alvo | Resultado Medido | Status |
|---|---|---|---|---|
| Quadrado externo (`add_rect`) | `100.0 × 100.0 mm` | `± 0.5 mm` | — | `Não executado` |
| Diagonal do quadrado | `141.42 mm` | `± 0.7 mm` | — | `Não executado` |
| Círculo interno (`add_circle`) | Diâmetro `40.0 mm` | `± 0.5 mm` | — | `Não executado` |
| Marcas de registro Print & Cut | Conforme `inset_mm` / `length_mm` | Leitura sem erro na plotter | — | `Não executado` |

---

## 4. Etapa C — Homologação de Templates e Nesting Físico

**Status:** `Não executado`

1. Gerar ao menos um exemplar de `milk-box-luxo`, `cube-box`, `pillow-box` e `gift-tag` via `silhouette_add_box_template`.
2. Organizar múltiplas instâncias na área útil com `silhouette_nest_shapes` respeitando `REGMARK` e `spacing_mm`.
3. Executar corte em papel de gramatura padrão (`180 g/m²` ou `240 g/m²`):
   - Verificar alinhamento de abas e encaixes durante a dobra e colagem.
   - Verificar que o tracejado de `SCORE` facilita a dobra sem destacar/rasgar o painel.
   - Confirmar zero sobreposição entre peças vizinhas aninhadas e zero invasão da área reservada de registro.

---

## 5. Registro de Aprovação Manual

| Campo | Registro |
|---|---|
| Versão avaliada | `1.1.0` |
| Data da homologação | `Não executado` |
| Responsável técnico | `Não executado` |
| Versão do Silhouette Studio | `Não executado` |
| Modelo da plotter / material | `Não executado` |
| Parecer final | `Não executado — aguardando execução em ambiente físico com GUI e plotter` |

