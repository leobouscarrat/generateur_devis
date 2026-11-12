"""Rendu du modèle 3D dans Streamlit (issue #24) : Maillage → figure plotly.

Fonctions pures (hors Streamlit) : l'écran appelle ``figure_modele_3d`` puis
``st.plotly_chart`` sur la figure, ou ``st.info`` sur le message qui explique
son absence — profil de pliage absent (``MESSAGE_SANS_PROFIL``) ou vraie raison
de l'échec de construction (issue #66), jamais d'erreur.
"""

from __future__ import annotations

import plotly.graph_objects as go

from generateur_devis.modele3d import ErreurGeometrie, Maillage, construire_modele_3d
from generateur_devis.schema.piece import PieceExtraite

MESSAGE_SANS_PROFIL = "Pas de profil de pliage : modèle 3D non représenté en V1."


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


def figure_modele_3d(piece: PieceExtraite, facteur_k: float) -> tuple[go.Figure | None, str | None]:
    """Figure 3D de la pièce, ou (None, message expliquant pourquoi elle est absente).

    - ``profil_pliage`` None → (None, ``MESSAGE_SANS_PROFIL``) ;
    - ``ErreurGeometrie`` de ``construire_modele_3d`` → (None, « Modèle 3D non
      représentable : <message de l'erreur> ») ;
    - sinon (figure, None).

    Ne lève jamais ``ErreurGeometrie``.
    """
    if piece.profil_pliage is None:
        return None, MESSAGE_SANS_PROFIL
    try:
        maillage = construire_modele_3d(piece, facteur_k)
    except ErreurGeometrie as e:
        return None, f"Modèle 3D non représentable : {e}"
    figure = maillage_vers_figure(maillage)
    if figure is None:
        return None, MESSAGE_SANS_PROFIL
    return figure, None
