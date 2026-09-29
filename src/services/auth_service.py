from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from src.core.security import create_access_token, hash_password, verify_password
from src.models.models import Empresa, Prefeitura, UsuarioAdmin
from src.schemas.enums import StatusVinculo
from src.schemas.schemas import EmpresaCreate, TokenResponse


class AuthService:
    def register_company(self, db: Session, dados: EmpresaCreate) -> Empresa:
        """
        Cadastra uma nova empresa vinculada a uma prefeitura existente.
        A empresa nasce com o status AGUARDANDO_VALIDACAO.
        """
        # 1. Verifica se a prefeitura selecionada existe
        prefeitura = (
            db.query(Prefeitura).filter(Prefeitura.id == dados.prefeitura_id).first()
        )
        if not prefeitura:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prefeitura não encontrada.",
            )

        # 2. Verifica unicidade de CNPJ e Email entre empresas
        empresa_existente = (
            db.query(Empresa)
            .filter((Empresa.cnpj == dados.cnpj) | (Empresa.email == dados.email))
            .first()
        )
        if empresa_existente:
            if empresa_existente.cnpj == dados.cnpj:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="CNPJ já registado.",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="E-mail já registado.",
            )

        # 3. Verifica se o email já é utilizado por um admin de prefeitura
        admin_existente = (
            db.query(UsuarioAdmin).filter(UsuarioAdmin.email == dados.email).first()
        )
        if admin_existente:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="E-mail já registado para um administrador da prefeitura.",
            )

        # 4. Garante razão social preenchida
        razao_social = (
            dados.razao_social or dados.nome_fantasia or f"Empresa {dados.cnpj}"
        )

        nova_empresa = Empresa(
            prefeitura_id=dados.prefeitura_id,
            cnpj=dados.cnpj,
            razao_social=razao_social,
            nome_fantasia=dados.nome_fantasia,
            email=dados.email,
            telefone=dados.telefone,
            endereco=dados.endereco,
            pwd_hash=hash_password(dados.senha),
            empresa_status=StatusVinculo.AGUARDANDO_VALIDACAO,
        )

        db.add(nova_empresa)
        db.commit()
        db.refresh(nova_empresa)
        return nova_empresa

    def authenticate_user(self, db: Session, email: str, senha: str) -> TokenResponse:
        """
        Autentica a entidade pelo e-mail e senha.
        Diferencia permissões:
        - Prefeitura (UsuarioAdmin): atua como superusuário (user_type = 'PREFEITURA').
        - Empresa: permissões padrão de empresa (user_type = 'EMPRESA').
        """
        # 1. Verifica se é um usuário da Prefeitura (Superusuário)
        admin = db.query(UsuarioAdmin).filter(UsuarioAdmin.email == email).first()
        if admin and verify_password(senha, admin.senha_hash):
            token_payload = {
                "sub": admin.id,
                "email": admin.email,
                "user_type": "PREFEITURA",
                "is_superuser": True,
                "id_prefeitura": admin.id_prefeitura,
            }
            access_token = create_access_token(token_payload)
            return TokenResponse(
                access_token=access_token,
                token_type="bearer",
                user_type="PREFEITURA",
                user_id=admin.id,
                email=admin.email,
                nome=admin.nome,
                prefeitura_id=admin.id_prefeitura,
                status_vinculo=None,
            )

        # 2. Verifica se é uma Empresa
        empresa = db.query(Empresa).filter(Empresa.email == email).first()
        if empresa and verify_password(senha, empresa.pwd_hash):
            token_payload = {
                "sub": empresa.id,
                "email": empresa.email,
                "user_type": "EMPRESA",
                "is_superuser": False,
                "prefeitura_id": empresa.prefeitura_id,
                "status_vinculo": (
                    empresa.empresa_status.value
                    if hasattr(empresa.empresa_status, "value")
                    else str(empresa.empresa_status)
                ),
            }
            access_token = create_access_token(token_payload)
            nome_empresa = empresa.nome_fantasia or empresa.razao_social
            return TokenResponse(
                access_token=access_token,
                token_type="bearer",
                user_type="EMPRESA",
                user_id=empresa.id,
                email=empresa.email,
                nome=nome_empresa,
                prefeitura_id=empresa.prefeitura_id,
                status_vinculo=empresa.empresa_status,
            )

        # 3. Credenciais não encontradas ou inválidas
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )


auth_service = AuthService()
