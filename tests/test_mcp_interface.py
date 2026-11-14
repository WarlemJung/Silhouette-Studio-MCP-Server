import pytest
import server

@pytest.mark.anyio
async def test_mcp_call_tool_flow():
    # 1. Preset list
    presets_res = await server.mcp.call_tool("silhouette_list_page_presets", {})
    assert presets_res is not None

    # 2. New design
    new_res = await server.mcp.call_tool(
        "silhouette_new_design", {"name": "mcp_flow_test", "preset": "a4", "overwrite": True}
    )
    assert new_res is not None

    # 3. Add rectangle
    rect_res = await server.mcp.call_tool(
        "silhouette_add_rectangle",
        {"design": "mcp_flow_test", "x_mm": 20, "y_mm": 20, "width_mm": 50, "height_mm": 30, "layer": "CUT"}
    )
    assert rect_res is not None

    # 4. Add circle
    circ_res = await server.mcp.call_tool(
        "silhouette_add_circle",
        {"design": "mcp_flow_test", "cx_mm": 100, "cy_mm": 100, "radius_mm": 15, "layer": "CUT"}
    )
    assert circ_res is not None

    # 5. Add score line
    line_res = await server.mcp.call_tool(
        "silhouette_add_line",
        {"design": "mcp_flow_test", "x1_mm": 20, "y1_mm": 20, "x2_mm": 70, "y2_mm": 20, "dashed": True, "layer": "SCORE"}
    )
    assert line_res is not None

    # 6. Describe design
    desc_res = await server.mcp.call_tool(
        "silhouette_describe_design", {"design": "mcp_flow_test"}
    )
    assert desc_res is not None

    # 7. Export
    exp_res = await server.mcp.call_tool(
        "silhouette_export", {"design": "mcp_flow_test", "formats": "dxf,svg"}
    )
    assert exp_res is not None

