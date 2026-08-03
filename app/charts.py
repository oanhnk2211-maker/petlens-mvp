from __future__ import annotations

import plotly.graph_objects as go
from app.models import AttributeScores


def radar_chart(scores: AttributeScores) -> go.Figure:
    labels = ["食品", "毒性", "玩具", "危险", "兴趣"]
    values = [scores.food, scores.poison, scores.toy, scores.hazard, scores.interest]
    fig = go.Figure(
        data=[go.Scatterpolar(r=values + [values[0]], theta=labels + [labels[0]], fill="toself")]
    )
    fig.update_layout(
        polar={"radialaxis": {"visible": True, "range": [0, 100]}},
        showlegend=False,
        height=340,
        margin={"l": 30, "r": 30, "t": 30, "b": 30},
    )
    return fig
