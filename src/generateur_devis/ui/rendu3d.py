"""Rendu du modèle 3D dans Streamlit (issue #24) : Maillage → figure plotly.

Fonction pure (hors Streamlit) : l'écran appelle ``st.plotly_chart`` sur la
figure retournée. Un maillage vide (pas de profil de pliage) retourne None —
l'écran affiche alors un message informatif, pas d'erreur.
"""

from __future__ import annotations

import plotly.graph_objects as go

from generateur_devis.modele3d import Maillage


def maillage_vers_figure(maillage: Maillage | None) -> go.Figure | None:
    """Convertit un maillage en figure plotly (Mesh3d), axes en mm.

    Returns None si le maillage est absent ou vide (pièce sans profil de
    pliage : rectangle englobant non représenté en V1).
    """
    if maillage is None or not maillage.sommets or not maillage.faces:
        return None
    xs, ys, zs = zip(*maillage.sommets, strict=True)
    # Mesh3d n'accepte que des triangles : chaque face quadrilatère du
    # maillage est scindée en deux triangles (a,b,c) et (a,c,d).
    triangles: list[tuple[int, int, int]] = []
    for face in maillage.faces:
        if len(face) == 3:
            triangles.append((face[0], face[1], face[2]))
        else:
            triangles.append((face[0], face[1], face[2]))
            triangles.append((face[0], face[2], face[3]))
    is_, js, ks = zip(*triangles, strict=True)
    figure = go.Figure(
        data=[
            go.Mesh3d(
                x=xs,
                y=ys,
                z=zs,
                i=is_,
                j=js,
                k=ks,
                color="lightsteelblue",
                opacity=0.9,
                flatshading=True,
            )
        ]
    )
    figure.update_layout(
        scene=dict(
            xaxis_title="x (mm)",
            yaxis_title="y (mm)",
            zaxis_title="z (mm)",
            aspectmode="data",
        ),
        margin=dict(l=0, r=0, t=30, b=0),
        height=420,
    )
    return figure
