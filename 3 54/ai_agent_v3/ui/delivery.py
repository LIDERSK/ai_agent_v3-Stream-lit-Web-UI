"""Delivering files to the user: per-file download, ZIP of everything, open the folder on this PC."""
from __future__ import annotations

import streamlit as st

from config import WORKSPACE_DIR
from core import workspace


def _open_folder(rel: str | None, key: str) -> None:
    try:
        workspace.open_in_explorer(rel)
        st.toast("Otvorené v správcovi súborov", icon="📂")
    except workspace.WorkspaceError as e:
        st.warning(str(e))


def render_files(files: list[str], key: str, topic: str = "") -> None:
    """Block under an assistant message listing the files it created."""
    files = workspace.existing(files)
    if not files:
        return
    with st.container(border=True, key=f"files_{key}"):
        st.markdown(f"**📁 Vytvorené súbory ({len(files)})**")
        for i, rel in enumerate(files):
            c_name, c_dl, c_open = st.columns([7, 1.6, 1.2], vertical_alignment="center")
            c_name.markdown(f"`{rel}`")
            try:
                data = workspace.safe_path(rel).read_bytes()
            except (workspace.WorkspaceError, OSError):
                continue
            c_dl.download_button("⬇ Stiahnuť", data, file_name=rel.rsplit("/", 1)[-1],
                                 key=f"dl_{key}_{i}", use_container_width=True)
            if c_open.button("📂", key=f"open_{key}_{i}", help="Ukázať v priečinku na tomto PC",
                             use_container_width=True):
                _open_folder(rel, f"o{key}{i}")
        c_zip, c_dir, _ = st.columns([3, 3, 4])
        c_zip.download_button("📦 Všetko ako ZIP", workspace.make_zip(files),
                              file_name=workspace.zip_name(files, topic), mime="application/zip",
                              key=f"zip_{key}", use_container_width=True)
        if c_dir.button("📂 Otvoriť priečinok", key=f"opendir_{key}", use_container_width=True):
            _open_folder(files[0] if len(files) == 1 else None, key)
        st.caption(f"Na tomto PC: `{WORKSPACE_DIR}`")
