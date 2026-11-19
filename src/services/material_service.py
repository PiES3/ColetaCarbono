from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from src.models.models import Material


def materiais_visiveis(db: Session, prefeitura_id: str | None) -> Query:
    """
    Materiais que o município enxerga: a lista IPCC, comum a todos, e os
    cadastrados pela própria prefeitura.
    """
    return db.query(Material).filter(
        or_(Material.prefeitura_id.is_(None), Material.prefeitura_id == prefeitura_id)
    )


def material_disponivel(
    db: Session, material_id: str, prefeitura_id: str | None
) -> Material | None:
    return (
        materiais_visiveis(db, prefeitura_id).filter(Material.id == material_id).first()
    )
